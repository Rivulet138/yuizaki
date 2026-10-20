from __future__ import annotations

import json

from database.models import Base
from database.repository import DatabaseRepository
from modules.system.workspace_context_migration import import_legacy_workspace_contexts
from modules.system.workspace_context_store import WorkspaceContextStore
from sqlalchemy import create_engine


class _FakeRepo:
    def __init__(self, workspace_ids: set[str], *, fail: bool = False) -> None:
        self.ids = workspace_ids
        self.fail = fail
        self.contexts: dict[str, dict] = {}

    def list_workspaces(self):
        return [{"id": workspace_id} for workspace_id in sorted(self.ids)]

    def import_workspace_context(self, workspace_id: str, context: dict, revision: int) -> bool:
        if self.fail:
            raise RuntimeError("database unavailable")
        if workspace_id not in self.ids:
            return False
        if workspace_id in self.contexts:
            return False
        self.contexts[workspace_id] = context
        return True


def _store(tmp_path) -> WorkspaceContextStore:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    store.put("default", {"theme": "dark"})
    store.put("scene", {"worldBook": {"enabled": True}})
    return store


def test_imports_contexts_and_archives_the_sidecar(tmp_path) -> None:
    store = _store(tmp_path)
    repo = _FakeRepo({"default", "scene"})

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary == {"imported": 2, "existing": 0, "orphaned": 0, "failed": 0}
    assert repo.contexts == {
        "default": {"theme": "dark"},
        "scene": {"worldBook": {"enabled": True}},
    }
    assert not store.storage_path.exists()
    assert list(tmp_path.glob("workspace_contexts.json.migrated-*"))


def test_second_run_after_archive_is_a_no_op(tmp_path) -> None:
    store = _store(tmp_path)
    repo = _FakeRepo({"default", "scene"})
    import_legacy_workspace_contexts(repo, store)

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary == {"imported": 0, "existing": 0, "orphaned": 0, "failed": 0}
    assert len(list(tmp_path.glob("workspace_contexts.json.migrated-*"))) == 1


def test_contexts_of_deleted_workspaces_are_preserved(tmp_path) -> None:
    store = _store(tmp_path)
    repo = _FakeRepo({"default"})

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary["imported"] == 1
    assert summary["orphaned"] == 1
    assert repo.contexts == {"default": {"theme": "dark"}}
    archived = list(tmp_path.glob("workspace_contexts.json.orphaned-*"))
    assert len(archived) == 1
    payload = json.loads(archived[0].read_text(encoding="utf-8"))
    assert payload["workspaces"]["scene"]["context"] == {"worldBook": {"enabled": True}}
    assert not store.storage_path.exists()


def test_database_failure_keeps_the_sidecar_for_retry(tmp_path) -> None:
    store = _store(tmp_path)
    repo = _FakeRepo({"default", "scene"}, fail=True)

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary["failed"] == 2
    assert store.storage_path.exists()
    assert not list(tmp_path.glob("workspace_contexts.json.migrated-*"))


def test_unreadable_sidecar_is_left_alone(tmp_path) -> None:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    store.storage_path.write_text("{not json", encoding="utf-8")
    repo = _FakeRepo({"default"})

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary["failed"] == 1
    assert store.storage_path.exists()
    assert repo.contexts == {}


def test_missing_sidecar_is_a_no_op(tmp_path) -> None:
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    repo = _FakeRepo({"default"})

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary == {"imported": 0, "existing": 0, "orphaned": 0, "failed": 0}


def test_import_against_a_real_repository(tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    repo = DatabaseRepository(db_path)
    repo.create_workspace("scene", "Scene")
    store = WorkspaceContextStore(tmp_path / "workspace_contexts.json")
    store.put("scene", {"theme": "dark"}, expected_revision=0)

    summary = import_legacy_workspace_contexts(repo, store)

    assert summary["imported"] == 1
    stored = next(
        workspace for workspace in repo.list_workspaces() if workspace["id"] == "scene"
    )
    assert stored["context"] == {"theme": "dark"}
    assert stored["contextRevision"] == 1
    repo.close()
