from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.memory.indexed_backend import IndexedMemoryBackend
from modules.memory.routes import MemoryState, create_memory_router
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document, VectorStore
from modules.system.memory_write_pipeline import (
    build_task_completed_event,
    normalize_relationship_memory_payload,
)


class _Embedding:
    dimension = 3

    def embed(self, text: str) -> np.ndarray:
        return np.asarray([float(len(text or "")), 1.0, 0.5], dtype=np.float32)


def _client(store) -> TestClient:
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store)))
    return TestClient(app)


def _source_replay_payload() -> dict:
    return {
        "id": "ordinary-source-memory",
        "text": "The user prefers jasmine tea.",
        "scope": "global",
        "source_kind": "user",
        "source_id": "turn-source-1",
        "turn_id": "turn-source-1",
        "dedupe": False,
    }


def _candidate_payload(task_id: str) -> dict:
    event = build_task_completed_event(
        task_name="backup",
        task_id=task_id,
        task_mode="once",
        owner_agent_id="agent",
        owner_agent_role="worker",
        session_id="turn-1",
    )
    return normalize_relationship_memory_payload(
        event,
        active_workspace_id="ws",
        companion_id="companion",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )


def _query(client: TestClient) -> list[dict]:
    response = client.post(
        "/memory/rag/query",
        json={"query": "jasmine tea", "scope": "global"},
    )
    assert response.status_code == 200
    return response.json()["results"]


def test_soft_forget_survives_sqlite_reopen_index_rebuild_and_source_replay_until_restore(tmp_path):
    db_path = tmp_path / "memory.db"
    initial_store = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    initial_client = _client(initial_store)
    payload = _source_replay_payload()

    created = initial_client.post("/memory/docs", json=payload)
    assert created.status_code == 200
    assert _query(initial_client)

    forgotten = initial_client.post(
        f"/memory/docs/{payload['id']}/soft-forget",
        json={"reason": "user_requested", "turn_id": "turn-forget-1"},
    )
    assert forgotten.status_code == 200
    assert _query(initial_client) == []

    reopened_authority = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    composite = IndexedMemoryBackend(
        authority=reopened_authority,
        index=VectorStore(embedding_service=_Embedding()),
    )
    assert composite.rebuild_index()["document_count"] == 1
    reopened_client = _client(composite)
    assert _query(reopened_client) == []

    replayed = reopened_client.post("/memory/docs", json=payload)
    assert replayed.status_code == 200
    [persisted] = reopened_authority.list_documents()
    assert persisted.metadata["soft_forgotten"] is True
    assert persisted.metadata["soft_forget_turn_id"] == "turn-forget-1"
    assert _query(reopened_client) == []

    restored = reopened_client.post(
        f"/memory/docs/{payload['id']}/restore",
        json={"reason": "user_confirmed_restore", "turn_id": "turn-restore-1"},
    )
    assert restored.status_code == 200
    assert restored.json()["changed"] is True
    assert [result["doc"]["id"] for result in _query(reopened_client)] == [payload["id"]]


def test_permanent_delete_leaves_no_authority_index_or_query_residue(tmp_path):
    authority = SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=_Embedding())
    index = VectorStore(embedding_service=_Embedding())
    composite = IndexedMemoryBackend(authority=authority, index=index)
    client = _client(composite)
    payload = _source_replay_payload()

    assert client.post("/memory/docs", json=payload).status_code == 200
    assert _query(client)

    deleted = client.delete(f"/memory/docs/{payload['id']}")
    assert deleted.status_code == 200
    assert authority.list_documents() == []
    assert index.list_documents() == []

    rebuilt = composite.rebuild_index()
    assert rebuilt["document_count"] == 0
    assert rebuilt["indexed_count"] == 0
    assert authority.search("jasmine tea") == []
    assert index.search("jasmine tea") == []
    assert _query(client) == []


@pytest.mark.parametrize("terminal_status", ["deleted", "rejected"])
def test_candidate_terminal_status_survives_rollback_to_pending_revision(terminal_status: str):
    store = VectorStore(embedding_service=_Embedding())
    client = _client(store)
    payload = _candidate_payload(f"rollback-{terminal_status}")
    doc_id = payload["doc_id"]
    store.add_metadata_document(
        Document(id=doc_id, text=payload["text"], metadata=payload["metadata"])
    )

    if terminal_status == "deleted":
        terminal = client.delete(f"/memory/docs/{doc_id}")
    else:
        terminal = client.post(
            f"/memory/docs/{doc_id}/review",
            json={"decision": "reject", "reason": "user_rejected"},
        )
    assert terminal.status_code == 200

    rolled_back = client.post(
        f"/memory/docs/{doc_id}/rollback",
        json={"revision": 1, "reason": "attempt_terminal_bypass"},
    )
    assert rolled_back.status_code == 200
    [persisted] = store.list_documents()
    assert persisted.metadata["review_status"] == terminal_status
    if terminal_status == "deleted":
        assert persisted.metadata["candidate_deleted"] is True

    query = client.post(
        "/memory/rag/query",
        json={
            "query": "backup",
            "scope": "workspace",
            "workspace_id": "ws",
            "layers": ["relationship"],
        },
    )
    assert query.status_code == 200
    assert query.json()["results"] == []
