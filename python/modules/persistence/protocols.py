"""Small persistence boundaries shared by storage implementations.

The application currently has both SQLAlchemy-backed repositories and a
native ``sqlite3`` memory store.  These protocols intentionally describe only
the lifecycle operations that a runtime container needs.  They do not impose
an ORM, schema, or transaction model on either implementation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol, TypeAlias, runtime_checkable

BackupTarget: TypeAlias = str | Path | sqlite3.Connection


@runtime_checkable
class TransactionProtocol(Protocol):
    """A resource that can finish or abandon its current transaction."""

    def commit(self) -> None:
        """Persist the current transaction."""
        ...

    def rollback(self) -> None:
        """Abandon the current transaction."""
        ...


@runtime_checkable
class CloseProtocol(Protocol):
    """A resource that can release its owned handles."""

    def close(self) -> None:
        """Release the resource."""
        ...


@runtime_checkable
class HealthCheckProtocol(Protocol):
    """A storage boundary that can report whether it is usable."""

    def health_check(self) -> bool:
        """Return ``True`` when a minimal read query succeeds."""
        ...


@runtime_checkable
class BackupProtocol(Protocol):
    """A storage boundary that can copy its durable state."""

    def backup(self, target: BackupTarget) -> Path | None:
        """Copy the database to ``target`` and return a path when applicable."""
        ...


@runtime_checkable
class PersistenceBackend(
    TransactionProtocol,
    CloseProtocol,
    HealthCheckProtocol,
    BackupProtocol,
    Protocol,
):
    """Minimum lifecycle contract required by :class:`UnitOfWork`."""


class PersistenceError(RuntimeError):
    """Base error raised when a persistence boundary cannot complete an operation."""


class PersistenceClosedError(PersistenceError):
    """Raised when an operation is attempted after the boundary is closed."""


__all__ = [
    "BackupProtocol",
    "BackupTarget",
    "CloseProtocol",
    "HealthCheckProtocol",
    "PersistenceBackend",
    "PersistenceClosedError",
    "PersistenceError",
    "TransactionProtocol",
]
