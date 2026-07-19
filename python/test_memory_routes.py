from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.memory.backend import MemoryBackendStatus
from modules.memory.routes import MemoryState, create_memory_router
from modules.memory.schema import MemorySearchFilters
from modules.memory.vector_store import Document


class _FakeMemoryStore:
    backend_name = "fake"

    def __init__(self, docs: list[Document]) -> None:
        self.docs = docs
        self.last_filters: MemorySearchFilters | None = None

    def add_document(self, doc: Document) -> None:
        self.delete_document(doc.id)
        self.docs.append(doc)

    def add_metadata_document(self, doc: Document) -> None:
        self.add_document(doc)

    def delete_document(self, doc_id: str) -> None:
        self.docs = [doc for doc in self.docs if doc.id != doc_id]

    def list_documents(self) -> list[Document]:
        return list(self.docs)

    def rebuild_index(self) -> dict[str, Any]:
        return {
            "status": "rebuilt",
            "backend": self.backend_name,
            "document_count": len(self.docs),
            "indexed_count": len(self.docs),
            "skipped_count": 0,
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: MemorySearchFilters | None = None,
    ) -> list[tuple[Document, float]]:
        self.last_filters = filters
        return []

    def search_with_rerank(self, *args: Any, **kwargs: Any) -> list[tuple[Document, float]]:
        self.last_filters = kwargs.get("filters")
        return []

    def get_status(self) -> MemoryBackendStatus:
        return MemoryBackendStatus(backend="fake", healthy=True, message="ok", document_count=len(self.docs))


def _build_client_with_store(active_workspace_id: str | None = None) -> tuple[TestClient, _FakeMemoryStore]:
    store = _FakeMemoryStore([
        Document(id="workspace-default", text="default workspace", metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic"}),
        Document(id="workspace-other", text="other workspace", metadata={"scope": "workspace", "workspace_id": "other", "layer": "semantic"}),
        Document(id="workspace-unscoped", text="unscoped workspace", metadata={"scope": "workspace", "layer": "semantic"}),
        Document(id="global-doc", text="global", metadata={"scope": "global", "layer": "semantic"}),
        Document(id="session-doc", text="session", metadata={"scope": "session", "session_id": "s1", "layer": "working"}),
    ])
    app = FastAPI()
    app.include_router(
        create_memory_router(
            MemoryState(store=store),
            get_active_workspace_id=(lambda: active_workspace_id) if active_workspace_id is not None else None,
        )
    )
    return TestClient(app), store


def _build_client() -> TestClient:
    client, _store = _build_client_with_store()
    return client


def test_memory_docs_defaults_to_workspace_scope_instead_of_all_docs():
    client = _build_client()

    response = client.get("/memory/docs")

    assert response.status_code == 200
    assert [doc["id"] for doc in response.json()["docs"]] == ["workspace-unscoped"]


def test_memory_docs_filters_workspace():
    client = _build_client()

    response = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "default"})

    assert response.status_code == 200
    assert [doc["id"] for doc in response.json()["docs"]] == ["workspace-default", "workspace-unscoped"]


def test_memory_docs_requires_valid_scope_and_layer():
    client = _build_client()

    invalid_scope = client.get("/memory/docs", params={"scope": "everything"})
    invalid_layer = client.get("/memory/docs", params={"layer": "all"})

    assert invalid_scope.status_code == 400
    assert invalid_layer.status_code == 400


def test_memory_docs_filters_session_scope_by_session_id():
    client = _build_client()

    response = client.get("/memory/docs", params={"scope": "session", "session_id": "s1"})

    assert response.status_code == 200
    assert [doc["id"] for doc in response.json()["docs"]] == ["session-doc"]


def test_memory_docs_default_to_active_workspace_when_provider_exists():
    client, _store = _build_client_with_store(active_workspace_id="default")

    response = client.get("/memory/docs")

    assert response.status_code == 200
    assert [doc["id"] for doc in response.json()["docs"]] == ["workspace-default", "workspace-unscoped"]


def test_memory_docs_reject_cross_workspace_request():
    client, _store = _build_client_with_store(active_workspace_id="default")

    response = client.get("/memory/docs", params={"scope": "workspace", "workspace_id": "other"})

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "workspace_mismatch"


def test_memory_add_defaults_workspace_scope_to_active_workspace():
    client, store = _build_client_with_store(active_workspace_id="default")

    response = client.post(
        "/memory/docs",
        json={"id": "new-doc", "text": "new memory", "scope": "workspace"},
    )

    assert response.status_code == 200
    created = next(doc for doc in store.docs if doc.id == "new-doc")
    assert created.metadata["workspace_id"] == "default"


def test_memory_update_and_delete_reject_cross_workspace_doc():
    client, _store = _build_client_with_store(active_workspace_id="default")

    update = client.put("/memory/docs/workspace-other", json={"text": "mutated"})
    delete = client.delete("/memory/docs/workspace-other")

    assert update.status_code == 403
    assert delete.status_code == 403
    assert update.json()["detail"]["error"] == "workspace_mismatch"
    assert delete.json()["detail"]["error"] == "workspace_mismatch"


def test_memory_batch_delete_rejects_cross_workspace_doc_without_partial_delete():
    client, store = _build_client_with_store(active_workspace_id="default")

    response = client.post("/memory/docs/batch-delete", json={"ids": ["workspace-default", "workspace-other"]})

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "workspace_mismatch"
    assert {doc.id for doc in store.docs} >= {"workspace-default", "workspace-other"}


def test_memory_batch_delete_permanently_removes_documents_without_route_shadowing():
    client, store = _build_client_with_store(active_workspace_id="default")

    response = client.post("/memory/docs/batch-delete", json={"ids": ["workspace-default", "workspace-unscoped"]})

    assert response.status_code == 200
    assert response.json() == {
        "status": "deleted",
        "ids": ["workspace-default", "workspace-unscoped"],
        "deleted_count": 2,
        "storage": None,
    }
    assert not {"workspace-default", "workspace-unscoped"} & {doc.id for doc in store.docs}


def test_memory_rag_query_rejects_cross_workspace_and_defaults_active_workspace():
    client, store = _build_client_with_store(active_workspace_id="default")

    rejected = client.post("/memory/rag/query", json={"query": "hello", "workspace_id": "other"})
    allowed = client.post("/memory/rag/query", json={"query": "hello"})

    assert rejected.status_code == 403
    assert rejected.json()["detail"]["error"] == "workspace_mismatch"
    assert allowed.status_code == 200
    assert store.last_filters is not None
    assert store.last_filters.scope == "workspace"
    assert store.last_filters.workspace_id == "default"


def test_memory_index_rebuild_delegates_to_store_and_reports_status():
    client, _store = _build_client_with_store()

    response = client.post("/memory/index/rebuild")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "rebuilt"
    assert data["backend"] == "fake"
    assert data["indexed_count"] == 5
    assert data["skipped_count"] == 0
    assert data["index_status"] == "idle"


def test_memory_maintenance_previews_and_permanently_deletes_without_touching_protected_memories():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=45)).isoformat()
    recent = (now - timedelta(days=2)).isoformat()
    store = _FakeMemoryStore([
        Document(id="stale-working", text="finish temporary task", metadata={"scope": "workspace", "workspace_id": "default", "layer": "working", "quality_score": 0.8, "importance": 0.5, "timestamp": old}),
        Document(id="low-quality", text="uncertain old fact", metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic", "quality_score": 0.3, "importance": 0.4, "timestamp": old}),
        Document(id="protected-relationship", text="user boundary", metadata={"scope": "workspace", "workspace_id": "default", "layer": "relationship", "quality_score": 0.2, "importance": 0.4, "timestamp": old}),
        Document(id="duplicate-keep", text="User likes tea", metadata={"scope": "workspace", "workspace_id": "default", "layer": "profile", "quality_score": 0.9, "importance": 0.9, "timestamp": recent}),
        Document(id="duplicate-old", text=" user   likes TEA ", metadata={"scope": "workspace", "workspace_id": "default", "layer": "profile", "quality_score": 0.7, "importance": 0.7, "timestamp": old}),
        Document(id="other-workspace", text="other private memory", metadata={"scope": "workspace", "workspace_id": "other", "layer": "working", "quality_score": 0.1, "timestamp": old}),
    ])
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store), get_active_workspace_id=lambda: "default"))
    client = TestClient(app)
    policy = {
        "scope": "workspace",
        "workspace_id": "default",
        "working_retention_days": 14,
        "low_quality_threshold": 0.55,
    }

    preview = client.post("/memory/maintenance/preview", json=policy)

    assert preview.status_code == 200
    data = preview.json()
    assert data["summary"] == {
        "scanned_count": 5,
        "active_count": 5,
        "delete_count": 3,
    }
    actions = {item["id"]: item["action"] for item in data["candidates"]}
    assert actions == {
        "duplicate-old": "delete",
        "low-quality": "delete",
        "stale-working": "delete",
    }
    assert "protected-relationship" not in actions
    assert "duplicate-keep" not in actions
    assert "other-workspace" not in actions

    applied = client.post(
        "/memory/maintenance/apply",
        json={**policy, "confirmation": "PERMANENT_DELETE", "preview_token": data["preview_token"]},
    )

    assert applied.status_code == 200
    assert applied.json()["changed_count"] == 3
    assert {doc.id for doc in store.docs} == {"protected-relationship", "duplicate-keep", "other-workspace"}


def test_memory_maintenance_requires_explicit_confirmation_before_purge():
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    store = _FakeMemoryStore([
        Document(id="stale-working", text="old working memory", metadata={"scope": "workspace", "workspace_id": "default", "layer": "working", "timestamp": old}),
    ])
    app = FastAPI()
    app.include_router(create_memory_router(MemoryState(store=store), get_active_workspace_id=lambda: "default"))
    client = TestClient(app)
    payload = {
        "scope": "workspace",
        "workspace_id": "default",
        "working_retention_days": 14,
    }

    rejected = client.post("/memory/maintenance/apply", json=payload)
    preview = client.post(
        "/memory/maintenance/preview",
        json=payload,
    )
    accepted = client.post(
        "/memory/maintenance/apply",
        json={
            **payload,
            "confirmation": "PERMANENT_DELETE",
            "preview_token": preview.json()["preview_token"],
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"]["error"] == "memory_purge_confirmation_required"
    assert accepted.status_code == 200
    assert accepted.json()["changed_ids"] == ["stale-working"]
    assert store.docs == []
