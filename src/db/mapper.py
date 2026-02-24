from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, update
from src.db.database import DBSession
from src.db.models import (
    Item,
    KnowledgeBase,
    KB_INGEST_STATUS_INGESTING,
    KB_INGEST_STATUS_VALUES,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Callable
import re
import jieba


def cut_cn(text: str) -> list[str]:
    _re_ws = re.compile(r"\s+")
    _re_keep = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]+")

    # 1) 简单清洗：把空白压缩
    text = _re_ws.sub(" ", text.strip())
    if not text:
        return []

    # 2) jieba 分词
    tokens = jieba.lcut(text)

    # 3) 过滤掉标点/空串，只保留中英文数字
    cleaned: list[str] = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if _re_keep.fullmatch(t):
            cleaned.append(t.lower())
    return cleaned


def make_fts(tokens: list[str]):
    return func.to_tsvector("simple", _tokens_to_ts_text(tokens))


def make_tsquery(tokens: list[str]):
    return func.plainto_tsquery("simple", _tokens_to_ts_text(tokens))


def _tokens_to_ts_text(tokens: list[str]) -> str:
    return " ".join(tokens)


async def create_kb(session: AsyncSession, file_name: str, project_id: int) -> int:
    """创建一个新的知识库记录，返回其ID"""
    kb = KnowledgeBase(
        file_name=file_name,
        project_id=project_id,
        ingest_status=KB_INGEST_STATUS_INGESTING,
    )
    session.add(kb)
    await session.flush()
    return kb.id


async def update_kb_ingest_status(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    ingest_status: str,
):
    if ingest_status not in KB_INGEST_STATUS_VALUES:
        raise ValueError(
            f"Invalid ingest_status: {ingest_status}, allowed: {KB_INGEST_STATUS_VALUES}"
        )

    await session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
        )
        .values(ingest_status=ingest_status, update_time=func.now())
    )


async def upsert_chunks(session: AsyncSession, kb_id: int, project_id: int, chunks: list[dict]):
    """
    批量插入或更新知识库中的文本块（chunk）。每个chunk包含：
    - chunk_index: int，文本块在文件中的顺序
    - text: str，文本内容
    - dense: list[float]，文本的向量表示
    - tokens: list[str]，文本的分词结果
    """
    rows = []
    for c in chunks:
        rows.append({
            "kb_id": kb_id,
            "project_id": project_id,
            "chunk_index": c["chunk_index"],
            "origin_text": c["text"],
            "embedding": c["dense"],
            "fts": make_fts(c["tokens"]),
            "is_deleted": 0,  # 重新写入时确保恢复可用
        })

    stmt = insert(Item).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kb_id", "chunk_index"],
        set_={
            "origin_text": stmt.excluded.origin_text,
            "embedding": stmt.excluded.embedding,
            "fts": stmt.excluded.fts,
            "project_id": stmt.excluded.project_id,
            "is_deleted": 0,
            "update_time": func.now(),
        }
    )

    await session.execute(stmt)


async def soft_delete_kb_and_chunks(session: AsyncSession, kb_id: int, project_id: int):
    """
    软删除知识库及其所有文本块。实际操作是将is_deleted字段设置为1。
    """
    await session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
        )
        .values(is_deleted=1, update_time=func.now())
    )
    await session.execute(
        update(Item)
        .where(Item.kb_id == kb_id, Item.project_id == project_id, Item.is_deleted == 0)
        .values(is_deleted=1, update_time=func.now())
    )


async def soft_delete_some_chunks(
    session: AsyncSession, kb_id: int, project_id: int, chunk_indexes: list[int]
):
    """
    软删除知识库中的部分文本块。实际操作是将对应chunk的is_deleted字段设置为1。
    """
    await session.execute(
        update(Item)
        .where(Item.kb_id == kb_id, Item.project_id == project_id)
        .where(Item.chunk_index.in_(chunk_indexes))
        .values(is_deleted=1, update_time=func.now())
    )


async def restore_kb_and_chunks(session: AsyncSession, kb_id: int, project_id: int):
    """
    恢复知识库及其所有文本块。实际操作是将is_deleted字段设置为0。
    """
    await session.execute(
        update(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id, KnowledgeBase.project_id == project_id)
        .values(is_deleted=0, update_time=func.now())
    )
    await session.execute(
        update(Item)
        .where(Item.kb_id == kb_id, Item.project_id == project_id)
        .values(is_deleted=0, update_time=func.now())
    )


async def retrieve_dense(
    session: AsyncSession,
    query_vector: list[float],
    project_id: int,
    top_k: int = 10,
):
    """
    检索与查询向量最相似的文本块，返回它们的ID、文本内容和相似度分数。相似度计算使用余弦距离（cosine_distance）。
    结果按相似度从高到低排序，返回前top_k条记录
    """
    stmt = (
        select(
            Item,
            Item.embedding.cosine_distance(query_vector).label("score")
        )
        .where(Item.project_id == project_id, Item.is_deleted == 0)
        .order_by(Item.embedding.cosine_distance(query_vector))
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "id": row.Item.id,
            "text": row.Item.origin_text,
            "score": float(row.score),
        }
        for row in rows
    ]


async def retrieve_bm25(
    session: AsyncSession,
    query: str,
    project_id: int,
    top_k: int = 10,
    cut_fn: Callable[[str], list[str]] | None = None,
):
    """
    使用BM25算法检索与查询文本最相关的文本块，返回它们的ID、文本内容和相关度分数。结果按相关度从高到低排序，返回前top_k条记录
    """
    if cut_fn is None:
        cut_fn = cut_cn

    tsq = make_tsquery(cut_fn(query))
    rank = func.ts_rank_cd(Item.fts, tsq)

    stmt = (
        select(Item, rank.label("score"))
        .where(Item.project_id == project_id, Item.is_deleted == 0)
        .where(Item.fts.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "id": row.Item.id,
            "text": row.Item.origin_text,
            "score": float(row.score),
        }
        for row in rows
    ]

async def get_kb_list_for_project(session: AsyncSession, project_id: int):
    """
    获取指定项目下的知识库列表，包含每个知识库的ID、文件名、chunks数量、入库状态、创建时间和更新时间。
    """
    stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.file_name,
            KnowledgeBase.ingest_status,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
            func.count(Item.id).label("chunk_count")
        )
        .where(KnowledgeBase.project_id == project_id, KnowledgeBase.is_deleted == 0)
        .outerjoin(
            Item,
            (Item.kb_id == KnowledgeBase.id)
            & (Item.project_id == project_id)
            & (Item.is_deleted == 0),
        )
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.file_name,
            KnowledgeBase.ingest_status,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
        )
    )

    result = await session.execute(stmt)
    rows = result.all()

    return [
        {
            "id": row.id,
            "file_name": row.file_name,
            "ingest_status": row.ingest_status,
            "chunk_count": row.chunk_count,
            "create_time": row.create_time,
            "update_time": row.update_time,
        }
        for row in rows
    ]


async def get_kb_task_status(
    session: AsyncSession,
    project_id: int,
    kb_id: int,
):
    """
    查询指定项目下某个知识库任务的状态。
    """
    stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.project_id,
            KnowledgeBase.file_name,
            KnowledgeBase.ingest_status,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
            func.count(Item.id).label("chunk_count"),
        )
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
        )
        .outerjoin(
            Item,
            (Item.kb_id == KnowledgeBase.id)
            & (Item.project_id == project_id)
            & (Item.is_deleted == 0),
        )
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.project_id,
            KnowledgeBase.file_name,
            KnowledgeBase.ingest_status,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
        )
    )

    result = await session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None

    return {
        "id": row.id,
        "project_id": row.project_id,
        "file_name": row.file_name,
        "ingest_status": row.ingest_status,
        "chunk_count": row.chunk_count,
        "create_time": row.create_time,
        "update_time": row.update_time,
    }


if __name__ == "__main__":
    # print(cut_cn(" 这是一个测试。This is a test! 12345，混合文本。 "))
    from src.utils.embedding_api import get_text_embedding

    async def main():
        async def insert_test():
            project_id = 1
            chunks = [
                {"chunk_index": 0, "text": "这是第一段文本。", "dense": (await get_text_embedding(["这是第一段文本。"]))[0], "tokens": cut_cn("这是第一段文本。")},
                {"chunk_index": 1, "text": "这是第二段文本。", "dense": (await get_text_embedding(["这是第二段文本。"]))[0], "tokens": cut_cn("这是第二段文本。")},
            ]

            async with DBSession() as session:
                async with session.begin():
                    kb_id = await create_kb(session, "测试文件", project_id)
                    await upsert_chunks(session, kb_id, project_id, chunks)
                    print(f"Created KB with id: {kb_id}")
                    print(f"Upserted {len(chunks)} chunks for KB id: {kb_id}")
        
        async def query_test():
            project_id = 1
            async with DBSession() as session:
                async with session.begin():
                    results = await retrieve_dense(session, (await get_text_embedding(["第一段文本"]))[0], project_id, top_k=5)
                    import json
                    print(json.dumps(results, ensure_ascii=False, indent=2))

        # await insert_test()
        await query_test()

    import asyncio
    asyncio.run(main())
    
