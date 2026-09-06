from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from modules.persistence import (
    PersistenceBackend,
    PersistenceClosedError,
    SQLAlchemyPersistenceAdapter,
    SQLitePersistenceAdapter,
    UnitOfWork,
)


def test_protocol_is_implemented_by_sqlite_adapter() -> None:
    connection = sqlite3.connect(":memory:")
    adapter = SQLitePersistenceAdapter(connection)

    assert isinstance(adapter, PersistenceBackend)
    assert adapter.health_check() is True
    adapter.close()


def test_unit_of_work_commits_and_closes_sqlite_connection(tmp_path: Path) -> None:
    database_path = tmp_path / "source.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE items (value TEXT NOT NULL)")

    with UnitOfWork(connection) as unit:
        unit.resource.execute("INSERT INTO items (value) VALUES (?)", ("saved",))
        assert unit.health_check() is True

    with sqlite3.connect(database_path) as reader:
        assert reader.execute("SELECT value FROM items").fetchone() == ("saved",)

    assert unit.closed is True
    with pytest.raises(PersistenceClosedError):
        unit.health_check()


def test_unit_of_work_rolls_back_on_exception(tmp_path: Path) -> None:
    database_path = tmp_path / "rollback.db"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE items (value TEXT NOT NULL)")

    with pytest.raises(RuntimeError, match="abort"), UnitOfWork(connection) as unit:
        unit.resource.execute("INSERT INTO items (value) VALUES (?)", ("discarded",))
        raise RuntimeError("abort")

    with sqlite3.connect(database_path) as reader:
        assert reader.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)


def test_sqlite_backup_round_trip(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    backup_path = tmp_path / "backup" / "copy.db"
    connection = sqlite3.connect(source_path)
    connection.execute("CREATE TABLE items (value TEXT NOT NULL)")
    connection.execute("INSERT INTO items (value) VALUES (?)", ("copied",))

    unit = UnitOfWork(connection)
    unit.commit()
    assert unit.backup(backup_path) == backup_path.resolve()
    unit.close()

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT value FROM items").fetchone() == ("copied",)


def test_sqlalchemy_session_adapter_lifecycle_and_backup(tmp_path: Path) -> None:
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    source_path = tmp_path / "sqlalchemy.db"
    backup_path = tmp_path / "sqlalchemy-copy.db"
    engine = create_engine(f"sqlite:///{source_path}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE items (value TEXT NOT NULL)"))

    session = Session(engine)
    session.execute(text("INSERT INTO items (value) VALUES ('sqlalchemy')"))
    unit = UnitOfWork(session, adapter=SQLAlchemyPersistenceAdapter(session))
    assert unit.health_check() is True
    unit.commit()
    assert unit.backup(backup_path) == backup_path.resolve()
    unit.close()

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT value FROM items").fetchone() == ("sqlalchemy",)
    engine.dispose()
