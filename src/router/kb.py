from fastapi.routing import APIRouter
from fastapi import UploadFile, File, BackgroundTasks, Form
from pathlib import Path
from datetime import date
from src.service.kb_service import KBService, PRESET_QA_SOURCE
from src.model.kb_model import (
    APIErrorResponse,
    KBDeleteData,
    KBDeleteRequest,
    KBDeleteResponse,
    KBDeleteSuccessResponse,
    KbIdPath,
    KBListItem,
    KBListResponse,
    KBListSuccessResponse,
    KBTaskStatusData,
    KBTaskStatusResponse,
    KBTaskStatusSuccessResponse,
    ProjectIdQuery,
    QABatchDeleteRequest,
    QAAddItemData,
    QACreateRequest,
    QADeleteItemRequest,
    QAAddItemResponse,
    QAAddItemSuccessResponse,
    QADeleteItemsData,
    QADeleteItemsResponse,
    QADeleteItemsSuccessResponse,
    QAListData,
    QAListResponse,
    QAListSuccessResponse,
    QAPageQuery,
    QAPageSizeQuery,
    QAUpdateItemRequest,
    QAUpdateItemData,
    QAUpdateItemResponse,
    QAUpdateItemSuccessResponse,
    RetrieveHybridData,
    RetrieveHybridRequest,
    RetrieveHybridResponse,
    RetrieveHybridSuccessResponse,
    SourceKeywordQuery,
    SourceExistsData,
    SourceExistsResponse,
    SourceExistsSuccessResponse,
    SourceQuery,
    UploadResponse,
    UploadSuccessResponse,
)

router = APIRouter(prefix="/kb", tags=["kb"])
SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".docx", ".txt", ".xlsx", ".xlsm"}


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    project_id: ProjectIdQuery,
    source: str | None = Form(default=None, description="来源（可选）"),
    info_date: date | None = Form(default=None, alias="date", description="信息产生日期（YYYY-MM-DD）"),
    file: UploadFile = File(...),
) -> UploadResponse:
    kb_service = KBService()

    # 上传入口先校验后缀，避免后续创建KB后才在读取阶段失败
    if not file.filename:
        return APIErrorResponse(error="Uploaded file must have a filename.")
    upload_suffix = Path(file.filename).suffix.lower()
    if upload_suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        display_suffix = upload_suffix if upload_suffix else "(none)"
        return APIErrorResponse(
            error=(
                f"Unsupported file type: {display_suffix}. "
                "Only .pdf, .docx, .txt, .xlsx and .xlsm are supported."
            )
        )

    try:
        append_to_existing = False
        dedup_origin_text = False

        if upload_suffix in {".xlsx", ".xlsm"}:
            normalized_source = PRESET_QA_SOURCE
            # 判断是否为QA专用KB（.xlsx/.xlsm），如果是则使用或创建项目级QA KB，并且入库时追加到现有KB中，同时启用原始文本去重
            append_to_existing = True
            dedup_origin_text = True
        else:
            normalized_source = (source or "").strip() or Path(file.filename).name
            if await kb_service.exists_non_qa_source(
                project_id=project_id,
                source=normalized_source,
            ):
                return APIErrorResponse(
                    error=f"该来源在当前项目中已存在：{normalized_source}"
                )
    except Exception as e:
        return APIErrorResponse(error=str(e))

    try:
        file_path = await kb_service.save_file_to_storage(file, project_id=project_id, kb_name="uploaded_kb")
    except Exception as e:
        return APIErrorResponse(error=str(e))

    try:
        if upload_suffix in {".xlsx", ".xlsm"}:
            kb_id = await kb_service.get_or_create_project_qa_kb(project_id=project_id)
        else:
            # 对于非QA专用KB（如pdf/txt/docx），正常创建一个新的KB记录
            kb_id = await kb_service.create_kb_ingest_task(
                kb_name=file_path.name,
                project_id=project_id,
                source=normalized_source,
                info_date=info_date,
            )

        background_tasks.add_task(
            kb_service.run_kb_ingest_task,
            kb_id,
            file_path.as_posix(),
            project_id,
            append_to_existing,
            dedup_origin_text,
            normalized_source,
            info_date,
        )
        return UploadSuccessResponse(
            kb_id=kb_id,
            message="Ingestion task started in background",
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.get("/list", response_model=KBListResponse)
async def get_project_kb_list(project_id: ProjectIdQuery) -> KBListResponse:
    kb_service = KBService()
    try:
        kb_list = await kb_service.get_kb_list_for_project(project_id)
        return KBListSuccessResponse(
            data=[KBListItem.model_validate(item) for item in kb_list]
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.get("/source/search", response_model=KBListResponse)
async def search_kb_by_source(
    project_id: ProjectIdQuery,
    source_keyword: SourceKeywordQuery,
) -> KBListResponse:
    kb_service = KBService()
    try:
        normalized_keyword = source_keyword.strip()
        if not normalized_keyword:
            return APIErrorResponse(error="source_keyword 不能为空")
        kb_list = await kb_service.search_kb_list_by_source(
            project_id=project_id,
            source_keyword=normalized_keyword,
        )
        return KBListSuccessResponse(
            data=[KBListItem.model_validate(item) for item in kb_list]
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.get("/source/exists", response_model=SourceExistsResponse)
async def check_source_exists(
    project_id: ProjectIdQuery,
    source: SourceQuery,
) -> SourceExistsResponse:
    kb_service = KBService()
    try:
        normalized_source = source.strip()
        if not normalized_source:
            return APIErrorResponse(error="source 不能为空")
        exists = await kb_service.exists_non_qa_source(
            project_id=project_id,
            source=normalized_source,
        )
        return SourceExistsSuccessResponse(
            data=SourceExistsData(
                source=normalized_source,
                exists=exists,
            )
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.get("/task/{kb_id}", response_model=KBTaskStatusResponse)
async def get_kb_ingest_task_status(project_id: ProjectIdQuery, kb_id: KbIdPath) -> KBTaskStatusResponse:
    kb_service = KBService()
    try:
        task_status = await kb_service.get_kb_ingest_task_status(project_id, kb_id)
        if task_status is None:
            return APIErrorResponse(error="Task not found")
        return KBTaskStatusSuccessResponse(
            data=KBTaskStatusData.model_validate(task_status)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/delete", response_model=KBDeleteResponse)
async def delete_kb(
    payload: KBDeleteRequest,
) -> KBDeleteResponse:
    kb_service = KBService()
    try:
        data = await kb_service.delete_kb(
            project_id=payload.project_id,
            kb_id=payload.kb_id,
        )
        return KBDeleteSuccessResponse(
            data=KBDeleteData.model_validate(data)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/qa/item", response_model=QAAddItemResponse)
async def add_single_qa_item(project_id: ProjectIdQuery, payload: QACreateRequest) -> QAAddItemResponse:
    kb_service = KBService()
    try:
        data = await kb_service.add_single_qa_item(
            project_id=project_id,
            question=payload.question,
            answer=payload.answer,
        )
        return QAAddItemSuccessResponse(data=QAAddItemData.model_validate(data))
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/qa/item/update", response_model=QAUpdateItemResponse)
async def update_qa_item(
    payload: QAUpdateItemRequest,
) -> QAUpdateItemResponse:
    kb_service = KBService()
    try:
        data = await kb_service.update_qa_item(
            project_id=payload.project_id,
            item_id=payload.item_id,
            question=payload.question,
            answer=payload.answer,
        )
        return QAUpdateItemSuccessResponse(
            data=QAUpdateItemData.model_validate(data)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/qa/item/delete", response_model=QADeleteItemsResponse)
async def delete_single_qa_item(
    payload: QADeleteItemRequest,
) -> QADeleteItemsResponse:
    kb_service = KBService()
    try:
        data = await kb_service.delete_single_qa_item(
            project_id=payload.project_id,
            item_id=payload.item_id,
        )
        return QADeleteItemsSuccessResponse(
            data=QADeleteItemsData.model_validate(data)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/qa/items/delete", response_model=QADeleteItemsResponse)
async def delete_multi_qa_items(
    payload: QABatchDeleteRequest,
) -> QADeleteItemsResponse:
    kb_service = KBService()
    try:
        data = await kb_service.delete_multi_qa_items(
            project_id=payload.project_id,
            item_ids=payload.item_ids,
        )
        return QADeleteItemsSuccessResponse(
            data=QADeleteItemsData.model_validate(data)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.get("/qa/list", response_model=QAListResponse)
async def get_qa_list(
    project_id: ProjectIdQuery,
    page: QAPageQuery = 1,
    page_size: QAPageSizeQuery = 20,
) -> QAListResponse:
    kb_service = KBService()
    try:
        data = await kb_service.get_qa_list(
            project_id=project_id,
            page=page,
            page_size=page_size,
        )
        return QAListSuccessResponse(data=QAListData.model_validate(data))
    except Exception as e:
        return APIErrorResponse(error=str(e))


@router.post("/retrieve/hybrid", response_model=RetrieveHybridResponse)
async def retrieve_hybrid(payload: RetrieveHybridRequest) -> RetrieveHybridResponse:
    kb_service = KBService()
    try:
        data = await kb_service.retrieve_hybrid(
            dense_query=payload.dense_query,
            bm25_query=payload.bm25_query,
            project_id=payload.project_id,
            top_k_embedding=payload.top_k_embedding,
            top_k_bm25=payload.top_k_bm25,
        )
        return RetrieveHybridSuccessResponse(
            data=RetrieveHybridData.model_validate(data)
        )
    except Exception as e:
        return APIErrorResponse(error=str(e))
