from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

MEMORY_OPERATION_TYPES = frozenset({
    "create",
    "update",
    "correction",
    "review",
    "forget",
    "restore",
    "rollback",
    "delete",
    "feedback",
    "maintenance",
})


@dataclass(frozen=True)
class MemoryOperation:
    """A durable, user-auditable mutation of a memory record.

    The operation ledger is intentionally separate from document metadata. A
    document may be compacted or projected into an index, while this event
    remains the authoritative explanation of who changed it and why.
    """

    operation_id: str
    operation: str
    document_id: str
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str = "memory-api"
    scope: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    reason: str | None = None
    evidence: Any = None
    before_revision: int | None = None
    after_revision: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise ValueError("operation_id is required")
        if self.operation not in MEMORY_OPERATION_TYPES:
            raise ValueError(f"unknown memory operation: {self.operation}")
        if not self.document_id.strip():
            raise ValueError("document_id is required")
        for field_name in ("workspace_id", "session_id"):
            value = getattr(self, field_name)
            normalized = str(value or "").strip() or None
            object.__setattr__(self, field_name, normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryOperationLog:
    """Bounded fallback ledger for non-SQLite memory backends."""

    def __init__(self, max_operations: int = 10_000) -> None:
        self.max_operations = max(100, int(max_operations))
        self._items: list[MemoryOperation] = []
        self._lock = RLock()

    def append(self, operation: MemoryOperation) -> None:
        with self._lock:
            self._items.append(operation)
            if len(self._items) > self.max_operations:
                del self._items[: len(self._items) - self.max_operations]

    def list(
        self,
        *,
        document_id: str | None = None,
        scope: str | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(500, int(limit)))
        normalized_workspace_id = str(workspace_id or "").strip() or None
        normalized_session_id = str(session_id or "").strip() or None
        with self._lock:
            items: Iterable[MemoryOperation] = reversed(self._items)
            selected = [
                item.to_dict()
                for item in items
                if (document_id is None or item.document_id == document_id)
                and (scope is None or item.scope == scope)
                # A scoped request must never treat an unscoped legacy event as
                # belonging to the requested workspace or session.
                and (normalized_workspace_id is None or item.workspace_id == normalized_workspace_id)
                and (normalized_session_id is None or item.session_id == normalized_session_id)
            ]
        return selected[:bounded_limit]


def new_operation(
    *,
    operation: str,
    document_id: str,
    scope: str | None = None,
    workspace_id: str | None = None,
    session_id: str | None = None,
    reason: str | None = None,
    evidence: Any = None,
    before_revision: int | None = None,
    after_revision: int | None = None,
    details: dict[str, Any] | None = None,
) -> MemoryOperation:
    return MemoryOperation(
        operation_id=f"memop_{uuid4().hex}",
        operation=operation,
        document_id=document_id,
        scope=scope,
        workspace_id=workspace_id,
        session_id=session_id,
        reason=reason,
        evidence=evidence,
        before_revision=before_revision,
        after_revision=after_revision,
        details=dict(details or {}),
    )
