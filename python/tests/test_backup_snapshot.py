"""Backups must retain committed WAL rows and use the configured authorities."""
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.system.backup_snapshot import configured_sources, snapshot_database
from routes.storage_api import create_storage_router


def test_online_backup_contains_wal_commits_and_is_standalone(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite"
    snapshot = tmp_path / "backup" / "snapshot.sqlite"
    with sqlite3.connect(live) as writer:
        writer.execute("CREATE TABLE entries (body TEXT)")
        writer.commit()
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO entries VALUES ('committed in WAL')")
        writer.commit()
        assert Path(f"{live}-wal").stat().st_size > 0
        snapshot_database(live, snapshot)
        with sqlite3.connect(snapshot) as reader:
            assert reader.execute("SELECT body FROM entries").fetchall() == [("committed in WAL",)]
            assert reader.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert reader.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert not Path(f"{snapshot}-wal").exists()
        assert writer.execute("SELECT COUNT(*) FROM entries").fetchone() == (1,)


def test_snapshot_rejects_source_overwrite_and_missing_database(tmp_path: Path) -> None:
    source = tmp_path / "database.sqlite"
    with sqlite3.connect(source) as writer:
        writer.execute("CREATE TABLE entries (body TEXT)")
    with pytest.raises(ValueError, match="source_equals_destination"):
        snapshot_database(source, source)
    with pytest.raises(FileNotFoundError):
        snapshot_database(tmp_path / "missing.sqlite", tmp_path / "backup.sqlite")


def test_offline_sources_resolve_custom_database_settings_and_memory(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "custom-settings.json"
    memory = tmp_path / "memory.sqlite"
    chat = tmp_path / "chat.sqlite"
    settings.write_text(json.dumps({"memory": {"backend": "sqlite", "sqlite_path": str(memory)}}), encoding="utf-8")
    monkeypatch.setenv("YUIZAKI_SETTINGS_PATH", str(settings))
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{chat.as_posix()}")
    monkeypatch.setenv("AUDIO_CACHE_DIR", str(tmp_path / "audio"))
    result = configured_sources()
    assert result["database"] == str(chat)
    assert result["memory"] == str(memory)
    assert result["settings"] == str(settings)
    assert result["source"] == "configured_offline"
    settings.write_text('{"memory":{"backend":"inmemory"}}', encoding="utf-8")
    assert configured_sources()["memory_persistence"] == "memory_only"


def test_offline_sources_do_not_claim_non_file_database_is_backed_up(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YUIZAKI_SETTINGS_PATH", str(tmp_path / "missing-settings.json"))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    with pytest.raises(ValueError, match="requires_file_sqlite"):
        configured_sources()


def test_running_sources_use_actual_repository_and_unwrapped_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YUIZAKI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    application = FastAPI()
    memory = SimpleNamespace(authority=SimpleNamespace(db_path=tmp_path / "facts.sqlite"))
    application.include_router(create_storage_router(
        audio_cache_dir=tmp_path / "audio", runtime_temp_dir=tmp_path / "tmp",
        memory_store_provider=lambda: memory,
        database_provider=lambda: SimpleNamespace(db_path=tmp_path / "conversation.sqlite"),
    ))
    with TestClient(application) as client:
        response = client.get("/api/system/storage/backup-sources")
        assert response.status_code == 200
        data = response.json()
        assert data["database"] == str(tmp_path / "conversation.sqlite")
        assert data["memory"] == str(tmp_path / "facts.sqlite")
        assert data["source"] == "running_backend"
        memory.authority = SimpleNamespace()
        assert client.get("/api/system/storage/backup-sources").json()["memory_persistence"] == "memory_only"


def test_running_sources_fail_closed_without_initialized_database(tmp_path: Path) -> None:
    application = FastAPI()
    application.include_router(create_storage_router(
        audio_cache_dir=tmp_path / "audio", runtime_temp_dir=tmp_path / "tmp",
        memory_store_provider=lambda: None, database_provider=lambda: None,
    ))
    with TestClient(application) as client:
        assert client.get("/api/system/storage/backup-sources").status_code == 409


def test_restore_into_live_wal_database_uses_sqlite_transaction_protocol(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(live) as connection:
        connection.execute("CREATE TABLE entries (body TEXT)")
        connection.execute("INSERT INTO entries VALUES ('snapshot row')")
        connection.commit()
        snapshot_database(live, snapshot)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO entries VALUES ('later WAL row')")
        connection.commit()
        snapshot_database(snapshot, live, standalone=False)
        assert connection.execute("SELECT body FROM entries").fetchall() == [("snapshot row",)]
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
        connection.execute("INSERT INTO entries VALUES ('post restore row')")
        connection.commit()
    with sqlite3.connect(live) as reopened:
        assert reopened.execute("SELECT COUNT(*) FROM entries").fetchone() == (2,)


@pytest.mark.parametrize("url", ["sqlite:///", "sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"])
def test_offline_sources_reject_empty_and_memory_only_database_urls(tmp_path: Path, monkeypatch, url: str) -> None:
    monkeypatch.setenv("YUIZAKI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="requires_file_sqlite"):
        configured_sources()


def test_offline_sources_accept_sqlite_driver_urls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("YUIZAKI_SETTINGS_PATH", str(tmp_path / "settings.json"))
    database = tmp_path / "driver.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{database.as_posix()}")
    assert configured_sources()["database"] == str(database)
