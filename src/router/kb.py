from fastapi.routing import APIRouter
from fastapi import UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field
from pathlib import Path
from src.service.kb_service import KBService

router = APIRouter(prefix="/kb", tags=["kb"])


class QACreateRequest(BaseModel):
    question: str = Field(..., min_length=1, description="问题")
    answer: str = Field(..., min_length=1, description="答案")


class QABatchDeleteRequest(BaseModel):
    item_ids: list[int] = Field(..., min_length=1, description="待删除的 item id 列表")


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile = File(...),
):
    kb_service = KBService()
    upload_suffix = Path(file.filename or "").suffix.lower()
    if upload_suffix == ".xls":
        return {
            "success": False,
            "error": "Legacy .xls is not supported. Please upload .xlsx/.xlsm.",
        }

    try:
        file_path = await kb_service.save_file_to_storage(file, project_id=project_id, kb_name="uploaded_kb")
    except Exception as e:
        return {"success": False, "error": str(e)}

    try:
        append_to_existing = False
        dedup_origin_text = False

        if upload_suffix in {".xlsx", ".xlsm"}:
            kb_id = await kb_service.get_or_create_project_qa_kb(project_id=project_id)
            append_to_existing = True
            dedup_origin_text = True
        else:
            kb_id = await kb_service.create_kb_ingest_task(
                kb_name=file_path.name,
                project_id=project_id,
            )

        background_tasks.add_task(
            kb_service.run_kb_ingest_task,
            kb_id,
            file_path.as_posix(),
            project_id,
            append_to_existing,
            dedup_origin_text,
        )
        return {
            "success": True,
            "kb_id": kb_id,
            "message": "Ingestion task started in background",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/list")
async def get_project_kb_list(project_id: int):
    kb_service = KBService()
    try:
        kb_list = await kb_service.get_kb_list_for_project(project_id)
        return {"success": True, "data": kb_list}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/task/{kb_id}")
async def get_kb_ingest_task_status(project_id: int, kb_id: int):
    kb_service = KBService()
    try:
        task_status = await kb_service.get_kb_ingest_task_status(project_id, kb_id)
        if task_status is None:
            return {"success": False, "error": "Task not found"}
        return {"success": True, "data": task_status}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/qa/item")
async def add_single_qa_item(project_id: int, payload: QACreateRequest):
    kb_service = KBService()
    try:
        data = await kb_service.add_single_qa_item(
            project_id=project_id,
            question=payload.question,
            answer=payload.answer,
        )
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.put("/qa/item/{item_id}")
async def update_qa_item(project_id: int, item_id: int, payload: QACreateRequest):
    kb_service = KBService()
    try:
        data = await kb_service.update_qa_item(
            project_id=project_id,
            item_id=item_id,
            question=payload.question,
            answer=payload.answer,
        )
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/qa/item/{item_id}")
async def delete_single_qa_item(project_id: int, item_id: int):
    kb_service = KBService()
    try:
        data = await kb_service.delete_single_qa_item(project_id=project_id, item_id=item_id)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/qa/items/delete")
async def delete_multi_qa_items(project_id: int, payload: QABatchDeleteRequest):
    kb_service = KBService()
    try:
        data = await kb_service.delete_multi_qa_items(
            project_id=project_id,
            item_ids=payload.item_ids,
        )
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/qa/list")
async def get_qa_list(project_id: int, limit: int = 200):
    kb_service = KBService()
    try:
        data = await kb_service.get_qa_list(project_id=project_id, limit=limit)
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}
