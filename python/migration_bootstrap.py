from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {
    "chat_messages",
    "chat_sessions",
    "user_statistics",
    "user_settings",
}
BASELINE_REVISION = "20260414_01"
HEAD_WITH_WORKSPACES = "20260414_02"
HEAD_WITH_COMPANIONS = "20260414_03"
HEAD_WITH_COMPANION_FK = "20260421_01"
HEAD_WITH_COMPANION_STATE = "20260422_01"


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def load_alembic_config() -> Config:
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    default_database_url = f"sqlite:///{(root / 'data' / 'chat.db').as_posix()}"
    database_url = os.getenv("DATABASE_URL", "").strip() or default_database_url
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def get_database_url(cfg: Config) -> str:
    default_database_url = f"sqlite:///{(_project_root() / 'data' / 'chat.db').as_posix()}"
    return str(cfg.get_main_option("sqlalchemy.url") or default_database_url)


def _inspect_db_state(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            table_names = set(inspector.get_table_names())
            has_alembic_version = "alembic_version" in table_names
            current_revision = MigrationContext.configure(connection).get_current_revision()

            chat_messages_columns = set()
            chat_sessions_columns = set()
            user_statistics_columns = set()
            user_settings_columns = set()
            workspaces_columns = set()
            companions_columns = set()
            workspace_foreign_keys: Sequence[Any] = []

            if "chat_messages" in table_names:
                chat_messages_columns = {col["name"] for col in inspector.get_columns("chat_messages")}
            if "chat_sessions" in table_names:
                chat_sessions_columns = {col["name"] for col in inspector.get_columns("chat_sessions")}
            if "user_statistics" in table_names:
                user_statistics_columns = {col["name"] for col in inspector.get_columns("user_statistics")}
            if "user_settings" in table_names:
                user_settings_columns = {col["name"] for col in inspector.get_columns("user_settings")}
            if "workspaces" in table_names:
                workspaces_columns = {col["name"] for col in inspector.get_columns("workspaces")}
                workspace_foreign_keys = inspector.get_foreign_keys("workspaces")
            if "companions" in table_names:
                companions_columns = {col["name"] for col in inspector.get_columns("companions")}

            return {
                "tables": table_names,
                "has_alembic_version": has_alembic_version,
                "current_revision": current_revision,
                "chat_messages_columns": chat_messages_columns,
                "chat_sessions_columns": chat_sessions_columns,
                "user_statistics_columns": user_statistics_columns,
                "user_settings_columns": user_settings_columns,
                "workspaces_columns": workspaces_columns,
                "companions_columns": companions_columns,
                "workspace_foreign_keys": workspace_foreign_keys,
            }
    finally:
        engine.dispose()


def _matches_legacy_baseline(state: dict[str, Any]) -> bool:
    if state["tables"] != EXPECTED_TABLES:
        return False

    expected_columns = {
        "chat_messages_columns": {"id", "session_id", "role", "content", "timestamp", "tokens_used", "model"},
        "chat_sessions_columns": {"id", "title", "created_at", "updated_at", "message_count", "total_tokens"},
        "user_statistics_columns": {"id", "date", "total_messages", "total_tokens", "avg_response_time", "ocr_count", "svc_count", "created_at"},
        "user_settings_columns": {"id", "key", "value", "updated_at"},
    }

    return all(state[key] == value for key, value in expected_columns.items())


def _matches_workspace_phase1_schema(state: dict[str, Any]) -> bool:
    expected_tables = EXPECTED_TABLES | {"workspaces"}
    if state["tables"] != expected_tables:
        return False

    expected_chat_sessions = {
        "id", "workspace_id", "title", "summary", "pinned", "archived", "created_at", "updated_at", "message_count", "total_tokens"
    }
    expected_workspaces = {
        "id", "name", "description", "icon", "color", "companion_profile_id", "default_model", "system_prompt", "tool_preset", "memory_scope", "mcp_preset_id", "created_at", "updated_at"
    }

    return expected_chat_sessions.issubset(state["chat_sessions_columns"]) and expected_workspaces.issubset(state["workspaces_columns"])


def _matches_companion_phase2_schema(state: dict[str, Any]) -> bool:
    expected_tables = EXPECTED_TABLES | {"workspaces", "companions"}
    if state["tables"] != expected_tables:
        return False

    expected_companions = {
        "id", "name", "avatar", "model_type", "model_id", "voice_profile", "persona_prompt", "emotion_state", "affinity_state", "energy_state", "created_at", "updated_at"
    }

    workspace_phase_view = dict(state)
    workspace_phase_view["tables"] = EXPECTED_TABLES | {"workspaces"}
    return _matches_workspace_phase1_schema(workspace_phase_view) and expected_companions.issubset(state["companions_columns"])


def _matches_companion_fk_phase5_schema(state: dict[str, Any]) -> bool:
    if not _matches_companion_phase2_schema(state):
        return False
    foreign_keys = state.get("workspace_foreign_keys") or []
    return any(
        fk.get("referred_table") == "companions" and fk.get("constrained_columns") == ["companion_profile_id"]
        for fk in foreign_keys
    )


def _schema_state(state: dict[str, Any]) -> dict[str, Any]:
    schema_state = dict(state)
    schema_state["tables"] = set(state["tables"]) - {"alembic_version"}
    return schema_state


def _matches_head_schema(state: dict[str, Any]) -> bool:
    schema_state = _schema_state(state)
    expected_chat_sessions = {
        "id",
        "workspace_id",
        "title",
        "summary",
        "pinned",
        "created_at",
        "updated_at",
        "message_count",
        "total_tokens",
    }
    expected_workspaces = {
        "id",
        "name",
        "description",
        "icon",
        "color",
        "companion_profile_id",
        "default_model",
        "system_prompt",
        "tool_preset",
        "memory_scope",
        "mcp_preset_id",
        "created_at",
        "updated_at",
    }
    expected_companions = {
        "id",
        "name",
        "avatar",
        "model_type",
        "model_id",
        "voice_profile",
        "persona_prompt",
        "temperament",
        "attachment_style",
        "support_style",
        "emotion_state",
        "affinity_state",
        "energy_state",
        "trust_state",
        "intimacy_state",
        "interruptibility_state",
        "fatigue_state",
        "created_at",
        "updated_at",
    }
    if schema_state["tables"] != EXPECTED_TABLES | {"workspaces", "companions"}:
        return False
    return schema_state["chat_sessions_columns"] == expected_chat_sessions and expected_workspaces.issubset(schema_state["workspaces_columns"]) and expected_companions.issubset(schema_state["companions_columns"]) and any(
        fk.get("referred_table") == "companions" and fk.get("constrained_columns") == ["companion_profile_id"]
        for fk in (schema_state.get("workspace_foreign_keys") or [])
    )


def check_database_at_head() -> tuple[bool, str]:
    cfg = load_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        return False, "alembic head revision not found"
    state = _inspect_db_state(get_database_url(cfg))
    current = state["current_revision"]

    if current != head:
        return False, f"database revision {current or 'none'} does not match head {head}"
    if not _matches_head_schema(state):
        return False, f"database revision {head} matches head but schema does not match the expected head layout"
    return True, f"database at head revision {head}"


def bootstrap_database() -> tuple[bool, str]:
    cfg = load_alembic_config()
    database_url = get_database_url(cfg)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        return False, "alembic head revision not found"
    state = _inspect_db_state(database_url)
    current = state["current_revision"]
    non_migration_tables = state["tables"] - {"alembic_version"}

    if current == head:
        if _matches_head_schema(state):
            return True, f"database already at head revision {head}"
        return False, f"database revision {head} matches head but schema does not match the expected head layout"

    if not state["has_alembic_version"] and not non_migration_tables:
        command.upgrade(cfg, "head")
        state = _inspect_db_state(database_url)
        current = state["current_revision"]
        if current == head and _matches_head_schema(state):
            return True, f"empty database upgraded to head revision {head}"
        return False, f"database upgrade completed but head verification failed (revision={current or 'none'})"

    if not state["has_alembic_version"]:
        if _matches_head_schema(state):
            command.stamp(cfg, head)
            return True, f"legacy companion-fk database stamped to head revision {head}"

        if _matches_legacy_baseline(state):
            command.upgrade(cfg, "head")
            upgraded_state = _inspect_db_state(database_url)
            if upgraded_state["current_revision"] == head and _matches_head_schema(upgraded_state):
                return True, f"legacy baseline database upgraded to head revision {head}"
            return False, f"database upgrade completed but head verification failed (revision={upgraded_state['current_revision'] or 'none'})"

        if _matches_workspace_phase1_schema(state):
            command.stamp(cfg, HEAD_WITH_WORKSPACES)
            return True, f"legacy workspace-aware database stamped to revision {HEAD_WITH_WORKSPACES}"

        if _matches_companion_fk_phase5_schema(state):
            command.stamp(cfg, HEAD_WITH_COMPANION_FK)
            return True, f"legacy companion-fk database stamped to revision {HEAD_WITH_COMPANION_FK}"

        if _matches_companion_phase2_schema(state):
            command.stamp(cfg, HEAD_WITH_COMPANIONS)
            return True, f"legacy companion-aware database stamped to revision {HEAD_WITH_COMPANIONS}"

        return False, "database schema does not match empty database or known legacy baseline; manual migration required"

    if current != head and _matches_head_schema(state):
        command.stamp(cfg, head)
        upgraded_state = _inspect_db_state(database_url)
        if upgraded_state["current_revision"] == head and _matches_head_schema(upgraded_state):
            return True, f"database stamped to head revision {head}"
        return False, f"database stamp completed but head verification failed (revision={upgraded_state['current_revision'] or 'none'})"

    if current != head:
        command.upgrade(cfg, "head")

    upgraded_state = _inspect_db_state(database_url)
    if upgraded_state["current_revision"] != head or not _matches_head_schema(upgraded_state):
        return False, f"database upgrade completed but head verification failed (revision={upgraded_state['current_revision'] or 'none'})"

    if current and current != head:
        return True, f"database upgraded from revision {current} to head revision {head}"
    return True, f"database upgraded to head revision {head}"


def main() -> int:
    ok, message = bootstrap_database()
    if ok:
        print(f"[OK] {message}")
        return 0
    print(f"[ERROR] {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
