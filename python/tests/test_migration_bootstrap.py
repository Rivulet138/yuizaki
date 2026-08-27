from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

import database.repository as repository_module
from database.repository import DatabaseRepository
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


def test_default_database_url_follows_runtime_data_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path / "runtime-data"))

    cfg = load_alembic_config()

    expected = (tmp_path / "runtime-data" / "chat.db").as_posix()
    assert cfg.get_main_option("sqlalchemy.url") == f"sqlite:///{expected}"

    repository = DatabaseRepository()
    try:
        assert repository.engine.url.database == expected
        assert repository.db_path == tmp_path / "runtime-data" / "chat.db"
    finally:
        repository.close()


def test_explicit_database_url_wins_over_runtime_data_directory(tmp_path, monkeypatch) -> None:
    explicit_db = tmp_path / "explicit" / "chat.db"
    runtime_data = tmp_path / "runtime-data"
    _set_database_url(explicit_db, monkeypatch)
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(runtime_data))

    cfg = load_alembic_config()
    ok, _ = bootstrap_database()
    repository = DatabaseRepository()
    try:
        expected_url = f"sqlite:///{explicit_db.as_posix()}"
        assert ok is True
        assert cfg.get_main_option("sqlalchemy.url") == expected_url
        assert repository.engine.url.database == explicit_db.as_posix()
        assert repository.db_path == explicit_db
        assert explicit_db.exists()
        assert not runtime_data.exists()
    finally:
        repository.close()


def test_explicit_non_sqlite_database_url_is_preserved(monkeypatch) -> None:
    database_url = "postgresql+psycopg://user:password@example.invalid/yuizaki"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("YUIZAKI_DATA_DIR", "ignored-data-dir")
    real_create_engine = create_engine
    captured: dict[str, object] = {}

    def capture_create_engine(url: str, **options: object):
        captured.update({"url": url, "options": options})
        return real_create_engine("sqlite:///:memory:")

    monkeypatch.setattr(repository_module, "create_engine", capture_create_engine)

    assert load_alembic_config().get_main_option("sqlalchemy.url") == database_url
    repository = DatabaseRepository()
    try:
        assert captured == {"url": database_url, "options": {"echo": False}}
        assert repository.database_url == database_url
        assert repository.db_path is None
    finally:
        repository.close()


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
