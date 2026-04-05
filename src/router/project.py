from fastapi.routing import APIRouter

from src.model.kb_model import APIErrorResponse
from src.model.project_model import (
    ProjectListItem,
    ProjectListResponse,
    ProjectListSuccessResponse,
)
from src.service.project_service import ProjectService


router = APIRouter(prefix="/project", tags=["project"])


@router.get("/list", response_model=ProjectListResponse)
async def get_project_list() -> ProjectListResponse:
    project_service = ProjectService()
    try:
        project_list = await project_service.get_project_list()
        return ProjectListSuccessResponse(
            data=[ProjectListItem.model_validate(item) for item in project_list]
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))
