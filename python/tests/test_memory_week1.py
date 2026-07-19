"""Week 1 memory infrastructure acceptance tests.

These tests verify:
1) typed memory write + importance filtering
2) backward-compatible legacy /memory/docs write
3) RAG query with type filter and recency reranking path
"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib
from typing import Any

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _FakeEmbeddingService:
    """Deterministic, lightweight embedding service for tests."""

    dimension = 4

    def embed(self, text: str) -> np.ndarray:
        text = text or ""
        return np.array(
            [
                float(len(text)),
                float(text.count("猫") + text.count("cat")),
                float(text.count("狗") + text.count("dog")),
                1.0,
            ],
            dtype=np.float32,
        )


def _memory_routes_module() -> Any:
    return importlib.import_module("modules.memory.routes")


def _memory_vector_store_module() -> Any:
    return importlib.import_module("modules.memory.vector_store")


def _memory_pipeline_module() -> Any:
    return importlib.import_module("modules.memory.pipeline")


def _make_client() -> tuple[TestClient, Any]:
    app = FastAPI()
    routes_module = _memory_routes_module()
    vector_store_module = _memory_vector_store_module()
    embedding_service: Any = _FakeEmbeddingService()
    store = vector_store_module.VectorStore(embedding_service=embedding_service)
    state = routes_module.MemoryState(store=store)
    app.include_router(routes_module.create_memory_router(state))
    return TestClient(app), store


def _make_client_with_pipeline() -> tuple[TestClient, Any]:
    app = FastAPI()
    routes_module = _memory_routes_module()
    vector_store_module = _memory_vector_store_module()
    pipeline_module = _memory_pipeline_module()
    embedding_service: Any = _FakeEmbeddingService()
    store = vector_store_module.VectorStore(embedding_service=embedding_service)
    pipeline = pipeline_module.RetrievalPipeline(store)
    state = routes_module.MemoryState(store=store, pipeline=pipeline)
    app.include_router(routes_module.create_memory_router(state))
    return TestClient(app), store


def test_add_memory_importance_filter_and_type_write() -> None:
    client, _ = _make_client()

    low_resp = client.post(
        "/memory/memory/add",
        json={"text": "这条不重要", "type": "fact", "importance": 0.2},
    )
    assert low_resp.status_code == 200
    low_data = low_resp.json()
    assert low_data["skipped"] is True
    assert low_data["reason"] == "low_importance"

    ok_resp = client.post(
        "/memory/memory/add",
        json={"text": "用户喜欢猫", "type": "preference", "importance": 0.9},
    )
    assert ok_resp.status_code == 200
    ok_data = ok_resp.json()
    assert ok_data["status"] == "ok"
    assert ok_data["type"] == "preference"

    docs_resp = client.get("/memory/docs", params={"scope": "global"})
    assert docs_resp.status_code == 200
    docs = docs_resp.json()["docs"]
    assert len(docs) == 1
    assert docs[0]["metadata"]["type"] == "preference"
    assert docs[0]["metadata"]["importance"] == 0.9
    assert "state" not in docs[0]["metadata"]
    assert 0 <= docs[0]["metadata"]["confidence"] <= 1
    assert 0 <= docs[0]["metadata"]["quality_score"] <= 1
    assert docs[0]["metadata"]["confidence_source"]


def test_legacy_docs_endpoint_backward_compatibility() -> None:
    client, _ = _make_client()

    resp = client.post(
        "/memory/docs",
        json={"id": "legacy-1", "text": "legacy text", "metadata": {"source": "legacy"}},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    docs = client.get("/memory/docs", params={"scope": "global"}).json()["docs"]
    assert len(docs) == 1
    assert docs[0]["id"] == "legacy-1"
    assert docs[0]["text"] == "legacy text"
    assert docs[0]["metadata"]["layer"] == "semantic"
    assert docs[0]["metadata"]["scope"] == "global"


def test_legacy_docs_without_id_get_unique_ids_and_scope_metadata() -> None:
    client, _ = _make_client()

    first = client.post(
        "/memory/docs",
        json={"text": "first doc", "workspace_id": "ws-1", "scope": "workspace"},
    )
    second = client.post(
        "/memory/docs",
        json={"text": "second doc", "workspace_id": "ws-1", "scope": "workspace"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert len(docs) == 2
    assert {doc["text"] for doc in docs} == {"first doc", "second doc"}
    assert all(doc["metadata"]["scope"] == "workspace" for doc in docs)
    assert all(doc["metadata"]["workspace_id"] == "ws-1" for doc in docs)


def test_legacy_docs_update_preserves_id_and_refreshes_vector_doc() -> None:
    client, _ = _make_client()

    created = client.post(
        "/memory/docs",
        json={
            "id": "editable-1",
            "text": "用户喜欢猫",
            "workspace_id": "ws-1",
            "scope": "workspace",
            "metadata": {"source": "manual", "layer": "profile"},
        },
    )
    assert created.status_code == 200

    updated = client.put(
        "/memory/docs/editable-1",
        json={
            "text": "用户现在更喜欢狗",
            "type": "preference",
            "layer": "profile",
            "importance": 0.86,
            "workspace_id": "ws-1",
            "scope": "workspace",
            "metadata": {"source": "manual-edit"},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == "updated"
    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert len(docs) == 1
    assert docs[0]["id"] == "editable-1"
    assert docs[0]["text"] == "用户现在更喜欢狗"
    assert docs[0]["metadata"]["type"] == "preference"
    assert docs[0]["metadata"]["layer"] == "profile"
    assert docs[0]["metadata"]["scope"] == "workspace"
    assert docs[0]["metadata"]["importance"] == 0.86
    assert docs[0]["metadata"]["source"] == "manual-edit"
    assert docs[0]["metadata"]["updated_at"]


def test_legacy_docs_update_and_delete_accept_encoded_slash_ids() -> None:
    client, _ = _make_client()

    created = client.post(
        "/memory/docs",
        json={
            "id": "folder/doc-1",
            "text": "slash id memory",
            "workspace_id": "ws-1",
            "scope": "workspace",
        },
    )
    assert created.status_code == 200

    updated = client.put(
        "/memory/docs/folder%2Fdoc-1",
        json={"text": "updated slash id memory", "workspace_id": "ws-1", "scope": "workspace"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == "folder/doc-1"

    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert docs[0]["id"] == "folder/doc-1"
    assert docs[0]["text"] == "updated slash id memory"

    deleted = client.delete("/memory/docs/folder%2Fdoc-1")
    assert deleted.status_code == 200
    assert deleted.json() == {"status": "deleted", "id": "folder/doc-1", "storage": None}
    assert client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"] == []


def test_legacy_docs_update_missing_doc_returns_404() -> None:
    client, _ = _make_client()

    response = client.put("/memory/docs/missing", json={"text": "new text"})

    assert response.status_code == 404


def test_add_memory_explicit_workspace_scope_overrides_session_default() -> None:
    client, _ = _make_client()

    resp = client.post(
        "/memory/memory/add",
        json={
            "text": "写入当前工作区的手动记忆",
            "type": "fact",
            "importance": 0.8,
            "scope": "workspace",
            "workspace_id": "ws-1",
            "session_id": "session-1",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["scope"] == "workspace"
    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert len(docs) == 1
    assert docs[0]["metadata"]["scope"] == "workspace"
    assert docs[0]["metadata"]["workspace_id"] == "ws-1"


def test_rag_query_type_filter_and_recency_rerank() -> None:
    client, store = _make_client()

    # Seed documents directly for deterministic timestamp control.
    now = datetime.now()
    old_ts = (now - timedelta(days=365)).isoformat()
    new_ts = now.isoformat()

    # Same semantic signal, different age.
    store.add_document(
        _memory_vector_store_module().Document(
            id="old-pref",
            text="用户喜欢猫",
            metadata={"type": "preference", "timestamp": old_ts, "importance": 0.8},
        )
    )
    store.add_document(
        _memory_vector_store_module().Document(
            id="new-pref",
            text="用户喜欢猫",
            metadata={"type": "preference", "timestamp": new_ts, "importance": 0.8},
        )
    )
    store.add_document(
        _memory_vector_store_module().Document(
            id="fact-1",
            text="用户住在上海",
            metadata={"type": "fact", "timestamp": new_ts, "importance": 0.7},
        )
    )

    filtered = client.post(
        "/memory/rag/query",
        json={
            "query": "用户喜欢什么",
            "top_k": 5,
            "memory_types": ["preference"],
            "recency_weight": 0.8,
        },
    )
    assert filtered.status_code == 200
    results = filtered.json()["results"]
    assert len(results) == 2
    assert all(item["doc"]["metadata"]["type"] == "preference" for item in results)
    assert results[0]["doc"]["id"] == "new-pref"


def test_rag_query_pipeline_respects_type_filter() -> None:
    client, store = _make_client_with_pipeline()
    vector_store_module = _memory_vector_store_module()
    store.add_document(
        vector_store_module.Document(
            id="pref-1",
            text="用户喜欢猫",
            metadata={"type": "preference", "layer": "semantic", "scope": "workspace", "workspace_id": "ws-1"},
        )
    )
    store.add_document(
        vector_store_module.Document(
            id="fact-1",
            text="用户住在上海",
            metadata={"type": "fact", "layer": "semantic", "scope": "workspace", "workspace_id": "ws-1"},
        )
    )

    response = client.post(
        "/memory/rag/query",
        json={
            "query": "用户信息",
            "top_k": 5,
            "scope": "workspace",
            "workspace_id": "ws-1",
            "layers": ["semantic"],
            "memory_types": ["preference"],
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["doc"]["id"] for item in results] == ["pref-1"]


def test_add_memory_returns_duplicate_candidates_and_can_bypass_dedupe() -> None:
    client, _ = _make_client()

    first = client.post(
        "/memory/memory/add",
        json={
            "text": "用户喜欢猫",
            "type": "preference",
            "importance": 0.9,
            "scope": "workspace",
            "workspace_id": "ws-1",
        },
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    duplicate = client.post(
        "/memory/memory/add",
        json={
            "text": "用户喜欢猫",
            "type": "preference",
            "importance": 0.9,
            "scope": "workspace",
            "workspace_id": "ws-1",
        },
    )
    assert duplicate.status_code == 200
    duplicate_data = duplicate.json()
    assert duplicate_data["status"] == "duplicate_candidates"
    assert duplicate_data["skipped"] is True
    assert duplicate_data["duplicate_candidates"][0]["id"] == first_id
    assert duplicate_data["duplicate_candidates"][0]["match_reason"] == "exact_text"

    bypassed = client.post(
        "/memory/memory/add",
        json={
            "text": "用户喜欢猫",
            "type": "preference",
            "importance": 0.9,
            "scope": "workspace",
            "workspace_id": "ws-1",
            "dedupe": False,
        },
    )
    assert bypassed.status_code == 200
    assert bypassed.json()["status"] == "ok"

    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert len(docs) == 2


def test_delete_permanently_removes_doc() -> None:
    client, _ = _make_client()

    created = client.post(
        "/memory/docs",
        json={
            "id": "delete-1",
            "text": "这条稍后会被删除",
            "scope": "workspace",
            "workspace_id": "ws-1",
        },
    )
    assert created.status_code == 200

    deleted = client.delete("/memory/docs/delete-1")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    visible_docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert visible_docs == []

    assert all(doc.id != "delete-1" for doc in _.list_documents())

    query = client.post(
        "/memory/rag/query",
        json={"query": "删除", "top_k": 5, "scope": "workspace", "workspace_id": "ws-1"},
    )
    assert query.status_code == 200
    assert query.json()["results"] == []


def test_batch_delete_permanently_removes_docs() -> None:
    client, _ = _make_client()

    for doc_id in ("batch-delete-1", "batch-delete-2"):
        created = client.post(
            "/memory/docs",
            json={
                "id": doc_id,
                "text": f"{doc_id} 稍后会被删除",
                "scope": "workspace",
                "workspace_id": "ws-1",
                "dedupe": False,
            },
        )
        assert created.status_code == 200

    deleted = client.post(
        "/memory/docs/batch-delete",
        json={"ids": ["batch-delete-1", "batch-delete-2", "batch-delete-1"]},
    )

    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["deleted_count"] == 2
    assert deleted.json()["ids"] == ["batch-delete-1", "batch-delete-2"]

    repeated = client.post(
        "/memory/docs/batch-delete",
        json={"ids": ["batch-delete-1", "batch-delete-2"]},
    )
    assert repeated.status_code == 404

    visible_docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert visible_docs == []

    assert all(doc.id not in {"batch-delete-1", "batch-delete-2"} for doc in _.list_documents())


def test_memory_maintenance_permanently_deletes_candidates_only_after_confirmation() -> None:
    client, store = _make_client()
    vector_store_module = _memory_vector_store_module()
    old_timestamp = (datetime.now() - timedelta(days=45)).isoformat()
    store.add_document(
        vector_store_module.Document(
            id="stale-working",
            text="已过期的工作记忆",
            metadata={
                "layer": "working",
                "scope": "workspace",
                "workspace_id": "ws-1",
                "timestamp": old_timestamp,
            },
        )
    )

    policy = {
        "scope": "workspace",
        "workspace_id": "ws-1",
        "working_retention_days": 14,
        "low_quality_threshold": 0.55,
        "include_stale_working": True,
        "include_low_quality": True,
        "include_exact_duplicates": True,
    }
    preview = client.post("/memory/maintenance/preview", json=policy)
    assert preview.status_code == 200
    assert preview.json()["summary"]["delete_count"] == 1
    assert preview.json()["candidates"][0]["id"] == "stale-working"
    preview_token = preview.json()["preview_token"]

    rejected = client.post("/memory/maintenance/apply", json={**policy, "preview_token": preview_token})
    assert rejected.status_code == 400
    assert store.list_documents()

    purged = client.post(
        "/memory/maintenance/apply",
        json={
            **policy,
            "confirmation": "PERMANENT_DELETE",
            "preview_token": preview_token,
        },
    )
    assert purged.status_code == 200
    assert purged.json()["changed_ids"] == ["stale-working"]
    assert store.list_documents() == []


def test_memory_maintenance_rejects_a_stale_preview() -> None:
    client, store = _make_client()
    vector_store_module = _memory_vector_store_module()
    old_timestamp = (datetime.now() - timedelta(days=45)).isoformat()
    store.add_document(vector_store_module.Document(
        id="stale-working",
        text="Old memory",
        metadata={
            "layer": "working",
            "scope": "workspace",
            "workspace_id": "ws-1",
            "timestamp": old_timestamp,
        },
    ))
    policy = {
        "scope": "workspace",
        "workspace_id": "ws-1",
        "working_retention_days": 14,
    }
    preview_token = client.post("/memory/maintenance/preview", json=policy).json()["preview_token"]
    store.add_metadata_document(vector_store_module.Document(
        id="new-memory",
        text="A new memory arrived after preview",
        metadata={"layer": "semantic", "scope": "workspace", "workspace_id": "ws-1"},
    ))

    response = client.post(
        "/memory/maintenance/apply",
        json={
            **policy,
            "confirmation": "PERMANENT_DELETE",
            "preview_token": preview_token,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "memory_maintenance_preview_stale"
    assert {doc.id for doc in store.list_documents()} == {"stale-working", "new-memory"}


def test_memory_maintenance_preview_token_binds_the_policy() -> None:
    client, _store = _make_client()
    policy = {
        "scope": "workspace",
        "workspace_id": "ws-1",
        "working_retention_days": 14,
    }
    preview_token = client.post("/memory/maintenance/preview", json=policy).json()["preview_token"]

    response = client.post(
        "/memory/maintenance/apply",
        json={
            **policy,
            "working_retention_days": 30,
            "confirmation": "PERMANENT_DELETE",
            "preview_token": preview_token,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "memory_maintenance_preview_stale"


def test_retired_memory_state_field_is_rejected_without_mutation() -> None:
    client, store = _make_client()
    vector_store_module = _memory_vector_store_module()
    store.add_document(
        vector_store_module.Document(
            id="active-1",
            text="用户喜欢猫",
            metadata={"layer": "semantic", "scope": "workspace", "workspace_id": "ws-1", "type": "preference"},
        )
    )

    docs = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "ws-1"}).json()["docs"]
    assert {doc["id"] for doc in docs} == {"active-1"}

    status = client.get("/memory/index/status")
    assert status.status_code == 200
    status_data = status.json()
    assert status_data["count"] == 1
    assert status_data["metadata"]["recallable_count"] == 1

    query = client.post(
        "/memory/rag/query",
        json={"query": "用户", "top_k": 5, "scope": "workspace", "workspace_id": "ws-1", "layers": ["semantic"]},
    )
    assert query.status_code == 200
    assert [item["doc"]["id"] for item in query.json()["results"]] == ["active-1"]

    update = client.put(
        "/memory/docs/active-1",
        json={"metadata": {"state": "archived"}, "scope": "workspace", "workspace_id": "ws-1"},
    )
    assert update.status_code == 422
    assert update.json()["detail"]["error"] == "retired_memory_fields"
    updated_doc = next(doc for doc in store.list_documents() if doc.id == "active-1")
    assert "state" not in updated_doc.metadata
    results = client.post(
        "/memory/rag/query",
        json={"query": "用户喜欢猫", "top_k": 5, "scope": "workspace", "workspace_id": "ws-1", "layers": ["semantic"]},
    ).json()["results"]
    assert [item["doc"]["id"] for item in results] == ["active-1"]


def test_rag_query_trace_exposes_filter_and_score_details() -> None:
    client, store = _make_client()
    vector_store_module = _memory_vector_store_module()
    store.add_document(
        vector_store_module.Document(
            id="trace-a",
            text="当前工作区记忆",
            metadata={"layer": "semantic", "scope": "workspace", "workspace_id": "ws-a", "type": "fact"},
        )
    )
    store.add_document(
        vector_store_module.Document(
            id="trace-b",
            text="别的工作区记忆",
            metadata={"layer": "semantic", "scope": "workspace", "workspace_id": "ws-b", "type": "fact"},
        )
    )

    response = client.post(
        "/memory/rag/query",
        json={"query": "工作区", "top_k": 3, "scope": "workspace", "workspace_id": "ws-a", "layers": ["semantic"]},
    )

    assert response.status_code == 200
    trace = response.json()["trace"]
    assert trace["candidate_limit"] >= 3
    assert trace["candidate_count"] == 1
    assert trace["filtered_count"] == 1
    assert trace["filtered_out_count"] == 0
    assert trace["backend_filter_downpushed"] is True
    assert trace["latency_ms"] >= 0
    assert trace["top_score"] is not None
    assert trace["average_score"] is not None


def test_typed_payload_rejects_invalid_scope_layer_and_unit_fields() -> None:
    client, _ = _make_client()

    invalid_scope = client.post("/memory/docs", json={"text": "bad", "scope": "planet"})
    assert invalid_scope.status_code == 422

    invalid_layer = client.post("/memory/memory/add", json={"text": "bad", "layer": "cache"})
    assert invalid_layer.status_code == 422

    invalid_importance = client.post("/memory/memory/add", json={"text": "bad", "importance": 1.2})
    assert invalid_importance.status_code == 422


def test_qdrant_filter_downpush_uses_metadata_conditions_and_memory_type_values() -> None:
    vector_client_module = importlib.import_module("modules.memory.vector_client")
    schema_module = importlib.import_module("modules.memory.schema")
    vector_store_module = _memory_vector_store_module()

    class FakeMatchValue:
        def __init__(self, value: object):
            self.value = value

    class FakeMatchAny:
        def __init__(self, any: list[object]):
            self.any = any

    class FakeFieldCondition:
        def __init__(self, key: str, match: object):
            self.key = key
            self.match = match

    class FakeFilter:
        def __init__(self, **kwargs: object):
            self.must = kwargs.get("must", [])
            self.must_not = kwargs.get("must_not", [])

    store = object.__new__(vector_client_module.QdrantVectorStore)
    store._filter = FakeFilter
    store._field_condition = FakeFieldCondition
    store._match_value = FakeMatchValue
    store._match_any = FakeMatchAny

    query_filter = store._build_query_filter(
        filters=schema_module.MemorySearchFilters(
            scope="workspace",
            workspace_id="ws-1",
            layers=["semantic", "profile"],
        ),
        memory_types=[vector_store_module.MemoryType.PREFERENCE],
    )

    must_by_key = {condition.key: condition.match for condition in query_filter.must}
    assert must_by_key["scope"].value == "workspace"
    assert "workspace_id" not in must_by_key
    assert must_by_key["layer"].any == ["semantic", "profile"]
    assert must_by_key["type"].value == "preference"
    assert query_filter.must_not == []
