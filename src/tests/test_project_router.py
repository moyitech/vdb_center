from datetime import datetime, timezone

import pytest
from fastapi import FastAPI

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from src.router.project import router as project_router
from src.service.project_service import ProjectService


def test_get_project_list(monkeypatch: pytest.MonkeyPatch):
    async def fake_get_project_list(self) -> list[dict]:
        return [
            {
                "project_id": 1101,
                "kb_count": 3,
                "chunk_count": 28,
                "create_time": datetime(2026, 4, 1, 8, 30, tzinfo=timezone.utc),
                "update_time": datetime(2026, 4, 5, 9, 45, tzinfo=timezone.utc),
            }
        ]

    monkeypatch.setattr(ProjectService, "get_project_list", fake_get_project_list)

    app = FastAPI()
    app.include_router(project_router)
    client = TestClient(app)

    response = client.get("/project/list")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"][0]["project_id"] == 1101
    assert body["data"][0]["kb_count"] == 3
    assert body["data"][0]["chunk_count"] == 28
    assert body["data"][0]["create_time"]
    assert body["data"][0]["update_time"]
