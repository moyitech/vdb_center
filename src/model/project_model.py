from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.model.kb_model import APIErrorResponse


class ProjectListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    kb_count: int = Field(..., ge=0, description="项目下KB数量")
    chunk_count: int = Field(..., ge=0, description="项目下有效chunk数量")
    create_time: datetime = Field(..., description="项目首次入库时间")
    update_time: datetime = Field(..., description="项目最近更新时间")


class ProjectListSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: list[ProjectListItem] = Field(default_factory=list, description="项目列表")


ProjectListResponse = ProjectListSuccessResponse | APIErrorResponse
