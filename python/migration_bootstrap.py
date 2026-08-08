from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from database.models import Base


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def load_alembic_config() -> Config:
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    default_database_url = f"sqlite:///{(root / 'data' / 'chat.db').as_posix()}"
    cfg.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", "").strip() or default_database_url)
    return cfg


def get_database_url(cfg: Config) -> str:
    return str(cfg.get_main_option("sqlalchemy.url"))


def _inspect_db_state(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            return {
                "tables": tables,
                "current_revision": MigrationContext.configure(connection).get_current_revision(),
                "columns": {
                    table: {column["name"] for column in inspector.get_columns(table)}
                    for table in tables
                    if table != "alembic_version"
                },
            }
    finally:
        engine.dispose()


def _matches_head_schema(state: dict[str, Any]) -> bool:
    expected_tables = set(Base.metadata.tables)
    if state["tables"] - {"alembic_version"} != expected_tables:
        return False
    return all(
        state["columns"].get(table_name) == {column.name for column in table.columns}
        for table_name, table in Base.metadata.tables.items()
    )


def check_database_at_head() -> tuple[bool, str]:
    cfg = load_alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        return False, "alembic head revision not found"
    state = _inspect_db_state(get_database_url(cfg))
    if state["current_revision"] != head:
        return False, f"database revision {state['current_revision'] or 'none'} does not match baseline {head}"
    if not _matches_head_schema(state):
        return False, "database schema does not match the current baseline"
    return True, f"database at current baseline {head}"


def bootstrap_database() -> tuple[bool, str]:
    cfg = load_alembic_config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        return False, "alembic head revision not found"
    state = _inspect_db_state(get_database_url(cfg))
    if not state["tables"]:
        command.upgrade(cfg, "head")
        ok, message = check_database_at_head()
        return (True, f"empty database created from baseline {head}") if ok else (False, message)
    return check_database_at_head()
