"""Session persona contract through SQLite, API, prompt assembly and migrations."""
from __future__ import annotations

from copy import deepcopy

import pytest
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import migration_bootstrap
from alembic import command
from database.models import Base
from database.repository import DatabaseError, DatabaseRepository
from modules.agent.prompt_assembly import build_prompt_assembly
from routes.workspace_api import create_workspace_router


@pytest.fixture
def repo(tmp_path):
    database = tmp_path / "sessions.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    repository = DatabaseRepository(database)
    repository.create_companion("default", "Default")
    for workspace_id in ("a", "b"):
        repository.create_workspace(workspace_id, workspace_id, context={"roleCard": {
            "enabled": True, "name": "SAVED_NAME", "scenario": "SAVED_SCENARIO",
            "exampleDialogue": "SAVED_EXAMPLE",
        }})
    yield repository
    repository.close()


def client_for(repo):
    app = FastAPI()
    app.include_router(create_workspace_router(lambda: repo, get_active_workspace_id=lambda: "a"))
    return TestClient(app)


def assemble(repo, session_id, *, workspace_id="a", profile=None):
    return build_prompt_assembly(
        db_repo=repo, generation_mgr=None, workspace_id=workspace_id, session_id=session_id,
        messages=[{"role": "user", "content": "unchanged history"}], prompt_profile=profile,
    )


def rendered(repo, session_id, **kwargs):
    return "\n".join(message["content"] for message in assemble(repo, session_id, **kwargs))


def test_persistence_create_list_update_and_reopen(repo):
    value = {"scenario": "  local scene  ", "exampleDialogue": "本地示例"}
    created = repo.create_chat_session("a", persona_overrides=value)
    session_id = created["id"]
    assert created["persona_overrides"] == value
    value["scenario"] = "caller mutation"
    assert repo.list_workspace_sessions("a")[0]["persona_overrides"]["scenario"] == "  local scene  "
    assert repo.get_all_sessions("a")[0]["persona_overrides"] == created["persona_overrides"]
    repo.update_chat_session(session_id, title="renamed", workspace_id="a")
    reopened = DatabaseRepository(repo.db_path)
    try:
        assert reopened.get_chat_session(session_id, workspace_id="a")["persona_overrides"] == created["persona_overrides"]
    finally:
        reopened.close()


@pytest.mark.parametrize("value", [None, {}, {"scenario": ""}, {"exampleDialogue": ""}, {"scenario": "x" * 1600}])
def test_api_round_trip_and_omission_preserves_override(repo, value):
    with client_for(repo) as client:
        response = client.post("/api/workspaces/a/sessions", json={"persona_overrides": value})
        assert response.status_code == 200, response.text
        session_id = response.json()["id"]
        assert response.json()["persona_overrides"] == value
        response = client.patch(f"/api/sessions/{session_id}", json={"title": "renamed"})
        assert response.status_code == 200, response.text
        assert response.json()["persona_overrides"] == value
        assert client.get("/api/workspaces/a/sessions").json()["sessions"][0]["persona_overrides"] == value
        response = client.patch(f"/api/sessions/{session_id}", json={"persona_overrides": {"exampleDialogue": "replacement"}})
        assert response.status_code == 200, response.text
        assert response.json()["persona_overrides"] == {"exampleDialogue": "replacement"}
        response = client.patch(f"/api/sessions/{session_id}", json={"persona_overrides": value})
        assert response.status_code == 200, response.text
        assert response.json()["persona_overrides"] == value
        if value is None:
            with repo.engine.connect() as connection:
                assert connection.execute(text("SELECT persona_overrides IS NULL FROM chat_sessions WHERE id=:id"), {"id": session_id}).scalar_one() == 1


@pytest.mark.parametrize("invalid", [
    "text", [], 1, True, {"scenario": None}, {"scenario": 1},
    {"exampleDialogue": False}, {"exampleDialogue": []}, {"exampleDialogue": {}},
    {"scenario": "x" * 1601}, {"exampleDialogue": "x" * 1601},
    {"enabled": True}, {"firstMessage": "hello"}, {"scenario": "valid", "unknown": "no"},
])
def test_invalid_payload_is_rejected_without_writing(repo, invalid):
    original = {"scenario": "ORIGINAL"}
    created = repo.create_chat_session("a", persona_overrides=original)
    with client_for(repo) as client:
        for method, endpoint in [
            (client.post, "/api/workspaces/a/sessions"),
            (client.patch, f"/api/sessions/{created['id']}"),
        ]:
            response = method(endpoint, json={"persona_overrides": invalid})
            assert response.status_code == 422, response.text
            assert response.json()["error"].startswith("persona_overrides_")
    assert len(repo.list_workspace_sessions("a")) == 1
    assert repo.get_chat_session(created["id"], workspace_id="a")["persona_overrides"] == original
    with pytest.raises((TypeError, ValueError)):
        repo.update_chat_session(created["id"], persona_overrides=invalid)
    with pytest.raises((TypeError, ValueError)):
        repo.create_chat_session("a", persona_overrides=invalid)


def test_session_overrides_win_conflicts_without_mutating_inputs_or_history(repo):
    created = repo.create_chat_session("a", persona_overrides={"scenario": "SESSION_SCENE", "exampleDialogue": "SESSION_EXAMPLE"})
    profile = {"roleCard": {"scenario": "REQUEST_SCENE", "exampleDialogue": "REQUEST_EXAMPLE", "name": "REQUEST_NAME"}}
    before = deepcopy(profile)
    stored = deepcopy(repo.list_workspaces())
    compiled = assemble(repo, created["id"], profile=profile)
    output = "\n".join(message["content"] for message in compiled)
    for expected in ("SESSION_SCENE", "SESSION_EXAMPLE", "REQUEST_NAME"):
        assert expected in output
    for hidden in ("REQUEST_SCENE", "REQUEST_EXAMPLE", "SAVED_SCENARIO", "SAVED_EXAMPLE"):
        assert hidden not in output
    assert profile == before
    assert repo.list_workspaces() == stored
    assert compiled[-1] == {"role": "user", "content": "unchanged history"}
    assert not any(message["role"] == "assistant" for message in compiled)
    assert repo.get_chat_history(created["id"]) == []


def test_empty_fields_clear_and_null_or_empty_object_restore_inheritance(repo):
    created = repo.create_chat_session("a", persona_overrides={"scenario": "", "exampleDialogue": ""})
    session_id = created["id"]
    profile = {"roleCard": {"scenario": "REQUEST_SCENE", "exampleDialogue": "REQUEST_EXAMPLE"}}
    output = rendered(repo, session_id, profile=profile)
    assert "REQUEST_SCENE" not in output and "REQUEST_EXAMPLE" not in output
    assert "SAVED_SCENARIO" not in output and "SAVED_EXAMPLE" not in output
    for reset in (None, {}):
        repo.update_chat_session(session_id, persona_overrides=reset)
        output = rendered(repo, session_id, profile=profile)
        assert "REQUEST_SCENE" in output and "REQUEST_EXAMPLE" in output
        assert "SAVED_SCENARIO" in rendered(repo, session_id)


def test_partial_override_inherits_other_fields_and_disabled_stays_disabled(repo):
    created = repo.create_chat_session("a", persona_overrides={"scenario": "SESSION_ONLY"})
    output = rendered(repo, created["id"])
    assert "SESSION_ONLY" in output and "SAVED_EXAMPLE" in output
    assert "id=role_card " not in rendered(repo, created["id"], profile={"roleCard": {"enabled": False}})
    repo.update_workspace("a", {}, context={"roleCard": {"enabled": False, "name": "DISABLED"}})
    assert "id=role_card " not in rendered(repo, created["id"])


@pytest.mark.parametrize("role_card", [None, False, {"enabled": False}])
@pytest.mark.parametrize("stored", [False, True])
def test_explicitly_closed_role_card_is_not_reenabled_by_session_overrides(repo, role_card, stored):
    overrides = {"scenario": "SESSION_SCENARIO", "exampleDialogue": "SESSION_EXAMPLE"}
    created = repo.create_chat_session("a", persona_overrides=overrides)
    if stored:
        repo.update_workspace("a", {}, context={"roleCard": role_card})
    profile = None if stored else {"roleCard": role_card}
    before = deepcopy(profile)
    compiled = assemble(repo, created["id"], profile=profile)
    output = "\n".join(message["content"] for message in compiled)
    assert "id=role_card " not in output
    assert "SESSION_SCENARIO" not in output
    assert "SESSION_EXAMPLE" not in output
    assert profile == before
    assert compiled[-1] == {"role": "user", "content": "unchanged history"}
    assert not any(message["role"] == "assistant" for message in compiled)
    assert repo.get_chat_session(created["id"], workspace_id="a")["persona_overrides"] == overrides


def test_session_isolation_missing_session_and_cross_workspace_rejection(repo):
    first = repo.create_chat_session("a", persona_overrides={"scenario": "ONLY_FIRST"})
    second = repo.create_chat_session("a", persona_overrides={"exampleDialogue": "ONLY_SECOND"})
    foreign = repo.create_chat_session("b", persona_overrides={"scenario": "FOREIGN_SECRET"})
    assert "ONLY_SECOND" not in rendered(repo, first["id"])
    output = rendered(repo, second["id"])
    assert "ONLY_SECOND" in output and "ONLY_FIRST" not in output
    assert "ONLY_FIRST" not in rendered(repo, "missing")
    assert "SAVED_SCENARIO" in rendered(repo, "missing")
    assert "FOREIGN_SECRET" not in rendered(repo, foreign["id"], workspace_id=None)
    with pytest.raises(DatabaseError, match="session_workspace_mismatch"):
        assemble(repo, foreign["id"])
    with client_for(repo) as client:
        response = client.patch(f"/api/sessions/{foreign['id']}", json={"persona_overrides": {"scenario": "intrusion"}})
        assert response.status_code == 403
        response = client.patch(f"/api/sessions/{first['id']}?workspace_id=b", json={"persona_overrides": None})
        assert response.status_code == 403
    assert repo.get_chat_session(foreign["id"], workspace_id="b")["persona_overrides"] == {"scenario": "FOREIGN_SECRET"}


@pytest.mark.parametrize("overrides", [None, {}, {"scenario": "", "exampleDialogue": "BRANCH_EXAMPLE"}])
def test_branch_copies_overrides_without_changing_source(repo, overrides):
    source = repo.create_chat_session("a", persona_overrides=overrides)
    message_id = repo.save_message(source["id"], "user", "branch point", workspace_id="a")["id"]
    before = repo.get_chat_session(source["id"], workspace_id="a")
    with client_for(repo) as client:
        response = client.post("/api/session-branches", json={"source_session_id": source["id"], "message_id": message_id})
        assert response.status_code == 200, response.text
        branch = response.json()
        assert branch["persona_overrides"] == overrides
        assert branch["parent_session_id"] == source["id"]
        response = client.patch(f"/api/sessions/{branch['id']}", json={"persona_overrides": {"scenario": "BRANCH_ONLY"}})
        assert response.status_code == 200, response.text
        denied = client.post("/api/session-branches", json={"source_session_id": source["id"], "message_id": message_id, "workspace_id": "b"})
        assert denied.status_code == 403
    assert repo.get_chat_session(source["id"], workspace_id="a") == before
    assert "BRANCH_ONLY" not in rendered(repo, source["id"])
    assert "BRANCH_ONLY" in rendered(repo, branch["id"])
    assert [message["content"] for message in repo.get_chat_history(branch["id"])] == ["branch point"]


def test_database_failures_are_not_reported_as_success(repo, monkeypatch):
    created = repo.create_chat_session("a")

    def fail(*args, **kwargs):
        raise DatabaseError("write failed")

    monkeypatch.setattr(repo, "update_chat_session", fail)
    monkeypatch.setattr(repo, "create_chat_session", fail)
    with client_for(repo) as client:
        for response in (
            client.post("/api/workspaces/a/sessions", json={"persona_overrides": {}}),
            client.patch(f"/api/sessions/{created['id']}", json={"persona_overrides": {}}),
        ):
            assert response.status_code == 400
            assert response.json()["error"] == "write failed"
    monkeypatch.setattr(repo, "get_chat_session", fail)
    with pytest.raises(DatabaseError, match="write failed"):
        assemble(repo, created["id"])


def test_old_schema_upgrade_preserves_rows_and_has_single_head(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    cfg = migration_bootstrap.load_alembic_config()
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_heads() == ["20261111_00"]
    command.upgrade(cfg, "20261020_01")
    engine = create_engine(str(cfg.get_main_option("sqlalchemy.url")))
    try:
        # The historical baseline imports current metadata. Remove the new column
        # to exercise an actual pre-feature schema and existing session row.
        with engine.begin() as connection:
            if "persona_overrides" in {column["name"] for column in inspect(connection).get_columns("chat_sessions")}:
                connection.exec_driver_sql("ALTER TABLE chat_sessions DROP COLUMN persona_overrides")
            connection.exec_driver_sql("INSERT INTO chat_sessions (id, workspace_id, title, created_at, updated_at, archived) VALUES ('old', 'default', 'Legacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)")
        command.upgrade(cfg, "head")
        column = next(column for column in inspect(engine).get_columns("chat_sessions") if column["name"] == "persona_overrides")
        assert column["nullable"] is True
        assert str(column["type"]) == "JSON"
        old = DatabaseRepository(database)
        try:
            assert old.get_chat_session("old", workspace_id="default")["persona_overrides"] is None
            assert old.update_chat_session("old", persona_overrides={"scenario": "migrated"})["persona_overrides"] == {"scenario": "migrated"}
        finally:
            old.close()
        assert migration_bootstrap.check_database_at_head()[0] is True
        command.downgrade(cfg, "20261020_01")
        assert "persona_overrides" not in {column["name"] for column in inspect(engine).get_columns("chat_sessions")}
        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT title, persona_overrides FROM chat_sessions WHERE id='old'").one() == ("Legacy", None)
    finally:
        engine.dispose()
