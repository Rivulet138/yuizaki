# pyright: reportImportCycles=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from .schema import MemorySearchFilters, RetrievalTrace

if TYPE_CHECKING:
    from .vector_store import Document


@dataclass
class MemoryBackendStatus:
    backend: str
    healthy: bool
    message: str
    document_count: int = 0
    metadata: dict[str, Any] | None = None


class MemorySearchIncompleteError(RuntimeError):
    code = "memory_search_scan_limit_reached"

    def __init__(
        self,
        *,
        requested_count: int,
        selected_ids: list[str],
        scanned_count: int,
        rejected_count: int,
        scan_limit: int,
    ) -> None:
        self.requested_count = requested_count
        self.selected_ids = selected_ids
        self.scanned_count = scanned_count
        self.rejected_count = rejected_count
        self.scan_limit = scan_limit
        self.trace: dict[str, Any] | None = None
        super().__init__(
            f"Memory search reached its {scan_limit}-document scan limit before producing "
            f"{requested_count} complete results"
        )

    @property
    def returned_count(self) -> int:
        return len(self.selected_ids)

    def to_detail(self) -> dict[str, Any]:
        trace = self.trace or {
            "complete": False,
            "error_code": self.code,
            "scan_limit_reached": True,
            "candidate_limit": self.scan_limit,
            "candidate_count": self.scanned_count,
            "filtered_count": self.returned_count,
            "filtered_out_count": self.rejected_count,
            "selected_ids": self.selected_ids,
        }
        return {
            "error": self.code,
            "message": str(self),
            "scan_limit_reached": True,
            "requested_count": self.requested_count,
            "returned_count": self.returned_count,
            "scanned_count": self.scanned_count,
            "rejected_count": self.rejected_count,
            "scan_limit": self.scan_limit,
            "trace": trace,
        }


class MemoryBackend(Protocol):
    backend_name: str

    def add_document(self, doc: Document) -> None: ...

    def add_metadata_document(self, doc: Document) -> None: ...

    def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> None: ...

    def delete_document(self, doc_id: str) -> None: ...

    def list_documents(self) -> list[Document]: ...

    def rebuild_index(self) -> dict[str, Any]: ...

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]: ...

    def search_with_rerank(
        self,
        query: str,
        top_k: int = 5,
        memory_types: Sequence[Any] | None = None,
        recency_weight: float = 0.2,
        quality_weight: float = 0.15,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]: ...

    def get_status(self) -> MemoryBackendStatus: ...


@dataclass
class MemoryQueryResult:
    results: list[tuple[Document, float]]
    trace: RetrievalTrace
