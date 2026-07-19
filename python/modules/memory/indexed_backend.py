from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Callable

from .backend import MemoryBackend, MemoryBackendStatus
from .schema import MemorySearchFilters
from .vector_store import Document


logger = logging.getLogger(__name__)


class IndexedMemoryBackend:
    """Keep durable memory in one authority and use a replaceable search index."""

    backend_name = "sqlite+qdrant"

    def __init__(self, authority: MemoryBackend, index: MemoryBackend):
        self.authority = authority
        self.index = index
        self._index_dirty = False
        self._remove_orphaned_index_entries()

    def _remove_orphaned_index_entries(self) -> None:
        authority_ids = {document.id for document in self.authority.list_documents()}
        indexed_documents = self._best_effort_index("list", self.index.list_documents) or []
        for document in indexed_documents:
            if document.id not in authority_ids:
                self._sync_index("delete_orphan", lambda doc_id=document.id: self.index.delete_document(doc_id))

    def _best_effort_index(self, operation: str, callback: Callable[[], Any]) -> Any | None:
        try:
            return callback()
        except Exception as exc:
            logger.warning("Memory index %s failed; SQLite authority remains valid: %s", operation, exc)
            return None

    def _sync_index(self, operation: str, callback: Callable[[], Any]) -> None:
        try:
            callback()
        except Exception as exc:
            self._index_dirty = True
            logger.warning("Memory index %s failed; SQLite authority remains valid: %s", operation, exc)

    def add_document(self, doc: Document) -> None:
        self.authority.add_document(doc)
        self._sync_index("add", lambda: self.index.add_document(doc))

    def add_metadata_document(self, doc: Document) -> None:
        self.authority.add_metadata_document(doc)
        self._sync_index("add_metadata", lambda: self.index.add_metadata_document(doc))

    def delete_document(self, doc_id: str) -> None:
        self.authority.delete_document(doc_id)
        self._sync_index("delete", lambda: self.index.delete_document(doc_id))

    def list_documents(self) -> list[Document]:
        return self.authority.list_documents()

    def rebuild_index(self) -> dict[str, Any]:
        try:
            authority_documents = self.authority.list_documents()
            indexed_documents = self.index.list_documents()
            for document in indexed_documents:
                self.index.delete_document(document.id)

            indexed_count = 0
            for document in authority_documents:
                self.index.add_document(document)
                indexed_count += 1
        except Exception:
            self._index_dirty = True
            raise
        self._index_dirty = False
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "authority": self.authority.backend_name,
            "index": self.index.backend_name,
            "document_count": len(authority_documents),
            "indexed_count": indexed_count,
            "skipped_count": 0,
        }

    def _authoritative_results(
        self,
        results: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        authority_by_id = {document.id: document for document in self.authority.list_documents()}
        return [
            (authority_by_id[document.id], score)
            for document, score in results
            if document.id in authority_by_id
        ]

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]:
        indexed = self._best_effort_index(
            "search",
            lambda: self.index.search(query=query, top_k=top_k, filters=filters),
        )
        if not indexed:
            return self.authority.search(query=query, top_k=top_k, filters=filters)
        authoritative = self._authoritative_results(indexed)
        if len(authoritative) < len(indexed):
            self._index_dirty = True
        if not authoritative:
            logger.warning("Memory index returned only stale document IDs; using SQLite authority")
            return self.authority.search(query=query, top_k=top_k, filters=filters)
        return authoritative

    def search_with_rerank(
        self,
        query: str,
        top_k: int = 5,
        memory_types: Sequence[Any] | None = None,
        recency_weight: float = 0.2,
        quality_weight: float = 0.15,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]:
        indexed = self._best_effort_index(
            "search_with_rerank",
            lambda: self.index.search_with_rerank(
                query=query,
                top_k=top_k,
                memory_types=memory_types,
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                filters=filters,
            ),
        )
        if not indexed:
            return self.authority.search_with_rerank(
                query=query,
                top_k=top_k,
                memory_types=memory_types,
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                filters=filters,
            )
        authoritative = self._authoritative_results(indexed)
        if len(authoritative) < len(indexed):
            self._index_dirty = True
        if not authoritative:
            logger.warning("Memory index rerank returned only stale document IDs; using SQLite authority")
            return self.authority.search_with_rerank(
                query=query,
                top_k=top_k,
                memory_types=memory_types,
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                filters=filters,
            )
        return authoritative

    def get_status(self) -> MemoryBackendStatus:
        authority_status = self.authority.get_status()
        index_status = self._best_effort_index("status", self.index.get_status)
        index_available = bool(index_status and index_status.healthy)
        authority_documents = self.authority.list_documents()
        expected_index_count = len(authority_documents)
        actual_index_count = index_status.document_count if index_status else None
        if index_available and actual_index_count != expected_index_count:
            self._index_dirty = True
        index_healthy = index_available and not self._index_dirty
        return MemoryBackendStatus(
            backend=self.backend_name,
            healthy=authority_status.healthy,
            message=(
                "SQLite authority ready; Qdrant index ready"
                if index_healthy
                else "SQLite authority ready; Qdrant index unavailable or out of sync and can be rebuilt"
            ),
            document_count=authority_status.document_count,
            metadata={
                "authority": authority_status.backend,
                "index": index_status.backend if index_status else self.index.backend_name,
                "index_healthy": index_healthy,
                "index_dirty": self._index_dirty,
                "expected_index_count": expected_index_count,
                "actual_index_count": actual_index_count,
                "index_metadata": index_status.metadata if index_status else None,
            },
        )
