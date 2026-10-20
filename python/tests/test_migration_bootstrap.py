from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import migration_bootstrap


PYTHON_ROOT = Path(__file__).resolve().parents[1]


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
        lambda: (True, "database at current baseline 20261020_00"),
    )

    exit_code = migration_bootstrap.main()

    assert exit_code == 0
    assert "[OK] database at current baseline 20261020_00" in capsys.readouterr().out


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
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "[OK]" in completed.stdout
    assert database.exists()


def test_script_entrypoint_is_idempotent(tmp_path) -> None:
    database = tmp_path / "chat.db"
    first = subprocess.run(
        [sys.executable, "migration_bootstrap.py"],
        cwd=PYTHON_ROOT, env=_script_env(database), capture_output=True, text=True, timeout=180,
    )
    second = subprocess.run(
        [sys.executable, "migration_bootstrap.py"],
        cwd=PYTHON_ROOT, env=_script_env(database), capture_output=True, text=True, timeout=180,
    )

    assert first.returncode == 0, first.stderr[-2000:]
    assert second.returncode == 0, second.stderr[-2000:]
    assert "20261020_00" in second.stdout


@pytest.mark.parametrize("module_path", ["migration_bootstrap.py"])
def test_module_still_defines_the_api_schema_policy_imports(module_path: str) -> None:
    """enforce_schema_policy imports these by name; a rename would break startup."""
    assert Path(PYTHON_ROOT, module_path).exists()
    assert callable(migration_bootstrap.bootstrap_database)
    assert callable(migration_bootstrap.check_database_at_head)
