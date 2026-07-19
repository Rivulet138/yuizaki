from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.repository import NotFoundError
from routes.database_api import create_database_router


class _SessionRepo:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.deleted_messages: list[int] = []
        self.cleared_sessions: list[str] = []
        self.history_calls: list[str] = []
        self.export_json_calls: list[str | None] = []
        self.export_csv_calls: list[str | None] = []

    def get_session_workspace_id(self, session_id: str) -> str:
        if session_id == "missing-session":
            raise NotFoundError(f"session_not_found: {session_id}")
        return "ws-active" if session_id in {"active-session", "folder/active-session"} else "ws-other"

    def get_message_session_id(self, message_id: int) -> str:
        if message_id == 404:
            raise NotFoundError(f"message_not_found: {message_id}")
        if message_id == 1:
            return "active-session"
        return "other-session"

    def get_chat_history(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        self.history_calls.append(session_id)
        return [{"role": "user", "content": "hello", "limit": limit}]

    def get_all_sessions(self) -> list[dict[str, Any]]:
        return [
            {"id": "active-session", "workspace_id": "ws-active"},
            {"id": "other-session", "workspace_id": "ws-other"},
            {"id": "legacy-default-session", "workspace_id": None},
        ]

    def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)

    def clear_session_messages(self, session_id: str) -> dict[str, Any]:
        self.cleared_sessions.append(session_id)
        return {"session_id": session_id, "deleted_count": 2}

    def delete_message(self, message_id: int) -> dict[str, Any]:
        self.deleted_messages.append(message_id)
        return {"message_id": message_id, "session_id": "active-session" if message_id == 1 else "other-session"}

    def get_statistics(self, days: int = 7) -> list[dict[str, Any]]:
        return []

    def update_daily_statistics(self) -> None:
        return None

    def get_database_stats(self) -> dict[str, Any]:
        return {"total_sessions": 0}

    def export_to_json(self, session_id: str | None = None) -> str:
        self.export_json_calls.append(session_id)
        return json.dumps([{"session_id": session_id, "content": "hello"}])

    def export_to_csv(self, session_id: str | None = None) -> str:
        self.export_csv_calls.append(session_id)
        return "Session ID,Content\r\nactive-session,hello\r\n"


def _build_client(repo: _SessionRepo, active_workspace_id: str | None = "ws-active") -> TestClient:
    app = FastAPI()
    app.include_router(
        create_database_router(
            lambda: repo,
            get_active_workspace_id=(lambda: active_workspace_id) if active_workspace_id is not None else None,
        )
    )
    return TestClient(app)


def test_history_rejects_session_outside_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/history/other-session")

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert repo.history_calls == []


def test_history_allows_session_in_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/history/active-session?limit=5")

    assert response.status_code == 200
    assert response.json()["history"][0]["content"] == "hello"
    assert repo.history_calls == ["active-session"]


def test_history_allows_session_when_requested_workspace_matches_owner() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/history/other-session?workspace_id=ws-other")

    assert response.status_code == 200
    assert response.json()["history"][0]["content"] == "hello"
    assert repo.history_calls == ["other-session"]


def test_history_rejects_session_when_requested_workspace_mismatches_owner() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/history/other-session?workspace_id=ws-active")

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"] == "workspace_mismatch"
    assert payload["requested_workspace_id"] == "ws-active"
    assert payload["session_workspace_id"] == "ws-other"
    assert repo.history_calls == []


def test_session_routes_accept_encoded_slash_ids() -> None:
    repo = _SessionRepo()
    client = _build_client(repo)

    history = client.get("/api/history/folder%2Factive-session?limit=2")
    cleared = client.delete("/api/sessions/folder%2Factive-session/messages")
    deleted = client.delete("/api/sessions/folder%2Factive-session")

    assert history.status_code == 200
    assert history.json()["history"][0]["limit"] == 2
    assert repo.history_calls == ["folder/active-session"]
    assert cleared.status_code == 200
    assert cleared.json()["session_id"] == "folder/active-session"
    assert repo.cleared_sessions == ["folder/active-session"]
    assert deleted.status_code == 200
    assert repo.deleted == ["folder/active-session"]


def test_legacy_session_list_filters_to_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/sessions")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["sessions"]] == ["active-session"]


def test_legacy_session_list_keeps_default_unscoped_sessions_for_default_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo, active_workspace_id="default").get("/api/sessions")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["sessions"]] == ["legacy-default-session"]


def test_delete_rejects_session_outside_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/sessions/other-session")

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert repo.deleted == []


def test_delete_allows_session_when_requested_workspace_matches_owner() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/sessions/other-session?workspace_id=ws-other")

    assert response.status_code == 200
    assert repo.deleted == ["other-session"]


def test_clear_session_messages_allows_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/sessions/active-session/messages")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "session_id": "active-session", "deleted_count": 2}
    assert repo.cleared_sessions == ["active-session"]


def test_clear_session_messages_rejects_session_outside_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/sessions/other-session/messages")

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert repo.cleared_sessions == []


def test_delete_message_allows_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/messages/1")

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "session_id": "active-session", "message_id": 1}
    assert repo.deleted_messages == [1]


def test_delete_message_rejects_message_outside_active_workspace() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/messages/2")

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert repo.deleted_messages == []


def test_delete_message_allows_requested_workspace_owner() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/messages/2?workspace_id=ws-other")

    assert response.status_code == 200
    assert response.json()["session_id"] == "other-session"
    assert repo.deleted_messages == [2]


def test_delete_message_returns_404_when_missing() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).delete("/api/messages/404")

    assert response.status_code == 404
    assert response.json() == {"error": "message_not_found: 404"}
    assert repo.deleted_messages == []


def test_export_rejects_session_outside_active_workspace() -> None:
    repo = _SessionRepo()
    json_response = _build_client(repo).post("/api/export/json?session_id=other-session")
    csv_response = _build_client(repo).post("/api/export/csv?session_id=other-session")

    assert json_response.status_code == 403
    assert csv_response.status_code == 403
    assert repo.export_json_calls == []
    assert repo.export_csv_calls == []


def test_export_allows_requested_workspace_owner() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).post("/api/export/json?session_id=other-session&workspace_id=ws-other")

    assert response.status_code == 200
    assert repo.export_json_calls == ["other-session"]


def test_export_all_keeps_legacy_compatibility() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).post("/api/export/json")

    assert response.status_code == 200
    assert repo.export_json_calls == [None]


def test_missing_session_returns_404_before_history_lookup() -> None:
    repo = _SessionRepo()
    response = _build_client(repo).get("/api/history/missing-session")

    assert response.status_code == 404
    assert response.json() == {"error": "session_not_found: missing-session"}
    assert repo.history_calls == []
