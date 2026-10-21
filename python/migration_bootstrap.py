from __future__ import annotations

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command
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


def _normalize_sql_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().strip("'").strip('"')


def _column_signature(column: Any) -> tuple[Any, ...]:
    server_default = getattr(column, "server_default", None)
    default_value = getattr(server_default, "arg", server_default) if server_default is not None else None
    return (
        str(column.name),
        str(column.type).lower(),
        bool(column.nullable),
        _normalize_sql_value(default_value),
        bool(getattr(column, "primary_key", False)),
    )


def _actual_column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column["name"]),
        str(column["type"]).lower(),
        bool(column.get("nullable", True)),
        _normalize_sql_value(column.get("default")),
        bool(column.get("primary_key", 0)),
    )


def _index_signature(name: str | None, unique: bool, columns: Any) -> tuple[Any, ...]:
    return (name, bool(unique), tuple(str(column) for column in columns))


def _unique_signature(columns: Any) -> tuple[str, ...]:
    return tuple(str(column) for column in columns)


def _expected_schema() -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table_name, table in Base.metadata.tables.items():
        tables[table_name] = {
            "columns": tuple(_column_signature(column) for column in table.columns),
            "primary_key": tuple(column.name for column in table.primary_key.columns),
            "indexes": tuple(
                sorted(
                    _index_signature(index.name, bool(index.unique), (column.name for column in index.columns))
                    for index in table.indexes
                )
            ),
            "unique_constraints": tuple(
                sorted(_unique_signature(column.name for column in constraint.columns)
                       for constraint in table.constraints
                       if constraint.__class__.__name__ == "UniqueConstraint")
            ),
            "foreign_keys": tuple(sorted(
                (
                    str(foreign_key.parent.name),
                    str(foreign_key.target_fullname),
                )
                for foreign_key in table.foreign_keys
            )),
        }
    return tables


def _inspect_db_state(database_url: str) -> dict[str, Any]:
    _ensure_sqlite_parent(database_url)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            schema: dict[str, Any] = {}
            for table in sorted(tables - {"alembic_version"}):
                schema[table] = {
                    "columns": tuple(_actual_column_signature(column) for column in inspector.get_columns(table)),
                    "primary_key": tuple(inspector.get_pk_constraint(table).get("constrained_columns") or ()),
                    "indexes": tuple(sorted(
                        _index_signature(index.get("name"), bool(index.get("unique")), index.get("column_names") or ())
                        for index in inspector.get_indexes(table)
                        if index.get("name")
                    )),
                    "unique_constraints": tuple(sorted(
                        _unique_signature(constraint.get("column_names") or ())
                        for constraint in inspector.get_unique_constraints(table)
                    )),
                    "foreign_keys": tuple(sorted(
                        (
                            str(column),
                            f"{foreign_key.get('referred_table')}.{referred_column}",
                        )
                        for foreign_key in inspector.get_foreign_keys(table)
                        for column, referred_column in zip(
                            foreign_key.get("constrained_columns") or (),
                            foreign_key.get("referred_columns") or (),
                        )
                    )),
                }
            return {
                "tables": tables,
                "current_revision": MigrationContext.configure(connection).get_current_revision(),
                "schema": schema,
            }
    finally:
        engine.dispose()


def _matches_head_schema(state: dict[str, Any]) -> bool:
    return state["schema"] == _expected_schema()


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
    return False, (
        f"database revision none does not match baseline {head}; "
        "existing databases without Alembic revision require explicit migration"
    )


def main() -> int:
    """Run the migration step the launcher invokes before starting the backend.

    ``tools/yuizaki-launcher`` calls this module as a script and aborts startup
    when it fails, so the exit code has to reflect the real outcome: a database
    that cannot be brought to the Alembic head must stop the launch rather than
    let the backend serve traffic against a stale schema.
    """
    ok, message = bootstrap_database()
    if ok:
        print(f"[OK] {message}")
        return 0
    print(f"[ERROR] {message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
