from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest
from modules.memory.indexed_backend import (
    IndexedMemoryBackend,
    MemoryIndexRebuildCancelled,
)
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_client import QdrantVectorStore
from modules.memory.vector_store import Document, VectorStore


class _EmbeddingService:
    dimension = 2

    def embed(self, text: str) -> np.ndarray:
        return np.array([float(len(text)), 1.0], dtype=np.float32)


class _FailingIndex(VectorStore):
    def __init__(self, *, fail_id: str):
        super().__init__(embedding_service=_EmbeddingService())
        self.fail_id = fail_id

    def add_document(self, doc: Document) -> None:
        if doc.id == self.fail_id:
            raise RuntimeError("embedding unavailable")
        super().add_document(doc)


class _BlockingIndex(VectorStore):
    def __init__(self):
        super().__init__(embedding_service=_EmbeddingService())
        self.started = threading.Event()
        self.release = threading.Event()
        self.block_rebuild = False

    def add_document(self, doc: Document) -> None:
        if self.block_rebuild and doc.id == "current":
            self.started.set()
            assert self.release.wait(timeout=5)
        super().add_document(doc)


class _DurableRecordingIndex(VectorStore):
    supports_durable_rebuild_checkpoint = True

    def __init__(self, *, fail_id: str | None = None):
        super().__init__(embedding_service=_EmbeddingService())
        self.fail_id = fail_id
        self.added_ids: list[str] = []
        self.generation_by_id: dict[str, str] = {}
        self.manifest_calls = 0

    def add_document(self, doc: Document) -> None:
        if doc.id == self.fail_id:
            raise RuntimeError("index write was not acknowledged")
        self.added_ids.append(doc.id)
        super().add_document(doc)

    def add_document_for_generation(self, doc: Document, index_generation: str) -> None:
        self.add_document(doc)
        self.generation_by_id[doc.id] = index_generation

    def get_rebuild_generation_ids(self, index_generation: str) -> set[str]:
        return {
            doc_id
            for doc_id, generation in self.generation_by_id.items()
            if generation == index_generation
        }

    def get_index_manifest(self, index_generation: str) -> tuple[set[str], set[str]]:
        self.manifest_calls += 1
        return self.get_rebuild_generation_ids(index_generation), set(self.generation_by_id)

    def delete_document(self, doc_id: str) -> None:
        self.generation_by_id.pop(doc_id, None)
        super().delete_document(doc_id)


def _store(*documents: Document) -> VectorStore:
    store = VectorStore(embedding_service=_EmbeddingService())
    for document in documents:
        store.add_document(document)
    return store


def test_indexed_rebuild_failure_keeps_existing_index_queryable_and_marks_dirty() -> None:
    authority = _store(
        Document(id="kept", text="new authoritative text", metadata={}),
        Document(id="fails", text="cannot embed", metadata={}),
    )
    index = _FailingIndex(fail_id="fails")
    VectorStore.add_document(index, Document(id="kept", text="old searchable text", metadata={}))
    VectorStore.add_document(index, Document(id="stale", text="still searchable", metadata={}))
    backend = IndexedMemoryBackend(authority=authority, index=index)
    VectorStore.add_document(index, Document(id="stale", text="still searchable", metadata={}))

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        backend.rebuild_index()

    assert {document.id for document in index.list_documents()} == {"kept", "stale"}
    assert backend.get_status().metadata["index_dirty"] is True
    assert {document.id for document in backend.list_documents()} == {"kept", "fails"}


def test_indexed_rebuild_cancels_at_document_boundary_and_reports_progress() -> None:
    authority = _store(
        Document(id="first", text="one", metadata={}),
        Document(id="second", text="two", metadata={}),
    )
    index = _store(Document(id="live", text="existing", metadata={}))
    backend = IndexedMemoryBackend(authority=authority, index=index)
    VectorStore.add_document(index, Document(id="live", text="existing", metadata={}))
    progress: list[tuple[int, int, str]] = []

    with pytest.raises(MemoryIndexRebuildCancelled) as caught:
        backend.rebuild_index(
            progress_callback=lambda processed, total, phase: progress.append((processed, total, phase)),
            should_cancel=lambda: bool(progress),
        )

    assert caught.value.code == "memory_index_rebuild_cancelled"
    assert caught.value.processed == 1
    assert progress == [(1, 2, "indexing")]
    assert "live" in {document.id for document in index.list_documents()}
    assert backend.get_status().metadata["index_dirty"] is True


def test_indexed_rebuild_success_deletes_stale_ids_and_clears_dirty() -> None:
    authority = _store(Document(id="current", text="authoritative", metadata={}))
    index = _store(Document(id="stale", text="obsolete", metadata={}))
    backend = IndexedMemoryBackend(authority=authority, index=index)
    VectorStore.add_document(index, Document(id="stale", text="obsolete", metadata={}))
    backend._index_dirty = True
    progress: list[tuple[int, int, str]] = []

    result = backend.rebuild_index(progress_callback=lambda *args: progress.append(args))

    assert result["status"] == "rebuilt"
    assert {document.id for document in index.list_documents()} == {"current"}
    assert backend.get_status().metadata["index_dirty"] is False
    assert progress[-1] == (1, 1, "complete")


def test_indexed_rebuild_does_not_delete_document_added_during_rebuild() -> None:
    authority = _store(Document(id="current", text="authoritative", metadata={}))
    index = _BlockingIndex()
    VectorStore.add_document(index, Document(id="stale", text="old", metadata={}))
    backend = IndexedMemoryBackend(authority=authority, index=index)
    VectorStore.add_document(index, Document(id="stale", text="old", metadata={}))
    index.block_rebuild = True
    with ThreadPoolExecutor(max_workers=1) as executor:
        rebuild = executor.submit(backend.rebuild_index)
        assert index.started.wait(timeout=5)
        assert [document.id for document, _score in backend.search("authoritative")] == ["current"]
        backend.add_document(Document(id="stale", text="new authoritative", metadata={}))
        index.release.set()
        rebuild.result(timeout=5)

    assert {document.id for document in index.list_documents()} == {"current", "stale"}
    assert next(document for document in index.list_documents() if document.id == "stale").text == "new authoritative"


def test_vector_store_cancelled_rebuild_keeps_previous_vectors() -> None:
    store = _store(
        Document(id="first", text="one", metadata={}),
        Document(id="second", text="two", metadata={}),
    )
    old_vectors = {doc_id: vector.copy() for doc_id, vector in store._vectors.items()}
    progress: list[tuple[int, int, str]] = []

    with pytest.raises(MemoryIndexRebuildCancelled):
        store.rebuild_index(
            progress_callback=lambda *args: progress.append(args),
            should_cancel=lambda: bool(progress),
        )

    assert store._vectors.keys() == old_vectors.keys()
    assert all(np.array_equal(store._vectors[key], value) for key, value in old_vectors.items())


def test_qdrant_rebuild_upserts_without_deleting_live_collection() -> None:
    store = object.__new__(QdrantVectorStore)
    store.collection_name = "memories"
    store._docs = {}
    store.list_documents = lambda: [Document(id="current", text="text", metadata={})]
    added: list[str] = []
    store.add_document = lambda document: added.append(document.id)
    store.client = SimpleNamespace(
        delete_collection=lambda **_kwargs: pytest.fail("live collection must not be deleted"),
    )

    result = store.rebuild_index()

    assert added == ["current"]
    assert result["collection_deleted"] is False


def test_checkpoint_advances_only_after_index_write_acknowledgement(tmp_path) -> None:
    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_EmbeddingService())
    for doc_id in ("a", "b", "c"):
        authority.add_metadata_document(Document(id=doc_id, text=doc_id, metadata={}))
    index = _DurableRecordingIndex(fail_id="b")
    backend = IndexedMemoryBackend(authority=authority, index=index)
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None
    checkpoints: list[tuple[str, int]] = []

    with pytest.raises(RuntimeError, match="not acknowledged"):
        backend.rebuild_index(
            snapshot_revision=context["snapshot_revision"],
            index_generation="generation-1",
            embedding_config_revision=context["embedding_config_revision"],
            checkpoint_callback=lambda cursor, processed, _total, _phase: checkpoints.append(
                (cursor, processed)
            ),
        )

    assert checkpoints == [("a", 1)]
    assert backend.get_status().metadata["index_dirty"] is True
    assert authority.get_active_index_generation() is None


def test_durable_checkpoint_resume_starts_after_cursor_and_activates_generation(tmp_path) -> None:
    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_EmbeddingService())
    for doc_id in ("a", "b", "c"):
        authority.add_metadata_document(Document(id=doc_id, text=doc_id, metadata={}))
    index = _DurableRecordingIndex()
    index.add_document_for_generation(Document(id="a", text="a", metadata={}), "generation-resumed")
    index.add_document_for_generation(Document(id="b", text="b", metadata={}), "generation-resumed")
    index.added_ids.clear()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None

    result = backend.rebuild_index(
        snapshot_revision=context["snapshot_revision"],
        index_generation="generation-resumed",
        cursor_key="b",
        embedding_config_revision=context["embedding_config_revision"],
        processed_count=2,
    )

    assert index.added_ids == ["c"]
    assert result["indexed_count"] == 3
    assert authority.get_active_index_generation() == {
        "generation": "generation-resumed",
        "snapshot_revision": context["snapshot_revision"],
        "embedding_config_revision": context["embedding_config_revision"],
    }
    assert backend.get_status().metadata["index_dirty"] is False


def test_restart_reuses_single_manifest_scan_for_validation_and_orphan_cleanup(tmp_path) -> None:
    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_EmbeddingService())
    authority.add_metadata_document(Document(id="a", text="a", metadata={}))
    index = _DurableRecordingIndex()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None
    backend.rebuild_index(
        snapshot_revision=context["snapshot_revision"],
        index_generation="generation-active",
        embedding_config_revision=context["embedding_config_revision"],
    )
    index.add_document_for_generation(
        Document(id="orphan", text="orphan", metadata={}),
        "generation-interrupted",
    )
    index.manifest_calls = 0

    restarted = IndexedMemoryBackend(authority=authority, index=index)

    assert restarted._index_dirty is False
    assert index.manifest_calls == 1
    assert {document.id for document in index.list_documents()} == {"a"}


def test_resume_resets_to_full_rebuild_when_generation_prefix_is_missing(tmp_path) -> None:
    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_EmbeddingService())
    for doc_id in ("a", "b", "c"):
        authority.add_metadata_document(Document(id=doc_id, text=doc_id, metadata={}))
    index = _DurableRecordingIndex()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None
    checkpoints: list[tuple[str, int, str]] = []

    backend.rebuild_index(
        snapshot_revision=context["snapshot_revision"],
        index_generation="generation-lost-prefix",
        cursor_key="b",
        embedding_config_revision=context["embedding_config_revision"],
        processed_count=2,
        checkpoint_callback=lambda cursor, processed, _total, phase: checkpoints.append(
            (cursor, processed, phase)
        ),
    )

    assert checkpoints[0] == ("", 0, "resetting")
    assert index.added_ids == ["a", "b", "c"]
    assert index.get_rebuild_generation_ids("generation-lost-prefix") == {"a", "b", "c"}


def test_checkpoint_manifest_ignores_stale_process_cache(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    authority = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    authority.add_metadata_document(Document(id="a", text="first", metadata={}))
    concurrent = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    index = _DurableRecordingIndex()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    concurrent.add_metadata_document(Document(id="b", text="second", metadata={}))
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None
    assert [doc.id for doc in authority.list_documents()] == ["a"]

    backend.rebuild_index(
        snapshot_revision=context["snapshot_revision"],
        index_generation="generation-cross-process",
        embedding_config_revision=context["embedding_config_revision"],
    )

    assert {doc.id for doc in index.list_documents()} == {"a", "b"}
    assert authority.get_active_index_generation()["snapshot_revision"] == context["snapshot_revision"]
    # The persisted generation is complete. This still-running authority
    # instance intentionally retains its stale cache and therefore falls back.
    assert backend.get_status().metadata["index_dirty"] is True


def test_restart_keeps_index_dirty_after_normal_sync_failure(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    authority = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    index = _DurableRecordingIndex()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    backend.add_document(Document(id="a", text="old text", metadata={}))
    applied = authority.get_active_index_generation()
    assert applied is not None

    index.fail_id = "a"
    backend.add_document(Document(id="a", text="new authoritative text", metadata={}))
    assert backend.get_status().metadata["index_dirty"] is True
    assert authority.get_active_index_generation() == applied

    reopened_authority = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    index.fail_id = None
    restarted = IndexedMemoryBackend(authority=reopened_authority, index=index)

    assert restarted.get_status().metadata["index_dirty"] is True
    assert restarted.search("new authoritative text")[0][0].text == "new authoritative text"


def test_restart_detects_missing_active_generation_collection(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    authority = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    index = _DurableRecordingIndex()
    backend = IndexedMemoryBackend(authority=authority, index=index)
    backend.add_document(Document(id="a", text="authoritative", metadata={}))
    assert backend.get_status().metadata["index_dirty"] is False

    lost_index = _DurableRecordingIndex()
    reopened_authority = SQLiteMemoryStore(db_path, embedding_service=_EmbeddingService())
    restarted = IndexedMemoryBackend(authority=reopened_authority, index=lost_index)

    assert restarted.get_status().metadata["index_dirty"] is True
    assert restarted.search("authoritative")[0][0].id == "a"
