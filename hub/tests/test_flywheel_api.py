from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub.app import flywheel_api


@contextmanager
def _fake_session_scope():
    yield object()


def test_list_flywheel_tasks_returns_canonical_and_compatibility_keys(monkeypatch):
    monkeypatch.setattr(flywheel_api, "_session_scope", _fake_session_scope)
    monkeypatch.setattr(
        flywheel_api.crud,
        "list_flywheel_tasks",
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=7,
                cycle_id=2,
                strategy_version_id=3,
                finding_id=5,
                action="investigate",
                title="Task title",
                details="Task details",
                priority=20,
                status="open",
                lane="fast_flow",
                environment="paper",
                source_kind="policy_cycle",
                source_ref="cycle:abc",
                metadata_json={"owner": "ops"},
                created_at=SimpleNamespace(isoformat=lambda: "2026-03-11T10:00:00+00:00"),
            )
        ],
    )

    app = FastAPI()
    app.include_router(flywheel_api.router)
    client = TestClient(app)

    response = client.get("/api/v1/flywheel/tasks")
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 1
    assert body["tasks"][0]["task_id"] == 7
    assert body["tasks"][0]["id"] == 7
    assert body["tasks"][0]["task_status"] == "open"
    assert body["tasks"][0]["status"] == "open"
    assert body["tasks"] == body["items"]


def test_list_flywheel_findings_returns_canonical_and_compatibility_keys(monkeypatch):
    monkeypatch.setattr(flywheel_api, "_session_scope", _fake_session_scope)
    monkeypatch.setattr(
        flywheel_api.crud,
        "list_flywheel_findings",
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=11,
                finding_key="finding-11",
                cycle_id=2,
                strategy_version_id=3,
                lane="fast_flow",
                environment="paper",
                source_kind="policy_cycle",
                finding_type="promotion_signal",
                title="Finding title",
                summary="Finding summary",
                lesson="Finding lesson",
                evidence={"k": "v"},
                priority=10,
                confidence=0.9,
                status="open",
                created_at=SimpleNamespace(isoformat=lambda: "2026-03-11T10:00:00+00:00"),
            )
        ],
    )

    app = FastAPI()
    app.include_router(flywheel_api.router)
    client = TestClient(app)

    response = client.get("/api/v1/flywheel/findings")
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 1
    assert body["findings"][0]["finding_id"] == 11
    assert body["findings"][0]["id"] == 11
    assert body["findings"][0]["finding_status"] == "open"
    assert body["findings"][0]["status"] == "open"
    assert body["findings"] == body["items"]
