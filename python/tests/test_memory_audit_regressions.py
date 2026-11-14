"""Acceptance for the five memory defects, using isolated synthetic data."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.memory.operations import new_operation
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.routes import MemoryState, create_memory_router
from modules.memory.schema import MemorySearchFilters, RetrievalRequest
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document, VectorStore


class Embedding:
    dimension = 2

    def embed(self, text):
        return np.array([float(len(text)), 1.0], dtype=np.float32)


META = {"scope": "workspace", "workspace_id": "audit", "layer": "semantic"}


def client_for(store):
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store), get_active_workspace_id=lambda: "audit"))
    return TestClient(app)


@pytest.mark.parametrize("backend", ["sqlite", "inmemory"])
def test_metadata_write_after_initial_search_is_recalled(tmp_path, backend):
    store = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding()) if backend == "sqlite" else VectorStore(embedding_service=Embedding())
    filters = MemorySearchFilters(scope="workspace", workspace_id="audit", layers=["semantic"])
    store.search_with_rerank("synthetic", filters=filters)
    store.add_metadata_document(Document("new", "synthetic", dict(META)))
    assert [doc.id for doc, _ in store.search_with_rerank("synthetic", filters=filters)] == ["new"]
    old_vector = store._vectors["new"].copy()
    store.add_metadata_document(Document("new", "updated synthetic content", dict(META)))
    store.search_with_rerank("synthetic", filters=filters)
    assert not np.array_equal(old_vector, store._vectors["new"])


def test_embedding_failure_keeps_authority_visible_and_retryable(tmp_path):
    class BrokenEmbedding(Embedding):
        def embed(self, text):
            raise RuntimeError("synthetic embedding failure")

    path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(path, embedding_service=BrokenEmbedding())
    store.add_document(Document("saved", "synthetic", dict(META)))
    assert [doc.id for doc in store.list_documents()] == ["saved"]
    assert store.get_document_index_status("saved") == "failed"
    status = store.get_status().metadata
    assert status["pending_index_count"] == 1
    assert status["authority_revision"] == store.get_authority_revision()
    assert status["index_generation"].startswith("local:")
    assert status["index_snapshot_revision"] is None
    with client_for(store) as client:
        response = client.get("/memory/index/status")
        assert response.status_code == 200
        assert response.json()["metadata"]["authority_revision"] == status["authority_revision"]
    restarted = SQLiteMemoryStore(path, embedding_service=Embedding())
    restarted.search("synthetic")
    assert restarted.get_document_index_status("saved") == "indexed"
    assert len(restarted.list_documents()) == 1


@pytest.mark.parametrize("operation", ["single", "batch", "maintenance"])
def test_permanent_delete_erases_candidate_body_and_nested_history(tmp_path, operation):
    marker = "SYNTHETIC_ERASE_MARKER"
    path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(path, embedding_service=Embedding())
    metadata = {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved",
                "expires_at": "2020-01-01T00:00:00Z", "evidence": {"raw": marker},
                "version_history": [{"text": marker}], "audit": [{"before": {"text": marker}}]}
    store.add_document(Document("candidate", marker, metadata))
    store.record_operation(new_operation(operation="create", document_id="candidate", scope="workspace", workspace_id="audit", evidence={"raw": marker}, details={"text": marker}, reason=marker))
    with client_for(store) as client:
        if operation == "single":
            response = client.delete("/memory/docs/candidate")
        elif operation == "batch":
            response = client.post("/memory/docs/batch-delete", json={"ids": ["candidate"]})
        else:
            preview = client.post("/memory/maintenance/preview", json={"scope": "workspace"})
            response = client.post("/memory/maintenance/apply", json={"scope": "workspace", "confirmation": "PERMANENT_DELETE", "preview_token": preview.json()["preview_token"]})
        assert response.status_code == 200, response.text
        assert response.json()["index_cleanup_status"] == "complete"
        assert response.json()["status"] in {"deleted", "purged"}
        exported = client.get("/memory/export", params={"include_state": "all"})
        assert marker not in exported.text
        assert marker not in json.dumps(store.list_operations(document_id="candidate"))
    restarted = SQLiteMemoryStore(path, embedding_service=Embedding())
    docs = restarted.list_documents()
    assert len(docs) == 1 and docs[0].text == ""
    assert docs[0].metadata["candidate_deleted"] is True
    assert marker not in json.dumps(docs[0].__dict__)
    assert restarted.search("synthetic") == []
    restarted.add_document(Document("candidate", marker, dict(META)))
    assert restarted.list_documents()[0].text == ""
    assert restarted.get_document_index_status("candidate") == "excluded"


def test_existing_tombstones_are_scrubbed_on_open(tmp_path):
    path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(path, embedding_service=Embedding())
    store.add_document(Document("legacy", "old private body", dict(META)))
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE memory_documents SET metadata_json = ? WHERE id = ?", (json.dumps({**META, "candidate": True, "candidate_deleted": True, "evidence": "old private body"}), "legacy"))
    restarted = SQLiteMemoryStore(path, embedding_service=Embedding())
    assert "old private body" not in json.dumps(restarted.list_documents()[0].__dict__)


@pytest.mark.parametrize("session_id", [None, "", " "])
def test_scope_update_validates_final_document(session_id):
    store = VectorStore(embedding_service=Embedding())
    store.add_document(Document("doc", "synthetic", dict(META)))
    with client_for(store) as client:
        response = client.put("/memory/docs/doc", json={"scope": "session", "session_id": session_id})
        assert response.status_code == 400
        assert store.list_documents()[0].metadata["scope"] == "workspace"


def test_relation_budget_applies_inside_neighbor_loop():
    docs = [Document("anchor", "synthetic", {**META, "source_ids": [f"r{i}" for i in range(6)]})]
    docs += [Document(f"r{i}", "related synthetic", dict(META)) for i in range(6)]

    class Backend:
        def list_documents(self):
            return docs

        def search_with_rerank(self, **kwargs):
            return [(docs[0], 1.0)]

    result = RetrievalPipeline(Backend()).recall(RetrievalRequest(query="synthetic", scope="workspace", workspace_id="audit", top_k=10, relation_limit=1))
    assert len(result["results"]) == 2
    assert result["trace"]["relation_accepted"] == 1
    assert result["trace"]["expansion_truncated"] is True


@pytest.mark.parametrize("backend", ["sqlite", "inmemory"])
def test_tombstone_metadata_and_api_mutations_cannot_retain_erased_payload(tmp_path, backend):
    store = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding()) if backend == "sqlite" else VectorStore(embedding_service=Embedding())
    metadata = {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved"}
    store.add_document(Document("candidate", "synthetic original", metadata))
    with client_for(store) as client:
        assert client.delete("/memory/docs/candidate").status_code == 200
        update = client.put("/memory/docs/candidate", json={"text": "SYNTHETIC_LATE_BODY", "edit_reason": "SYNTHETIC_LATE_BODY"})
        restore = client.post("/memory/docs/candidate/restore", json={})
        assert update.status_code == restore.status_code == 409
    store.update_metadata("candidate", {**metadata, "evidence": "SYNTHETIC_LATE_BODY"})
    doc = store.list_documents()[0]
    assert doc.metadata["candidate_deleted"] is True
    assert "SYNTHETIC_LATE_BODY" not in json.dumps(doc.__dict__)
    if backend == "sqlite":
        store.record_operation(new_operation(operation="update", document_id="candidate", reason="SYNTHETIC_LATE_BODY", evidence="SYNTHETIC_LATE_BODY", details={"before": "SYNTHETIC_LATE_BODY"}))
        restarted = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding())
        assert "SYNTHETIC_LATE_BODY" not in json.dumps(restarted.list_operations(document_id="candidate"))
        assert restarted.list_documents()[0].metadata["candidate_deleted"] is True


def test_candidate_purge_keeps_replay_identity_through_authority_write(tmp_path):
    class Store(SQLiteMemoryStore):
        def delete_document(self, doc_id):
            raise AssertionError("candidate identity must not be removed before its tombstone is durable")

    store = Store(tmp_path / "memory.db", embedding_service=Embedding())
    store.add_document(Document("candidate", "synthetic original", {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved"}))
    with client_for(store) as client:
        assert client.delete("/memory/docs/candidate").status_code == 200
    assert store.list_documents()[0].text == ""
    assert store.list_documents()[0].metadata["candidate_deleted"] is True
    store.add_document(Document("candidate", "synthetic replay", dict(META)))
    assert store.list_documents()[0].text == ""


def test_inflight_embedding_cannot_replace_deleted_candidate():
    from modules.memory.metadata import candidate_tombstone_metadata

    class PausingEmbedding(Embedding):
        hook = None

        def embed(self, text):
            if self.hook is not None:
                callback, self.hook = self.hook, None
                callback()
            return super().embed(text)

    embedding = PausingEmbedding()
    store = VectorStore(embedding_service=embedding)
    metadata = {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved"}
    store.add_document(Document("candidate", "synthetic original", dict(metadata)))
    embedding.hook = lambda: store.add_metadata_document(Document("candidate", "", candidate_tombstone_metadata(metadata)))
    store.add_document(Document("candidate", "synthetic late embedding", dict(metadata)))
    doc = store.list_documents()[0]
    assert doc.text == "" and doc.metadata["candidate_deleted"] is True
    assert "candidate" not in store._vectors


@pytest.mark.parametrize("index_failure", [False, True])
def test_index_projection_uses_tombstone_authority_even_when_embedding_fails(tmp_path, index_failure):
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.metadata import candidate_tombstone_metadata

    class Projection(VectorStore):
        def add_document(self, doc):
            if index_failure and doc.metadata.get("candidate_deleted"):
                raise RuntimeError("synthetic projection embedding failure")
            super().add_document(doc)

        def update_metadata(self, doc_id, metadata):
            # Qdrant's payload update accepts its caller's metadata verbatim.
            self._docs[doc_id].metadata = dict(metadata)

    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding())
    index = Projection(embedding_service=Embedding())
    backend = IndexedMemoryBackend(authority, index)
    metadata = {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved"}
    backend.add_document(Document("candidate", "SYNTHETIC_ERASED_INDEX_BODY", dict(metadata)))
    backend.add_metadata_document(Document("candidate", "", candidate_tombstone_metadata(metadata)))
    backend.update_metadata("candidate", {**META, "evidence": "SYNTHETIC_ERASED_INDEX_BODY"})
    assert authority.list_documents()[0].metadata["candidate_deleted"] is True
    assert "SYNTHETIC_ERASED_INDEX_BODY" not in json.dumps([doc.__dict__ for doc in index.list_documents()])
    assert backend.get_document_index_status("candidate") == "excluded"


@pytest.mark.parametrize("operation", ["single", "batch", "maintenance"])
def test_delete_reports_pending_projection_cleanup_and_rebuild_recovers(tmp_path, operation):
    from modules.memory.indexed_backend import IndexedMemoryBackend

    class Projection(VectorStore):
        fail_delete = False
        delete_calls = 0

        def delete_document(self, doc_id):
            self.delete_calls += 1
            if self.fail_delete:
                raise ConnectionError("synthetic remote index unavailable")
            super().delete_document(doc_id)

    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding())
    index = Projection(embedding_service=Embedding())
    backend = IndexedMemoryBackend(authority, index)
    metadata = {**META, "candidate": True, "candidate_id": "candidate", "review_status": "approved",
                "expires_at": "2020-01-01T00:00:00Z"}
    backend.add_document(Document("candidate", "SYNTHETIC_REMOTE_BODY", metadata))
    assert backend.get_index_cleanup_status() == "complete"
    backend.add_document(Document("healthy", "synthetic healthy body", dict(META)))
    with client_for(backend) as client:
        complete = client.delete("/memory/docs/healthy")
        assert complete.status_code == 200, complete.text
        assert complete.json()["status"] == "deleted"
        assert complete.json()["index_cleanup_status"] == "complete"
    index.fail_delete = True
    with client_for(backend) as client:
        if operation == "single":
            response = client.delete("/memory/docs/candidate")
        elif operation == "batch":
            response = client.post("/memory/docs/batch-delete", json={"ids": ["candidate"]})
        else:
            preview = client.post("/memory/maintenance/preview", json={"scope": "workspace"})
            response = client.post("/memory/maintenance/apply", json={"scope": "workspace", "confirmation": "PERMANENT_DELETE", "preview_token": preview.json()["preview_token"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "authority_deleted"
    assert response.json()["index_cleanup_status"] == "pending"
    assert authority.list_documents()[0].text == ""
    assert authority.list_documents()[0].metadata["candidate_deleted"] is True
    assert index.list_documents()[0].text == "SYNTHETIC_REMOTE_BODY"
    assert backend.get_document_index_status("candidate") == "excluded"
    calls = index.delete_calls
    assert backend.get_index_cleanup_status() == "pending"
    assert index.delete_calls == calls
    index.fail_delete = False
    backend.rebuild_index()
    assert backend.get_index_cleanup_status() == "complete"
    assert "SYNTHETIC_REMOTE_BODY" not in json.dumps([doc.__dict__ for doc in index.list_documents()])
