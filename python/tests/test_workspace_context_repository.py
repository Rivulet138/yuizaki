from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from database.models import Base
from database.repository import ContextRevisionConflict, DatabaseRepository


def _repo(tmp_path: Path) -> DatabaseRepository:
    db_path = tmp_path / "chat.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return DatabaseRepository(db_path)


def _workspace(repo: DatabaseRepository, workspace_id: str = "default") -> dict:
    for workspace in repo.list_workspaces():
        if workspace["id"] == workspace_id:
            return workspace
    raise AssertionError(f"workspace {workspace_id} missing")


def test_create_with_context_sets_first_revision(tmp_path) -> None:
    repo = _repo(tmp_path)

    created = repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    assert created["context"] == {"theme": "dark"}
    assert created["contextRevision"] == 1
    assert _workspace(repo, "scene")["contextRevision"] == 1
    repo.close()


def test_create_without_context_starts_at_zero(tmp_path) -> None:
    repo = _repo(tmp_path)

    created = repo.create_workspace("scene", "Scene")

    assert created["context"] is None
    assert created["contextRevision"] == 0
    repo.close()


def test_context_and_metadata_commit_together(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene")

    updated = repo.update_workspace(
        "scene",
        {"name": "Renamed"},
        context={"theme": "dark"},
        expected_context_revision=0,
    )

    assert updated["name"] == "Renamed"
    assert updated["context"] == {"theme": "dark"}
    assert updated["contextRevision"] == 1
    repo.close()


def test_stale_revision_changes_nothing(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    with pytest.raises(ContextRevisionConflict) as error:
        repo.update_workspace(
            "scene",
            {"name": "must-not-apply"},
            context={"theme": "light"},
            expected_context_revision=0,
        )

    assert error.value.expected == 0
    assert error.value.current == 1
    assert error.value.context == {"theme": "dark"}
    stored = _workspace(repo, "scene")
    assert stored["name"] == "Scene"
    assert stored["context"] == {"theme": "dark"}
    assert stored["contextRevision"] == 1
    repo.close()


def test_metadata_only_update_keeps_revision(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    updated = repo.update_workspace("scene", {"name": "Renamed"})

    assert updated["context"] == {"theme": "dark"}
    assert updated["contextRevision"] == 1
    repo.close()


def test_null_context_clears_and_bumps_revision(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    cleared = repo.update_workspace("scene", {}, context=None, expected_context_revision=1)

    assert cleared["context"] is None
    assert cleared["contextRevision"] == 2
    repo.close()


def test_context_survives_reopen(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark", "nested": {"n": 1}})
    repo.close()

    reopened = DatabaseRepository(tmp_path / "chat.db")
    stored = _workspace(reopened, "scene")
    assert stored["context"] == {"theme": "dark", "nested": {"n": 1}}
    assert stored["contextRevision"] == 1
    reopened.close()


def test_delete_with_stale_revision_keeps_row(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    with pytest.raises(ContextRevisionConflict):
        repo.delete_workspace("scene", expected_context_revision=0)

    assert _workspace(repo, "scene")["context"] == {"theme": "dark"}
    repo.close()


def test_delete_with_matching_revision_removes_row(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    repo.delete_workspace("scene", expected_context_revision=1)

    assert all(workspace["id"] != "scene" for workspace in repo.list_workspaces())
    repo.close()


def test_import_does_not_overwrite_existing_context(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene", context={"theme": "dark"})

    imported = repo.import_workspace_context("scene", {"theme": "light"}, 5)

    assert imported is False
    assert _workspace(repo, "scene")["context"] == {"theme": "dark"}
    assert _workspace(repo, "scene")["contextRevision"] == 1
    repo.close()


def test_import_seeds_empty_workspace_and_keeps_sidecar_revision(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.create_workspace("scene", "Scene")

    imported = repo.import_workspace_context("scene", {"theme": "dark"}, 3)

    assert imported is True
    stored = _workspace(repo, "scene")
    assert stored["context"] == {"theme": "dark"}
    assert stored["contextRevision"] == 3
    repo.close()


def test_import_skips_missing_workspace(tmp_path) -> None:
    repo = _repo(tmp_path)

    assert repo.import_workspace_context("absent", {"theme": "dark"}, 1) is False
    repo.close()
