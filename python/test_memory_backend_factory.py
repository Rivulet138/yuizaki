from __future__ import annotations

from typing import Any

import numpy as np

from modules.core.config import MemoryConfig
from modules.memory import vector_store as vector_store_module
from modules.memory.backend_factory import create_memory_backend
from modules.memory.vector_store import Document


class _FakeEmbeddingService:
    load_count = 0

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.dimension = 4
        _FakeEmbeddingService.load_count += 1

    def embed(self, text: str) -> np.ndarray:
        return np.array([float(len(text)), 1.0, 0.5, 0.25], dtype=np.float32)


class _RoleAwareEmbeddingService:
    dimension = 4

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def embed(self, text: str) -> np.ndarray:
        self.calls.append(("fallback", text))
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def embed_document(self, text: str) -> np.ndarray:
        self.calls.append(("document", text))
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        self.calls.append(("query", text))
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


def test_create_memory_backend_does_not_load_embedding_model_until_vector_use(monkeypatch: Any) -> None:
    _FakeEmbeddingService.load_count = 0
    monkeypatch.setattr(vector_store_module, "EmbeddingService", _FakeEmbeddingService)

    store = create_memory_backend(MemoryConfig(backend="inmemory", embedding_model="test/model"))

    assert _FakeEmbeddingService.load_count == 0

    status = store.get_status()

    assert status.healthy is True
    assert status.metadata == {"embedding_model_loaded": False}
    assert _FakeEmbeddingService.load_count == 0

    store.add_metadata_document(Document(id="meta-1", text="status snapshot", metadata={"layer": "profile"}))

    assert _FakeEmbeddingService.load_count == 0
    assert [doc.id for doc in store.list_documents()] == ["meta-1"]
    assert store.search("status") == []

    store.add_document(Document(id="doc-1", text="hello", metadata={}))

    assert _FakeEmbeddingService.load_count == 1
    assert store.get_status().metadata == {
        "embedding_model_loaded": True,
        "embedding_dimension": 4,
    }


def test_inmemory_backend_uses_role_aware_embeddings_for_documents_and_queries() -> None:
    embedding_service = _RoleAwareEmbeddingService()
    store = vector_store_module.VectorStore(embedding_service=embedding_service)

    store.add_document(Document(id="doc-1", text="memory document", metadata={}))
    results = store.search("memory query")

    assert [doc.id for doc, _score in results] == ["doc-1"]
    assert embedding_service.calls == [
        ("document", "memory document"),
        ("query", "memory query"),
    ]


def test_inmemory_rebuild_rewrites_vectors_for_all_authoritative_docs() -> None:
    embedding_service = _RoleAwareEmbeddingService()
    store = vector_store_module.VectorStore(embedding_service=embedding_service)

    store.add_document(Document(id="doc-1", text="active memory", metadata={}))
    store.add_document(Document(id="doc-2", text="second memory", metadata={}))
    embedding_service.calls.clear()

    result = store.rebuild_index()

    assert result["status"] == "rebuilt"
    assert result["indexed_count"] == 2
    assert result["skipped_count"] == 0
    assert embedding_service.calls == [("document", "active memory"), ("document", "second memory")]


def test_index_failure_does_not_lose_sqlite_authority(tmp_path: Any) -> None:
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.sqlite_store import SQLiteMemoryStore

    class _FailingIndex(vector_store_module.VectorStore):
        backend_name = "failing-index"

        def add_document(self, doc: Document) -> None:
            raise RuntimeError("index unavailable")

        def search(self, *args: Any, **kwargs: Any):
            raise RuntimeError("index unavailable")

    embedding_service = _RoleAwareEmbeddingService()
    authority = SQLiteMemoryStore(tmp_path / "authority.db", embedding_service=embedding_service)
    store = IndexedMemoryBackend(authority=authority, index=_FailingIndex(embedding_service=embedding_service))

    store.add_document(Document(id="durable-1", text="durable memory", metadata={}))

    assert [doc.id for doc in authority.list_documents()] == ["durable-1"]
    assert [doc.id for doc, _score in store.search("durable")] == ["durable-1"]
    status = store.get_status()
    assert status.metadata["index_dirty"] is True
    assert status.metadata["index_healthy"] is False


def test_dirty_index_cannot_recall_a_soft_forgotten_authority_document(tmp_path: Any) -> None:
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.sqlite_store import SQLiteMemoryStore

    class _FailingUpdateIndex(vector_store_module.VectorStore):
        backend_name = "failing-update-index"
        fail_writes = False

        def add_document(self, doc: Document) -> None:
            if self.fail_writes:
                raise RuntimeError("index update unavailable")
            super().add_document(doc)

    embedding_service = _RoleAwareEmbeddingService()
    authority = SQLiteMemoryStore(tmp_path / "authority.db", embedding_service=embedding_service)
    index = _FailingUpdateIndex(embedding_service=embedding_service)
    store = IndexedMemoryBackend(authority=authority, index=index)
    store.add_document(Document(id="memory-1", text="private memory", metadata={}))

    index.fail_writes = True
    store.add_document(Document(
        id="memory-1",
        text="private memory",
        metadata={"soft_forgotten": True},
    ))

    assert store.search("private") == []
    assert store.search_with_rerank("private") == []
    assert store.get_status().metadata["index_dirty"] is True


def test_stale_index_ids_fall_back_to_sqlite_authority(tmp_path: Any) -> None:
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.sqlite_store import SQLiteMemoryStore

    class _StaleIndex(vector_store_module.VectorStore):
        backend_name = "stale-index"

        def search(self, *args: Any, **kwargs: Any):
            return [(Document(id="removed-1", text="stale memory", metadata={}), 0.99)]

        def search_with_rerank(self, *args: Any, **kwargs: Any):
            return [(Document(id="removed-1", text="stale memory", metadata={}), 0.99)]

    embedding_service = _RoleAwareEmbeddingService()
    authority = SQLiteMemoryStore(tmp_path / "authority.db", embedding_service=embedding_service)
    authority.add_document(Document(id="current-1", text="current durable memory", metadata={}))
    store = IndexedMemoryBackend(authority=authority, index=_StaleIndex(embedding_service=embedding_service))

    assert [doc.id for doc, _score in store.search("current")] == ["current-1"]
    assert [doc.id for doc, _score in store.search_with_rerank("current")] == ["current-1"]
    status = store.get_status()
    assert status.metadata["index_dirty"] is True
    assert status.metadata["index_healthy"] is False


def test_rebuild_clears_dirty_index_state(tmp_path: Any) -> None:
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.sqlite_store import SQLiteMemoryStore

    class _RecoverableIndex(vector_store_module.VectorStore):
        backend_name = "recoverable-index"
        available = False

        def add_document(self, doc: Document) -> None:
            if not self.available:
                raise RuntimeError("index unavailable")
            super().add_document(doc)

    embedding_service = _RoleAwareEmbeddingService()
    authority = SQLiteMemoryStore(tmp_path / "authority.db", embedding_service=embedding_service)
    index = _RecoverableIndex(embedding_service=embedding_service)
    store = IndexedMemoryBackend(authority=authority, index=index)

    store.add_document(Document(id="durable-1", text="durable memory", metadata={}))
    assert store.get_status().metadata["index_dirty"] is True

    index.available = True
    result = store.rebuild_index()

    assert result["indexed_count"] == 1
    assert store.get_status().metadata["index_dirty"] is False
    assert store.get_status().metadata["index_healthy"] is True


def test_index_count_drift_is_detected_after_backend_restart(tmp_path: Any) -> None:
    from modules.memory.indexed_backend import IndexedMemoryBackend
    from modules.memory.sqlite_store import SQLiteMemoryStore

    embedding_service = _RoleAwareEmbeddingService()
    authority = SQLiteMemoryStore(tmp_path / "authority.db", embedding_service=embedding_service)
    authority.add_document(Document(id="durable-1", text="durable memory", metadata={}))

    restarted_store = IndexedMemoryBackend(
        authority=authority,
        index=vector_store_module.VectorStore(embedding_service=embedding_service),
    )
    status = restarted_store.get_status()

    assert status.metadata["expected_index_count"] == 1
    assert status.metadata["actual_index_count"] == 0
    assert status.metadata["index_dirty"] is True
    assert status.metadata["index_healthy"] is False


def test_qdrant_backend_status_does_not_load_embedding_model_before_collection_use(monkeypatch: Any, tmp_path: Any) -> None:
    _FakeEmbeddingService.load_count = 0
    monkeypatch.setattr(vector_store_module, "EmbeddingService", _FakeEmbeddingService)

    class _FakeCollections:
        collections: list[Any] = []

    class _FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None, **_kwargs: Any) -> None:
            self.url = url
            self.api_key = api_key

        def get_collections(self) -> _FakeCollections:
            return _FakeCollections()

    class _FakeDistance:
        COSINE = "Cosine"

    class _FakeVectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class _FakePointIdsList:
        pass

    class _FakePointStruct:
        pass

    class _FakeFilter:
        pass

    class _FakeFieldCondition:
        pass

    class _FakeMatchValue:
        pass

    class _FakeMatchAny:
        pass

    def _fake_import_module(name: str) -> Any:
        if name == "qdrant_client":
            return type("QdrantClientModule", (), {"QdrantClient": _FakeQdrantClient})
        if name == "qdrant_client.models":
            return type(
                "QdrantModelsModule",
                (),
                {
                    "Distance": _FakeDistance,
                    "VectorParams": _FakeVectorParams,
                    "PointIdsList": _FakePointIdsList,
                    "PointStruct": _FakePointStruct,
                    "Filter": _FakeFilter,
                    "FieldCondition": _FakeFieldCondition,
                    "MatchValue": _FakeMatchValue,
                    "MatchAny": _FakeMatchAny,
                },
            )
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("modules.memory.vector_client.importlib.import_module", _fake_import_module)

    store = create_memory_backend(MemoryConfig(
        backend="qdrant",
        qdrant_url="http://127.0.0.1:6333",
        sqlite_path=str(tmp_path / "memory.db"),
        embedding_model="test/model",
    ))

    assert _FakeEmbeddingService.load_count == 0
    status = store.get_status()
    assert status.healthy is True
    assert status.backend == "sqlite+qdrant"
    assert status.metadata == {
        "authority": "sqlite",
        "index": "qdrant",
        "index_healthy": True,
        "index_dirty": False,
        "expected_index_count": 0,
        "actual_index_count": 0,
        "index_metadata": {
            "collection": "memories",
            "initialized": False,
            "url": "http://127.0.0.1:6333",
            "api_key_configured": False,
        },
    }
    assert _FakeEmbeddingService.load_count == 0


def test_qdrant_backend_requires_configured_url() -> None:
    try:
        create_memory_backend(MemoryConfig(backend="qdrant", qdrant_url=""))
    except ValueError as exc:
        assert str(exc) == "qdrant_url_required"
    else:
        raise AssertionError("expected qdrant_url_required")


def test_qdrant_backend_uses_role_aware_embeddings_for_documents_and_queries(monkeypatch: Any) -> None:
    embedding_service = _RoleAwareEmbeddingService()
    captured: dict[str, Any] = {"vectors": [], "queries": []}

    class _FakeCollections:
        collections: list[Any] = []

    class _FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None, **_kwargs: Any) -> None:
            self.url = url
            self.api_key = api_key

        def get_collections(self) -> _FakeCollections:
            return _FakeCollections()

        def create_collection(self, **kwargs: Any) -> None:
            captured["collection"] = kwargs

        def upsert(self, collection_name: str, points: list[Any]) -> None:
            captured["vectors"].append((collection_name, points[0].vector))

        def query_points(self, **kwargs: Any) -> Any:
            captured["queries"].append(kwargs["query"])
            return type("Result", (), {"points": []})()

    class _FakeDistance:
        COSINE = "Cosine"

    class _FakePointStruct:
        def __init__(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    class _FakeVectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class _FakePointIdsList:
        pass

    class _FakeFilter:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeFieldCondition:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeMatchValue:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeMatchAny:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    def _fake_import_module(name: str) -> Any:
        if name == "qdrant_client":
            return type("QdrantClientModule", (), {"QdrantClient": _FakeQdrantClient})
        if name == "qdrant_client.models":
            return type(
                "QdrantModelsModule",
                (),
                {
                    "Distance": _FakeDistance,
                    "VectorParams": _FakeVectorParams,
                    "PointIdsList": _FakePointIdsList,
                    "PointStruct": _FakePointStruct,
                    "Filter": _FakeFilter,
                    "FieldCondition": _FakeFieldCondition,
                    "MatchValue": _FakeMatchValue,
                    "MatchAny": _FakeMatchAny,
                },
            )
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("modules.memory.vector_client.importlib.import_module", _fake_import_module)

    from modules.memory.vector_client import QdrantVectorStore

    store = QdrantVectorStore("http://127.0.0.1:6333", embedding_service=embedding_service)
    store.add_document(Document(id="doc-1", text="memory document", metadata={}))
    store._collection_ready = True
    store.search("memory query")

    assert embedding_service.calls == [
        ("document", "memory document"),
        ("query", "memory query"),
    ]
    assert captured["vectors"][0][0] == "memories"
    assert captured["vectors"][0][1] == [1.0, 0.0, 0.0, 0.0]
    assert captured["queries"] == [[1.0, 0.0, 0.0, 0.0]]


def test_qdrant_rebuild_deletes_collection_and_reindexes_authoritative_docs(monkeypatch: Any) -> None:
    embedding_service = _RoleAwareEmbeddingService()
    captured: dict[str, Any] = {"created": 0, "deleted": 0, "vectors": [], "payloads": []}

    class _FakeCollection:
        name = "memories"

    class _FakeCollections:
        collections: list[Any] = [_FakeCollection()]

    class _FakePoint:
        def __init__(self, id: str, payload: dict[str, Any]) -> None:
            self.id = id
            self.payload = payload

    class _FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None, **_kwargs: Any) -> None:
            self.url = url
            self.api_key = api_key
            self.collection_exists = True
            self.points = [
                _FakePoint("11111111-1111-4111-8111-111111111111", {"doc_id": "doc-1", "text": "active memory", "metadata": {}}),
                _FakePoint("22222222-2222-4222-8222-222222222222", {"doc_id": "doc-2", "text": "second memory", "metadata": {}}),
            ]

        def get_collections(self) -> _FakeCollections:
            collections = [_FakeCollection()] if self.collection_exists else []
            return type("Collections", (), {"collections": collections})()

        def scroll(self, **_kwargs: Any) -> tuple[list[Any], None]:
            return self.points, None

        def delete_collection(self, collection_name: str) -> None:
            captured["deleted"] += 1
            captured["deleted_collection"] = collection_name
            self.collection_exists = False

        def create_collection(self, **kwargs: Any) -> None:
            captured["created"] += 1
            captured["created_collection"] = kwargs
            self.collection_exists = True

        def upsert(self, collection_name: str, points: list[Any]) -> None:
            captured["vectors"].append((collection_name, points[0].id, points[0].vector))
            captured["payloads"].append(points[0].payload)

        def get_collection(self, _collection_name: str) -> Any:
            return type("CollectionInfo", (), {"points_count": len(captured["vectors"])})()

        def count(self, **_kwargs: Any) -> Any:
            return type("CountResult", (), {"count": len(captured["vectors"])})()

    class _FakeDistance:
        COSINE = "Cosine"

    class _FakePointStruct:
        def __init__(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    class _FakeVectorParams:
        def __init__(self, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    class _FakePointIdsList:
        pass

    class _FakeFilter:
        pass

    class _FakeFieldCondition:
        pass

    class _FakeMatchValue:
        pass

    class _FakeMatchAny:
        pass

    def _fake_import_module(name: str) -> Any:
        if name == "qdrant_client":
            return type("QdrantClientModule", (), {"QdrantClient": _FakeQdrantClient})
        if name == "qdrant_client.models":
            return type(
                "QdrantModelsModule",
                (),
                {
                    "Distance": _FakeDistance,
                    "VectorParams": _FakeVectorParams,
                    "PointIdsList": _FakePointIdsList,
                    "PointStruct": _FakePointStruct,
                    "Filter": _FakeFilter,
                    "FieldCondition": _FakeFieldCondition,
                    "MatchValue": _FakeMatchValue,
                    "MatchAny": _FakeMatchAny,
                },
            )
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("modules.memory.vector_client.importlib.import_module", _fake_import_module)

    from modules.memory.vector_client import QdrantVectorStore

    store = QdrantVectorStore("http://127.0.0.1:6333", embedding_service=embedding_service)
    result = store.rebuild_index()

    assert result["collection_deleted"] is True
    assert result["indexed_count"] == 2
    assert result["skipped_count"] == 0
    assert captured["deleted"] == 1
    assert captured["created"] == 1
    assert captured["vectors"][0][0] == "memories"
    assert captured["vectors"][0][2] == [1.0, 0.0, 0.0, 0.0]
    assert all("state" not in payload and "state" not in payload["metadata"] for payload in captured["payloads"])
    assert embedding_service.calls == [("document", "active memory"), ("document", "second memory")]
    status = store.get_status()
    assert status.document_count == 2
    assert status.metadata["exact_points_count"] == 2


def test_qdrant_backend_passes_full_url_and_api_key(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _FakeCollections:
        collections: list[Any] = []

    class _FakeQdrantClient:
        def __init__(self, url: str | None = None, api_key: str | None = None, **kwargs: Any) -> None:
            captured["init"] = {"url": url, "api_key": api_key, "kwargs": kwargs}

        def get_collections(self) -> _FakeCollections:
            return _FakeCollections()

    class _FakeDistance:
        COSINE = "Cosine"

    class _FakeVectorParams:
        pass

    class _FakePointIdsList:
        pass

    class _FakePointStruct:
        pass

    class _FakeFilter:
        pass

    class _FakeFieldCondition:
        pass

    class _FakeMatchValue:
        pass

    class _FakeMatchAny:
        pass

    def _fake_import_module(name: str) -> Any:
        if name == "qdrant_client":
            return type("QdrantClientModule", (), {"QdrantClient": _FakeQdrantClient})
        if name == "qdrant_client.models":
            return type(
                "QdrantModelsModule",
                (),
                {
                    "Distance": _FakeDistance,
                    "VectorParams": _FakeVectorParams,
                    "PointIdsList": _FakePointIdsList,
                    "PointStruct": _FakePointStruct,
                    "Filter": _FakeFilter,
                    "FieldCondition": _FakeFieldCondition,
                    "MatchValue": _FakeMatchValue,
                    "MatchAny": _FakeMatchAny,
                },
            )
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr("modules.memory.vector_client.importlib.import_module", _fake_import_module)

    from modules.memory.vector_client import QdrantVectorStore

    store = QdrantVectorStore("https://qdrant.example.com/api/v1", qdrant_api_key="qk-test", timeout=12.5)

    assert store.get_status().healthy is True
    assert captured["init"] == {
        "url": "https://qdrant.example.com/api/v1",
        "api_key": "qk-test",
        "kwargs": {"timeout": 12.5},
    }


def test_qdrant_backend_accepts_non_uuid_document_ids_with_real_local_client() -> None:
    from modules.memory.vector_client import QdrantVectorStore
    from modules.memory.schema import MemorySearchFilters

    embedding_service = _RoleAwareEmbeddingService()
    store = QdrantVectorStore(":memory:", collection_name="memory_test_non_uuid_ids", embedding_service=embedding_service)

    store.add_document(Document(id="doc-1", text="memory document", metadata={"scope": "workspace", "layer": "semantic"}))

    results = store.search("memory query")

    assert [doc.id for doc, _score in results] == ["doc-1"]
    assert store.list_documents()[0].id == "doc-1"

    store.add_document(Document(id="workspace-a", text="workspace a memory", metadata={"scope": "workspace", "workspace_id": "ws-a", "layer": "semantic"}))
    store.add_document(Document(id="workspace-b", text="workspace b memory", metadata={"scope": "workspace", "workspace_id": "ws-b", "layer": "semantic"}))
    store.add_document(Document(id="session-a", text="session a memory", metadata={"scope": "session", "session_id": "s-a", "layer": "working"}))

    workspace_results = store.search(
        "memory query",
        top_k=10,
        filters=MemorySearchFilters(scope="workspace", workspace_id="ws-a", layers=["semantic"]),
    )
    workspace_ids = {doc.id for doc, _score in workspace_results}
    assert {"doc-1", "workspace-a"} <= workspace_ids
    assert "workspace-b" not in workspace_ids
    assert "session-a" not in workspace_ids

    session_without_id = store.search(
        "memory query",
        top_k=10,
        filters=MemorySearchFilters(scope="session", layers=["working"]),
    )
    assert session_without_id == []
