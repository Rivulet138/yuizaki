from __future__ import annotations

from datetime import datetime, timezone
import importlib
from typing import Any

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _EmbeddingService:
    dimension = 2

    def embed(self, _text: str) -> np.ndarray:
        return np.array([1.0, 0.0], dtype=np.float32)


def _modules() -> tuple[Any, Any, Any]:
    return (
        importlib.import_module("modules.memory.routes"),
        importlib.import_module("modules.memory.vector_store"),
        importlib.import_module("modules.memory.pipeline"),
    )


def _client() -> tuple[TestClient, Any]:
    routes, vector_store, _pipeline = _modules()
    store = vector_store.VectorStore(embedding_service=_EmbeddingService())
    app = FastAPI()
    app.include_router(routes.create_memory_router(routes.MemoryState(store=store)))
    return TestClient(app), store


def test_doc_expiry_is_optional_normalized_and_rejects_invalid_values() -> None:
    client, store = _client()

    permanent = client.post(
        "/memory/docs",
        json={"id": "permanent", "text": "permanent", "metadata": {"expires_at": None}},
    )
    canonical = client.post(
        "/memory/docs",
        json={"id": "canonical", "text": "canonical", "metadata": {"expires_at": "2099-01-01T00:00:00Z"}},
    )
    offset = client.post(
        "/memory/docs",
        json={"id": "offset", "text": "offset", "metadata": {"expires_at": "2099-01-01T08:00:00+08:00"}},
    )
    lowercase_z = client.post(
        "/memory/docs",
        json={"id": "lowercase-z", "text": "lowercase", "metadata": {"expires_at": "2099-01-01T00:00:00z"}},
    )
    padded = client.post(
        "/memory/docs",
        json={"id": "padded", "text": "padded", "metadata": {"expires_at": " 2099-01-01T00:00:00Z "}},
    )
    naive = client.post(
        "/memory/docs",
        json={"id": "naive", "text": "remember", "metadata": {"expires_at": "2099-01-01T00:00:00"}},
    )
    malformed = client.post(
        "/memory/docs",
        json={"id": "malformed", "text": "remember", "metadata": {"expires_at": "tomorrow"}},
    )
    expired = client.post(
        "/memory/docs",
        json={"id": "expired", "text": "remember", "metadata": {"expires_at": "2000-01-01T00:00:00Z"}},
    )

    assert permanent.status_code == 200
    assert canonical.status_code == 200
    assert offset.status_code == 400
    assert lowercase_z.status_code == 400
    assert padded.status_code == 400
    assert naive.status_code == 400
    assert malformed.status_code == 400
    assert expired.status_code == 400
    docs = {doc.id: doc for doc in store.list_documents()}
    assert "expires_at" not in docs["permanent"].metadata
    assert docs["canonical"].metadata["expires_at"] == "2099-01-01T00:00:00Z"
    for response in (offset, lowercase_z, padded, naive, malformed):
        assert response.json()["detail"] == "expires_at must use uppercase UTC Z RFC3339 format"


def test_doc_update_can_clear_expiry_without_losing_unknown_metadata() -> None:
    client, store = _client()
    created = client.post(
        "/memory/docs",
        json={
            "id": "editable",
            "text": "remember",
            "metadata": {
                "expires_at": "2099-01-01T00:00:00Z",
                "extension_field": {"preserve": True},
            },
        },
    )
    assert created.status_code == 200

    updated = client.put(
        "/memory/docs/editable",
        json={"metadata": {"expires_at": None, "source": "manual"}},
    )

    assert updated.status_code == 200
    doc = next(doc for doc in store.list_documents() if doc.id == "editable")
    assert "expires_at" not in doc.metadata
    assert doc.metadata["extension_field"] == {"preserve": True}
    assert doc.metadata["source"] == "manual"


def test_expired_docs_are_hidden_from_list_and_vector_search_before_ranking() -> None:
    client, store = _client()
    _, vector_store, _ = _modules()
    store.add_document(vector_store.Document(
        id="expired",
        text="same",
        metadata={"scope": "global", "expires_at": "2000-01-01T00:00:00Z"},
    ))
    store.add_document(vector_store.Document(
        id="active",
        text="same",
        metadata={"scope": "global", "expires_at": "2099-01-01T00:00:00Z"},
    ))

    listed = client.get("/memory/docs", params={"scope": "global"})
    results = store.search_with_rerank("same", top_k=10)

    assert [doc["id"] for doc in listed.json()["docs"]] == ["active"]
    assert [doc.id for doc, _score in results] == ["active"]


def test_soft_forgotten_docs_are_hidden_from_list_and_vector_search() -> None:
    client, store = _client()
    _, vector_store, _ = _modules()
    store.add_document(vector_store.Document(
        id="forgotten",
        text="same",
        metadata={"scope": "global", "soft_forgotten": True},
    ))
    store.add_document(vector_store.Document(
        id="active",
        text="same",
        metadata={"scope": "global"},
    ))

    listed = client.get("/memory/docs", params={"scope": "global"})
    results = store.search_with_rerank("same", top_k=10)

    assert [doc["id"] for doc in listed.json()["docs"]] == ["active"]
    assert [doc.id for doc, _score in results] == ["active"]


def test_retrieval_pipeline_defensively_filters_expired_results_with_trace_reason() -> None:
    _, vector_store, pipeline_module = _modules()
    expired = vector_store.Document(
        id="expired",
        text="same",
        metadata={
            "scope": "workspace",
            "workspace_id": "ws-1",
            "layer": "semantic",
            "expires_at": "2000-01-01T00:00:00Z",
        },
    )

    class _Store:
        def search_with_rerank(self, **_kwargs: Any) -> list[tuple[Any, float]]:
            return [(expired, 1.0)]

    pipeline = pipeline_module.RetrievalPipeline(_Store())
    result = pipeline.recall(importlib.import_module("modules.memory.schema").RetrievalRequest(
        query="same",
        scope="workspace",
        workspace_id="ws-1",
        layers=["semantic"],
    ))

    assert result["results"] == []
    assert result["trace"]["filter_reasons"] == {"expired": 1}


def test_maintenance_preview_includes_expired_scoped_document() -> None:
    client, store = _client()
    _, vector_store, _ = _modules()
    store.add_document(vector_store.Document(
        id="expired",
        text="old",
        metadata={
            "scope": "workspace",
            "workspace_id": "ws-1",
            "layer": "semantic",
            "expires_at": "2000-01-01T00:00:00Z",
        },
    ))

    preview = client.post(
        "/memory/maintenance/preview",
        json={
            "scope": "workspace",
            "workspace_id": "ws-1",
            "include_stale_working": False,
            "include_low_quality": False,
            "include_exact_duplicates": False,
        },
    )

    assert preview.status_code == 200
    candidates = preview.json()["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["id"] == "expired"
    assert candidates[0]["action"] == "delete"
    assert candidates[0]["reasons"] == ["expired"]


def test_expiry_boundary_is_inclusive() -> None:
    expiry = importlib.import_module("modules.memory.expiry")
    instant = datetime(2030, 1, 1, tzinfo=timezone.utc)

    assert expiry.is_memory_expired({"expires_at": "2030-01-01T00:00:00Z"}, now=instant) is True


def _fake_qdrant_store_with_expired_prefix(expired_count: int) -> tuple[Any, list[int]]:
    vector_client = importlib.import_module("modules.memory.vector_client")
    store = object.__new__(vector_client.QdrantVectorStore)
    store._embedding_service = _EmbeddingService()
    store._reranker = None
    store._reranker_candidate_count = 32
    store.collection_name = "memories"
    store._collection_exists = lambda: True
    store._build_query_filter = lambda **_kwargs: None
    captured_offsets: list[int] = []

    class _Point:
        def __init__(self, point_id: str, expires_at: str, score: float) -> None:
            self.id = point_id
            self.score = score
            self.payload = {
                "doc_id": point_id,
                "text": "same",
                "metadata": {"expires_at": expires_at},
            }

    class _Client:
        def query_points(self, **kwargs: Any) -> Any:
            offset = int(kwargs.get("offset") or 0)
            limit = int(kwargs["limit"])
            captured_offsets.append(offset)
            total = expired_count + 1
            points = []
            for index in range(offset, min(offset + limit, total)):
                if index < expired_count:
                    points.append(_Point(
                        f"expired-{index}",
                        "2000-01-01T00:00:00Z",
                        1.0 - index * 0.0001,
                    ))
                else:
                    points.append(_Point("active", "2099-01-01T00:00:00Z", 0.5))
            return type("Result", (), {"points": points})()

    store.client = _Client()
    return store, captured_offsets


def test_qdrant_search_pages_past_an_expired_first_window() -> None:
    store, captured_offsets = _fake_qdrant_store_with_expired_prefix(9)

    results = store.search("same", top_k=1)

    assert captured_offsets == [0, 8]
    assert [doc.id for doc, _score in results] == ["active"]


def test_qdrant_rerank_pages_until_it_finds_an_active_candidate() -> None:
    store, captured_offsets = _fake_qdrant_store_with_expired_prefix(65)

    results = store.search_with_rerank("same", top_k=1)

    assert captured_offsets == [0, 64]
    assert [doc.id for doc, _score in results] == ["active"]


def test_qdrant_search_and_rerank_raise_when_scan_limit_hides_a_later_active_doc() -> None:
    incomplete_error = importlib.import_module("modules.memory.backend").MemorySearchIncompleteError

    search_store, search_offsets = _fake_qdrant_store_with_expired_prefix(4096)
    with pytest.raises(incomplete_error) as search_exc:
        search_store.search("same", top_k=1)
    assert search_exc.value.scanned_count == 4096
    assert search_exc.value.scan_limit == 4096
    assert search_exc.value.returned_count == 0
    assert search_offsets[-1] == 4088

    rerank_store, _rerank_offsets = _fake_qdrant_store_with_expired_prefix(4096)
    with pytest.raises(incomplete_error) as rerank_exc:
        rerank_store.search_with_rerank("same", top_k=1)
    assert rerank_exc.value.scanned_count == 4096
    assert rerank_exc.value.code == "memory_search_scan_limit_reached"


def test_pipeline_and_api_propagate_scan_limit_as_structured_incomplete_trace() -> None:
    routes, _vector_store, pipeline_module = _modules()
    backend = importlib.import_module("modules.memory.backend")

    class _IncompleteStore:
        backend_name = "qdrant"

        def search_with_rerank(self, **_kwargs: Any) -> list[tuple[Any, float]]:
            raise backend.MemorySearchIncompleteError(
                requested_count=1,
                selected_ids=[],
                scanned_count=4096,
                rejected_count=4096,
                scan_limit=4096,
            )

    pipeline = pipeline_module.RetrievalPipeline(_IncompleteStore())
    request = importlib.import_module("modules.memory.schema").RetrievalRequest(
        query="same",
        scope="global",
        layers=["semantic"],
        top_k=1,
    )

    with pytest.raises(backend.MemorySearchIncompleteError):
        pipeline.recall(request)
    assert pipeline.last_trace is not None
    assert pipeline.last_trace["complete"] is False
    assert pipeline.last_trace["scan_limit_reached"] is True
    assert pipeline.last_trace["error_code"] == "memory_search_scan_limit_reached"

    app = FastAPI()
    app.include_router(routes.create_memory_router(routes.MemoryState(
        store=_IncompleteStore(),
        pipeline=pipeline,
    )))
    response = TestClient(app).post(
        "/memory/rag/query",
        json={"query": "same", "scope": "global", "top_k": 1},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "memory_search_scan_limit_reached"
    assert detail["scan_limit_reached"] is True
    assert detail["trace"]["complete"] is False
