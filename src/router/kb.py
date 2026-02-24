from fastapi.routing import APIRouter
from fastapi import UploadFile, File, BackgroundTasks
from src.service.kb_service import KBService

router = APIRouter(prefix="/kb", tags=["kb"])


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    project_id: int,
    file: UploadFile = File(...),
):
    kb_service = KBService()
    try:
        file_path = await kb_service.save_file_to_storage(file, project_id=project_id, kb_name="uploaded_kb")
    except Exception as e:
        return {"success": False, "error": str(e)}

    try:
        kb_id = await kb_service.create_kb_ingest_task(
            kb_name=file_path.name,
            project_id=project_id,
        )
        background_tasks.add_task(
            kb_service.run_kb_ingest_task,
            kb_id,
            file_path.as_posix(),
            project_id,
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
