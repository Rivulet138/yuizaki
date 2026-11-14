"""Resolve configured backup sources and snapshot SQLite through its online API.

The CLI is a short-lived helper for Electron; it never imports or starts app.py.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def snapshot_database(source: Path, destination: Path, *, standalone: bool = True) -> None:
    source = source.expanduser().resolve(strict=True)
    destination = destination.expanduser().resolve()
    if source == destination:
        raise ValueError("backup_source_equals_destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=10)
    writer = None
    try:
        if reader.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup_source_integrity_check_failed")
        writer = sqlite3.connect(destination, timeout=10)
        reader.backup(writer, pages=256, sleep=0.05)
        if writer.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("backup_integrity_check_failed")
        # Make the resulting file independent of any sidecar WAL.
        if standalone:
            writer.execute("PRAGMA journal_mode=DELETE")
    finally:
        if writer is not None:
            writer.close()
        reader.close()


def configured_sources() -> dict:
    # Match uvicorn's normal .env loading without overriding inherited paths.
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env", override=False)
    from modules.core.config import config
    from modules.core.paths import (
        audio_cache_dir_from_env,
        data_dir_from_env,
        database_url_from_env,
        resolve_backend_path,
        settings_path_from_env,
    )
    data_dir = data_dir_from_env()
    settings_path = settings_path_from_env()
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
    if not isinstance(settings, dict):
        raise TypeError("invalid_settings_for_backup")
    memory = settings.get("memory", {})
    if not isinstance(memory, dict):
        raise TypeError("invalid_memory_settings_for_backup")
    from sqlalchemy.engine import make_url

    database_url = make_url(database_url_from_env())
    raw_database = database_url.database
    if database_url.get_backend_name() != "sqlite" or raw_database in (None, "", ":memory:"):
        raise ValueError("backup_requires_file_sqlite_database")
    backend = str(memory.get("backend", config.memory.backend)).strip().lower()
    memory_path = resolve_backend_path(memory.get("sqlite_path") or config.memory.sqlite_path, data_dir / "memory.db")
    return {
        "source": "configured_offline",
        "database": str(resolve_backend_path(raw_database, data_dir / "chat.db")),
        "memory": str(memory_path),
        "memory_persistence": "memory_only" if backend == "inmemory" else "disk",
        "settings": str(settings_path),
        "data_dir": str(data_dir),
        "audio_cache": str(audio_cache_dir_from_env()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sources")
    for command in ("snapshot", "restore"):
        snapshot = sub.add_parser(command)
        snapshot.add_argument("source", type=Path)
        snapshot.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "sources":
        result = configured_sources()
    else:
        snapshot_database(args.source, args.destination, standalone=args.command == "snapshot")
        result = {"ok": True, "method": "sqlite_online_backup"}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    # Direct-file invocation keeps the helper available in packaged runtimes.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    main()
