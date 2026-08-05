from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.repository import NotFoundError
from routes.summary_api import create_summary_router


def _limiter():
    return SimpleNamespace(check=lambda _key: SimpleNamespace(allowed=True, retry_after=0))


class FakeGenerationManager:
    def __init__(self) -> None:
        timestamp = datetime.now().isoformat()
        self.audit_logs = [
            {
                "timestamp": timestamp,
                "session_id": "s-active",
                "source": "auto",
                "outcome": "ok",
                "detail": "active",
            },
            {
                "timestamp": timestamp,
                "session_id": "s-other",
                "source": "auto",
                "outcome": "ok",
                "detail": "other",
            },
            {
                "timestamp": timestamp,
                "session_id": "s-missing",
                "source": "auto",
                "outcome": "ok",
                "detail": "stale",
            },
        ]

    def list_summary_session_ids(self) -> list[str]:
        return ["s-active", "s-other", "s-missing"]

    def get_summary(self, session_id: str) -> str:
        return f"summary:{session_id}"

    def get_summary_stats(self, session_id: str) -> dict[str, Any]:
        return {
            "sid": session_id,
            "quality": {
                "overall": 90,
                "facts": 80,
                "preferences": 70,
                "goals_open_tasks": 60,
            },
        }

    def get_summary_audit(self, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self.audit_logs
        if session_id is not None:
            logs = [item for item in logs if item.get("session_id") == session_id]
        return logs[:limit]


class FakeRepo:
    def __init__(self) -> None:
        self.workspace_by_session = {
            "s-active": "ws-active",
            "s/active": "ws-active",
            "s-other": "ws-other",
        }

    def get_session_workspace_id(self, session_id: str) -> str:
        try:
            return self.workspace_by_session[session_id]
        except KeyError as exc:
            raise NotFoundError(f"session_not_found: {session_id}") from exc


class FakeLlmClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def rewrite_session_summary(self, _generation_mgr: Any, session_id: str, source: str = "manual") -> dict[str, Any]:
        self.calls.append((session_id, source))
        return {"ok": True, "session_id": session_id, "source": source}


def _build_client(
    admin_token: str,
    *,
    generation_mgr: Any | None = None,
    llm_client: Any | None = None,
    db_repo: Any | None = None,
    active_workspace_id: str | None = None,
) -> tuple[TestClient, dict[str, dict[str, object]]]:
    alert_state: dict[str, dict[str, object]] = {"demo": {"acked": False}}
    app = FastAPI()
    app.include_router(
        create_summary_router(
            get_generation_mgr=lambda: generation_mgr,
            get_llm_client=lambda: llm_client,
            get_summary_list_limiter=_limiter,
            get_summary_detail_limiter=_limiter,
            get_summary_rewrite_limiter=_limiter,
            get_governance_alert_state=lambda: alert_state,
            save_governance_alert_state=lambda: None,
            get_summary_admin_token=lambda: admin_token,
            get_db_repo=lambda: db_repo,
            get_active_workspace_id=lambda: active_workspace_id or "",
        )
    )
    return TestClient(app), alert_state


def test_summary_alert_mutations_require_admin_token_when_configured() -> None:
    client, alert_state = _build_client("secret")

    unauthorized = client.post("/api/summary/alerts/clear")
    authorized = client.post("/api/summary/alerts/clear", headers={"Authorization": "Bearer secret"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert alert_state == {}


def test_summary_admin_token_header_is_independent_from_backend_authorization() -> None:
    client, alert_state = _build_client("summary-secret")

    authorized = client.post(
        "/api/summary/alerts/clear",
        headers={
            "Authorization": "Bearer backend-secret",
            "x-yuizaki-admin-token": "summary-secret",
        },
    )

    assert authorized.status_code == 200
    assert alert_state == {}


def test_summary_admin_token_header_takes_precedence_over_legacy_bearer() -> None:
    client, alert_state = _build_client("summary-secret")

    rejected = client.post(
        "/api/summary/alerts/clear",
        headers={
            "Authorization": "Bearer summary-secret",
            "x-yuizaki-admin-token": "wrong-secret",
        },
    )

    assert rejected.status_code == 401
    assert alert_state == {"demo": {"acked": False}}


def test_summary_audit_static_route_is_not_captured_by_session_detail() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/audit")

    assert response.status_code == 200
    payload = response.json()
    assert "logs" in payload
    assert "summary" not in payload
    assert [item["session_id"] for item in payload["logs"]] == ["s-active"]


def test_summary_detail_rejects_cross_workspace_session() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/s-other")

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"


def test_summary_detail_allows_active_workspace_session() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/s-active")

    assert response.status_code == 200
    assert response.json()["summary"] == "summary:s-active"


def test_summary_detail_accepts_encoded_slash_session_ids() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/s%2Factive")

    assert response.status_code == 200
    assert response.json()["summary"] == "summary:s/active"


def test_summary_list_filters_to_active_workspace_sessions() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary")

    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert [item["session_id"] for item in sessions] == ["s-active"]


def test_summary_audit_rejects_explicit_cross_workspace_session() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/audit", params={"session_id": "s-other"})

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"


def test_summary_report_filters_sessions_and_audit_to_active_workspace() -> None:
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.get("/api/summary/report/json")

    assert response.status_code == 200
    report = response.json()
    assert [item["session_id"] for item in report["sessions"]] == ["s-active"]
    assert [item["session_id"] for item in report["audit"]] == ["s-active"]


def test_summary_rewrite_rejects_cross_workspace_before_llm_call() -> None:
    llm_client = FakeLlmClient()
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        llm_client=llm_client,
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.post("/api/summary/s-other/rewrite", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert llm_client.calls == []


def test_summary_rewrite_allows_active_workspace_session() -> None:
    llm_client = FakeLlmClient()
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        llm_client=llm_client,
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.post("/api/summary/s-active/rewrite", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert llm_client.calls == [("s-active", "manual")]


def test_summary_rewrite_accepts_encoded_slash_session_ids() -> None:
    llm_client = FakeLlmClient()
    client, _alert_state = _build_client(
        "secret",
        generation_mgr=FakeGenerationManager(),
        llm_client=llm_client,
        db_repo=FakeRepo(),
        active_workspace_id="ws-active",
    )

    response = client.post("/api/summary/s%2Factive/rewrite", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json()["session_id"] == "s/active"
    assert llm_client.calls == [("s/active", "manual")]
