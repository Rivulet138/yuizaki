from __future__ import annotations

from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from migration_bootstrap import HEAD_WITH_WORKSPACES, HEAD_WITH_COMPANIONS, HEAD_WITH_COMPANION_FK, bootstrap_database, check_database_at_head, load_alembic_config
from database.models import Base


def _set_database_url(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")


def test_bootstrap_empty_database_upgrades_to_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "empty.db"
    _set_database_url(db_path, monkeypatch)

    ok, message = bootstrap_database()

    assert ok is True
    assert "upgraded to head" in message
    head_ok, _ = check_database_at_head()
    assert head_ok is True


def test_bootstrap_legacy_database_stamps_baseline(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is True
    assert "stamped" in message

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert revision == ScriptDirectory.from_config(load_alembic_config()).get_current_head()


def test_bootstrap_unknown_schema_fails(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "unknown.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE weird_table (id INTEGER PRIMARY KEY, value TEXT)"))
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is False
    assert "manual migration required" in message


def test_bootstrap_workspace_phase1_schema_stamps_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "workspace_phase1.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id VARCHAR(50), role VARCHAR(20), content TEXT, timestamp DATETIME, tokens_used INTEGER, model VARCHAR(100))"))
            connection.execute(text("CREATE TABLE chat_sessions (id VARCHAR(50) PRIMARY KEY, workspace_id VARCHAR(50), title VARCHAR(255), summary TEXT, pinned BOOLEAN, archived BOOLEAN, created_at DATETIME, updated_at DATETIME, message_count INTEGER, total_tokens INTEGER)"))
            connection.execute(text("CREATE TABLE user_statistics (id INTEGER PRIMARY KEY, date VARCHAR(10), total_messages INTEGER, total_tokens INTEGER, avg_response_time FLOAT, ocr_count INTEGER, svc_count INTEGER, created_at DATETIME)"))
            connection.execute(text("CREATE TABLE user_settings (id INTEGER PRIMARY KEY, key VARCHAR(100), value TEXT, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE workspaces (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), description TEXT, icon VARCHAR(64), color VARCHAR(32), companion_profile_id VARCHAR(50), default_model VARCHAR(100), system_prompt TEXT, tool_preset TEXT, memory_scope VARCHAR(32), mcp_preset_id VARCHAR(50), created_at DATETIME, updated_at DATETIME)"))
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is True
    assert "workspace-aware" in message

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert revision == HEAD_WITH_WORKSPACES


def test_bootstrap_companion_phase2_schema_stamps_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "companion_phase2.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id VARCHAR(50), role VARCHAR(20), content TEXT, timestamp DATETIME, tokens_used INTEGER, model VARCHAR(100))"))
            connection.execute(text("CREATE TABLE chat_sessions (id VARCHAR(50) PRIMARY KEY, workspace_id VARCHAR(50), title VARCHAR(255), summary TEXT, pinned BOOLEAN, archived BOOLEAN, created_at DATETIME, updated_at DATETIME, message_count INTEGER, total_tokens INTEGER)"))
            connection.execute(text("CREATE TABLE user_statistics (id INTEGER PRIMARY KEY, date VARCHAR(10), total_messages INTEGER, total_tokens INTEGER, avg_response_time FLOAT, ocr_count INTEGER, svc_count INTEGER, created_at DATETIME)"))
            connection.execute(text("CREATE TABLE user_settings (id INTEGER PRIMARY KEY, key VARCHAR(100), value TEXT, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE workspaces (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), description TEXT, icon VARCHAR(64), color VARCHAR(32), companion_profile_id VARCHAR(50), default_model VARCHAR(100), system_prompt TEXT, tool_preset TEXT, memory_scope VARCHAR(32), mcp_preset_id VARCHAR(50), created_at DATETIME, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE companions (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), avatar VARCHAR(255), model_type VARCHAR(32), model_id VARCHAR(100), voice_profile TEXT, persona_prompt TEXT, emotion_state VARCHAR(32), affinity_state FLOAT, energy_state FLOAT, created_at DATETIME, updated_at DATETIME)"))
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is True
    assert "companion-aware" in message

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert revision == HEAD_WITH_COMPANIONS


def test_bootstrap_companion_fk_phase5_schema_stamps_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "companion_fk_phase5.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id VARCHAR(50), role VARCHAR(20), content TEXT, timestamp DATETIME, tokens_used INTEGER, model VARCHAR(100))"))
            connection.execute(text("CREATE TABLE chat_sessions (id VARCHAR(50) PRIMARY KEY, workspace_id VARCHAR(50), title VARCHAR(255), summary TEXT, pinned BOOLEAN, archived BOOLEAN, created_at DATETIME, updated_at DATETIME, message_count INTEGER, total_tokens INTEGER)"))
            connection.execute(text("CREATE TABLE user_statistics (id INTEGER PRIMARY KEY, date VARCHAR(10), total_messages INTEGER, total_tokens INTEGER, avg_response_time FLOAT, ocr_count INTEGER, svc_count INTEGER, created_at DATETIME)"))
            connection.execute(text("CREATE TABLE user_settings (id INTEGER PRIMARY KEY, key VARCHAR(100), value TEXT, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE companions (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), avatar VARCHAR(255), model_type VARCHAR(32), model_id VARCHAR(100), voice_profile TEXT, persona_prompt TEXT, emotion_state VARCHAR(32), affinity_state FLOAT, energy_state FLOAT, temperament VARCHAR(32), attachment_style VARCHAR(32), support_style VARCHAR(32), created_at DATETIME, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE workspaces (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), description TEXT, icon VARCHAR(64), color VARCHAR(32), companion_profile_id VARCHAR(50) NOT NULL REFERENCES companions(id), default_model VARCHAR(100), system_prompt TEXT, tool_preset TEXT, memory_scope VARCHAR(32), mcp_preset_id VARCHAR(50), created_at DATETIME, updated_at DATETIME)"))
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is True
    assert "companion-fk" in message

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    finally:
        engine.dispose()

    assert revision == HEAD_WITH_COMPANION_FK
