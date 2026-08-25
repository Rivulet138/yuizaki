from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from migration_bootstrap import bootstrap_database, check_database_at_head, load_alembic_config


def _set_database_url(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")


def test_bootstrap_empty_database_creates_current_baseline(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "empty.db"
    _set_database_url(db_path, monkeypatch)

    ok, message = bootstrap_database()

    assert ok is True
    assert "created from baseline" in message
    head_ok, _ = check_database_at_head()
    assert head_ok is True

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            workspace = connection.execute(text("SELECT id FROM workspaces WHERE id = 'default'")).scalar_one()
            companion = connection.execute(text("SELECT id FROM companions WHERE id = 'default'")).scalar_one()
    finally:
        engine.dispose()

    assert revision == ScriptDirectory.from_config(load_alembic_config()).get_current_head()
    assert workspace == "default"
    assert companion == "default"


def test_bootstrap_rejects_nonbaseline_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY)"))
    finally:
        engine.dispose()

    _set_database_url(db_path, monkeypatch)
    ok, message = bootstrap_database()

    assert ok is False
    assert "does not match" in message


def test_bootstrap_upgrades_managed_database_to_current_head(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "managed-old.db"
    _set_database_url(db_path, monkeypatch)
    cfg = load_alembic_config()
    command.upgrade(cfg, "20260808_00")

    ok, message = bootstrap_database()

    assert ok is True
    assert "upgraded to baseline" in message
    head_ok, _ = check_database_at_head()
    assert head_ok is True
