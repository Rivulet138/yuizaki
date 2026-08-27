from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any, cast

from .backend import MemoryBackend, MemoryBackendStatus
from .schema import MemorySearchFilters
from .vector_store import (
    Document,
    _raise_if_rebuild_cancelled,
    is_memory_recallable,
)
from .vector_store import (
    MemoryIndexRebuildCancelled as _MemoryIndexRebuildCancelled,
)

logger = logging.getLogger(__name__)
MemoryIndexRebuildCancelled = _MemoryIndexRebuildCancelled


class IndexedMemoryBackend:
    """Keep durable memory in one authority and use a replaceable search index."""

    backend_name = "sqlite+qdrant"

    def __init__(self, authority: MemoryBackend, index: MemoryBackend):
        self.authority = authority
        self.index = index
        self._index_dirty = False
        self._startup_index_ids: set[str] | None = None
        self._mutation_lock = threading.RLock()
        self._initialize_index_state()
        if not self._index_dirty:
            self._remove_orphaned_index_entries()

    def _initialize_index_state(self) -> None:
        get_revision = getattr(self.authority, "get_authority_revision", None)
        get_active = getattr(self.authority, "get_active_index_generation", None)
        if not callable(get_revision) or not callable(get_active):
            return
        revision_reader = cast(Callable[[], int], get_revision)
        active_reader = cast(Callable[[], dict[str, Any] | None], get_active)
        revision = int(revision_reader())
        active = active_reader()
        if revision == 0 and active is None:
            return
        if not isinstance(active, dict):
            self._index_dirty = True
            return
        self._index_dirty = not (
            int(str(active.get("snapshot_revision", -1))) == revision
            and str(active.get("embedding_config_revision") or "")
            == self._embedding_config_revision()
        )
        if self._index_dirty:
            return
        list_ids = getattr(self.authority, "list_document_ids", None)
        read_manifest = getattr(self.index, "get_index_manifest", None)
        read_generation_ids = getattr(self.index, "get_rebuild_generation_ids", None)
        generation = str(active.get("generation") or "")
        if callable(list_ids) and (callable(read_manifest) or callable(read_generation_ids)) and generation:
            try:
                manifest_reader = cast(Callable[[int], list[str]], list_ids)
                authority_ids = set(manifest_reader(revision))
                if callable(read_manifest):
                    index_manifest_reader = cast(
                        Callable[[str], tuple[set[str], set[str]]],
                        read_manifest,
                    )
                    indexed_ids, all_index_ids = index_manifest_reader(generation)
                    self._startup_index_ids = set(all_index_ids)
                else:
                    generation_reader = cast(Callable[[str], set[str]], read_generation_ids)
                    indexed_ids = set(generation_reader(generation))
                self._index_dirty = indexed_ids != authority_ids
            except Exception as exc:
                self._index_dirty = True
                logger.warning("Memory index generation validation failed; using SQLite authority: %s", exc)

    def _remove_orphaned_index_entries(self) -> None:
        authority_ids = {document.id for document in self.authority.list_documents()}
        startup_index_ids = self._startup_index_ids
        self._startup_index_ids = None
        if startup_index_ids is not None:
            indexed_ids = startup_index_ids
        else:
            list_document_ids = getattr(self.index, "list_document_ids", None)
            if callable(list_document_ids):
                indexed_ids = set(self._best_effort_index("list_ids", list_document_ids) or ())
            else:
                indexed_documents = self._best_effort_index("list", self.index.list_documents) or []
                indexed_ids = {document.id for document in indexed_documents}
        for doc_id in indexed_ids - authority_ids:
            self._sync_index("delete_orphan", lambda stale_id=doc_id: self.index.delete_document(stale_id))

    def _best_effort_index(self, operation: str, callback: Callable[[], Any]) -> Any | None:
        try:
            return callback()
        except Exception as exc:
            logger.warning("Memory index %s failed; SQLite authority remains valid: %s", operation, exc)
            return None

    def _prepare_authority_mutation(self) -> int | None:
        get_revision = getattr(self.authority, "get_authority_revision", None)
        get_active = getattr(self.authority, "get_active_index_generation", None)
        if not callable(get_revision) or not callable(get_active):
            return None
        revision_reader = cast(Callable[[], int], get_revision)
        active_reader = cast(Callable[[], dict[str, Any] | None], get_active)
        revision = int(revision_reader())
        active = active_reader()
        if revision == 0 and active is None:
            return revision
        if not isinstance(active, dict) or (
            int(str(active.get("snapshot_revision", -1))) != revision
            or str(active.get("embedding_config_revision") or "")
            != self._embedding_config_revision()
        ):
            self._index_dirty = True
        return revision

    def _sync_index(
        self,
        operation: str,
        callback: Callable[[], Any],
        *,
        previous_revision: int | None = None,
    ) -> None:
        try:
            callback()
            if previous_revision is None or self._index_dirty:
                return
            get_revision = getattr(self.authority, "get_authority_revision", None)
            get_active = getattr(self.authority, "get_active_index_generation", None)
            activate = getattr(self.authority, "activate_index_generation", None)
            if not all(callable(method) for method in (get_revision, get_active, activate)):
                return
            revision_reader = cast(Callable[[], int], get_revision)
            active_reader = cast(Callable[[], dict[str, Any] | None], get_active)
            activate_generation = cast(Callable[[str, int, str], None], activate)
            applied_revision = int(revision_reader())
            if applied_revision not in {previous_revision, previous_revision + 1}:
                self._index_dirty = True
                return
            active = active_reader()
            generation = (
                str(active.get("generation"))
                if isinstance(active, dict) and active.get("generation")
                else "live"
            )
            activate_generation(generation, applied_revision, self._embedding_config_revision())
        except Exception as exc:
            self._index_dirty = True
            logger.warning("Memory index %s failed; SQLite authority remains valid: %s", operation, exc)

    def _write_index_document(self, doc: Document) -> None:
        writer = getattr(self.index, "add_document_for_generation", None)
        get_active = getattr(self.authority, "get_active_index_generation", None)
        if callable(writer) and callable(get_active):
            active = get_active()
            generation = (
                str(active.get("generation"))
                if isinstance(active, dict) and active.get("generation")
                else "live"
            )
            writer(doc, generation)
            return
        self.index.add_document(doc)

    def add_document(self, doc: Document) -> None:
        with self._mutation_lock:
            previous_revision = self._prepare_authority_mutation()
            self.authority.add_document(doc)
            self._sync_index(
                "add",
                lambda: self._write_index_document(doc),
                previous_revision=previous_revision,
            )

    def add_metadata_document(self, doc: Document) -> None:
        with self._mutation_lock:
            previous_revision = self._prepare_authority_mutation()
            self.authority.add_metadata_document(doc)
            self._sync_index(
                "add_metadata",
                lambda: self._write_index_document(doc),
                previous_revision=previous_revision,
            )

    def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> None:
        with self._mutation_lock:
            previous_revision = self._prepare_authority_mutation()
            self.authority.update_metadata(doc_id, metadata)
            self._sync_index(
                "update_metadata",
                lambda: self.index.update_metadata(doc_id, metadata),
                previous_revision=previous_revision,
            )

    def delete_document(self, doc_id: str) -> None:
        with self._mutation_lock:
            previous_revision = self._prepare_authority_mutation()
            self.authority.delete_document(doc_id)
            self._sync_index(
                "delete",
                lambda: self.index.delete_document(doc_id),
                previous_revision=previous_revision,
            )

    def list_documents(self) -> list[Document]:
        return self.authority.list_documents()

    def persist_rebuild_job(self, snapshot: dict[str, Any]) -> None:
        persist = getattr(self.authority, "persist_rebuild_job", None)
        if callable(persist):
            persist(snapshot)

    def load_latest_rebuild_job(self) -> dict[str, Any] | None:
        load = getattr(self.authority, "load_latest_rebuild_job", None)
        if not callable(load):
            return None
        result = load()
        return result if isinstance(result, dict) else None

    def mark_index_dirty(self) -> None:
        self._index_dirty = True

    def _embedding_config_revision(self) -> str:
        embedding_service = getattr(self.index, "_embedding_service", None)
        model = getattr(embedding_service, "model", None)
        payload = {
            "backend": str(getattr(self.index, "backend_name", type(self.index).__name__)),
            "collection": str(getattr(self.index, "collection_name", "")),
            "embedding_class": (
                f"{type(embedding_service).__module__}.{type(embedding_service).__qualname__}"
                if embedding_service is not None
                else ""
            ),
            "embedding_model": str(
                getattr(embedding_service, "_model_name", "")
                or getattr(model, "name_or_path", "")
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def get_rebuild_checkpoint_context(self) -> dict[str, Any] | None:
        raw_get_revision = getattr(self.authority, "get_authority_revision", None)
        list_page = getattr(self.authority, "list_documents_page", None)
        list_ids = getattr(self.authority, "list_document_ids", None)
        activate = getattr(self.authority, "activate_index_generation", None)
        if not all(callable(method) for method in (raw_get_revision, list_page, list_ids, activate)):
            return None
        get_revision = cast(Callable[[], int], raw_get_revision)
        generation_writer = getattr(self.index, "add_document_for_generation", None)
        generation_ids = getattr(self.index, "get_rebuild_generation_ids", None)
        return {
            "snapshot_revision": int(get_revision()),
            "embedding_config_revision": self._embedding_config_revision(),
            "durable_resume": bool(
                getattr(self.index, "supports_durable_rebuild_checkpoint", False)
                and callable(generation_writer)
                and callable(generation_ids)
            ),
        }

    def _rebuild_index_from_checkpoint(
        self,
        *,
        snapshot_revision: int,
        index_generation: str,
        cursor_key: str | None,
        embedding_config_revision: str,
        processed_count: int,
        checkpoint_callback: Callable[[str, int, int, str], None] | None,
        progress_callback: Callable[[int, int, str], None] | None,
        should_cancel: Callable[[], bool] | Any | None,
    ) -> dict[str, Any]:
        raw_get_revision = getattr(self.authority, "get_authority_revision", None)
        raw_list_page = getattr(self.authority, "list_documents_page", None)
        raw_list_ids = getattr(self.authority, "list_document_ids", None)
        raw_activate = getattr(self.authority, "activate_index_generation", None)
        if not all(
            callable(method)
            for method in (raw_get_revision, raw_list_page, raw_list_ids, raw_activate)
        ):
            raise RuntimeError("memory authority does not support rebuild checkpoints")
        get_revision = cast(Callable[[], int], raw_get_revision)
        list_page = cast(
            Callable[[int, str | None, int], list[Document]],
            raw_list_page,
        )
        list_ids = cast(Callable[[int], list[str]], raw_list_ids)
        activate = cast(Callable[[str, int, str], None], raw_activate)
        if int(get_revision()) != snapshot_revision:
            list_page(snapshot_revision, cursor_key, 1)
        if self._embedding_config_revision() != embedding_config_revision:
            raise RuntimeError("memory embedding configuration changed during index rebuild")

        authority_ids = list_ids(snapshot_revision)
        authority_id_set = set(authority_ids)
        total = len(authority_ids)
        indexed_count = 0
        current_cursor = cursor_key
        generation_writer = getattr(self.index, "add_document_for_generation", None)
        generation_ids_reader = getattr(self.index, "get_rebuild_generation_ids", None)
        write_generation = (
            cast(Callable[[Document, str], None], generation_writer)
            if callable(generation_writer)
            else None
        )
        read_generation_ids = (
            cast(Callable[[str], set[str]], generation_ids_reader)
            if callable(generation_ids_reader)
            else None
        )
        generation_aware = write_generation is not None and read_generation_ids is not None
        if current_cursor is not None:
            expected_prefix = {doc_id for doc_id in authority_ids if doc_id <= current_cursor}
            indexed_prefix = (
                set(read_generation_ids(index_generation))
                if read_generation_ids is not None
                else set()
            )
            if not generation_aware or not expected_prefix.issubset(indexed_prefix):
                current_cursor = None
                indexed_count = 0
                if checkpoint_callback is not None:
                    checkpoint_callback("", 0, total, "resetting")
            else:
                indexed_count = len(expected_prefix)
        _raise_if_rebuild_cancelled(
            should_cancel,
            processed=indexed_count,
            total=total,
            phase="indexing",
        )
        while True:
            page = list_page(snapshot_revision, current_cursor, 64)
            if not page:
                break
            for document in page:
                if write_generation is not None and read_generation_ids is not None:
                    write_generation(document, index_generation)
                else:
                    self.index.add_document(document)
                indexed_count += 1
                current_cursor = document.id
                if checkpoint_callback is not None:
                    checkpoint_callback(current_cursor, indexed_count, total, "indexing")
                if progress_callback is not None:
                    progress_callback(indexed_count, total, "indexing")
                _raise_if_rebuild_cancelled(
                    should_cancel,
                    processed=indexed_count,
                    total=total,
                    phase="indexing",
                )

        with self._mutation_lock:
            if int(get_revision()) != snapshot_revision:
                list_page(snapshot_revision, current_cursor, 1)
            list_document_ids = getattr(self.index, "list_document_ids", None)
            if callable(list_document_ids):
                index_id_reader = cast(Callable[[], Sequence[str] | set[str]], list_document_ids)
                stale_ids = set(index_id_reader()) - authority_id_set
            else:
                stale_ids = {
                    document.id
                    for document in self.index.list_documents()
                    if document.id not in authority_id_set
                }
            for deleted_count, doc_id in enumerate(stale_ids, start=1):
                _raise_if_rebuild_cancelled(
                    should_cancel,
                    processed=deleted_count - 1,
                    total=len(stale_ids),
                    phase="deleting_stale",
                )
                self.index.delete_document(doc_id)
                if progress_callback is not None:
                    progress_callback(deleted_count, len(stale_ids), "deleting_stale")
            indexed_ids = (
                set(read_generation_ids(index_generation))
                if read_generation_ids is not None and write_generation is not None
                else {document.id for document in self.index.list_documents()}
            )
            if indexed_ids != authority_id_set:
                raise RuntimeError("memory index generation does not match authority manifest")
            activate(index_generation, snapshot_revision, embedding_config_revision)
            self._index_dirty = False

        if progress_callback is not None:
            progress_callback(indexed_count, total, "complete")
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "authority": self.authority.backend_name,
            "index": self.index.backend_name,
            "document_count": total,
            "indexed_count": indexed_count,
            "skipped_count": 0,
            "index_generation": index_generation,
            "snapshot_revision": snapshot_revision,
            "embedding_config_revision": embedding_config_revision,
        }

    def rebuild_index(
        self,
        progress_callback: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | Any | None = None,
        *,
        snapshot_revision: int | None = None,
        index_generation: str | None = None,
        cursor_key: str | None = None,
        embedding_config_revision: str | None = None,
        processed_count: int = 0,
        checkpoint_callback: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, Any]:
        self._index_dirty = True
        try:
            if (
                snapshot_revision is not None
                and index_generation
                and embedding_config_revision
                and self.get_rebuild_checkpoint_context() is not None
            ):
                return self._rebuild_index_from_checkpoint(
                    snapshot_revision=snapshot_revision,
                    index_generation=index_generation,
                    cursor_key=cursor_key,
                    embedding_config_revision=embedding_config_revision,
                    processed_count=processed_count,
                    checkpoint_callback=checkpoint_callback,
                    progress_callback=progress_callback,
                    should_cancel=should_cancel,
                )
            with self._mutation_lock:
                authority_documents = self.authority.list_documents()
            snapshot_by_id = {document.id: document for document in authority_documents}
            total = len(authority_documents)
            indexed_count = 0
            _raise_if_rebuild_cancelled(should_cancel, processed=0, total=total, phase="indexing")
            for document in authority_documents:
                # Re-read under the mutation lock so an edit that races the
                # embedding pass is noticed without holding the lock during
                # provider/index I/O. The final reconcile closes any later
                # write window before clearing the dirty flag.
                with self._mutation_lock:
                    current_document = next(
                        (item for item in self.authority.list_documents() if item.id == document.id),
                        None,
                    )
                if current_document is None:
                    continue
                self.index.add_document(current_document)
                with self._mutation_lock:
                    latest_document = next(
                        (item for item in self.authority.list_documents() if item.id == document.id),
                        None,
                    )
                if latest_document is not None and latest_document != current_document:
                    self.index.add_document(latest_document)
                indexed_count += 1
                if progress_callback is not None:
                    progress_callback(indexed_count, total, "indexing")
                _raise_if_rebuild_cancelled(
                    should_cancel,
                    processed=indexed_count,
                    total=total,
                    phase="indexing",
                )

            # Serialize only the short final reconcile with mutations. Queries
            # continue using the authority while the index is marked dirty.
            with self._mutation_lock:
                current_documents = self.authority.list_documents()
                changed_documents = [
                    document
                    for document in current_documents
                    if snapshot_by_id.get(document.id) != document
                ]
                for reconciled_count, document in enumerate(changed_documents, start=1):
                    _raise_if_rebuild_cancelled(
                        should_cancel,
                        processed=reconciled_count - 1,
                        total=len(changed_documents),
                        phase="reconciling",
                    )
                    self.index.add_document(document)
                    if progress_callback is not None:
                        progress_callback(reconciled_count, len(changed_documents), "reconciling")
                    _raise_if_rebuild_cancelled(
                        should_cancel,
                        processed=reconciled_count,
                        total=len(changed_documents),
                        phase="reconciling",
                    )

                current_ids = {document.id for document in current_documents}
                indexed_documents = self.index.list_documents()
                stale_documents = [document for document in indexed_documents if document.id not in current_ids]
                for deleted_count, document in enumerate(stale_documents, start=1):
                    _raise_if_rebuild_cancelled(
                        should_cancel,
                        processed=deleted_count - 1,
                        total=len(stale_documents),
                        phase="deleting_stale",
                    )
                    self.index.delete_document(document.id)
                    if progress_callback is not None:
                        progress_callback(deleted_count, len(stale_documents), "deleting_stale")
                self._index_dirty = False
        except Exception:
            self._index_dirty = True
            raise
        if progress_callback is not None:
            progress_callback(indexed_count, total, "complete")
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
        *,
        filters: MemorySearchFilters | None = None,
        memory_types: Sequence[Any] | None = None,
    ) -> list[tuple[Document, float]]:
        authority_by_id = {document.id: document for document in self.authority.list_documents()}
        return [
            (authority_by_id[document.id], score)
            for document, score in results
            if document.id in authority_by_id
            and is_memory_recallable(
                authority_by_id[document.id],
                filters=filters,
                memory_types=memory_types,
            )
        ]

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]:
        if self._index_dirty:
            return self.authority.search(query=query, top_k=top_k, filters=filters)
        indexed = self._best_effort_index(
            "search",
            lambda: self.index.search(query=query, top_k=top_k, filters=filters),
        )
        if not indexed:
            return self.authority.search(query=query, top_k=top_k, filters=filters)
        authoritative = self._authoritative_results(indexed, filters=filters)
        if len(authoritative) < len(indexed):
            self._index_dirty = True
            logger.warning("Memory index returned stale or hidden documents; using SQLite authority")
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
        if self._index_dirty:
            return self.authority.search_with_rerank(
                query=query,
                top_k=top_k,
                memory_types=memory_types,
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                filters=filters,
            )
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
        authoritative = self._authoritative_results(
            indexed,
            filters=filters,
            memory_types=memory_types,
        )
        if len(authoritative) < len(indexed):
            self._index_dirty = True
            logger.warning("Memory index rerank returned stale or hidden documents; using SQLite authority")
            return self.authority.search_with_rerank(
                query=query,
                top_k=top_k,
                memory_types=memory_types,
                recency_weight=recency_weight,
                quality_weight=quality_weight,
                filters=filters,
            )
        return authoritative

    def get_score_components(
        self,
        query: str,
        doc_id: str,
        recency_weight: float,
        quality_weight: float,
    ) -> dict[str, float] | None:
        for backend in (self.index, self.authority):
            getter = getattr(backend, "get_score_components", None)
            if not callable(getter):
                continue
            components = getter(query, doc_id, recency_weight, quality_weight)
            if isinstance(components, dict):
                return {
                    str(key): float(value)
                    for key, value in components.items()
                    if isinstance(value, (int, float))
                }
        return None

    def get_status(self) -> MemoryBackendStatus:
        authority_status = self.authority.get_status()
        index_status = self._best_effort_index("status", self.index.get_status)
        index_available = bool(index_status and index_status.healthy)
        authority_documents = self.authority.list_documents()
        expected_index_count = len(authority_documents)
        actual_index_count = index_status.document_count if index_status else None
        id_set_in_sync: bool | None = None
        if index_available:
            list_document_ids = getattr(self.index, "list_document_ids", None)
            if callable(list_document_ids):
                indexed_ids = self._best_effort_index("list_ids_for_status", list_document_ids)
            else:
                indexed_documents = self._best_effort_index("list_for_status", self.index.list_documents)
                indexed_ids = (
                    {document.id for document in indexed_documents}
                    if indexed_documents is not None
                    else None
                )
            if indexed_ids is not None:
                authority_ids = {document.id for document in authority_documents}
                id_set_in_sync = authority_ids == set(indexed_ids)
                if not id_set_in_sync:
                    self._index_dirty = True
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
                "id_set_in_sync": id_set_in_sync,
                "index_metadata": index_status.metadata if index_status else None,
            },
        )
