from src.db.mapper import (
    create_kb,
    upsert_chunks,
    cut_cn,
    retrieve_dense,
    retrieve_bm25,
    update_kb_ingest_status,
    get_or_create_project_qa_kb_id,
    get_project_qa_kb_id,
    get_next_chunk_index,
    get_item_id_by_chunk_index,
    soft_delete_items_by_ids,
    get_existing_origin_texts,
    update_qa_item_by_id,
    get_qa_item_list,
    get_kb_list_for_project as mapper_get_kb_list_for_project,
    get_kb_task_status as mapper_get_kb_task_status,
)
from src.db.models import (
    KB_INGEST_STATUS_INGESTING,
    KB_INGEST_STATUS_SUCCEEDED,
    KB_INGEST_STATUS_FAILED,
)
from src.utils.embedding_api import get_text_embedding
from src.db.database import DBSession
from src.utils.file_loader import read_pdf, read_docx, read_csv, read_qa_excel
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
    

    async def _load_file(self, file_path: str) -> list[dict]:
        file_path = file_path.replace("~", str(Path.home()))
        suffix = Path(file_path).suffix.lower()

        # 文件名校验
        if suffix == ".pdf":
            chunks, _ = read_pdf(file_path)
            return [{"text": chunk} for chunk in chunks]
        elif suffix == ".docx":
            chunks, _ = read_docx(file_path)
            return [{"text": chunk} for chunk in chunks]
        elif suffix == ".csv":
            chunks, _ = read_csv(file_path)
            return [{"text": chunk} for chunk in chunks]
        elif suffix in {".xlsx", ".xlsm"}:
            records = read_qa_excel(file_path)
            return [
                {
                    "text": self._build_qa_text(record["question"], record["answer"]),
                    "question": record["question"],
                    "answer": record["answer"],
                }
                for record in records
            ]
        else:
            raise ValueError("Unsupported file type. Only PDF, DOCX, CSV and XLSX are supported.")
    
    async def _iter_processed_chunks(
        self,
        chunks: list[dict],
        start_chunk_index: int = 0,
    ) -> AsyncGenerator[dict, None]:
        for i in tqdm(range(0, len(chunks), self.embedding_batch_size)):
            batch_chunks = chunks[i:i + self.embedding_batch_size]
            batch_texts = [chunk["text"] for chunk in batch_chunks]
            embeddings = await get_text_embedding(batch_texts)

            if len(embeddings) != len(batch_texts):
                raise ValueError(
                    f"Embedding count mismatch: got {len(embeddings)}, expected {len(batch_texts)}"
                )

            for offset, (chunk, embedding) in enumerate(zip(batch_chunks, embeddings)):
                yield {
                    "chunk_index": start_chunk_index + i + offset,
                    "text": chunk["text"],
                    "question": chunk.get("question"),
                    "answer": chunk.get("answer"),
                    "dense": embedding,
                    "tokens": cut_cn(chunk["text"]),
                }

    async def create_kb_from_file(
        self, file_path: str, kb_name: str, project_id: int
    ) -> tuple[bool, str]:
        """
        通过读取文件创建知识库，支持PDF、Word、CSV和Excel格式。首先根据文件类型调用相应的读取函数将文件内容切分成文本块，然后对每个文本块进行后处理，包括生成向量和分词。最后将处理后的数据批量插入数据库中，返回新创建的知识库ID。
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

    async def get_or_create_project_qa_kb(self, project_id: int) -> int:
        """
        获取或创建项目级 QA 专用 KB（qa_items=true）。
        """
        async with DBSession() as session:
            kb_id = await get_or_create_project_qa_kb_id(session, project_id)
            await session.commit()
            return kb_id

    def _build_qa_text(self, question: str, answer: str) -> str:
        return f"问题：{question.strip()}\n答案：{answer.strip()}"

    async def _dedup_qa_chunks_by_origin_text(
        self,
        session,
        kb_id: int,
        project_id: int,
        chunks: list[dict],
    ) -> tuple[list[dict], int]:
        """
        仅用于 QA 相关场景：按 origin_text 去重（含“库内已存在”与“本次上传内重复”）。
        """
        if not chunks:
            return [], 0

        unique_chunks: list[dict] = []
        seen_in_batch: set[str] = set()
        for chunk in chunks:
            text_value = chunk["text"]
            if text_value in seen_in_batch:
                print("重复的：", text_value)
                continue
            seen_in_batch.add(text_value)
            unique_chunks.append(chunk)

        existing = await get_existing_origin_texts(
            session=session,
            kb_id=kb_id,
            project_id=project_id,
            origin_texts=[chunk["text"] for chunk in unique_chunks],
        )
        filtered = [chunk for chunk in unique_chunks if chunk["text"] not in existing]
        skipped_count = len(chunks) - len(filtered)
        return filtered, skipped_count

    async def add_single_qa_item(
        self,
        project_id: int,
        question: str,
        answer: str,
    ) -> dict:
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            raise ValueError("question and answer must not be empty.")

        qa_text = self._build_qa_text(question, answer)

        async with DBSession() as session:
            kb_id = await get_or_create_project_qa_kb_id(session, project_id)
            try:
                # 已存在 QA KB 时也统一标记为 ingesting，表示正在追加写入。
                await update_kb_ingest_status(
                    session, kb_id, project_id, KB_INGEST_STATUS_INGESTING
                )
                await session.commit()

                existing = await get_existing_origin_texts(
                    session=session,
                    kb_id=kb_id,
                    project_id=project_id,
                    origin_texts=[qa_text],
                )
                if qa_text in existing:
                    await update_kb_ingest_status(
                        session, kb_id, project_id, KB_INGEST_STATUS_SUCCEEDED
                    )
                    await session.commit()
                    return {
                        "kb_id": kb_id,
                        "item_id": None,
                        "chunk_index": None,
                        "skipped": True,
                        "reason": "duplicate_origin_text",
                    }

                embedding = (await get_text_embedding([qa_text]))[0]
                chunk_index = await get_next_chunk_index(session, kb_id, project_id)
                await upsert_chunks(
                    session,
                    kb_id,
                    project_id,
                    [
                        {
                            "chunk_index": chunk_index,
                            "text": qa_text,
                            "question": question,
                            "answer": answer,
                            "dense": embedding,
                            "tokens": cut_cn(qa_text),
                        }
                    ],
                )
                item_id = await get_item_id_by_chunk_index(
                    session,
                    kb_id,
                    project_id,
                    chunk_index,
                )
                await update_kb_ingest_status(
                    session, kb_id, project_id, KB_INGEST_STATUS_SUCCEEDED
                )
                await session.commit()
            except Exception:
                await session.rollback()
                try:
                    await update_kb_ingest_status(
                        session, kb_id, project_id, KB_INGEST_STATUS_FAILED
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                raise

        return {
            "kb_id": kb_id,
            "item_id": item_id,
            "chunk_index": chunk_index,
        }

    async def delete_single_qa_item(self, project_id: int, item_id: int) -> dict:
        return await self.delete_multi_qa_items(project_id=project_id, item_ids=[item_id])

    async def delete_multi_qa_items(self, project_id: int, item_ids: list[int]) -> dict:
        normalized_ids = sorted({item_id for item_id in item_ids if item_id > 0})
        if not normalized_ids:
            raise ValueError("item_ids must contain at least one positive integer.")

        async with DBSession() as session:
            kb_id = await get_or_create_project_qa_kb_id(session, project_id)
            deleted_count = await soft_delete_items_by_ids(
                session,
                kb_id,
                project_id,
                normalized_ids,
            )
            await session.commit()

        return {
            "kb_id": kb_id,
            "requested_count": len(normalized_ids),
            "deleted_count": deleted_count,
        }

    async def update_qa_item(
        self,
        project_id: int,
        item_id: int,
        question: str,
        answer: str,
    ) -> dict:
        question = question.strip()
        answer = answer.strip()
        if not question or not answer:
            raise ValueError("question and answer must not be empty.")

        qa_text = self._build_qa_text(question, answer)
        embedding = (await get_text_embedding([qa_text]))[0]
        tokens = cut_cn(qa_text)

        async with DBSession() as session:
            kb_id = await get_or_create_project_qa_kb_id(session, project_id)
            try:
                await update_kb_ingest_status(
                    session, kb_id, project_id, KB_INGEST_STATUS_INGESTING
                )
                updated = await update_qa_item_by_id(
                    session=session,
                    kb_id=kb_id,
                    project_id=project_id,
                    item_id=item_id,
                    question=question,
                    answer=answer,
                    text_value=qa_text,
                    embedding=embedding,
                    tokens=tokens,
                )
                if not updated:
                    raise ValueError(f"QA item not found: item_id={item_id}")

                await update_kb_ingest_status(
                    session, kb_id, project_id, KB_INGEST_STATUS_SUCCEEDED
                )
                await session.commit()
            except Exception:
                await session.rollback()
                try:
                    await update_kb_ingest_status(
                        session, kb_id, project_id, KB_INGEST_STATUS_FAILED
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                raise

        return {"kb_id": kb_id, "item_id": item_id}

    async def get_qa_list(self, project_id: int, page: int = 1, page_size: int = 20) -> dict:
        async with DBSession() as session:
            kb_id = await get_project_qa_kb_id(session, project_id)
            if kb_id is None:
                return {
                    "kb_id": None,
                    "current_page": page,
                    "page_size": page_size,
                    "total_pages": 0,
                    "total_count": 0,
                    "items": [],
                }

            items, total_count = await get_qa_item_list(
                session=session,
                kb_id=kb_id,
                project_id=project_id,
                page=page,
                page_size=page_size,
            )
            total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 0
            return {
                "kb_id": kb_id,
                "current_page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_count": total_count,
                "items": items,
            }

    async def run_kb_ingest_task(
        self,
        kb_id: int,
        file_path: str,
        project_id: int,
        append_to_existing: bool = False,
        dedup_origin_text: bool = False,
    ) -> tuple[bool, str]:
        """
        执行知识库入库任务。可直接调用，也可在 FastAPI BackgroundTasks 中调用。
        """
        total_input_count = 0
        skipped_count = 0
        async with DBSession() as session:
            try:
                await update_kb_ingest_status(
                    session,
                    kb_id,
                    project_id,
                    KB_INGEST_STATUS_INGESTING,
                    success_count=0,
                    failed_count=0,
                )
                await session.commit()

                chunks = await self._load_file(file_path)
                total_input_count = len(chunks)
                if not chunks:
                    raise ValueError("No valid chunks extracted from the file.")

                if dedup_origin_text:
                    chunks, skipped_count = await self._dedup_qa_chunks_by_origin_text(
                        session=session,
                        kb_id=kb_id,
                        project_id=project_id,
                        chunks=chunks,
                    )

                start_chunk_index = 0
                if append_to_existing:
                    start_chunk_index = await get_next_chunk_index(
                        session,
                        kb_id,
                        project_id,
                    )

                upsert_batch: list[dict] = []
                total_upserted = 0

                async for chunk_data in self._iter_processed_chunks(
                    chunks,
                    start_chunk_index=start_chunk_index,
                ):
                    upsert_batch.append(chunk_data)
                    if len(upsert_batch) >= self.db_upsert_batch_size:
                        await upsert_chunks(session, kb_id, project_id, upsert_batch)
                        total_upserted += len(upsert_batch)
                        upsert_batch.clear()

                if upsert_batch:
                    await upsert_chunks(session, kb_id, project_id, upsert_batch)
                    total_upserted += len(upsert_batch)

                if total_upserted == 0 and not dedup_origin_text:
                    raise ValueError("Failed to process chunks from the file.")

                # failed_count 统计“未写入数量”，包含去重跳过条数。
                failed_count = max(0, total_input_count - total_upserted)
                await update_kb_ingest_status(
                    session,
                    kb_id,
                    project_id,
                    KB_INGEST_STATUS_SUCCEEDED,
                    success_count=total_upserted,
                    failed_count=failed_count,
                )
                await session.commit()

                if dedup_origin_text:
                    return True, (
                        f"Knowledge base created successfully with ID: {kb_id}, "
                        f"project_id: {project_id}, success_count: {total_upserted}, failed_count: {failed_count}, skipped_duplicates: {skipped_count}"
                    )

                return True, (
                    f"Knowledge base created successfully with ID: {kb_id}, "
                    f"project_id: {project_id}, success_count: {total_upserted}, failed_count: {failed_count}"
                )
            except Exception as e:
                await session.rollback()
                try:
                    print(f"Error occurred during KB ingestion (kb_id={kb_id}): {e}")
                    # 失败任务中，failed_count 统计未写入数量，包含去重跳过条数。
                    failed_count = max(0, total_input_count)
                    await update_kb_ingest_status(
                        session,
                        kb_id,
                        project_id,
                        KB_INGEST_STATUS_FAILED,
                        success_count=0,
                        failed_count=failed_count,
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
        # success, message = await service.create_kb_from_file(
        #     "~/Downloads/20250916太原理工大学2025版学生手册（封面＋正文）.pdf",
        #     "学生手册",
        #     1001,
        # )
        # print(success, message)

        retrieve_result = await service.retrieve_hybrid("换宿舍", 1101, top_k_embedding=10, top_k_bm25=10)
        print(retrieve_result)

        # kb_list = await service.get_kb_list_for_project(1001)
        # print(kb_list)

        

    import asyncio
    asyncio.run(main())
