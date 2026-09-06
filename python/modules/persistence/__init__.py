"""Persistence boundary primitives."""

from .protocols import (
    BackupProtocol,
    BackupTarget,
    CloseProtocol,
    HealthCheckProtocol,
    PersistenceBackend,
    PersistenceClosedError,
    PersistenceError,
    TransactionProtocol,
)
from .unit_of_work import (
    DelegatingPersistenceAdapter,
    SQLAlchemyPersistenceAdapter,
    SQLitePersistenceAdapter,
    UnitOfWork,
    adapt_persistence,
)

__all__ = [
    "BackupProtocol",
    "BackupTarget",
    "CloseProtocol",
    "DelegatingPersistenceAdapter",
    "HealthCheckProtocol",
    "PersistenceBackend",
    "PersistenceClosedError",
    "PersistenceError",
    "SQLAlchemyPersistenceAdapter",
    "SQLitePersistenceAdapter",
    "TransactionProtocol",
    "UnitOfWork",
    "adapt_persistence",
]
