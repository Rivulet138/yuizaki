from __future__ import annotations

import json
import sqlite3

import pytest

from modules.memory.sqlite_store import AuthorityRevisionMismatchError, SQLiteMemoryStore
from modules.memory.vector_store import Document


def test_authority_revision_tracks_committed_document_mutations(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    assert store.get_authority_revision() == 0

    store.add_metadata_document(Document(id="a", text="first", metadata={}))
    assert store.get_authority_revision() == 1

    store.update_metadata("a", {"scope": "global"})
    assert store.get_authority_revision() == 2

    store.delete_document("missing")
    assert store.get_authority_revision() == 2
    store.delete_document("a")
    assert store.get_authority_revision() == 3


def test_legacy_metadata_migration_advances_revision_once(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memory_documents (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.executemany(
            "INSERT INTO memory_documents (id, text, metadata_json) VALUES (?, ?, ?)",
            [("a", "first", "{}"), ("b", "second", "{}")],
        )

    store = SQLiteMemoryStore(db_path)
    assert store.get_authority_revision() == 1
    assert all(doc.metadata["schema_version"] == 1 for doc in store.list_documents())

    reopened = SQLiteMemoryStore(db_path)
    assert reopened.get_authority_revision() == 1


def test_documents_page_is_stable_and_rejects_changed_snapshot(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    for doc_id in ("c", "a", "b"):
        store.add_metadata_document(Document(id=doc_id, text=doc_id, metadata={}))

    revision = store.get_authority_revision()
    first_page = store.list_documents_page(revision, None, 2)
    second_page = store.list_documents_page(revision, first_page[-1].id, 2)
    assert [doc.id for doc in first_page] == ["a", "b"]
    assert [doc.id for doc in second_page] == ["c"]

    store.add_metadata_document(Document(id="d", text="d", metadata={}))
    with pytest.raises(AuthorityRevisionMismatchError, match="expected 3, found 4"):
        store.list_documents_page(revision, "b", 2)


def test_documents_page_uses_one_sqlite_read_snapshot(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path)
    concurrent_store = SQLiteMemoryStore(db_path)
    store.add_metadata_document(Document(id="a", text="first", metadata={}))
    revision = store.get_authority_revision()
    original_revision = store._authority_revision

    def read_revision_then_write(connection):
        actual = original_revision(connection)
        concurrent_store.add_metadata_document(Document(id="b", text="second", metadata={}))
        return actual

    monkeypatch.setattr(store, "_authority_revision", read_revision_then_write)
    page = store.list_documents_page(revision, None, 10)

    assert [doc.id for doc in page] == ["a"]
    assert concurrent_store.get_authority_revision() == revision + 1


def test_rebuild_job_legacy_table_migrates_and_round_trips_checkpoint(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE memory_index_rebuild_jobs (
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
                result_json TEXT
            )
            """
        )

    store = SQLiteMemoryStore(db_path)
    checkpoint = {
        "job_id": "job-1",
        "state": "running",
        "phase": "indexing",
        "total_count": 8,
        "processed_count": 3,
        "started_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:01Z",
        "finished_at": None,
        "last_error": None,
        "recoverable": True,
        "retry_of": None,
        "result": {"status": "partial"},
        "index_generation": "generation-1",
        "snapshot_revision": 7,
        "cursor_key": "memory-003",
        "embedding_config_revision": "embedding-v2",
    }
    store.persist_rebuild_job(checkpoint)

    assert store.load_latest_rebuild_job() == checkpoint
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(memory_index_rebuild_jobs)")}
        stored_result = connection.execute(
            "SELECT result_json FROM memory_index_rebuild_jobs WHERE job_id = 'job-1'"
        ).fetchone()[0]
    assert {
        "index_generation",
        "snapshot_revision",
        "cursor_key",
        "embedding_config_revision",
    } <= columns
    assert json.loads(stored_result) == {"status": "partial"}


def test_index_generation_activation_requires_current_snapshot(tmp_path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    store.add_metadata_document(Document(id="a", text="first", metadata={}))
    snapshot_revision = store.get_authority_revision()

    assert store.get_active_index_generation() is None
    store.activate_index_generation("generation-1", snapshot_revision, "embedding-v1")
    assert store.get_active_index_generation() == {
        "generation": "generation-1",
        "snapshot_revision": snapshot_revision,
        "embedding_config_revision": "embedding-v1",
    }

    store.add_metadata_document(Document(id="b", text="second", metadata={}))
    with pytest.raises(AuthorityRevisionMismatchError):
        store.activate_index_generation("generation-2", snapshot_revision, "embedding-v1")
    assert store.get_active_index_generation()["generation"] == "generation-1"
