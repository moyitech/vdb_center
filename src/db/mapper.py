from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, update
from src.db.database import DBSession
from src.db.models import (
    Item,
    KnowledgeBase,
    KB_INGEST_STATUS_INGESTING,
    KB_INGEST_STATUS_SUCCEEDED,
    KB_INGEST_STATUS_VALUES,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import CursorResult
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from typing import Any, Callable, cast
from datetime import date
import re
import jieba


KB_DELETE_REASON_DELETED = "deleted"
KB_DELETE_REASON_NOT_FOUND = "not_found"
KB_DELETE_REASON_ALREADY_DELETED = "already_deleted"
KB_DELETE_REASON_QA_KB_FORBIDDEN = "qa_kb_forbidden"
KB_DELETE_REASON_INGESTING_FORBIDDEN = "ingesting_forbidden"


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


async def create_kb(
    session: AsyncSession,
    file_name: str,
    project_id: int,
    *,
    source: str | None = None,
    date: date | None = None,
    qa_items: bool = False,
    ingest_status: str = KB_INGEST_STATUS_INGESTING,
) -> int:
    """创建一个新的知识库记录，返回其ID"""
    if ingest_status not in KB_INGEST_STATUS_VALUES:
        raise ValueError(
            f"Invalid ingest_status: {ingest_status}, allowed: {KB_INGEST_STATUS_VALUES}"
        )

    kb = KnowledgeBase(
        file_name=file_name,
        source=source,
        date=date,
        project_id=project_id,
        ingest_status=ingest_status,
        qa_items=qa_items,
    )
    session.add(kb)
    await session.flush()
    return kb.id


async def get_project_qa_kb_id(session: AsyncSession, project_id: int) -> int | None:
    """
    获取项目下 QA 专用 KB 的 ID（qa_items=true）。不存在则返回 None。
    """
    stmt = (
        select(KnowledgeBase.id)
        .where(
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.qa_items.is_(True),
            KnowledgeBase.is_deleted == 0,
        )
        .order_by(KnowledgeBase.id.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def exists_non_qa_source(
    session: AsyncSession,
    project_id: int,
    source: str,
) -> bool:
    normalized_source = source.strip()
    if not normalized_source:
        return False

    stmt = (
        select(KnowledgeBase.id)
        .where(
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.qa_items.is_(False),
            KnowledgeBase.is_deleted == 0,
            KnowledgeBase.source == normalized_source,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_or_create_project_qa_kb_id(session: AsyncSession, project_id: int) -> int:
    """
    获取或创建项目级 QA 专用 KB（每个 project 最多一个）。
    """
    # 事务级项目锁，避免并发请求在“先查后建”阶段创建出多个 QA KB。
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": int(project_id)},
    )

    kb_id = await get_project_qa_kb_id(session, project_id)
    if kb_id is not None:
        return kb_id

    try:
        return await create_kb(
            session=session,
            file_name="qa_items",
            project_id=project_id,
            qa_items=True,
            ingest_status=KB_INGEST_STATUS_SUCCEEDED,
        )
    except IntegrityError:
        await session.rollback()
        kb_id = await get_project_qa_kb_id(session, project_id)
        if kb_id is None:
            raise
        return kb_id


async def get_next_chunk_index(session: AsyncSession, kb_id: int, project_id: int) -> int:
    """
    计算下一个可用 chunk_index（单调递增，包含已删除记录）。
    """
    stmt = (
        select(func.coalesce(func.max(Item.chunk_index), -1))
        .where(Item.kb_id == kb_id, Item.project_id == project_id)
    )
    result = await session.execute(stmt)
    max_chunk_index = result.scalar_one()
    return int(max_chunk_index) + 1


async def get_item_id_by_chunk_index(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    chunk_index: int,
) -> int | None:
    stmt = (
        select(Item.id)
        .where(
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.chunk_index == chunk_index,
            Item.is_deleted == 0,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def soft_delete_items_by_ids(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    item_ids: list[int],
) -> int:
    """
    按 item id 批量软删除，返回删除条数。
    """
    if not item_ids:
        return 0

    result = cast(
        CursorResult[Any],
        await session.execute(
        update(Item)
        .where(
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.is_deleted == 0,
            Item.id.in_(item_ids),
        )
        .values(is_deleted=1, update_time=func.now())
        ),
    )
    return int(result.rowcount or 0)


async def get_existing_origin_texts(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    origin_texts: list[str],
) -> set[str]:
    """
    查询已存在的 origin_text，返回命中集合（仅未删除记录）。
    """
    if not origin_texts:
        return set()

    stmt = (
        select(Item.origin_text)
        .where(
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.is_deleted == 0,
            Item.origin_text.in_(origin_texts),
        )
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all() if row[0] is not None}


async def update_kb_ingest_status(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    ingest_status: str,
    *,
    success_count: int | None = None,
    failed_count: int | None = None,
):
    if ingest_status not in KB_INGEST_STATUS_VALUES:
        raise ValueError(
            f"Invalid ingest_status: {ingest_status}, allowed: {KB_INGEST_STATUS_VALUES}"
        )

    values: dict[str, object] = {
        "ingest_status": ingest_status,
        "update_time": func.now(),
    }
    if success_count is not None:
        values["success_count"] = max(0, int(success_count))
    if failed_count is not None:
        values["failed_count"] = max(0, int(failed_count))

    await session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
        )
        .values(**values)
    )


async def update_kb_source_and_date(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    source: str,
    info_date: date | None,
):
    await session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
        )
        .values(
            source=source,
            date=info_date,
            update_time=func.now(),
        )
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
            "source": c.get("source"),
            "date": c.get("date"),
            "question": c.get("question"),
            "answer": c.get("answer"),
            "embedding": c["dense"],
            "fts": make_fts(c["tokens"]),
            "is_deleted": 0,  # 重新写入时确保恢复可用
        })

    stmt = insert(Item).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kb_id", "chunk_index"],
        set_={
            "origin_text": stmt.excluded.origin_text,
            "source": stmt.excluded.source,
            "date": stmt.excluded.date,
            "question": stmt.excluded.question,
            "answer": stmt.excluded.answer,
            "embedding": stmt.excluded.embedding,
            "fts": stmt.excluded.fts,
            "project_id": stmt.excluded.project_id,
            "is_deleted": 0,
            "update_time": func.now(),
        }
    )

    await session.execute(stmt)


async def update_qa_item_by_id(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    item_id: int,
    question: str,
    answer: str,
    text_value: str,
    embedding: list[float],
    tokens: list[str],
) -> bool:
    """
    更新单条 QA item（仅在指定 QA KB 范围内）。
    """
    result = cast(
        CursorResult[Any],
        await session.execute(
        update(Item)
        .where(
            Item.id == item_id,
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.is_deleted == 0,
        )
        .values(
            question=question,
            answer=answer,
            origin_text=text_value,
            embedding=embedding,
            fts=make_fts(tokens),
            update_time=func.now(),
        )
        ),
    )
    return int(result.rowcount or 0) > 0


async def get_qa_item_list(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """
    获取 QA 专用 KB 下的 item 分页列表。
    """
    total_stmt = (
        select(func.count(Item.id))
        .where(
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.is_deleted == 0,
        )
    )
    total_result = await session.execute(total_stmt)
    total_count = int(total_result.scalar_one() or 0)

    offset = (page - 1) * page_size
    stmt = (
        select(
            Item.id,
            Item.kb_id,
            Item.chunk_index,
            Item.source,
            Item.date,
            Item.question,
            Item.answer,
            Item.create_time,
            Item.update_time,
        )
        .where(
            Item.kb_id == kb_id,
            Item.project_id == project_id,
            Item.is_deleted == 0,
        )
        .order_by(Item.chunk_index.asc())
        .offset(offset)
        .limit(page_size)
    )

    result = await session.execute(stmt)
    rows = result.all()
    return (
        [
            {
                "id": row.id,
                "kb_id": row.kb_id,
                "chunk_index": row.chunk_index,
                "source": row.source,
                "date": row.date,
                "question": row.question,
                "answer": row.answer,
                "create_time": row.create_time,
                "update_time": row.update_time,
            }
            for row in rows
        ],
        total_count,
    )


async def soft_delete_kb_and_chunks(
    session: AsyncSession,
    kb_id: int,
    project_id: int,
    *,
    forbid_qa_kb: bool = True,
    forbid_ingesting: bool = True,
) -> dict[str, int | bool | str]:
    """
    软删除知识库及其所有文本块，并返回删除结果。
    - 默认禁止删除 QA 专用 KB（qa_items=true）
    - 默认禁止删除 ingesting 状态 KB
    """
    base_result: dict[str, int | bool | str] = {
        "kb_id": kb_id,
        "project_id": project_id,
        "kb_deleted": False,
        "item_deleted_count": 0,
        "reason": KB_DELETE_REASON_NOT_FOUND,
    }

    kb_stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.is_deleted,
        )
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.project_id == project_id,
        )
        .with_for_update()
    )
    kb_result = await session.execute(kb_stmt)
    kb_row = kb_result.one_or_none()
    if kb_row is None:
        return base_result

    if kb_row.is_deleted != 0:
        base_result["reason"] = KB_DELETE_REASON_ALREADY_DELETED
        return base_result

    if forbid_qa_kb and bool(kb_row.qa_items):
        base_result["reason"] = KB_DELETE_REASON_QA_KB_FORBIDDEN
        return base_result

    if forbid_ingesting and kb_row.ingest_status == KB_INGEST_STATUS_INGESTING:
        base_result["reason"] = KB_DELETE_REASON_INGESTING_FORBIDDEN
        return base_result

    kb_update_result = cast(
        CursorResult[Any],
        await session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.project_id == project_id,
                KnowledgeBase.is_deleted == 0,
            )
            .values(is_deleted=1, update_time=func.now())
        ),
    )
    item_update_result = cast(
        CursorResult[Any],
        await session.execute(
            update(Item)
            .where(
                Item.kb_id == kb_id,
                Item.project_id == project_id,
                Item.is_deleted == 0,
            )
            .values(is_deleted=1, update_time=func.now())
        ),
    )

    kb_deleted = int(kb_update_result.rowcount or 0) > 0
    base_result["kb_deleted"] = kb_deleted
    base_result["item_deleted_count"] = int(item_update_result.rowcount or 0)
    base_result["reason"] = (
        KB_DELETE_REASON_DELETED
        if kb_deleted
        else KB_DELETE_REASON_ALREADY_DELETED
    )
    return base_result


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
            "source": row.Item.source,
            "date": row.Item.date,
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
            "source": row.Item.source,
            "date": row.Item.date,
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
            KnowledgeBase.source,
            KnowledgeBase.date,
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.success_count,
            KnowledgeBase.failed_count,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
            func.count(Item.id).label("chunk_count")
        )
        .where(
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
            KnowledgeBase.qa_items.is_(False),
        )
        .outerjoin(
            Item,
            (Item.kb_id == KnowledgeBase.id)
            & (Item.project_id == project_id)
            & (Item.is_deleted == 0),
        )
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.file_name,
            KnowledgeBase.source,
            KnowledgeBase.date,
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.success_count,
            KnowledgeBase.failed_count,
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
            "source": row.source,
            "date": row.date,
            "qa_items": row.qa_items,
            "ingest_status": row.ingest_status,
            "success_count": row.success_count,
            "failed_count": row.failed_count,
            "chunk_count": row.chunk_count,
            "create_time": row.create_time,
            "update_time": row.update_time,
        }
        for row in rows
    ]


async def search_kb_list_by_source(
    session: AsyncSession,
    project_id: int,
    source_keyword: str,
):
    normalized_keyword = source_keyword.strip()
    if not normalized_keyword:
        return []

    like_pattern = f"%{normalized_keyword}%"
    stmt = (
        select(
            KnowledgeBase.id,
            KnowledgeBase.file_name,
            KnowledgeBase.source,
            KnowledgeBase.date,
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.create_time,
            KnowledgeBase.update_time,
            func.count(Item.id).label("chunk_count"),
        )
        .where(
            KnowledgeBase.project_id == project_id,
            KnowledgeBase.is_deleted == 0,
            KnowledgeBase.qa_items.is_(False),
            KnowledgeBase.source.is_not(None),
            KnowledgeBase.source.ilike(like_pattern),
        )
        .outerjoin(
            Item,
            (Item.kb_id == KnowledgeBase.id)
            & (Item.project_id == project_id)
            & (Item.is_deleted == 0),
        )
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.file_name,
            KnowledgeBase.source,
            KnowledgeBase.date,
            KnowledgeBase.qa_items,
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
            "source": row.source,
            "date": row.date,
            "qa_items": row.qa_items,
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
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.success_count,
            KnowledgeBase.failed_count,
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
            KnowledgeBase.qa_items,
            KnowledgeBase.ingest_status,
            KnowledgeBase.success_count,
            KnowledgeBase.failed_count,
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
        "qa_items": row.qa_items,
        "ingest_status": row.ingest_status,
        "success_count": row.success_count,
        "failed_count": row.failed_count,
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
    
