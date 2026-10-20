from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from database.repository import ContextRevisionConflict, DatabaseError, NotFoundError
from routes.workspace_api import create_workspace_router

_UNSET = object()

_BASE_WORKSPACE = {
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


class _FakeRepo:
    """Mirrors the repository's atomic context contract without SQLite."""

    def __init__(self) -> None:
        self.workspaces = {
            "default": {
                **_BASE_WORKSPACE,
                "id": "default",
                "name": "Default",
                "context": None,
                "contextRevision": 0,
            }
        }

    def list_workspaces(self):
        return [deepcopy(workspace) for workspace in self.workspaces.values()]

    def create_workspace(self, *, workspace_id: str, name: str, description=None, context=None):
        if workspace_id in self.workspaces:
            raise DatabaseError("workspace_exists")
        workspace = {
            **_BASE_WORKSPACE,
            "id": workspace_id,
            "name": name,
            "description": description,
            "context": deepcopy(context),
            "contextRevision": 1 if context is not None else 0,
        }
        self.workspaces[workspace_id] = workspace
        return deepcopy(workspace)

    def update_workspace(
        self,
        workspace_id: str,
        updates: dict,
        *,
        context=_UNSET,
        expected_context_revision: int | None = None,
    ):
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise NotFoundError(f"workspace_not_found: {workspace_id}")
        current = workspace["contextRevision"]
        if expected_context_revision is not None and expected_context_revision != current:
            raise ContextRevisionConflict(
                workspace_id,
                expected_context_revision,
                current,
                deepcopy(workspace["context"]),
            )
        workspace.update(updates)
        if context is not _UNSET:
            workspace["context"] = deepcopy(context)
            workspace["contextRevision"] = current + 1
        return deepcopy(workspace)

    def delete_workspace(self, workspace_id: str, *, expected_context_revision: int | None = None):
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise NotFoundError(f"workspace_not_found: {workspace_id}")
        if workspace_id == "default":
            raise DatabaseError("cannot_delete_default_workspace")
        current = workspace["contextRevision"]
        if expected_context_revision is not None and expected_context_revision != current:
            raise ContextRevisionConflict(
                workspace_id,
                expected_context_revision,
                current,
                deepcopy(workspace["context"]),
            )
        del self.workspaces[workspace_id]


def _client():
    repo = _FakeRepo()
    app = FastAPI()
    app.include_router(create_workspace_router(lambda: repo))
    return TestClient(app), repo


def test_workspace_context_is_stored_and_returned_with_list() -> None:
    client, _ = _client()

    response = client.patch("/api/workspaces/default", json={
        "context": {"roleCard": {"enabled": True, "name": "A"}},
    })

    assert response.status_code == 200
    assert response.json()["context"]["roleCard"]["name"] == "A"
    listed = client.get("/api/workspaces").json()["workspaces"]
    assert listed[0]["context"]["roleCard"]["name"] == "A"
    assert listed[0]["contextRevision"] == 1


def test_workspace_create_and_delete_manage_context() -> None:
    client, repo = _client()

    created = client.post("/api/workspaces", json={
        "id": "scene-a",
        "name": "Scene A",
        "context": {"worldBook": {"enabled": True}},
    })
    assert created.status_code == 200
    assert created.json()["context"]["worldBook"]["enabled"] is True
    assert repo.workspaces["scene-a"]["context"] == {"worldBook": {"enabled": True}}
    assert repo.workspaces["scene-a"]["contextRevision"] == 1

    deleted = client.delete("/api/workspaces/scene-a")
    assert deleted.status_code == 200
    assert "scene-a" not in repo.workspaces


def test_workspace_context_rejects_non_object_payload() -> None:
    client, _ = _client()

    response = client.patch("/api/workspaces/default", json={"context": ["bad"]})

    assert response.status_code == 400


def test_workspace_context_null_clears_existing_context() -> None:
    client, repo = _client()
    client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})

    response = client.patch("/api/workspaces/default", json={"context": None})

    assert response.status_code == 200
    assert response.json()["context"] is None
    assert repo.workspaces["default"]["context"] is None
    # The revision keeps increasing so a stale writer still loses the race.
    assert response.json()["contextRevision"] == 2


def test_workspace_metadata_patch_leaves_context_revision_alone() -> None:
    client, _ = _client()
    client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})

    response = client.patch("/api/workspaces/default", json={"name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["contextRevision"] == 1
    assert response.json()["context"] == {"theme": "dark"}


def test_workspace_context_revision_conflict_returns_409() -> None:
    client, _ = _client()
    first = client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})
    assert first.json()["contextRevision"] == 1

    stale = client.patch("/api/workspaces/default", json={
        "context": {"theme": "light"},
        "contextRevision": 0,
    })

    assert stale.status_code == 409
    body = stale.json()
    assert body["error"] == "context_revision_conflict"
    assert body["contextRevision"] == 1
    assert body["context"] == {"theme": "dark"}


def test_workspace_context_revision_accepts_matching_write() -> None:
    client, _ = _client()
    client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})

    response = client.patch("/api/workspaces/default", json={
        "context": {"theme": "light"},
        "contextRevision": 1,
    })

    assert response.status_code == 200
    assert response.json()["contextRevision"] == 2


def test_stale_context_conflict_does_not_apply_unrelated_db_fields() -> None:
    client, repo = _client()
    client.patch("/api/workspaces/default", json={"context": {"theme": "dark"}})

    response = client.patch("/api/workspaces/default", json={
        "name": "must-not-apply",
        "context": {"theme": "light"},
        "contextRevision": 0,
    })

    assert response.status_code == 409
    assert repo.workspaces["default"]["name"] == "Default"


def test_delete_conflict_does_not_delete_workspace_or_context() -> None:
    client, repo = _client()
    client.post("/api/workspaces", json={"id": "scene-a", "name": "Scene A"})
    client.patch("/api/workspaces/scene-a", json={"context": {"theme": "dark"}})

    response = client.delete("/api/workspaces/scene-a?contextRevision=0")

    assert response.status_code == 409
    assert "scene-a" in repo.workspaces
    assert repo.workspaces["scene-a"]["context"] == {"theme": "dark"}


def test_delete_with_matching_revision_removes_workspace() -> None:
    client, repo = _client()
    client.post("/api/workspaces", json={"id": "scene-b", "name": "Scene B"})
    client.patch("/api/workspaces/scene-b", json={"context": {"theme": "dark"}})

    response = client.delete("/api/workspaces/scene-b?contextRevision=1")

    assert response.status_code == 200
    assert "scene-b" not in repo.workspaces
