"""Memory ownership contracts exercised through FastAPI and temporary SQLite."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.memory.operations import MemoryOperationLog, new_operation
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.routes import (
    MemoryState,
    create_memory_pipeline_router,
    create_memory_router,
)
from modules.memory.schema import MemorySearchFilters, RetrievalRequest
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document, VectorStore


class Embedding:
    dimension = 2

    def embed(self, text):
        return np.array([float(len(text)), 1.0], dtype=np.float32)


def make_client(store, active):
    app = FastAPI()
    getter = (lambda: active[0]) if active is not None else None
    app.include_router(create_memory_router(MemoryState(store=store), get_active_workspace_id=getter))
    pipeline = RetrievalPipeline(store)
    app.include_router(create_memory_pipeline_router(
        lambda **kwargs: pipeline.recall(RetrievalRequest(
            **{**kwargs, "layers": kwargs["layers"].split(",") if kwargs["layers"] else ["semantic"]},
        )), get_active_workspace_id=getter,
    ))
    return TestClient(app)


def seed(store, doc_id, workspace, *, session="shared", expired=False, scope="session", layer="semantic"):
    metadata = {"scope": scope, "workspace_id": workspace, "session_id": session,
                "layer": layer, "type": "fact", "quality_score": 0.9}
    if expired:
        metadata["expires_at"] = "2020-01-01T00:00:00Z"
    store.add_document(Document(doc_id, f"synthetic secret {doc_id}", metadata))
    store.record_operation(new_operation(operation="create", document_id=doc_id,
                                        scope=scope, workspace_id=workspace, session_id=session))


@pytest.fixture
def store(tmp_path):
    return SQLiteMemoryStore(tmp_path / "memory.db", embedding_service=Embedding())


@pytest.mark.parametrize("endpoint,key", [("docs", "docs"), ("export", "docs"), ("operations", "operations")])
@pytest.mark.parametrize("explicit_workspace", [False, True])
def test_session_routes_exclude_other_workspace_and_unassigned(store, endpoint, key, explicit_workspace):
    for doc_id, workspace in [("owned-a", "A"), ("owned-b", "B"), ("unassigned", None)]:
        seed(store, doc_id, workspace)
    seed(store, "other-session", "A", session="other")
    params = {"scope": "session", "session_id": " shared "}
    if explicit_workspace:
        params["workspace_id"] = " A "
    with make_client(store, ["A"]) as client:
        response = client.get(f"/memory/{endpoint}", params=params)
    assert response.status_code == 200, response.text
    field = "document_id" if endpoint == "operations" else "id"
    assert [doc[field] for doc in response.json()[key]] == ["owned-a"]
    if endpoint != "docs":
        assert response.json()["workspace_id"] == "A"


@pytest.mark.parametrize("endpoint", ["/memory/query", "/memory/rag/query", "/api/memory/pipeline/query"])
def test_session_recall_routes_exclude_cross_workspace(store, endpoint):
    for doc_id, workspace in [("owned-a", "A"), ("owned-b", "B"), ("unassigned", None)]:
        seed(store, doc_id, workspace)
    payload = {"query": "synthetic secret", "scope": "session", "session_id": "shared", "top_k": 10}
    with make_client(store, ["A"]) as client:
        response = client.get(endpoint, params=payload) if endpoint.startswith("/api/") else client.post(endpoint, json=payload)
    assert response.status_code == 200, response.text
    assert [item["doc"]["id"] for item in response.json()["results"]] == ["owned-a"]
    assert response.json()["trace"]["workspace_id"] == "A"


def test_session_maintenance_cannot_delete_other_workspace(store):
    for doc_id, workspace in [("owned-a", "A"), ("owned-b", "B"), ("unassigned", None)]:
        seed(store, doc_id, workspace, expired=True)
    payload = {"scope": "session", "session_id": " shared "}
    with make_client(store, ["A"]) as client:
        preview = client.post("/memory/maintenance/preview", json=payload)
        assert preview.status_code == 200, preview.text
        assert [doc["id"] for doc in preview.json()["candidates"]] == ["owned-a"]
        applied = client.post("/memory/maintenance/apply", json={
            **payload, "preview_token": preview.json()["preview_token"], "confirmation": "PERMANENT_DELETE",
        })
        assert applied.status_code == 200, applied.text
        assert applied.json()["changed_ids"] == ["owned-a"]
    assert {doc.id for doc in store.list_documents()} == {"owned-b", "unassigned"}


@pytest.mark.parametrize("active", [None, ["A"]])
@pytest.mark.parametrize("moved_field,moved_value", [("workspace_id", "B"), ("session_id", "other"), ("scope", "workspace")])
def test_maintenance_revalidates_every_candidate_before_any_delete(tmp_path, active, moved_field, moved_value):
    class MovingStore(SQLiteMemoryStore):
        reads_until_move = None

        def list_documents(self):
            if self.reads_until_move is not None:
                self.reads_until_move -= 1
                if self.reads_until_move == 0:
                    self.reads_until_move = None
                    doc = next(doc for doc in super().list_documents() if doc.id == "z-moved")
                    self.add_metadata_document(Document(doc.id, doc.text, {**doc.metadata, moved_field: moved_value}))
            return super().list_documents()

    store = MovingStore(tmp_path / "moving.db", embedding_service=Embedding())
    seed(store, "a-stable", "A", expired=True)
    seed(store, "z-moved", "A", expired=True)
    payload = {"scope": "session", "session_id": "shared", "workspace_id": "A"}
    with make_client(store, active) as client:
        preview = client.post("/memory/maintenance/preview", json=payload)
        store.reads_until_move = 2  # Move after plan reconstruction, at the deletion boundary.
        applied = client.post("/memory/maintenance/apply", json={
            **payload, "preview_token": preview.json()["preview_token"], "confirmation": "PERMANENT_DELETE",
        })
    assert applied.status_code == 403, applied.text
    assert {doc.id for doc in store.list_documents()} == {"a-stable", "z-moved"}
    assert next(doc for doc in store.list_documents() if doc.id == "z-moved").metadata[moved_field] == moved_value


def import_payload(*, workspace=None, metadata=None, **doc_fields):
    return {"format": "yuizaki-memory-export", "version": 1, "scope": "session",
            "session_id": "shared", "workspace_id": workspace,
            "docs": [{"id": "imported", "text": "synthetic imported", "metadata": metadata or {}, **doc_fields}]}


@pytest.mark.parametrize("active_workspace,envelope,source", [("A", "A", None), ("A", None, "A"), (None, None, "A")])
def test_session_import_owner_is_stable_after_restart_and_workspace_switch(tmp_path, active_workspace, envelope, source):
    path = tmp_path / "roundtrip.db"
    store = SQLiteMemoryStore(path, embedding_service=Embedding())
    active = [active_workspace] if active_workspace is not None else None
    metadata = {"workspace_id": source, "scope": "session", "session_id": "shared"}
    with make_client(store, active) as client:
        response = client.post("/memory/import", json=import_payload(workspace=envelope, metadata=metadata))
    assert response.status_code == 200, response.text
    assert response.json()["imported_count"] == 1
    assert response.json()["workspace_id"] == "A"
    restarted = SQLiteMemoryStore(path, embedding_service=Embedding())
    assert restarted.list_documents()[0].metadata["workspace_id"] == "A"
    with make_client(restarted, ["B"]) as client:
        assert client.get("/memory/docs", params={"scope": "session", "session_id": "shared"}).json()["docs"] == []
        assert client.put("/memory/docs/imported", json={"text": "changed", "session_id": "shared"}).status_code == 403
        assert client.delete("/memory/docs/imported", params={"session_id": "shared"}).status_code == 403
    assert restarted.list_documents()[0].text == "synthetic imported"


@pytest.mark.parametrize("active", [None, ["A"], ["default"]])
def test_unassigned_legacy_session_import_requires_explicit_workspace(store, active):
    with make_client(store, active) as client:
        response = client.post("/memory/import", json=import_payload())
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["error"] == "workspace_assignment_required"
    assert store.list_documents() == []


@pytest.mark.parametrize("source", [
    {"metadata": {"workspace_id": "B"}},
    {"workspace_id": "B"},
    {"workspace_id": "A", "metadata": {"workspace_id": "B"}},
])
def test_session_import_preflights_conflicting_owners_before_writes(store, source):
    payload = import_payload(workspace="A", **source)
    payload["docs"].insert(0, {"id": "would-write-first", "text": "synthetic valid"})
    with make_client(store, ["A"]) as client:
        response = client.post("/memory/import", json=payload)
    assert response.status_code == 403, response.text
    assert store.list_documents() == []


@pytest.mark.parametrize("layer", ["profile", "working", "episodic", "relationship", "reflective", "semantic", "session"])
@pytest.mark.parametrize("legacy_export", [False, True])
@pytest.mark.parametrize("scope", ["workspace", "session"])
def test_export_import_preserves_explicit_layer_for_facts(tmp_path, layer, legacy_export, scope):
    source = SQLiteMemoryStore(tmp_path / "source.db", embedding_service=Embedding())
    seed(source, "roundtrip", "A", scope=scope, session="shared" if scope == "session" else None, layer=layer)
    params = {"scope": scope, "session_id": "shared"} if scope == "session" else {}
    with make_client(source, ["A"]) as client:
        export = client.get("/memory/export", params=params).json()
    if legacy_export:
        for doc in export["docs"]:
            doc.pop("layer", None)
    else:
        assert export["docs"][0]["layer"] == layer
    target = SQLiteMemoryStore(tmp_path / "target.db", embedding_service=Embedding())
    payload = {key: export[key] for key in ("format", "version", "scope", "workspace_id", "session_id", "docs")}
    with make_client(target, ["A"]) as client:
        imported = client.post("/memory/import", json=payload)
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported_count"] == 1
        reexported = client.get("/memory/export", params=params).json()["docs"][0]
    assert reexported["metadata"]["layer"] == layer
    assert reexported["metadata"]["type"] == "fact"


@pytest.mark.parametrize("endpoint", ["docs", "export", "operations"])
def test_no_active_workspace_keeps_unassigned_session_compatibility_without_wildcard(store, endpoint):
    seed(store, "legacy", None)
    seed(store, "bound", "B")
    with make_client(store, None) as client:
        response = client.get(f"/memory/{endpoint}", params={"scope": "session", "session_id": "shared"})
    assert response.status_code == 200, response.text
    key, field = ("operations", "document_id") if endpoint == "operations" else ("docs", "id")
    assert [doc[field] for doc in response.json()[key]] == ["legacy"]


@pytest.mark.parametrize("active", [None, ["default"], ["A"]])
def test_global_and_default_workspace_compatibility(store, active):
    seed(store, "legacy-workspace", None, scope="workspace", session=None)
    seed(store, "global", None, scope="global", session=None)
    with make_client(store, active) as client:
        assert [doc["id"] for doc in client.get("/memory/docs").json()["docs"]] == ["legacy-workspace"]
        assert [doc["id"] for doc in client.get("/memory/export", params={"scope": "global"}).json()["docs"]] == ["global"]
        query = client.post("/memory/query", json={"query": "synthetic", "scope": "global"})
        assert [item["doc"]["id"] for item in query.json()["results"]] == ["global"]


def test_implicit_session_write_binds_active_workspace_and_orphan_mutations_are_rejected(store):
    seed(store, "orphan", None)
    with make_client(store, ["A"]) as client:
        created = client.post("/memory/docs", json={"id": "new", "text": "synthetic new", "session_id": "shared", "dedupe": False})
        assert created.status_code == 200, created.text
        assert client.put("/memory/docs/orphan", json={"text": "changed", "session_id": "shared"}).status_code == 403
        assert client.delete("/memory/docs/orphan", params={"session_id": "shared"}).status_code == 403
    assert next(doc for doc in store.list_documents() if doc.id == "new").metadata["workspace_id"] == "A"


@pytest.mark.parametrize("backend", ["sqlite", "inmemory", "postfilter"])
def test_recall_checks_workspace_even_when_backend_returns_cross_workspace(tmp_path, backend):
    docs = [Document(str(workspace), "synthetic", {"scope": "session", "session_id": "shared", "workspace_id": workspace,
                                               "layer": "semantic"}) for workspace in ("A", "B", None)]
    if backend == "postfilter":
        class Backend:
            def search_with_rerank(self, **kwargs):
                return [(doc, 1.0) for doc in docs]
        store = Backend()
    else:
        store = SQLiteMemoryStore(tmp_path / "backend.db", embedding_service=Embedding()) if backend == "sqlite" else VectorStore(embedding_service=Embedding())
        for doc in docs:
            store.add_document(doc)
        results = store.search_with_rerank("synthetic", top_k=10, filters=MemorySearchFilters(scope="session", session_id="shared", workspace_id="A"))
        assert [doc.id for doc, _ in results] == ["A"]
    result = RetrievalPipeline(store).recall(RetrievalRequest(query="synthetic", scope="session", session_id="shared", workspace_id="A", relation_expansion=False))
    assert [item["doc"]["id"] for item in result["results"]] == ["A"]


def test_unassigned_session_operation_log_is_not_a_workspace_wildcard():
    log = MemoryOperationLog()
    for workspace in (None, "A", "B"):
        log.append(new_operation(operation="create", document_id=str(workspace), scope="session", workspace_id=workspace, session_id="shared"))
    assert [item["document_id"] for item in log.list(scope="session", session_id="shared")] == ["None"]


@pytest.mark.parametrize("path", ["docs", "export", "operations", "overview"])
def test_explicit_foreign_workspace_is_rejected_by_read_routes(store, path):
    seed(store, "foreign", "B")
    with make_client(store, ["A"]) as client:
        response = client.get(f"/memory/{path}", params={"scope": "session", "workspace_id": "B", "session_id": "shared"})
    assert response.status_code == 403, response.text


def test_import_never_assigns_owner_from_a_sibling_record(store):
    payload = import_payload(metadata={"workspace_id": "A"})
    payload["docs"].append({"id": "unassigned", "text": "synthetic orphan"})
    with make_client(store, ["A"]) as client:
        response = client.post("/memory/import", json=payload)
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["error"] == "workspace_assignment_required"
    assert store.list_documents() == []


@pytest.mark.parametrize("metadata_layer", ["invalid", 17, ["profile"]])
def test_import_rejects_invalid_legacy_layer_before_writes(store, metadata_layer):
    payload = import_payload(workspace="A", metadata={"layer": metadata_layer})
    with make_client(store, ["A"]) as client:
        response = client.post("/memory/import", json=payload)
    assert response.status_code == 400, response.text
    assert store.list_documents() == []


def test_session_overview_counts_only_own_workspace(store):
    seed(store, "owned-a", "A")
    seed(store, "owned-b", "B")
    seed(store, "unassigned", None)
    with make_client(store, ["A"]) as client:
        response = client.get("/memory/overview", params={"scope": "session", "session_id": "shared"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [doc["id"] for doc in response.json()["latest_activity"]] == ["owned-a"]
