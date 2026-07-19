from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .backend import MemoryBackendStatus
from .schema import MemorySearchFilters
from .vector_store import Document, EmbeddingProvider, VectorStore


class SQLiteMemoryStore(VectorStore):
    """SQLite is authoritative; embeddings are a rebuildable in-process index."""

    backend_name = "sqlite"

    def __init__(self, db_path: str | Path, embedding_service: EmbeddingProvider | None = None):
        super().__init__(embedding_service=embedding_service)
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        self._index_ready = False
        self._initialize_database()
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

    def _persist(self, doc: Document) -> None:
        metadata_json = json.dumps(doc.metadata or {}, ensure_ascii=False, sort_keys=True, default=str)
        with self._db_lock, self._connection() as connection:
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

    def add_document(self, doc: Document) -> None:
        self._persist(doc)
        super().add_document(doc)

    def add_metadata_document(self, doc: Document) -> None:
        self._persist(doc)
        super().add_metadata_document(doc)

    def delete_document(self, doc_id: str) -> None:
        with self._db_lock, self._connection() as connection:
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
