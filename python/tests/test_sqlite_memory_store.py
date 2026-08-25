from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document


class _FakeEmbeddingService:
    dimension = 3

    def embed(self, text: str) -> np.ndarray:
        lowered = text.lower()
        return np.array([
            float(lowered.count("tea")),
            float(lowered.count("coffee")),
            1.0,
        ], dtype=np.float32)


def test_sqlite_memory_is_authoritative_and_vectors_rebuild_after_restart(tmp_path):
    db_path = tmp_path / "memory.db"
    first = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    first.add_document(Document(
        id="preference-1",
        text="User prefers tea",
        metadata={"layer": "profile", "source": "manual"},
    ))

    reopened = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())

    assert [(doc.id, doc.text) for doc in reopened.list_documents()] == [
        ("preference-1", "User prefers tea"),
    ]
    assert reopened.get_status().metadata["authority"] == "sqlite"
    assert reopened.get_status().metadata["index_ready"] is False

    results = reopened.search("tea")
    assert [doc.id for doc, _score in results] == ["preference-1"]
    assert reopened.get_status().metadata["index_ready"] is True


def test_sqlite_memory_round_trips_canonical_metadata(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    store.add_metadata_document(Document(
        id="current-event",
        text="Current event",
        metadata={"layer": "episodic", "scope": "workspace", "workspace_id": "default"},
    ))
    store.add_metadata_document(Document(
        id="older-event",
        text="Old event",
        metadata={"layer": "episodic", "scope": "workspace", "workspace_id": "default"},
    ))

    reopened = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    assert [doc.id for doc in reopened.list_documents()] == ["current-event", "older-event"]
    assert all("state" not in doc.metadata for doc in reopened.list_documents())
    with sqlite3.connect(db_path) as connection:
        stored_ids = [row[0] for row in connection.execute("SELECT id FROM memory_documents ORDER BY id")]
    assert stored_ids == ["current-event", "older-event"]


def test_sqlite_failure_does_not_mutate_in_memory_authority(tmp_path, monkeypatch):
    store = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_FakeEmbeddingService())

    def fail_persist(_doc):
        raise OSError("disk unavailable")

    monkeypatch.setattr(store, "_persist", fail_persist)

    try:
        store.add_document(Document(id="unsafe", text="User prefers tea", metadata={}))
    except OSError:
        pass
    else:
        raise AssertionError("persistence failure should propagate")

    assert store.list_documents() == []


def test_sqlite_memory_compaction_releases_free_pages(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    large_text = "memory payload " * 2000
    for index in range(80):
        store.add_metadata_document(Document(
            id=f"memory-{index}",
            text=large_text,
            metadata={"index": index},
        ))
    for index in range(80):
        store.delete_document(f"memory-{index}")

    with sqlite3.connect(db_path) as connection:
        free_pages_before = connection.execute("PRAGMA freelist_count").fetchone()[0]
    result = store.compact_storage()
    with sqlite3.connect(db_path) as connection:
        free_pages_after = connection.execute("PRAGMA freelist_count").fetchone()[0]

    assert free_pages_before > 0
    assert free_pages_after == 0
    assert result["backend"] == "sqlite"
    assert result["after_bytes"] <= result["before_bytes"]


def test_sqlite_concurrent_updates_preserve_every_revision(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    store.add_metadata_document(Document(id="shared", text="revision 1", metadata={}))

    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(
            lambda revision: store.add_metadata_document(Document(
                id="shared",
                text=f"revision {revision}",
                metadata={},
            )),
            range(2, 12),
        ))

    current = next(doc for doc in store.list_documents() if doc.id == "shared")
    reopened = SQLiteMemoryStore(db_path, embedding_service=_FakeEmbeddingService())
    persisted = next(doc for doc in reopened.list_documents() if doc.id == "shared")
    assert current.metadata["revision"] == 11
    assert len(current.metadata["version_history"]) == 10
    assert persisted.text == current.text
    assert persisted.metadata == current.metadata
