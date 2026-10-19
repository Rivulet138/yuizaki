from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.system.workspace_context_store import WorkspaceContextStore
from routes.workspace_api import create_workspace_router


class _FakeRepo:
    def __init__(self) -> None:
        self.workspaces = {
            "default": {
                "id": "default",
                "name": "Default",
                "description": None,
                "icon": None,
                "color": None,
                "companion_profile_id": "default",
                "default_model": None,
                "system_prompt": None,
                "tool_preset": None,
                "memory_scope": "workspace",
                "mcp_preset_id": None,
                "created_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        }

    def list_workspaces(self):
        return list(self.workspaces.values())

    def create_workspace(self, *, workspace_id: str, name: str, description=None):
        workspace = {
            **self.workspaces["default"],
            "id": workspace_id,
            "name": name,
            "description": description,
        }
        self.workspaces[workspace_id] = workspace
        return workspace

    def update_workspace(self, workspace_id: str, updates: dict):
        workspace = self.workspaces[workspace_id]
        workspace.update(updates)
        return workspace

    def delete_workspace(self, workspace_id: str):
        self.workspaces.pop(workspace_id, None)


def _client(tmp_path):
    repo = _FakeRepo()
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    app = FastAPI()
    app.include_router(create_workspace_router(lambda: repo, context_store=store))
    return TestClient(app), repo, store


def test_workspace_context_is_stored_and_returned_with_list(tmp_path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.patch("/api/workspaces/default", json={
        "context": {"roleCard": {"enabled": True, "name": "A"}},
    })

    assert response.status_code == 200
    assert response.json()["context"]["roleCard"]["name"] == "A"
    listed = client.get("/api/workspaces").json()["workspaces"]
    assert listed[0]["context"]["roleCard"]["name"] == "A"


def test_workspace_create_and_delete_manage_context(tmp_path) -> None:
    client, _, store = _client(tmp_path)

    created = client.post("/api/workspaces", json={
        "id": "scene-a",
        "name": "Scene A",
        "context": {"worldBook": {"enabled": True}},
    })
    assert created.status_code == 200
    assert created.json()["context"]["worldBook"]["enabled"] is True
    assert store.get("scene-a") == {"worldBook": {"enabled": True}}

    deleted = client.delete("/api/workspaces/scene-a")
    assert deleted.status_code == 200
    assert store.get("scene-a") is None


def test_workspace_context_rejects_non_object_payload(tmp_path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.patch("/api/workspaces/default", json={"context": ["bad"]})

    assert response.status_code == 400


def test_workspace_context_null_clears_existing_context(tmp_path) -> None:
    client, _, store = _client(tmp_path)
    client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})

    response = client.patch("/api/workspaces/default", json={"context": None})

    assert response.status_code == 200
    assert response.json()["context"] is None
    assert store.get("default") is None
