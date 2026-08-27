from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from database.models import Base
from modules.core.paths import database_url_from_env


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def load_alembic_config() -> Config:
    root = _project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url_from_env())
    return cfg


def get_database_url(cfg: Config) -> str:
    return str(cfg.get_main_option("sqlalchemy.url"))


def _ensure_sqlite_parent(database_url: str) -> None:
    parsed_url = make_url(database_url)
    database_name = parsed_url.database
    if parsed_url.get_backend_name() != "sqlite" or database_name in (None, "", ":memory:"):
        return
    Path(database_name).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _inspect_db_state(database_url: str) -> dict[str, Any]:
    _ensure_sqlite_parent(database_url)
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
    if state["current_revision"] is not None:
        command.upgrade(cfg, "head")
        ok, message = check_database_at_head()
        return (True, f"database upgraded to baseline {head}") if ok else (False, message)
    return check_database_at_head()
