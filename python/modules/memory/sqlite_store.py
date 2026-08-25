from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .backend import MemoryBackendStatus
from .metadata import append_memory_version, has_prior_version_snapshot, normalize_memory_metadata
from .schema import MemorySearchFilters
from .vector_store import Document, EmbeddingProvider, VectorStore


_APPEND_ONLY_HISTORY_LIMITS = {
    "audit": 100,
    "confidence_history": 50,
    "correction_history": 25,
}


def _merge_append_only_metadata(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(incoming)
    for key, limit in _APPEND_ONLY_HISTORY_LIMITS.items():
        raw_current_items = current.get(key)
        raw_incoming_items = incoming.get(key)
        current_items = raw_current_items if isinstance(raw_current_items, list) else []
        incoming_items = raw_incoming_items if isinstance(raw_incoming_items, list) else []
        items = list(current_items)
        for item in incoming_items:
            if item not in items:
                items.append(item)
        overflow = max(0, len(items) - limit)
        merged[key] = items[-limit:]
        if key == "audit":
            truncated = max(
                int(current.get("audit_truncated", 0) or 0),
                int(incoming.get("audit_truncated", 0) or 0),
            ) + overflow
            if truncated:
                merged["audit_truncated"] = truncated
            else:
                merged.pop("audit_truncated", None)
    return merged


class SQLiteMemoryStore(VectorStore):
    """SQLite is authoritative; embeddings are a rebuildable in-process index."""

    backend_name = "sqlite"

    def __init__(
        self,
        db_path: str | Path,
        embedding_service: EmbeddingProvider | None = None,
        reranker: Any | None = None,
        reranker_candidate_count: int = 32,
    ):
        super().__init__(
            embedding_service=embedding_service,
            reranker=reranker,
            reranker_candidate_count=reranker_candidate_count,
        )
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        self._index_ready = False
        self._initialize_database()
        self._migrate_legacy_metadata()
        self._load_documents()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._db_lock, self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_documents (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _load_documents(self) -> None:
        with self._db_lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT id, text, metadata_json FROM memory_documents ORDER BY updated_at, id"
            ).fetchall()
        for doc_id, text, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            super().add_metadata_document(Document(id=str(doc_id), text=str(text), metadata=metadata))

    def _migrate_legacy_metadata(self) -> None:
        with self._db_lock, self._connection() as connection:
            rows = connection.execute("SELECT id, metadata_json FROM memory_documents").fetchall()
            for doc_id, metadata_json in rows:
                try:
                    legacy = json.loads(metadata_json)
                except (TypeError, json.JSONDecodeError):
                    legacy = {}
                normalized = normalize_memory_metadata(legacy)
                if normalized != legacy:
                    connection.execute(
                        "UPDATE memory_documents SET metadata_json = ? WHERE id = ?",
                        (json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str), doc_id),
                    )

    def _persist(self, doc: Document) -> None:
        with self._db_lock, self._connection() as connection:
            row = connection.execute(
                "SELECT text, metadata_json FROM memory_documents WHERE id = ?",
                (doc.id,),
            ).fetchone()
            existing = None
            if row is not None:
                try:
                    existing_metadata = json.loads(row[1])
                except (TypeError, json.JSONDecodeError):
                    existing_metadata = {}
                existing = Document(id=doc.id, text=str(row[0]), metadata=existing_metadata)

            metadata = normalize_memory_metadata(doc.metadata)
            if existing is not None:
                metadata = _merge_append_only_metadata(existing.metadata, metadata)
                incoming_audit = metadata.get("audit")
                latest_action = (
                    incoming_audit[-1].get("action")
                    if isinstance(incoming_audit, list)
                    and incoming_audit
                    and isinstance(incoming_audit[-1], dict)
                    else None
                )
                if latest_action != "restore":
                    for lifecycle_key in (
                        "soft_forgotten",
                        "soft_forgotten_at",
                        "soft_forget_turn_id",
                        "superseded_by",
                    ):
                        if lifecycle_key in existing.metadata and lifecycle_key not in metadata:
                            metadata[lifecycle_key] = existing.metadata[lifecycle_key]
                old_revision = int(normalize_memory_metadata(existing.metadata).get("revision", 1))
                if not has_prior_version_snapshot(metadata, revision=old_revision, text=existing.text):
                    metadata = append_memory_version(
                        doc_id=doc.id,
                        old_text=existing.text,
                        old_metadata=existing.metadata,
                        new_metadata=metadata,
                    )
            metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
            connection.execute(
                """
                INSERT INTO memory_documents (id, text, metadata_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    text = excluded.text,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (doc.id, doc.text, metadata_json),
            )
        doc.metadata = metadata

    def add_document(self, doc: Document) -> None:
        with self._db_lock:
            self._persist(doc)
            super().add_document(doc)

    def add_metadata_document(self, doc: Document) -> None:
        with self._db_lock:
            self._persist(doc)
            super().add_metadata_document(doc)

    def delete_document(self, doc_id: str) -> None:
        with self._db_lock:
            with self._connection() as connection:
                connection.execute("DELETE FROM memory_documents WHERE id = ?", (doc_id,))
            super().delete_document(doc_id)

    def compact_storage(self) -> dict[str, int | str]:
        """Return deleted SQLite pages to disk after an explicit purge."""
        before_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        with self._db_lock:
            connection = self._connect()
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                connection.execute("VACUUM")
            finally:
                connection.close()
        after_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "backend": self.backend_name,
            "before_bytes": before_bytes,
            "after_bytes": after_bytes,
            "reclaimed_bytes": max(0, before_bytes - after_bytes),
        }

    def _ensure_index(self) -> None:
        if self._index_ready:
            return
        super().rebuild_index()
        self._index_ready = True

    def rebuild_index(self) -> dict[str, Any]:
        result = super().rebuild_index()
        self._index_ready = True
        return result

    def search(self, query: str, top_k: int = 5, filters: MemorySearchFilters | None = None):
        self._ensure_index()
        return super().search(query=query, top_k=top_k, filters=filters)

    def search_with_rerank(
        self,
        query: str,
        top_k: int = 5,
        memory_types: Sequence[Any] | None = None,
        recency_weight: float = 0.2,
        quality_weight: float = 0.15,
        filters: MemorySearchFilters | None = None,
    ):
        self._ensure_index()
        return super().search_with_rerank(
            query=query,
            top_k=top_k,
            memory_types=memory_types,
            recency_weight=recency_weight,
            quality_weight=quality_weight,
            filters=filters,
        )

    def get_status(self) -> MemoryBackendStatus:
        status = super().get_status()
        metadata = dict(status.metadata or {})
        metadata.update({
            "database_path": str(self.db_path),
            "index_ready": self._index_ready,
            "authority": "sqlite",
        })
        return MemoryBackendStatus(
            backend=self.backend_name,
            healthy=True,
            message="SQLite memory authority ready",
            document_count=len(self._docs),
            metadata=metadata,
        )
