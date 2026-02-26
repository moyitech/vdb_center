from datetime import datetime, date as DateType
from typing import Annotated, Literal

from fastapi import Path, Query
from pydantic import BaseModel, ConfigDict, Field


IngestStatus = Literal["ingesting", "succeeded", "failed"]

ProjectIdQuery = Annotated[int, Query(..., gt=0, description="项目ID")]
KbIdPath = Annotated[int, Path(..., gt=0, description="知识库ID")]
ItemIdPath = Annotated[int, Path(..., gt=0, description="QA条目ID")]
SourceQuery = Annotated[str, Query(..., min_length=1, description="来源")]
SourceKeywordQuery = Annotated[str, Query(..., min_length=1, description="来源关键词")]
QAPageQuery = Annotated[
    int,
    Query(ge=1, description="页码（从1开始）"),
]
QAPageSizeQuery = Annotated[
    int,
    Query(ge=1, le=1000, description="每页条数"),
]


class APIErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[False] = Field(
        default=False,
        description="是否成功，失败时固定为 false",
    )
    error: str = Field(..., min_length=1, description="错误信息")


class UploadSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(
        default=True,
        description="是否成功，成功时固定为 true",
    )
    kb_id: int = Field(..., gt=0, description="入库任务对应的KB ID")
    message: str = Field(..., min_length=1, description="任务启动结果信息")


UploadResponse = UploadSuccessResponse | APIErrorResponse


class SourceExistsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="来源")
    exists: bool = Field(..., description="是否已存在")


class SourceExistsSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: SourceExistsData = Field(..., description="来源存在性检查结果")


SourceExistsResponse = SourceExistsSuccessResponse | APIErrorResponse


class KBListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., gt=0, description="KB ID")
    file_name: str | None = Field(default=None, description="KB文件名")
    source: str | None = Field(default=None, description="来源文件名或URL")
    date: DateType | None = Field(default=None, description="信息产生日期")
    qa_items: bool = Field(..., description="是否QA专用KB")
    ingest_status: IngestStatus = Field(..., description="入库状态")
    task_status: str | None = Field(default=None, description="任务状态（中文）")
    chunk_count: int = Field(..., ge=0, description="当前有效chunk数量")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime = Field(..., description="更新时间")


class KBListSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: list[KBListItem] = Field(default_factory=list, description="项目KB列表")


KBListResponse = KBListSuccessResponse | APIErrorResponse


class KBTaskStatusData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., gt=0, description="KB ID")
    project_id: int = Field(..., gt=0, description="项目ID")
    file_name: str | None = Field(default=None, description="KB文件名")
    qa_items: bool = Field(..., description="是否QA专用KB")
    ingest_status: IngestStatus = Field(..., description="入库状态")
    task_status: str | None = Field(default=None, description="任务状态（中文）")
    success_count: int = Field(..., ge=0, description="最近一次上传成功写入数量")
    failed_count: int = Field(..., ge=0, description="最近一次上传未写入数量")
    chunk_count: int = Field(..., ge=0, description="当前有效chunk数量")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime = Field(..., description="更新时间")


class KBTaskStatusSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: KBTaskStatusData = Field(..., description="任务状态数据")


KBTaskStatusResponse = KBTaskStatusSuccessResponse | APIErrorResponse


KBDeleteReason = Literal[
    "deleted",
    "not_found",
    "already_deleted",
    "qa_kb_forbidden",
    "ingesting_forbidden",
]


class KBDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    kb_id: int = Field(..., gt=0, description="待删除KB ID")


class KBDeleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: int = Field(..., gt=0, description="KB ID")
    project_id: int = Field(..., gt=0, description="项目ID")
    kb_deleted: bool = Field(..., description="是否执行了KB删除")
    item_deleted_count: int = Field(..., ge=0, description="实际软删除的item数量")
    reason: KBDeleteReason = Field(..., description="删除结果原因")


class KBDeleteSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: KBDeleteData = Field(..., description="删除KB结果")


KBDeleteResponse = KBDeleteSuccessResponse | APIErrorResponse


class QACreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="问题")
    answer: str = Field(..., min_length=1, description="答案")


class QABatchDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    item_ids: list[Annotated[int, Field(gt=0)]] = Field(
        ...,
        min_length=1,
        description="待删除的item id列表（正整数）",
    )


class QAUpdateItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    item_id: int = Field(..., gt=0, description="更新条目ID")
    question: str = Field(..., min_length=1, description="问题")
    answer: str = Field(..., min_length=1, description="答案")


class QADeleteItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    item_id: int = Field(..., gt=0, description="删除条目ID")


class QAAddItemData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: int = Field(..., gt=0, description="QA专用KB ID")
    item_id: int | None = Field(default=None, gt=0, description="新增条目ID")
    chunk_index: int | None = Field(default=None, ge=0, description="新增条目的chunk序号")
    skipped: bool | None = Field(default=None, description="是否被跳过（例如去重）")
    reason: str | None = Field(default=None, description="跳过原因")


class QAAddItemSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: QAAddItemData = Field(..., description="新增单条QA结果")


QAAddItemResponse = QAAddItemSuccessResponse | APIErrorResponse


class QAUpdateItemData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: int = Field(..., gt=0, description="QA专用KB ID")
    item_id: int = Field(..., gt=0, description="更新条目ID")


class QAUpdateItemSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: QAUpdateItemData = Field(..., description="更新单条QA结果")


QAUpdateItemResponse = QAUpdateItemSuccessResponse | APIErrorResponse


class QADeleteItemsData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: int = Field(..., gt=0, description="QA专用KB ID")
    requested_count: int = Field(..., ge=1, description="请求删除的条数")
    deleted_count: int = Field(..., ge=0, description="实际删除的条数")


class QADeleteItemsSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: QADeleteItemsData = Field(..., description="删除QA结果")


QADeleteItemsResponse = QADeleteItemsSuccessResponse | APIErrorResponse


class QAListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., gt=0, description="item ID")
    kb_id: int = Field(..., gt=0, description="所属KB ID")
    chunk_index: int = Field(..., ge=0, description="chunk序号")
    source: str | None = Field(default=None, description="来源文件名或URL")
    date: DateType | None = Field(default=None, description="信息产生日期")
    question: str | None = Field(default=None, description="问题")
    answer: str | None = Field(default=None, description="答案")
    create_time: datetime = Field(..., description="创建时间")
    update_time: datetime = Field(..., description="更新时间")


class QAListData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kb_id: int | None = Field(default=None, gt=0, description="QA专用KB ID，若不存在则为null")
    current_page: int = Field(..., ge=1, description="当前页码")
    page_size: int = Field(..., ge=1, description="每页条数")
    total_pages: int = Field(..., ge=0, description="总页数")
    total_count: int = Field(..., ge=0, description="总数量")
    items: list[QAListItem] = Field(default_factory=list, description="QA条目列表")


class QAListSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: QAListData = Field(..., description="QA列表数据")


QAListResponse = QAListSuccessResponse | APIErrorResponse


class RetrieveHybridRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int = Field(..., gt=0, description="项目ID")
    dense_query: str | None = Field(
        default=None,
        description="向量检索查询；为空时不执行 dense 召回",
    )
    bm25_query: str | None = Field(
        default=None,
        description="BM25 检索查询；为空时不执行 BM25 召回",
    )
    top_k_embedding: int = Field(
        default=10,
        ge=0,
        le=100,
        description="向量检索返回条数",
    )
    top_k_bm25: int = Field(
        default=10,
        ge=0,
        le=100,
        description="BM25检索返回条数",
    )


class RetrieveItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., gt=0, description="item ID")
    text: str = Field(..., description="文本内容")
    source: str | None = Field(default=None, description="来源文件名或URL")
    date: DateType | None = Field(default=None, description="信息产生日期")
    score: float = Field(..., description="相似度或相关度得分")


class RetrieveHybridData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dense: list[RetrieveItem] = Field(default_factory=list, description="向量检索结果")
    bm25: list[RetrieveItem] = Field(default_factory=list, description="BM25检索结果")
    merged_results: list[RetrieveItem] = Field(default_factory=list, description="合并去重结果")


class RetrieveHybridSuccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: Literal[True] = Field(default=True, description="是否成功")
    data: RetrieveHybridData = Field(..., description="混合检索结果")


RetrieveHybridResponse = RetrieveHybridSuccessResponse | APIErrorResponse
