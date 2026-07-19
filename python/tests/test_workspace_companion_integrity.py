from __future__ import annotations

from pathlib import Path

import pytest

from database.models import Base, Companion, Workspace
from database.repository import DatabaseError, DatabaseRepository, NotFoundError


def _make_repo(tmp_path: Path) -> DatabaseRepository:
    db_path = tmp_path / "integrity.db"
    repo = DatabaseRepository(str(db_path))
    Base.metadata.create_all(repo.engine)
    session = repo.SessionLocal()
    try:
        session.add(Workspace(id="default", name="Default Workspace", memory_scope="workspace"))
        session.add(Companion(id="default", name="Default Companion"))
        session.commit()
    finally:
        session.close()
    repo.update_workspace("default", {"companion_profile_id": "default"})
    return repo


def test_update_workspace_rejects_missing_companion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        with pytest.raises(DatabaseError) as exc:
            repo.update_workspace("default", {"companion_profile_id": "ghost-companion"})
        assert "invalid_companion_binding" in str(exc.value)
    finally:
        repo.close()


def test_update_workspace_accepts_existing_companion(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        repo.create_companion(companion_id="c-1", name="Companion 1")
        updated = repo.update_workspace("default", {"companion_profile_id": "c-1"})
        assert updated["companion_profile_id"] == "c-1"
    finally:
        repo.close()


def test_update_workspace_rejects_invalid_memory_scope(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        with pytest.raises(DatabaseError) as exc:
            repo.update_workspace("default", {"memory_scope": "project"})
        assert "invalid_memory_scope" in str(exc.value)
    finally:
        repo.close()


def test_delete_companion_rebinds_workspaces_to_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        repo.create_companion(companion_id="c-2", name="Companion 2")
        repo.create_workspace(workspace_id="ws-1", name="Workspace 1")
        repo.update_workspace("ws-1", {"companion_profile_id": "c-2"})

        refs_before = repo.list_workspaces_referencing_companion("c-2")
        assert [item["id"] for item in refs_before] == ["ws-1"]

        repo.delete_companion("c-2")

        refs_after = repo.list_workspaces_referencing_companion("c-2")
        assert refs_after == []
        session = repo.SessionLocal()
        try:
            rebound = session.query(Workspace).filter_by(id="ws-1").first()
            assert rebound is not None
            assert rebound.companion_profile_id == "default"
        finally:
            session.close()
    finally:
        repo.close()


def test_delete_companion_fails_when_default_missing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        repo.create_companion(companion_id="c-3", name="Companion 3")
        repo.update_workspace("default", {"companion_profile_id": "c-3"})
        session = repo.SessionLocal()
        try:
            default_workspace = session.query(Workspace).filter_by(id="default").first()
            assert default_workspace is not None
            default_workspace.companion_profile_id = "c-3"
            default = session.query(Companion).filter_by(id="default").first()
            assert default is not None
            session.delete(default)
            session.commit()
        finally:
            session.close()

        with pytest.raises(DatabaseError) as exc:
            repo.delete_companion("c-3")
        assert "default_companion_missing" in str(exc.value)
    finally:
        repo.close()


def test_create_chat_session_rejects_unknown_workspace(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        with pytest.raises(NotFoundError) as exc:
            repo.create_chat_session("missing-workspace", "Hidden Session")
        assert "workspace_not_found: missing-workspace" in str(exc.value)
    finally:
        repo.close()


def test_list_workspace_sessions_rejects_unknown_workspace(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        with pytest.raises(NotFoundError) as exc:
            repo.list_workspace_sessions("missing-workspace")
        assert "workspace_not_found: missing-workspace" in str(exc.value)
    finally:
        repo.close()


def test_save_message_does_not_move_existing_session_between_workspaces(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        repo.create_workspace(workspace_id="ws-1", name="Workspace 1")
        repo.create_workspace(workspace_id="ws-2", name="Workspace 2")
        chat_session = repo.create_chat_session("ws-1", "Workspace 1 Chat")

        repo.save_message(chat_session["id"], "user", "hello", workspace_id="ws-1")
        with pytest.raises(DatabaseError) as exc:
            repo.save_message(chat_session["id"], "assistant", "cross workspace", workspace_id="ws-2")

        assert "session_workspace_mismatch" in str(exc.value)
        assert [item["id"] for item in repo.list_workspace_sessions("ws-1")] == [chat_session["id"]]
        assert repo.list_workspace_sessions("ws-2") == []
    finally:
        repo.close()


def test_delete_message_updates_session_counters(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        chat_session = repo.create_chat_session("default", "Counter Chat")
        first = repo.save_message(chat_session["id"], "user", "hello", tokens=7)
        second = repo.save_message(chat_session["id"], "assistant", "hi", tokens=11)

        result = repo.delete_message(int(first["id"]))

        assert result == {"message_id": first["id"], "session_id": chat_session["id"]}
        history = repo.get_chat_history(chat_session["id"])
        assert len(history) == 1
        assert history[0] == {
            "id": second["id"],
            "role": "assistant",
            "content": "hi",
            "timestamp": history[0]["timestamp"],
            "tokens": 11,
            "model": "",
        }
        stored = repo.list_workspace_sessions("default")[0]
        assert stored["message_count"] == 1
        assert stored["total_tokens"] == 11
    finally:
        repo.close()


def test_update_message_preserves_session_counters(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        chat_session = repo.create_chat_session("default", "Edit Chat")
        message = repo.save_message(chat_session["id"], "user", "old question", tokens=7)

        updated = repo.update_message(int(message["id"]), "new question")

        assert updated["content"] == "new question"
        history = repo.get_chat_history(chat_session["id"])
        assert history[0]["content"] == "new question"
        stored = repo.list_workspace_sessions("default")[0]
        assert stored["message_count"] == 1
        assert stored["total_tokens"] == 7
    finally:
        repo.close()


def test_delete_messages_after_updates_session_counters(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        chat_session = repo.create_chat_session("default", "Regenerate Chat")
        first = repo.save_message(chat_session["id"], "user", "rewrite from here", tokens=5)
        repo.save_message(chat_session["id"], "assistant", "old answer", tokens=11)
        repo.save_message(chat_session["id"], "user", "later question", tokens=7)

        result = repo.delete_messages_after(int(first["id"]))

        assert result == {"message_id": first["id"], "session_id": chat_session["id"], "deleted_count": 2}
        history = repo.get_chat_history(chat_session["id"])
        assert [item["content"] for item in history] == ["rewrite from here"]
        stored = repo.list_workspace_sessions("default")[0]
        assert stored["message_count"] == 1
        assert stored["total_tokens"] == 5
    finally:
        repo.close()


def test_clear_session_messages_keeps_session_and_resets_counters(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    try:
        chat_session = repo.create_chat_session("default", "Clear Chat")
        repo.save_message(chat_session["id"], "user", "hello", tokens=7)
        repo.save_message(chat_session["id"], "assistant", "hi", tokens=11)

        result = repo.clear_session_messages(chat_session["id"])

        assert result == {"session_id": chat_session["id"], "deleted_count": 2}
        assert repo.get_chat_history(chat_session["id"]) == []
        stored = repo.list_workspace_sessions("default")[0]
        assert stored["id"] == chat_session["id"]
        assert stored["message_count"] == 0
        assert stored["total_tokens"] == 0
    finally:
        repo.close()
