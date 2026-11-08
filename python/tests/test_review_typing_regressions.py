from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import migration_bootstrap
import pytest
from database.models import Base
from database.repository import DatabaseError, DatabaseRepository, NotFoundError
from modules.system.qq_bridge import QqBridgeError, QqBridgeSupervisor
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint, event
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[DatabaseRepository]:
    repository = DatabaseRepository(tmp_path / "review.db")
    Base.metadata.create_all(repository.engine)
    repository.create_workspace("review", "Review")
    try:
        yield repository
    finally:
        repository.close()


@pytest.mark.parametrize("turn_key", [None, "review-turn"])
def test_pair_validation_integrity_error_keeps_original_cause(
    repo: DatabaseRepository, monkeypatch: pytest.MonkeyPatch, turn_key: str | None
) -> None:
    original = IntegrityError("workspace validation", {}, RuntimeError("invalid workspace"))
    monkeypatch.setattr(repo, "_require_workspace", Mock(side_effect=original))

    with pytest.raises(DatabaseError) as error:
        repo.save_message_pair(
            "review-session", "hello", "reply",
            workspace_id="review", turn_idempotency_key=turn_key,
        )

    assert error.value.__cause__ is original
    assert repo.get_chat_history("review-session") == []


def test_unversioned_zero_row_update_is_not_a_revision_conflict(repo: DatabaseRepository) -> None:
    with repo.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER ignore_workspace_update BEFORE UPDATE ON workspaces "
            "BEGIN SELECT RAISE(IGNORE); END"
        )

    with pytest.raises(DatabaseError, match="workspace_update_no_rows"):
        repo.update_workspace("review", {"name": "Not applied"})

    assert next(item for item in repo.list_workspaces() if item["id"] == "review")["name"] == "Review"


def test_workspace_removed_after_commit_reports_not_found(repo: DatabaseRepository) -> None:
    def remove_workspace(_session: object) -> None:
        with repo.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM workspaces WHERE id = 'review'")

    event.listen(repo.SessionLocal, "after_commit", remove_workspace)
    try:
        with pytest.raises(DatabaseError) as error:
            repo.update_workspace("review", {"name": "Renamed"})
    finally:
        event.remove(repo.SessionLocal, "after_commit", remove_workspace)

    assert isinstance(error.value.__cause__, NotFoundError)
    assert str(error.value.__cause__) == "workspace_not_found: review"


def test_expected_schema_includes_unique_constraint_subclasses(monkeypatch: pytest.MonkeyPatch) -> None:
    class ReviewUniqueConstraint(UniqueConstraint):
        pass

    metadata = MetaData()
    Table("review", metadata, Column("value", Integer), ReviewUniqueConstraint("value"))
    monkeypatch.setattr(migration_bootstrap, "Base", SimpleNamespace(metadata=metadata))

    assert migration_bootstrap._expected_schema()["review"]["unique_constraints"] == (("value",),)


def test_stop_keeps_process_reference_through_timeout(tmp_path: Path) -> None:
    supervisor = QqBridgeSupervisor(data_dir=tmp_path, resource={}, env={}, capture=False)
    process = SimpleNamespace(
        poll=Mock(return_value=None),
        terminate=Mock(side_effect=lambda: setattr(supervisor, "_process", None)),
        wait=Mock(side_effect=subprocess.TimeoutExpired("bridge", 10)),
        kill=Mock(),
    )
    supervisor._process = process

    with pytest.raises(QqBridgeError) as excinfo:
        supervisor.stop()

    assert excinfo.value.code == "qq_bridge_stop_failed"
    process.terminate.assert_called_once_with()
    assert process.wait.call_count == 2
    assert all(call.kwargs == {"timeout": 10} for call in process.wait.call_args_list)
    process.kill.assert_called_once_with()
    assert supervisor._process is process
    assert supervisor.status()["running"] is True

    process.poll.return_value = 0
    status = supervisor.stop()
    assert status["running"] is False
    assert supervisor._process is None


def test_socket_persistence_keeps_legacy_repository_fallback() -> None:
    from socket_server import DesktopPetSocketServer

    repository = SimpleNamespace(
        save_message_pair=None,
        save_message=Mock(side_effect=[{"id": 11}, {"id": 12}]),
    )
    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    server.runtime_context = SimpleNamespace(db_repo=repository)

    result = server._persist_chat_exchange(
        session_id="review-session", workspace_id="review",
        messages=[{"role": "user", "content": "hello"}], assistant_text="reply",
    )

    assert result == {"user_message_id": 11, "assistant_message_id": 12}
    assert repository.save_message.call_count == 2


def test_socket_persistence_replays_atomic_message_pair(repo: DatabaseRepository) -> None:
    from socket_server import DesktopPetSocketServer

    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    server.runtime_context = SimpleNamespace(db_repo=repo)

    def persist() -> dict[str, int | None]:
        return server._persist_chat_exchange(
            session_id="review-session", workspace_id="review", turn_id="review-turn",
            messages=[{"role": "user", "content": "hello"}], assistant_text="reply",
        )

    result = persist()
    assert all(value is not None for value in result.values())
    assert persist() == result
    assert [item["role"] for item in repo.get_chat_history("review-session")] == ["user", "assistant"]
