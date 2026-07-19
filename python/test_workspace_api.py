from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.repository import NotFoundError
from routes.workspace_api import create_workspace_router


class _MissingWorkspaceRepo:
    def __init__(self) -> None:
        self.updates: list[str] = []

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [
            {"id": "default"},
            {"id": "team/alpha", "tool_preset": '["read_file"]', "mcp_preset_id": "local"},
        ]

    def get_session_workspace_id(self, session_id: str) -> str:
        if session_id == "other-session":
            return "ws-other"
        if session_id == "active-session":
            return "ws-active"
        raise NotFoundError(f"session_not_found: {session_id}")

    def list_workspace_sessions(self, workspace_id: str) -> list[dict[str, Any]]:
        if workspace_id == "team/alpha":
            return [{"id": "session-1", "workspace_id": workspace_id}]
        raise NotFoundError(f"workspace_not_found: {workspace_id}")

    def create_chat_session(self, workspace_id: str, title: str | None = None) -> dict[str, Any]:
        if workspace_id == "team/alpha":
            return {"id": "session-new", "workspace_id": workspace_id, "title": title}
        raise NotFoundError(f"workspace_not_found: {workspace_id}")

    def update_workspace(self, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"id": workspace_id, **payload}

    def delete_workspace(self, workspace_id: str) -> None:
        self.updates.append(workspace_id)

    def update_chat_session(
        self,
        session_id: str,
        *,
        summary: str | None = None,
        pinned: bool | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        self.updates.append(session_id)
        raise NotFoundError(f"session_not_found: {session_id}")


def _build_client(active_workspace_id: str | None = None) -> tuple[TestClient, _MissingWorkspaceRepo]:
    app = FastAPI()
    repo = _MissingWorkspaceRepo()
    app.include_router(
        create_workspace_router(
            lambda: repo,
            get_active_workspace_id=(lambda: active_workspace_id) if active_workspace_id is not None else None,
        )
    )
    return TestClient(app), repo


def test_list_workspace_sessions_returns_404_for_unknown_workspace() -> None:
    client, _repo = _build_client()
    response = client.get("/api/workspaces/missing/sessions")

    assert response.status_code == 404
    assert response.json() == {"error": "workspace_not_found: missing"}


def test_create_workspace_session_returns_404_for_unknown_workspace() -> None:
    client, _repo = _build_client()
    response = client.post("/api/workspaces/missing/sessions", json={"title": "Ghost"})

    assert response.status_code == 404
    assert response.json() == {"error": "workspace_not_found: missing"}


def test_workspace_routes_accept_encoded_slash_ids() -> None:
    client, repo = _build_client()

    sessions = client.get("/api/workspaces/team%2Falpha/sessions")
    created = client.post("/api/workspaces/team%2Falpha/sessions", json={"title": "Slash"})
    updated = client.patch("/api/workspaces/team%2Falpha", json={"name": "Alpha"})
    preset = client.get("/api/workspaces/team%2Falpha/effective-preset")
    deleted = client.delete("/api/workspaces/team%2Falpha")

    assert sessions.status_code == 200
    assert sessions.json()["workspace_id"] == "team/alpha"
    assert sessions.json()["sessions"][0]["workspace_id"] == "team/alpha"
    assert created.status_code == 200
    assert created.json()["workspace_id"] == "team/alpha"
    assert updated.status_code == 200
    assert updated.json() == {"id": "team/alpha", "name": "Alpha"}
    assert preset.status_code == 200
    assert preset.json()["workspace_id"] == "team/alpha"
    assert preset.json()["tool_names"] == ["read_file"]
    assert deleted.status_code == 200
    assert repo.updates[-1] == "team/alpha"


def test_create_workspace_uses_desktop_pet_scene_wording_by_default() -> None:
    class _CreateWorkspaceRepo(_MissingWorkspaceRepo):
        def create_workspace(
            self,
            workspace_id: str,
            name: str,
            description: str | None = None,
        ) -> dict[str, Any]:
            return {"id": workspace_id, "name": name, "description": description}

    app = FastAPI()
    app.include_router(create_workspace_router(lambda: _CreateWorkspaceRepo()))

    with TestClient(app) as client:
        response = client.post("/api/workspaces", json={"id": "quiet"})

    assert response.status_code == 200
    assert response.json()["name"] == "新场景"


def test_update_session_returns_404_for_unknown_session() -> None:
    client, _repo = _build_client()
    response = client.patch("/api/sessions/missing-session", json={"title": "Ghost"})

    assert response.status_code == 404
    assert response.json() == {"error": "session_not_found: missing-session"}


def test_update_session_rejects_session_outside_active_workspace() -> None:
    client, repo = _build_client(active_workspace_id="ws-active")
    response = client.patch("/api/sessions/other-session", json={"title": "Nope"})

    assert response.status_code == 403
    assert response.json()["error"] == "workspace_mismatch"
    assert repo.updates == []


def test_update_session_allows_requested_workspace_owner() -> None:
    client, repo = _build_client(active_workspace_id="ws-active")
    response = client.patch("/api/sessions/other-session?workspace_id=ws-other", json={"title": "Pinned"})

    assert response.status_code == 404
    assert response.json() == {"error": "session_not_found: other-session"}
    assert repo.updates == ["other-session"]


def test_slow_workspace_repo_call_does_not_block_event_loop() -> None:
    class _SlowRepo(_MissingWorkspaceRepo):
        def list_workspaces(self) -> list[dict[str, Any]]:
            time.sleep(0.2)
            return [{"id": "default"}]

    app = FastAPI()
    repo = _SlowRepo()
    app.include_router(create_workspace_router(lambda: repo))

    @app.get("/api/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        result: dict[str, int] = {}

        def call_slow_route() -> None:
            result["status"] = client.get("/api/workspaces").status_code

        worker = threading.Thread(target=call_slow_route)
        worker.start()
        time.sleep(0.03)

        start = time.perf_counter()
        ping_response = client.get("/api/ping")
        elapsed = time.perf_counter() - start
        worker.join(timeout=1)

    assert ping_response.status_code == 200
    assert ping_response.json() == {"ok": True}
    assert elapsed < 0.15
    assert result["status"] == 200
