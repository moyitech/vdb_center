from src.db.mapper import (
    create_kb,
    upsert_chunks,
    cut_cn,
    retrieve_dense,
    retrieve_bm25,
    update_kb_ingest_status,
    get_kb_list_for_project as mapper_get_kb_list_for_project,
    get_kb_task_status as mapper_get_kb_task_status,
)
from src.db.models import KB_INGEST_STATUS_SUCCEEDED, KB_INGEST_STATUS_FAILED
from src.utils.embedding_api import get_text_embedding
from src.db.database import DBSession
from src.utils.file_loader import read_pdf, read_docx, read_csv
from tqdm import tqdm
from pathlib import Path
from typing import AsyncGenerator
from fastapi import UploadFile


class KBService:
    def __init__(self, embedding_batch_size: int = 10, db_upsert_batch_size: int = 200):
        self.embedding_batch_size = embedding_batch_size
        self.db_upsert_batch_size = db_upsert_batch_size


    def _construct_file_name(self, project_id: int, kb_name: str, file_name: str) -> str:
        template = "{project_id}_{kb_name}_{original_file_name}"
        original_file_name = Path(file_name).name
        return template.format(
            project_id=project_id,
            kb_name=kb_name,
            original_file_name=original_file_name
        )
    
    async def save_file_to_storage(self, file: UploadFile, project_id: int, kb_name: str) -> Path:
        # 保存来自 fastapi 的上传文件到本地存储，并返回保存后的文件路径
        # 这里可以根据实际需求修改保存路径和文件命名规则
        save_dir = Path(__file__).parent.parent.parent / "uploaded_files"
        save_dir.mkdir(exist_ok=True)
        if not file.filename:
            raise ValueError("Uploaded file must have a filename.")
        file_name = self._construct_file_name(project_id, kb_name, file.filename)
        save_path = save_dir / file_name
        with save_path.open("wb") as f:
            content = await file.read()
            f.write(content)
        return save_path.resolve()
    

    async def _load_file(self, file_path: str) -> list[str]:
        file_path = file_path.replace("~", str(Path.home()))

        # 文件名校验
        if file_path.endswith(".pdf"):
            chunks, _ = read_pdf(file_path)
        elif file_path.endswith(".docx"):
            chunks, _ = read_docx(file_path)
        elif file_path.endswith(".csv"):
            chunks, _ = read_csv(file_path)
        else:
            raise ValueError("Unsupported file type. Only PDF, DOCX and CSV are supported.")

        return chunks
    
    async def _iter_processed_chunks(self, chunks: list[str]) -> AsyncGenerator[dict, None]:
        for i in tqdm(range(0, len(chunks), self.embedding_batch_size)):
            batch_chunks = chunks[i:i + self.embedding_batch_size]
            embeddings = await get_text_embedding(batch_chunks)

            if len(embeddings) != len(batch_chunks):
                raise ValueError(
                    f"Embedding count mismatch: got {len(embeddings)}, expected {len(batch_chunks)}"
                )

            for offset, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                yield {
                    "chunk_index": i + offset,
                    "text": chunk,
                    "dense": embedding,
                    "tokens": cut_cn(chunk),
                }

    async def create_kb_from_file(
        self, file_path: str, kb_name: str, project_id: int
    ) -> tuple[bool, str]:
        """
        通过读取文件创建知识库，支持PDF、Word和CSV格式。首先根据文件类型调用相应的读取函数将文件内容切分成文本块，然后对每个文本块进行后处理，包括生成向量和分词。最后将处理后的数据批量插入数据库中，返回新创建的知识库ID。
        """
        kb_id = await self.create_kb_ingest_task(kb_name, project_id)
        success, message = await self.run_kb_ingest_task(kb_id, file_path, project_id)
        return success, message

    async def create_kb_ingest_task(self, kb_name: str, project_id: int) -> int:
        """
        创建知识库入库任务，返回任务ID（即kb_id），初始状态为 ingesting。
        """
        async with DBSession() as session:
            kb_id = await create_kb(session, kb_name, project_id)
            await session.commit()
            return kb_id

    async def run_kb_ingest_task(
        self,
        kb_id: int,
        file_path: str,
        project_id: int,
    ) -> tuple[bool, str]:
        """
        执行知识库入库任务。可直接调用，也可在 FastAPI BackgroundTasks 中调用。
        """
        async with DBSession() as session:
            try:
                chunks = await self._load_file(file_path)
                if not chunks:
                    raise ValueError("No valid chunks extracted from the file.")

                upsert_batch: list[dict] = []
                total_upserted = 0

                async for chunk_data in self._iter_processed_chunks(chunks):
                    upsert_batch.append(chunk_data)
                    if len(upsert_batch) >= self.db_upsert_batch_size:
                        await upsert_chunks(session, kb_id, project_id, upsert_batch)
                        total_upserted += len(upsert_batch)
                        upsert_batch.clear()

                if upsert_batch:
                    await upsert_chunks(session, kb_id, project_id, upsert_batch)
                    total_upserted += len(upsert_batch)

                if total_upserted == 0:
                    raise ValueError("Failed to process chunks from the file.")

                await update_kb_ingest_status(
                    session, kb_id, project_id, KB_INGEST_STATUS_SUCCEEDED
                )
                await session.commit()

                return True, (
                    f"Knowledge base created successfully with ID: {kb_id}, "
                    f"project_id: {project_id}, chunks: {total_upserted}"
                )
            except Exception as e:
                await session.rollback()
                try:
                    print(f"Error occurred during KB ingestion (kb_id={kb_id}): {e}")
                    await update_kb_ingest_status(
                        session, kb_id, project_id, KB_INGEST_STATUS_FAILED
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                return False, f"Knowledge base ingestion failed (kb_id={kb_id}): {e}"

    
    async def get_kb_ingest_task_status(
        self,
        project_id: int,
        kb_id: int,
    ) -> dict | None:
        """
        查询入库任务状态。
        """
        async with DBSession() as session:
            return await mapper_get_kb_task_status(session, project_id, kb_id)

    async def retrieve_hybrid(
        self,
        query: str,
        project_id: int,
        top_k_embedding: int = 10,
        top_k_bm25: int = 10
    ):
        """
        混合检索：结合BM25和向量相似度两种方法，返回与查询最相关的文本块。
        """
        query_vector = (await get_text_embedding([query]))[0]
        
        async with DBSession() as session:
            async with session.begin():
                dense_results = await retrieve_dense(session, query_vector, project_id, top_k_embedding)
                bm25_results = await retrieve_bm25(session, query, project_id, top_k_bm25)

        remove_dups_ids = {r["id"] for r in dense_results}

        merged_results = dense_results + [
            r for r in bm25_results
            if r["id"] not in remove_dups_ids
        ]

        return {
            "dense": dense_results,
            "bm25": bm25_results,
            "merged_results": merged_results
        }

    async def get_kb_list_for_project(self, project_id: int) -> list[dict]:
        """
        获取指定项目下的知识库列表。
        """
        async with DBSession() as session:
            return await mapper_get_kb_list_for_project(session, project_id)


if __name__ == "__main__":
    service = KBService()
    async def main():
        success, message = await service.create_kb_from_file(
            "~/Downloads/20250916太原理工大学2025版学生手册（封面＋正文）.pdf",
            "学生手册",
            1001,
        )
        print(success, message)

        retrieve_result = await service.retrieve_hybrid("换宿舍", 1001, top_k_embedding=10, top_k_bm25=10)
        print(retrieve_result)

        kb_list = await service.get_kb_list_for_project(1001)
        print(kb_list)

        

    import asyncio
    asyncio.run(main())
