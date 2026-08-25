from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest
from modules.memory.indexed_backend import IndexedMemoryBackend
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document, VectorStore
from modules.system.memory_write_pipeline import (
    build_tool_success_event,
    build_task_completed_event,
    normalize_relationship_memory_payload,
    persist_relationship_memory,
)
from modules.system.relationship_runtime import (
    build_relationship_memory_writer,
    collect_relationship_events,
)


class _Store:
    def __init__(self, results=None):
        self.docs = []
        self.results = results or []

    def list_documents(self):
        return list(self.docs)

    def add_metadata_document(self, doc):
        self.docs.append(doc)

    def add_document(self, doc):
        self.docs = [item for item in self.docs if item.id != doc.id]
        self.docs.append(doc)

    def delete_document(self, doc_id):
        self.docs = [item for item in self.docs if item.id != doc_id]

    def search_with_rerank(self, **_kwargs):
        return list(self.results)


class _Embedding:
    dimension = 3

    def embed(self, text: str) -> np.ndarray:
        return np.asarray([float(len(text or "")), 1.0, 0.5], dtype=np.float32)


def _candidate_payload(*, category: str = "none", task_id: str = "task-api"):
    payload = build_task_completed_event(
        task_name="backup", task_id=task_id, task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    payload["metadata"]["sensitive_category"] = category
    payload["metadata"]["sensitivity"] = category
    return normalize_relationship_memory_payload(
        payload,
        active_workspace_id="ws",
        companion_id="c",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )


def _normalize(
    payload: dict,
    *,
    workspace_id: str = "ws",
    allow_low_risk_admission: bool = False,
) -> dict:
    return normalize_relationship_memory_payload(
        payload,
        active_workspace_id=workspace_id,
        companion_id="c",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
        allow_low_risk_admission=allow_low_risk_admission,
    )


def _real_writer(store, *, workspace_id: str = "ws"):
    class _Repo:
        def get_workspace_companion(self, requested_workspace_id: str):
            assert requested_workspace_id == workspace_id
            return {"id": "c"}

    return build_relationship_memory_writer(
        get_active_workspace_id=lambda: workspace_id,
        get_db_repo=lambda: _Repo(),
        get_memory_store=lambda: store,
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )


def test_completed_event_is_pending_candidate_with_stable_idempotent_persistence():
    payload = build_task_completed_event(
        task_name="backup", task_id="task-1", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    normalized = normalize_relationship_memory_payload(
        payload,
        active_workspace_id="ws",
        companion_id="companion",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )
    store = _Store()
    first = persist_relationship_memory(normalized, memory_store=store)
    second = persist_relationship_memory(normalized, memory_store=store)

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert len(store.docs) == 1
    assert store.docs[0].metadata["candidate"] is True
    assert store.docs[0].metadata["review_status"] == "pending"
    assert store.docs[0].metadata["source_kind"] == "task_completed"
    assert store.docs[0].metadata["review_required"] is True
    assert store.docs[0].metadata["sensitive_category"] == "none"
    assert store.docs[0].metadata["sensitivity"] == "none"


@pytest.mark.parametrize("workspace_location", ["payload", "metadata"])
def test_candidate_workspace_must_match_active_workspace(workspace_location: str):
    payload = build_task_completed_event(
        task_name="backup", task_id="task-workspace", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    if workspace_location == "payload":
        payload["workspace_id"] = "other"
    else:
        payload["metadata"]["workspace_id"] = "other"

    with pytest.raises(ValueError, match="does not match active_workspace_id"):
        normalize_relationship_memory_payload(
            payload,
            active_workspace_id="ws",
            companion_id="companion",
            resolve_relationship_scope=lambda _kind, _scope: "workspace",
            normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
        )


def test_candidate_workspace_is_normalized_to_active_workspace():
    payload = build_task_completed_event(
        task_name="backup", task_id="task-workspace-default", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    payload["workspace_id"] = "  ws  "
    payload["metadata"]["workspace_id"] = "ws"

    normalized = normalize_relationship_memory_payload(
        payload,
        active_workspace_id=" ws ",
        companion_id="companion",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )

    assert normalized["metadata"]["workspace_id"] == "ws"
    assert normalized["doc_id"] == normalized["metadata"]["candidate_id"]


def test_pending_candidate_is_not_retrievable_or_relationship_history():
    pending = Document(
        id="pending",
        text="private task",
        metadata={"candidate": True, "review_status": "pending", "layer": "relationship", "scope": "workspace", "workspace_id": "ws", "event_type": "relationship_state", "companion_id": "c"},
    )
    store = _Store(results=[(pending, 1.0)])
    recalled = RetrievalPipeline(store).recall(RetrievalRequest(query="private", layers=["relationship"], scope="workspace", workspace_id="ws"))
    events = collect_relationship_events(memory_store=store, companion_id="c", limit=10, workspace_id="ws")

    assert recalled["results"] == []
    assert events == []


def test_candidate_tombstone_is_not_revived_by_idempotent_writer():
    payload = build_task_completed_event(
        task_name="backup", task_id="task-delete", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    normalized = normalize_relationship_memory_payload(
        payload,
        active_workspace_id="ws",
        companion_id="c",
        resolve_relationship_scope=lambda _kind, _scope: "workspace",
        normalize_relationship_importance=lambda _kind, value: float(value or 0.8),
    )
    store = _Store()
    persist_relationship_memory(normalized, memory_store=store)
    tombstone = store.docs[0]
    tombstone.metadata["review_status"] = "deleted"
    tombstone.metadata["deleted_at"] = "2026-01-01T00:00:00Z"
    result = persist_relationship_memory(normalized, memory_store=store)

    assert result["idempotent"] is True
    assert len(store.docs) == 1
    assert store.docs[0].metadata["review_status"] == "deleted"


def test_sensitive_candidate_is_explicitly_review_required_and_not_auto_approved():
    normalized = _candidate_payload(category="health", task_id="task-health")
    store = _Store()
    persist_relationship_memory(normalized, memory_store=store)

    metadata = store.docs[0].metadata
    assert metadata["sensitive_category"] == "health"
    assert metadata["sensitivity"] == "health"
    assert metadata["review_required"] is True
    assert metadata["review_status"] == "pending"


@pytest.mark.parametrize("field", ["sensitive_category", "sensitivity"])
def test_invalid_sensitivity_is_rejected_instead_of_falling_back_to_none(field: str):
    payload = build_task_completed_event(
        task_name="backup", task_id=f"invalid-{field}", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    payload["metadata"][field] = "classified-but-unknown"

    with pytest.raises(ValueError, match="unsupported memory sensitivity"):
        _normalize(payload)


def test_conflicting_sensitivity_fields_are_rejected():
    payload = build_task_completed_event(
        task_name="backup", task_id="conflicting-sensitivity", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    payload["metadata"]["sensitive_category"] = "health"
    payload["metadata"]["sensitivity"] = "finance"

    with pytest.raises(ValueError, match="conflicting memory sensitivity"):
        _normalize(payload)


@pytest.mark.parametrize(
    ("tool_name", "tool_source", "expected_source", "expected_trust"),
    [
        ("read_file", "builtin", "builtin", "verified"),
        ("web_search", "builtin", "web", "untrusted"),
        ("screen_ocr", "builtin", "ocr", "untrusted"),
        ("server.lookup", "mcp", "mcp", "untrusted"),
        ("plugin.notes.capture", "plugin", "plugin", "untrusted"),
    ],
)
def test_tool_candidate_preserves_source_and_trust(
    tool_name: str,
    tool_source: str,
    expected_source: str,
    expected_trust: str,
):
    event = build_tool_success_event(
        tool_name=tool_name,
        tool_source=tool_source,
        args={"query": "tea"},
        text="tool completed",
        importance=0.8,
        owner_agent_id="agent",
        owner_agent_role="reflector",
    )
    metadata = _normalize(event)["metadata"]

    assert metadata["event_kind"] == "tool_success"
    assert metadata["source_kind"] == expected_source
    assert metadata["trust_level"] == expected_trust
    assert metadata["evidence"] == {"query": "tea"}


def test_low_risk_admission_requires_explicit_trusted_non_sensitive_source():
    trusted = build_tool_success_event(
        tool_name="read_status",
        tool_source="builtin",
        args={},
        text="status read",
        importance=0.8,
        owner_agent_id="agent",
        owner_agent_role="reflector",
        allow_low_risk_admission=True,
    )
    admitted = _normalize(trusted, allow_low_risk_admission=True)["metadata"]
    assert admitted["review_status"] == "approved"
    assert admitted["review_required"] is False
    assert admitted["admission_policy"] == "low_risk_auto"

    external = build_tool_success_event(
        tool_name="web_search",
        tool_source="builtin",
        args={},
        text="search complete",
        importance=0.8,
        owner_agent_id="agent",
        owner_agent_role="reflector",
        allow_low_risk_admission=True,
    )
    held = _normalize(external, allow_low_risk_admission=True)["metadata"]
    assert held["review_status"] == "pending"
    assert held["review_required"] is True
    assert held["admission_reason"] == "untrusted_source_requires_review"


def test_candidate_payload_cannot_override_server_derived_trust_level():
    event = build_tool_success_event(
        tool_name="read_status",
        args={},
        text="status read",
        importance=0.8,
        owner_agent_id="agent",
        owner_agent_role="reflector",
    )
    event["metadata"]["trust_level"] = "probably"

    metadata = _normalize(event)["metadata"]

    assert metadata["trust_level"] == "verified"


@pytest.mark.asyncio
async def test_tool_executor_persists_source_through_real_writer_and_sqlite(tmp_path):
    context_module = __import__("modules.agent.context", fromlist=["AgentRequestContext", "bind_runtime_bindings"])
    policy_module = __import__("modules.agent.policy_engine", fromlist=["PolicyEngine"])
    registry_module = __import__("modules.agent.tool_registry", fromlist=["ToolDefinition", "ToolRegistry"])
    result_module = __import__("modules.agent.tool_result", fromlist=["ToolResultEnvelope"])
    executor_module = __import__("modules.agent.tool_executor", fromlist=["ToolExecutor"])

    db_path = tmp_path / "tool-memory.db"
    store = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    registry = registry_module.ToolRegistry()
    registry.register(registry_module.ToolDefinition(
        name="web_search",
        description="search",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: result_module.ToolResultEnvelope(
            success=True,
            content="result",
            source="builtin",
            tool_name="web_search",
        ),
    ))
    executor = executor_module.ToolExecutor(
        registry,
        policy_module.PolicyEngine(store_file=tmp_path / "permissions.json"),
    )
    ctx = context_module.AgentRequestContext(
        sid="memory-source",
        session_id="session-source",
        request_id="request-source",
        messages=[],
    )
    context_module.bind_runtime_bindings(ctx, relationship_event_writer=_real_writer(store))

    outcome = await executor.execute("web_search", {"query": "tea"}, ctx=ctx)

    assert outcome.success is True
    reopened = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    [persisted] = reopened.list_documents()
    assert persisted.metadata["event_kind"] == "tool_success"
    assert persisted.metadata["source_kind"] == "web"
    assert persisted.metadata["tool_source"] == "builtin"
    assert persisted.metadata["trust_level"] == "untrusted"
    assert persisted.metadata["review_status"] == "pending"
    assert reopened.search("search") == []


def test_rejected_candidate_stays_out_of_recall_and_history():
    normalized = _candidate_payload(task_id="task-rejected")
    store = _Store()
    persist_relationship_memory(normalized, memory_store=store)
    store.docs[0].metadata["review_status"] = "rejected"
    store.results = [(store.docs[0], 1.0)]

    recalled = RetrievalPipeline(store).recall(
        RetrievalRequest(query="backup", layers=["relationship"], scope="workspace", workspace_id="ws")
    )
    events = collect_relationship_events(memory_store=store, companion_id="c", limit=10, workspace_id="ws")
    assert recalled["results"] == []
    assert events == []


def test_candidate_delete_api_creates_non_reviewable_tombstone_and_blocks_revival():
    routes_module = __import__("modules.memory.routes", fromlist=["MemoryState", "create_memory_router"])
    store = VectorStore(embedding_service=_Embedding())
    state = routes_module.MemoryState(store=store)
    app = FastAPI()
    app.include_router(routes_module.create_memory_router(state))
    client = TestClient(app)

    normalized = _candidate_payload(task_id="task-delete-api")
    store.add_metadata_document(Document(id=normalized["doc_id"], text=normalized["text"], metadata=normalized["metadata"]))
    doc_id = normalized["doc_id"]

    response = client.delete(f"/memory/docs/{doc_id}")
    assert response.status_code == 200
    assert response.json()["tombstone"] is True
    tombstone = next(doc for doc in store.list_documents() if doc.id == doc_id)
    assert tombstone.metadata["candidate_deleted"] is True
    assert tombstone.metadata["candidate_deleted_at"]
    assert tombstone.metadata["review_status"] == "deleted"

    review = client.post(f"/memory/docs/{doc_id}/review", json={"decision": "approve"})
    assert review.status_code == 409
    assert "deleted" in str(review.json()["detail"])

    query = client.post(
        "/memory/rag/query",
        json={"query": "backup", "scope": "workspace", "workspace_id": "ws", "layers": ["relationship"]},
    )
    assert query.status_code == 200
    assert query.json()["results"] == []
    rebuild = client.post("/memory/index/rebuild")
    assert rebuild.status_code == 200
    query_after_rebuild = client.post(
        "/memory/rag/query",
        json={"query": "backup", "scope": "workspace", "workspace_id": "ws", "layers": ["relationship"]},
    )
    assert query_after_rebuild.status_code == 200
    assert query_after_rebuild.json()["results"] == []

    replay = persist_relationship_memory(normalized, memory_store=store)
    assert replay["idempotent"] is True
    assert len([doc for doc in store.list_documents() if doc.id == doc_id]) == 1


def test_rejected_candidate_is_terminal_and_deleted_candidates_are_auditable():
    routes_module = __import__("modules.memory.routes", fromlist=["MemoryState", "create_memory_router"])
    store = VectorStore(embedding_service=_Embedding())
    state = routes_module.MemoryState(store=store)
    app = FastAPI()
    app.include_router(routes_module.create_memory_router(state))
    client = TestClient(app)

    rejected = _candidate_payload(task_id="task-reject-api")
    store.add_metadata_document(Document(id=rejected["doc_id"], text=rejected["text"], metadata=rejected["metadata"]))
    rejected_id = rejected["doc_id"]
    assert client.post(f"/memory/docs/{rejected_id}/review", json={"decision": "reject"}).status_code == 200
    terminal_review = client.post(f"/memory/docs/{rejected_id}/review", json={"decision": "approve"})
    assert terminal_review.status_code == 409

    deleted = _candidate_payload(task_id="task-batch-delete")
    store.add_metadata_document(Document(id=deleted["doc_id"], text=deleted["text"], metadata=deleted["metadata"]))
    deleted_id = deleted["doc_id"]
    batch = client.post("/memory/docs/batch-delete", json={"ids": [deleted_id]})
    assert batch.status_code == 200
    tombstone_list = client.get("/memory/candidates?status=deleted")
    assert tombstone_list.status_code == 200
    assert {item["id"] for item in tombstone_list.json()["candidates"]} >= {deleted_id}


def test_candidate_non_revival_survives_sqlite_restart_index_rebuild_and_real_writer(tmp_path):
    db_path = tmp_path / "memory.db"
    first_store = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    writer = _real_writer(first_store)
    event = build_task_completed_event(
        task_name="backup", task_id="task-durable-delete", task_mode="once",
        owner_agent_id="agent", owner_agent_role="worker", session_id="turn-1",
    )
    writer(event)
    [candidate] = first_store.list_documents()

    routes_module = __import__("modules.memory.routes", fromlist=["MemoryState", "create_memory_router"])
    app = FastAPI()
    app.include_router(routes_module.create_memory_router(routes_module.MemoryState(store=first_store)))
    response = TestClient(app).delete(f"/memory/docs/{candidate.id}")
    assert response.status_code == 200
    assert response.json()["tombstone"] is True

    restarted_authority = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    composite = IndexedMemoryBackend(
        authority=restarted_authority,
        index=VectorStore(embedding_service=_Embedding()),
    )
    rebuild = composite.rebuild_index()
    assert rebuild["document_count"] == 1
    assert composite.search("backup") == []
    tombstone_before = restarted_authority.list_documents()[0]
    assert tombstone_before.metadata["candidate_deleted"] is True
    assert tombstone_before.metadata["review_status"] == "deleted"

    _real_writer(composite)(event)
    [tombstone_after] = composite.list_documents()
    assert tombstone_after.id == tombstone_before.id
    assert tombstone_after.text == tombstone_before.text
    assert tombstone_after.metadata == tombstone_before.metadata
    assert composite.search("backup") == []

    final_restart = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    [persisted_tombstone] = final_restart.list_documents()
    assert persisted_tombstone.metadata["candidate_deleted"] is True
    assert persisted_tombstone.metadata["review_status"] == "deleted"
