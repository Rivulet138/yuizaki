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


class AuthorityRevisionMismatchError(RuntimeError):
    """Raised when a rebuild checkpoint no longer matches SQLite authority."""

    def __init__(self, expected: int, actual: int):
        super().__init__(f"memory authority revision changed: expected {expected}, found {actual}")
        self.expected = expected
        self.actual = actual


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_authority_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    authority_revision INTEGER NOT NULL DEFAULT 0,
                    active_index_generation TEXT,
                    active_snapshot_revision INTEGER,
                    active_embedding_config_revision TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO memory_authority_state (singleton, authority_revision)
                VALUES (1, 0)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_index_rebuild_jobs (
                    job_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    total_count INTEGER NOT NULL,
                    processed_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT,
                    last_error TEXT,
                    recoverable INTEGER NOT NULL DEFAULT 0,
                    retry_of TEXT,
                    result_json TEXT,
                    index_generation TEXT,
                    snapshot_revision INTEGER,
                    cursor_key TEXT,
                    embedding_config_revision TEXT
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(memory_index_rebuild_jobs)")
            }
            for name, column_type in (
                ("index_generation", "TEXT"),
                ("snapshot_revision", "INTEGER"),
                ("cursor_key", "TEXT"),
                ("embedding_config_revision", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE memory_index_rebuild_jobs ADD COLUMN {name} {column_type}"
                    )

    @staticmethod
    def _authority_revision(connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT authority_revision FROM memory_authority_state WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise RuntimeError("memory authority state is missing")
        return int(row[0])

    @staticmethod
    def _increment_authority_revision(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE memory_authority_state
            SET authority_revision = authority_revision + 1
            WHERE singleton = 1
            """
        )

    def get_authority_revision(self) -> int:
        with self._db_lock, self._connection() as connection:
            return self._authority_revision(connection)

    def list_documents_page(
        self,
        snapshot_revision: int,
        cursor_key: str | None,
        limit: int,
    ) -> list[Document]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        with self._db_lock, self._connection() as connection:
            connection.execute("BEGIN")
            actual_revision = self._authority_revision(connection)
            if actual_revision != snapshot_revision:
                raise AuthorityRevisionMismatchError(snapshot_revision, actual_revision)
            if cursor_key is None:
                rows = connection.execute(
                    """
                    SELECT id, text, metadata_json
                    FROM memory_documents
                    ORDER BY id
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, text, metadata_json
                    FROM memory_documents
                    WHERE id > ?
                    ORDER BY id
                    LIMIT ?
                    """,
                    (cursor_key, limit),
                ).fetchall()
        documents: list[Document] = []
        for doc_id, text, metadata_json in rows:
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            documents.append(Document(id=str(doc_id), text=str(text), metadata=metadata))
        return documents

    def list_document_ids(self, snapshot_revision: int) -> list[str]:
        with self._db_lock, self._connection() as connection:
            connection.execute("BEGIN")
            actual_revision = self._authority_revision(connection)
            if actual_revision != snapshot_revision:
                raise AuthorityRevisionMismatchError(snapshot_revision, actual_revision)
            rows = connection.execute(
                "SELECT id FROM memory_documents ORDER BY id"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def activate_index_generation(
        self,
        generation: str,
        snapshot_revision: int,
        embedding_config_revision: str,
    ) -> None:
        if not generation:
            raise ValueError("generation must not be empty")
        with self._db_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actual_revision = self._authority_revision(connection)
            if actual_revision != snapshot_revision:
                raise AuthorityRevisionMismatchError(snapshot_revision, actual_revision)
            connection.execute(
                """
                UPDATE memory_authority_state
                SET active_index_generation = ?,
                    active_snapshot_revision = ?,
                    active_embedding_config_revision = ?
                WHERE singleton = 1
                """,
                (generation, snapshot_revision, embedding_config_revision),
            )

    def get_active_index_generation(self) -> dict[str, Any] | None:
        with self._db_lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT active_index_generation, active_snapshot_revision,
                       active_embedding_config_revision
                FROM memory_authority_state
                WHERE singleton = 1
                """
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return {
            "generation": str(row[0]),
            "snapshot_revision": int(row[1]),
            "embedding_config_revision": str(row[2]),
        }

    def persist_rebuild_job(self, snapshot: dict[str, Any]) -> None:
        """Persist local index-maintenance state for restart recovery."""
        result = snapshot.get("result")
        with self._db_lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO memory_index_rebuild_jobs (
                    job_id, state, phase, total_count, processed_count,
                    started_at, updated_at, finished_at, last_error,
                    recoverable, retry_of, result_json, index_generation,
                    snapshot_revision, cursor_key, embedding_config_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    state = excluded.state,
                    phase = excluded.phase,
                    total_count = excluded.total_count,
                    processed_count = excluded.processed_count,
                    started_at = excluded.started_at,
                    updated_at = excluded.updated_at,
                    finished_at = excluded.finished_at,
                    last_error = excluded.last_error,
                    recoverable = excluded.recoverable,
                    retry_of = excluded.retry_of,
                    result_json = excluded.result_json,
                    index_generation = excluded.index_generation,
                    snapshot_revision = excluded.snapshot_revision,
                    cursor_key = excluded.cursor_key,
                    embedding_config_revision = excluded.embedding_config_revision
                """,
                (
                    str(snapshot.get("job_id") or ""),
                    str(snapshot.get("state") or "unknown"),
                    str(snapshot.get("phase") or "unknown"),
                    int(snapshot.get("total_count") or 0),
                    int(snapshot.get("processed_count") or 0),
                    str(snapshot.get("started_at") or ""),
                    str(snapshot.get("updated_at") or ""),
                    snapshot.get("finished_at"),
                    snapshot.get("last_error"),
                    1 if bool(snapshot.get("recoverable")) else 0,
                    snapshot.get("retry_of"),
                    json.dumps(result, ensure_ascii=False, sort_keys=True, default=str) if result is not None else None,
                    snapshot.get("index_generation"),
                    snapshot.get("snapshot_revision"),
                    snapshot.get("cursor_key"),
                    snapshot.get("embedding_config_revision"),
                ),
            )

    def load_latest_rebuild_job(self) -> dict[str, Any] | None:
        with self._db_lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT job_id, state, phase, total_count, processed_count,
                       started_at, updated_at, finished_at, last_error,
                       recoverable, retry_of, result_json, index_generation,
                       snapshot_revision, cursor_key, embedding_config_revision
                FROM memory_index_rebuild_jobs
                ORDER BY updated_at DESC, job_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        result: Any = None
        if row[11]:
            try:
                result = json.loads(row[11])
            except (TypeError, json.JSONDecodeError):
                result = None
        return {
            "job_id": str(row[0]),
            "state": str(row[1]),
            "phase": str(row[2]),
            "total_count": int(row[3]),
            "processed_count": int(row[4]),
            "started_at": str(row[5]),
            "updated_at": str(row[6]),
            "finished_at": row[7],
            "last_error": row[8],
            "recoverable": bool(row[9]),
            "retry_of": row[10],
            "result": result,
            "index_generation": row[12],
            "snapshot_revision": int(row[13]) if row[13] is not None else None,
            "cursor_key": row[14],
            "embedding_config_revision": row[15],
        }

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
            migrated = False
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
                    migrated = True
            if migrated:
                self._increment_authority_revision(connection)

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
            self._increment_authority_revision(connection)
        doc.metadata = metadata

    def add_document(self, doc: Document) -> None:
        with self._db_lock:
            self._persist(doc)
            super().add_document(doc)

    def add_metadata_document(self, doc: Document) -> None:
        with self._db_lock:
            self._persist(doc)
            super().add_metadata_document(doc)

    def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> None:
        normalized = normalize_memory_metadata(metadata)
        with self._db_lock, self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM memory_documents WHERE id = ?", (doc_id,)
            ).fetchone()
            if row is None:
                raise KeyError(doc_id)
            connection.execute(
                "UPDATE memory_documents SET metadata_json = ? WHERE id = ?",
                (json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str), doc_id),
            )
            self._increment_authority_revision(connection)
        document = next((item for item in self._docs.values() if item.id == doc_id), None)
        if document is not None:
            document.metadata = normalized

    def delete_document(self, doc_id: str) -> None:
        with self._db_lock:
            with self._connection() as connection:
                cursor = connection.execute("DELETE FROM memory_documents WHERE id = ?", (doc_id,))
                if cursor.rowcount:
                    self._increment_authority_revision(connection)
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

    def rebuild_index(
        self,
        progress_callback: Any | None = None,
        should_cancel: Any | None = None,
    ) -> dict[str, Any]:
        result = super().rebuild_index(
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
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
