from __future__ import annotations

import importlib
from typing import Any


def _modules() -> tuple[Any, Any]:
    return (
        importlib.import_module("modules.memory.vector_client"),
        importlib.import_module("modules.memory.vector_store"),
    )


def _store(client: Any) -> Any:
    vector_client, _vector_store = _modules()
    store = object.__new__(vector_client.QdrantVectorStore)
    store.client = client
    store.collection_name = "memories"
    store._docs = {}
    store._collection_exists = lambda: True
    return store


def test_qdrant_update_metadata_uses_set_payload_and_updates_filter_fields() -> None:
    calls: list[dict[str, Any]] = []

    class _Client:
        def set_payload(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    store = _store(_Client())
    store._point_id = lambda doc_id: f"point:{doc_id}"
    metadata = {
        "scope": "workspace",
        "workspace_id": "ws-1",
        "layer": "profile",
        "quality_score": 0.75,
        "recall_feedback": {"summary": {"helpful": 4}},
    }

    store.update_metadata("doc-1", metadata)

    assert calls == [{
        "collection_name": "memories",
        "payload": {
            "metadata": metadata,
            "timestamp": None,
            "type": None,
            "layer": "profile",
            "scope": "workspace",
            "session_id": None,
            "workspace_id": "ws-1",
            "quality_score": 0.75,
            "confidence": None,
            "source": None,
        },
        "points": ["point:doc-1"],
        "wait": True,
    }]


def test_qdrant_add_document_waits_for_upsert_acknowledgement() -> None:
    _vector_client, vector_store = _modules()
    calls: list[dict[str, Any]] = []

    class _Client:
        def upsert(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    store = _store(_Client())
    store._embedding_service = type(
        "EmbeddingService",
        (),
        {"embed": staticmethod(lambda _text: __import__("numpy").array([1.0, 0.0]))},
    )()
    store._ensure_collection = lambda _dimension: None
    store._point_id = lambda doc_id: f"point:{doc_id}"
    store._point_struct = lambda **kwargs: kwargs

    store.add_document(vector_store.Document(id="doc-1", text="tea", metadata={}))

    assert len(calls) == 1
    assert calls[0]["collection_name"] == "memories"
    assert calls[0]["wait"] is True
    point = calls[0]["points"][0]
    assert point["id"] == "point:doc-1"
    assert point["vector"] == [1.0, 0.0]
    assert point["payload"]["doc_id"] == "doc-1"
    assert point["payload"]["text"] == "tea"


def test_qdrant_delete_document_waits_for_acknowledgement() -> None:
    calls: list[dict[str, Any]] = []

    class _Client:
        def delete(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    store = _store(_Client())
    store._point_id = lambda doc_id: f"point:{doc_id}"
    store._point_ids_list = lambda **kwargs: kwargs

    store.delete_document("doc-1")

    assert calls == [{
        "collection_name": "memories",
        "points_selector": {"points": ["point:doc-1"]},
        "wait": True,
    }]


def test_qdrant_update_metadata_falls_back_to_overwrite_payload() -> None:
    calls: list[dict[str, Any]] = []

    class _Point:
        def __init__(self) -> None:
            self.id = "point:doc-1"
            self.payload = {
                "doc_id": "doc-1",
                "text": "tea preference",
                "metadata": {"scope": "workspace", "layer": "semantic"},
            }

    class _Client:
        def retrieve(self, **_kwargs: Any) -> list[_Point]:
            return [_Point()]

        def overwrite_payload(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    store = _store(_Client())
    store._point_id = lambda doc_id: f"point:{doc_id}"
    metadata = {"scope": "workspace", "layer": "profile", "quality_score": 0.8}

    store.update_metadata("doc-1", metadata)

    assert calls[0]["collection_name"] == "memories"
    assert calls[0]["points"] == ["point:doc-1"]
    assert calls[0]["payload"]["doc_id"] == "doc-1"
    assert calls[0]["payload"]["text"] == "tea preference"
    assert calls[0]["payload"]["metadata"] == metadata
    assert calls[0]["payload"]["layer"] == "profile"
    assert calls[0]["wait"] is True


def test_qdrant_rerank_applies_recall_feedback_quality() -> None:
    _vector_client, vector_store = _modules()
    store = _store(object())
    store._reranker = None
    store._reranker_candidate_count = 32
    favored = vector_store.Document(
        id="favored",
        text="tea preference",
        metadata={
            "quality_score": 0.6,
            "recall_feedback": {"summary": {"helpful": 8}},
        },
    )
    baseline = vector_store.Document(
        id="baseline",
        text="tea preference",
        metadata={"quality_score": 0.6},
    )
    store.search = lambda **_kwargs: [(baseline, 0.8), (favored, 0.8)]
    store._doc_matches_filters = lambda *_args, **_kwargs: True

    results = store.search_with_rerank(
        "tea",
        top_k=2,
        recency_weight=0.0,
        quality_weight=0.5,
    )

    assert [doc.id for doc, _score in results] == ["favored", "baseline"]
    components = store.get_score_components("tea", "favored", 0.0, 0.5)
    assert components is not None
    assert components["quality"] == 0.8


def test_qdrant_manifest_scroll_uses_minimal_payload_and_large_pages() -> None:
    calls: list[dict[str, Any]] = []

    class _Point:
        def __init__(self, point_id: str, doc_id: str, generation: str) -> None:
            self.id = point_id
            self.payload = {"doc_id": doc_id, "index_generation": generation}

    pages = [
        ([_Point("point:a", "a", "active"), _Point("point:b", "b", "old")], "next"),
        ([_Point("point:c", "c", "active")], None),
    ]

    class _Client:
        def scroll(self, **kwargs: Any):
            calls.append(kwargs)
            return pages[len(calls) - 1]

    store = _store(_Client())

    generation_ids, all_ids = store.get_index_manifest("active")

    assert generation_ids == {"a", "c"}
    assert all_ids == {"a", "b", "c"}
    assert all(call["with_payload"] == ["doc_id", "index_generation"] for call in calls)
    assert all(call["with_vectors"] is False for call in calls)
    assert all(call["limit"] == 1024 for call in calls)
    assert calls[0]["offset"] is None
    assert calls[1]["offset"] == "next"


def test_qdrant_loopback_http_skips_proxy_and_certificate_store_only_locally() -> None:
    vector_client, _vector_store = _modules()

    assert vector_client._loopback_http_client_options("http://127.0.0.1:6333") == {
        "trust_env": False,
        "verify": False,
    }
    assert vector_client._loopback_http_client_options("http://localhost:6333") == {
        "trust_env": False,
        "verify": False,
    }
    assert vector_client._loopback_http_client_options("http://[::1]:6333") == {
        "trust_env": False,
        "verify": False,
    }
    assert vector_client._loopback_http_client_options("https://localhost:6333") == {}
    assert vector_client._loopback_http_client_options("http://qdrant.internal:6333") == {}
