from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from src.router.kb import router as kb_router
from src.service.kb_service import KBService


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(kb_router)
    return TestClient(app)


def _kb_item(kb_id: int = 1101) -> dict:
    return {
        "id": kb_id,
        "file_name": "guide.pdf",
        "source": "guide.pdf",
        "date": date(2026, 4, 1),
        "qa_items": False,
        "ingest_status": "succeeded",
        "task_status": "已完成",
        "chunk_count": 12,
        "create_time": datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
        "update_time": datetime(2026, 4, 2, 9, 45, tzinfo=timezone.utc),
    }


def test_get_kb_list_uses_default_pagination(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[int, int, int]] = []

    async def fake_get_kb_list_for_project(
        self,
        project_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        calls.append((project_id, page, page_size))
        return {
            "current_page": page,
            "page_size": page_size,
            "total_pages": 1,
            "total_count": 1,
            "items": [_kb_item()],
        }

    monkeypatch.setattr(KBService, "get_kb_list_for_project", fake_get_kb_list_for_project)

    response = _client().get("/kb/list", params={"project_id": 1001})

    assert response.status_code == 200
    assert calls == [(1001, 1, 20)]
    body = response.json()
    assert body["success"] is True
    assert body["data"]["current_page"] == 1
    assert body["data"]["page_size"] == 20
    assert body["data"]["total_count"] == 1
    assert body["data"]["items"][0]["id"] == 1101


def test_get_kb_list_accepts_explicit_pagination(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[int, int, int]] = []

    async def fake_get_kb_list_for_project(
        self,
        project_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        calls.append((project_id, page, page_size))
        return {
            "current_page": page,
            "page_size": page_size,
            "total_pages": 3,
            "total_count": 25,
            "items": [_kb_item(kb_id=1201)],
        }

    monkeypatch.setattr(KBService, "get_kb_list_for_project", fake_get_kb_list_for_project)

    response = _client().get(
        "/kb/list",
        params={"project_id": 1001, "page": 2, "page_size": 10},
    )

    assert response.status_code == 200
    assert calls == [(1001, 2, 10)]
    body = response.json()
    assert body["data"]["current_page"] == 2
    assert body["data"]["page_size"] == 10
    assert body["data"]["total_pages"] == 3
    assert body["data"]["items"][0]["id"] == 1201


def test_get_kb_list_rejects_invalid_pagination():
    client = _client()

    invalid_page = client.get(
        "/kb/list",
        params={"project_id": 1001, "page": 0},
    )
    invalid_page_size = client.get(
        "/kb/list",
        params={"project_id": 1001, "page_size": 1001},
    )

    assert invalid_page.status_code == 422
    assert invalid_page_size.status_code == 422


def test_source_search_keeps_list_response(monkeypatch: pytest.MonkeyPatch):
    async def fake_search_kb_list_by_source(
        self,
        project_id: int,
        source_keyword: str,
    ) -> list[dict]:
        assert project_id == 1001
        assert source_keyword == "guide"
        return [_kb_item()]

    monkeypatch.setattr(KBService, "search_kb_list_by_source", fake_search_kb_list_by_source)

    response = _client().get(
        "/kb/source/search",
        params={"project_id": 1001, "source_keyword": " guide "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert body["data"][0]["id"] == 1101
