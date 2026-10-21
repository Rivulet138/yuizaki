from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

import migration_bootstrap
from alembic import command
from database.models import ChatMessage

PYTHON_ROOT = Path(__file__).resolve().parents[1]


def _idempotency_index_contract() -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Read the current index contract and derive its previous shape."""
    table = ChatMessage.__table__
    idempotency_column = table.c.turn_idempotency_key
    role_column = table.c.role
    scope_column = table.c.session_id
    index = next(
        index
        for index in table.indexes
        if index.unique
        and index.columns.contains_column(idempotency_column)
        and index.columns.contains_column(role_column)
    )
    current_columns = tuple(column.name for column in index.columns)
    previous_columns = tuple(
        column for column in current_columns if column != scope_column.name
    )
    return str(index.name), current_columns, previous_columns


def _script_env(database: Path) -> dict[str, str]:
    """Environment for a real `python migration_bootstrap.py` run.

    The parent environment is inherited on purpose: the launcher runs this with
    its own env, and a sanitized env would hide the installed alembic behind the
    local `python/alembic` migration directory.
    """
    return {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "PYTHONPATH": str(PYTHON_ROOT),
    }


def test_main_reports_success_and_returns_zero(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        migration_bootstrap,
        "bootstrap_database",
        lambda: (True, "database at current baseline"),
    )

    exit_code = migration_bootstrap.main()

    assert exit_code == 0
    assert "[OK] database at current baseline" in capsys.readouterr().out


def test_main_reports_failure_and_returns_non_zero(monkeypatch, capsys) -> None:
    """The launcher aborts on a non-zero exit, so a bad schema must not pass."""
    monkeypatch.setattr(
        migration_bootstrap,
        "bootstrap_database",
        lambda: (False, "database schema does not match the current baseline"),
    )

    exit_code = migration_bootstrap.main()

    assert exit_code == 1
    assert "[ERROR] database schema does not match" in capsys.readouterr().out


def test_script_entrypoint_bootstraps_a_real_database(tmp_path, monkeypatch) -> None:
    """`python migration_bootstrap.py` is what the launcher actually runs."""
    database = tmp_path / "chat.db"
    completed = subprocess.run(
        [sys.executable, "migration_bootstrap.py"],
        cwd=PYTHON_ROOT,
        env=_script_env(database),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "[OK]" in completed.stdout
    assert database.exists()


def test_script_entrypoint_is_idempotent(tmp_path) -> None:
    database = tmp_path / "chat.db"
    first = subprocess.run(
        [sys.executable, "migration_bootstrap.py"],
        cwd=PYTHON_ROOT, env=_script_env(database), capture_output=True, text=True, timeout=180, check=False,
    )
    second = subprocess.run(
        [sys.executable, "migration_bootstrap.py"],
        cwd=PYTHON_ROOT, env=_script_env(database), capture_output=True, text=True, timeout=180, check=False,
    )

    assert first.returncode == 0, first.stderr[-2000:]
    assert second.returncode == 0, second.stderr[-2000:]
    assert "database upgraded to baseline" in second.stdout


def test_bootstrap_upgrades_the_previous_revision_index(tmp_path, monkeypatch) -> None:
    database = tmp_path / "chat.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    cfg = migration_bootstrap.load_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    assert head is not None
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")
    index_name, current_columns, previous_columns = _idempotency_index_contract()
    table_name = ChatMessage.__tablename__

    engine = create_engine(str(cfg.get_main_option("sqlalchemy.url")))
    try:
        old_index = next(
            index for index in inspect(engine).get_indexes(table_name)
            if index.get("name") == index_name
        )
        assert tuple(old_index["column_names"]) == previous_columns
        assert bool(old_index["unique"])
    finally:
        engine.dispose()

    ok, message = migration_bootstrap.bootstrap_database()

    assert ok, message
    engine = create_engine(str(cfg.get_main_option("sqlalchemy.url")))
    try:
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == head
        new_index = next(
            index for index in inspect(engine).get_indexes(table_name)
            if index.get("name") == index_name
        )
        assert tuple(new_index["column_names"]) == current_columns
        assert bool(new_index["unique"])
    finally:
        engine.dispose()


def test_module_still_defines_the_api_schema_policy_imports() -> None:
    """enforce_schema_policy imports these by name; a rename would break startup."""
    assert migration_bootstrap.__file__ is not None
    assert Path(migration_bootstrap.__file__).exists()
    assert callable(migration_bootstrap.bootstrap_database)
    assert callable(migration_bootstrap.check_database_at_head)
