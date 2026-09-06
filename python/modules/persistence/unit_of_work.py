"""Adapters and unit-of-work lifecycle for local persistence.

This module is deliberately independent from the existing repositories.  A
caller may wrap an existing SQLAlchemy ``Session`` or a native
``sqlite3.Connection`` without changing how that repository stores data.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Generic, TypeVar, cast

from sqlalchemy import text as sqlalchemy_text
from sqlalchemy.exc import SQLAlchemyError

from .protocols import (
    BackupTarget,
    PersistenceBackend,
    PersistenceClosedError,
    PersistenceError,
)

ResourceT = TypeVar("ResourceT")


def _target_path(target: BackupTarget) -> Path | None:
    if isinstance(target, (str, Path)):
        return Path(target).expanduser().resolve()
    return None


def _open_backup_target(target: BackupTarget) -> tuple[sqlite3.Connection, Path | None, bool]:
    """Return a SQLite destination and whether this adapter owns it."""

    if isinstance(target, sqlite3.Connection):
        return target, None, False

    path = _target_path(target)
    if path is None:
        raise PersistenceError("backup_target_must_be_path_or_sqlite_connection")
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path), path, True


def _backup_sqlite_connection(source: sqlite3.Connection, target: BackupTarget) -> Path | None:
    destination, path, owned = _open_backup_target(target)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        if owned:
            destination.close()
    return path


def _sqlalchemy_sqlite_connection(session: Any) -> tuple[sqlite3.Connection, bool]:
    """Resolve a SQLite DB-API connection from a SQLAlchemy session.

    SQLAlchemy intentionally exposes several wrapper layers depending on the
    installed version and pool implementation.  The returned boolean marks a
    raw engine connection that this function acquired and therefore owns.
    """

    candidates: list[Any] = [session]
    connection_method = getattr(session, "connection", None)
    if callable(connection_method):
        candidates.append(connection_method())
    candidates.append(getattr(session, "bind", None))

    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, sqlite3.Connection):
            return candidate, False
        for attribute in ("driver_connection", "dbapi_connection", "connection"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, sqlite3.Connection):
                return nested, False

    bind = getattr(session, "bind", None)
    raw_connection = getattr(bind, "raw_connection", None)
    if callable(raw_connection):
        raw = raw_connection()
        # SQLAlchemy 2 exposes the DB-API connection as ``driver_connection``.
        # Avoid touching the deprecated ``_ConnectionFairy.connection`` member
        # so health/backup checks do not emit warnings on every startup.
        for candidate in (raw, getattr(raw, "driver_connection", None), getattr(raw, "dbapi_connection", None)):
            if isinstance(candidate, sqlite3.Connection):
                return candidate, True
        close = getattr(raw, "close", None)
        if callable(close):
            close()

    raise PersistenceError("sqlalchemy_session_is_not_bound_to_sqlite")


class SQLitePersistenceAdapter(PersistenceBackend):
    """Adapt a native :class:`sqlite3.Connection` to the persistence protocol."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def commit(self) -> None:
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()

    def health_check(self) -> bool:
        try:
            self.connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def backup(self, target: BackupTarget) -> Path | None:
        try:
            return _backup_sqlite_connection(self.connection, target)
        except sqlite3.Error as exc:
            raise PersistenceError("sqlite_backup_failed") from exc


class SQLAlchemyPersistenceAdapter(PersistenceBackend):
    """Adapt an existing SQLAlchemy Session without owning its factory."""

    def __init__(
        self,
        session: Any,
        *,
        backup_source: Callable[[], sqlite3.Connection] | None = None,
    ):
        self.session = session
        self._backup_source = backup_source

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def close(self) -> None:
        self.session.close()

    def health_check(self) -> bool:
        try:
            # SQLAlchemy 2 requires ``text`` for raw textual SQL.
            result = self.session.execute(sqlalchemy_text("SELECT 1"))
            scalar = getattr(result, "scalar", None)
            if callable(scalar):
                scalar()
            return True
        except ImportError:
            return False
        except (SQLAlchemyError, AttributeError, TypeError, ValueError):
            return False

    def backup(self, target: BackupTarget) -> Path | None:
        source: sqlite3.Connection | None = None
        owned = False
        try:
            if self._backup_source is not None:
                source = self._backup_source()
            else:
                source, owned = _sqlalchemy_sqlite_connection(self.session)
            if not isinstance(source, sqlite3.Connection):
                raise PersistenceError("sqlalchemy_backup_source_must_be_sqlite_connection")
            return _backup_sqlite_connection(source, target)
        except PersistenceError:
            raise
        except sqlite3.Error as exc:
            raise PersistenceError("sqlalchemy_sqlite_backup_failed") from exc
        finally:
            if owned and source is not None:
                source.close()


class DelegatingPersistenceAdapter(PersistenceBackend, Generic[ResourceT]):
    """Wrap a resource that already implements the protocol.

    This is useful for tests and for future repositories whose native resource
    already exposes ``health_check`` and ``backup`` methods.
    """

    def __init__(self, resource: ResourceT):
        self.resource = resource

    def commit(self) -> None:
        cast(Any, self.resource).commit()

    def rollback(self) -> None:
        cast(Any, self.resource).rollback()

    def close(self) -> None:
        cast(Any, self.resource).close()

    def health_check(self) -> bool:
        result = cast(Any, self.resource).health_check()
        return bool(result)

    def backup(self, target: BackupTarget) -> Path | None:
        return cast(Any, self.resource).backup(target)


def adapt_persistence(resource: object) -> PersistenceBackend:
    """Select an adapter for a SQLite, SQLAlchemy, or protocol-native resource."""

    if isinstance(resource, sqlite3.Connection):
        return SQLitePersistenceAdapter(resource)
    if all(callable(getattr(resource, name, None)) for name in ("commit", "rollback", "close")):
        if all(callable(getattr(resource, name, None)) for name in ("health_check", "backup")):
            return DelegatingPersistenceAdapter(resource)
        return SQLAlchemyPersistenceAdapter(resource)
    raise TypeError("resource_does_not_match_persistence_protocol")


class UnitOfWork(Generic[ResourceT]):
    """Context-managed transaction boundary over an existing resource.

    Successful contexts commit, exceptional contexts roll back, and both paths
    close the resource.  Explicit lifecycle calls remain available for code
    that cannot use a context manager.
    """

    def __init__(
        self,
        resource: ResourceT | PersistenceBackend,
        *,
        adapter: PersistenceBackend | None = None,
    ):
        self._adapter = adapter or adapt_persistence(resource)
        self._closed = False

    @property
    def resource(self) -> ResourceT | PersistenceBackend:
        """Return the original resource when the adapter exposes one."""

        return cast(Any, getattr(self._adapter, "resource", getattr(self._adapter, "session", getattr(self._adapter, "connection", self._adapter))))

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> UnitOfWork[ResourceT]:
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

    def _ensure_open(self) -> None:
        if self._closed:
            raise PersistenceClosedError("unit_of_work_closed")

    def commit(self) -> None:
        self._ensure_open()
        self._adapter.commit()

    def rollback(self) -> None:
        self._ensure_open()
        self._adapter.rollback()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._adapter.close()
        finally:
            self._closed = True

    def health_check(self) -> bool:
        self._ensure_open()
        return bool(self._adapter.health_check())

    def backup(self, target: BackupTarget) -> Path | None:
        self._ensure_open()
        return self._adapter.backup(target)


__all__ = [
    "DelegatingPersistenceAdapter",
    "SQLAlchemyPersistenceAdapter",
    "SQLitePersistenceAdapter",
    "UnitOfWork",
    "adapt_persistence",
]
