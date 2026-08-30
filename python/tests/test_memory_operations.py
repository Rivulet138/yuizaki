from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.memory.operations import MemoryOperationLog, new_operation
from modules.memory.routes import MemoryState, create_memory_pipeline_router, create_memory_router
from modules.memory.schema import MemorySearchFilters
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_store import Document, VectorStore, is_memory_recallable


class _Embedding:
    dimension = 4

    def embed(self, text: str) -> np.ndarray:
        return np.array([float(len(text)), 1.0, 0.0, 0.0], dtype=np.float32)


def test_operation_log_is_bounded_and_newest_first() -> None:
    log = MemoryOperationLog(max_operations=100)
    for index in range(105):
        log.append(new_operation(operation="create", document_id=f"doc-{index}"))

    operations = log.list(limit=200)
    assert len(operations) == 100
    assert operations[0]["document_id"] == "doc-104"


def test_operation_log_normalizes_scope_ids() -> None:
    log = MemoryOperationLog()
    log.append(
        new_operation(
            operation="create",
            document_id="doc-1",
            workspace_id=" ws-1 ",
            session_id=" session-1 ",
        )
    )

    operations = log.list(workspace_id="ws-1", session_id="session-1")
    assert len(operations) == 1
    assert operations[0]["workspace_id"] == "ws-1"
    assert operations[0]["session_id"] == "session-1"


def test_sqlite_operation_ledger_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    store = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    document = Document(
        id="doc-1",
        text="用户喜欢安静的通知",
        metadata={"scope": "workspace", "workspace_id": "ws-1", "layer": "profile"},
    )
    store.add_document(document)
    operation = new_operation(
        operation="create",
        document_id=document.id,
        scope="workspace",
        workspace_id="ws-1",
        reason="manual_capture",
        evidence={"source_id": "turn-1"},
        after_revision=1,
    )
    store.record_operation(operation)

    restarted = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    operations = restarted.list_operations(document_id=document.id, workspace_id="ws-1")
    assert operations[0]["operation_id"] == operation.operation_id
    assert operations[0]["reason"] == "manual_capture"
    assert operations[0]["evidence"] == {"source_id": "turn-1"}


def test_sqlite_operation_ledger_creates_history_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    SQLiteMemoryStore(db_path, embedding_service=_Embedding())

    with sqlite3.connect(db_path) as connection:
        indexes = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(memory_operations)")
        }

    assert indexes == {
        "idx_memory_operations_document_at",
        "idx_memory_operations_scope_at",
        "sqlite_autoindex_memory_operations_1",
    }


def test_sqlite_operation_ledger_keeps_scoped_queries_exact(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite", embedding_service=_Embedding())
    store.record_operation(
        new_operation(
            operation="update",
            document_id="legacy-doc",
            scope="workspace",
            reason="unscoped_legacy_event",
        )
    )
    store.record_operation(
        new_operation(
            operation="update",
            document_id="workspace-doc",
            scope="workspace",
            workspace_id="ws-1",
            reason="scoped_event",
        )
    )

    operations = store.list_operations(scope="workspace", workspace_id="ws-1")
    assert [item["document_id"] for item in operations] == ["workspace-doc"]


def test_sqlite_operation_ledger_migrates_legacy_scope_id_whitespace(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.sqlite"
    SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_operations (
                operation_id, operation, document_id, at, actor, scope,
                workspace_id, session_id, reason, evidence_json,
                before_revision, after_revision, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-op",
                "update",
                "legacy-doc",
                "2026-01-01T00:00:00Z",
                "legacy",
                "session",
                " ws-1 ",
                " session-1 ",
                "legacy event",
                None,
                None,
                None,
                "{}",
            ),
        )

    restarted = SQLiteMemoryStore(db_path, embedding_service=_Embedding())
    operations = restarted.list_operations(
        scope="session",
        workspace_id="ws-1",
        session_id="session-1",
    )
    assert [item["operation_id"] for item in operations] == ["legacy-op"]
    assert operations[0]["workspace_id"] == "ws-1"
    assert operations[0]["session_id"] == "session-1"


def test_operations_endpoint_defaults_to_workspace_scope() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    created = client.post(
        "/memory/docs",
        json={
            "text": "workspace fact",
            "scope": "workspace",
            "workspace_id": "ws-1",
            "dedupe": False,
        },
    )
    assert created.status_code == 200
    response = client.get("/memory/operations", params={"workspace_id": "ws-1"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "workspace"
    assert payload["count"] == 1
    assert payload["operations"][0]["operation"] == "create"


def test_correction_is_recorded_as_a_correction_operation() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    created = client.post(
        "/memory/docs",
        json={
            "text": "用户喜欢安静的通知",
            "scope": "workspace",
            "workspace_id": "ws-1",
            "dedupe": False,
        },
    )
    assert created.status_code == 200
    doc_id = created.json()["id"]

    corrected = client.post(
        f"/memory/docs/{doc_id}/correction",
        json={"text": "用户喜欢低打扰的通知", "reason": "用户明确更正"},
    )
    assert corrected.status_code == 200

    response = client.get(
        "/memory/operations",
        params={"document_id": doc_id, "workspace_id": "ws-1"},
    )
    assert response.status_code == 200
    operations = response.json()["operations"]
    assert [item["operation"] for item in operations[:2]] == ["correction", "create"]


def test_compatibility_add_memory_keeps_filter_and_shared_metadata() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    skipped = client.post(
        "/memory/memory/add",
        json={
            "text": "过于短暂的上下文",
            "importance": 0.2,
            "scope": "workspace",
            "workspace_id": "ws-1",
        },
    )
    assert skipped.status_code == 200
    assert skipped.json()["skipped"] is True

    created = client.post(
        "/memory/memory/add",
        json={
            "text": "用户偏好低打扰的通知",
            "importance": 0.8,
            "memory_role": "user_fact",
            "scope": "workspace",
            "workspace_id": "ws-1",
            "dedupe": False,
        },
    )
    assert created.status_code == 200
    assert created.json()["memory_role"] == "user_fact"

    docs = client.get("/memory/docs", params={"workspace_id": "ws-1"})
    assert docs.status_code == 200
    assert len(docs.json()["docs"]) == 1
    assert docs.json()["docs"][0]["metadata"]["memory_role"] == "user_fact"


def test_operations_scope_does_not_promote_unscoped_legacy_events() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    state.operation_log.append(
        new_operation(
            operation="update",
            document_id="other-workspace-doc",
            scope="workspace",
            reason="legacy_event_without_workspace",
        )
    )
    app = FastAPI()
    app.include_router(
        create_memory_router(state, get_active_workspace_id=lambda: "ws-active")
    )
    client = TestClient(app)

    response = client.get(
        "/memory/operations",
        params={
            "document_id": "other-workspace-doc",
            "workspace_id": "ws-active",
        },
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_session_memory_mutations_require_owning_session() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state, get_active_workspace_id=lambda: "ws-1"))
    client = TestClient(app)

    created = client.post(
        "/memory/docs",
        json={
            "text": "只属于会话一的偏好",
            "scope": "session",
            "workspace_id": "ws-1",
            "session_id": "session-1",
            "dedupe": False,
        },
    )
    assert created.status_code == 200
    doc_id = created.json()["id"]

    for path, method, payload in [
        (f"/memory/docs/{doc_id}", "put", {"text": "错误会话不能改"}),
        (f"/memory/docs/{doc_id}/soft-forget", "post", {}),
        (f"/memory/docs/{doc_id}/feedback", "post", {"feedback": "helpful"}),
        (f"/memory/docs/{doc_id}/correction", "post", {"text": "错误会话不能改"}),
        (f"/memory/docs/{doc_id}", "delete", None),
    ]:
        response = getattr(client, method)(path, params={"session_id": "session-2"}, json=payload) if payload is not None else getattr(client, method)(path, params={"session_id": "session-2"})
        assert response.status_code == 403, (path, response.text)
        assert response.json()["detail"]["error"] == "session_mismatch"

    preview = client.post(
        "/memory/docs/delete-preview",
        params={"session_id": "session-2"},
        json={"ids": [doc_id]},
    )
    assert preview.status_code == 403

    batch = client.post(
        "/memory/docs/batch-delete",
        params={"session_id": "session-2"},
        json={"ids": [doc_id]},
    )
    assert batch.status_code == 403

    forgotten = client.post(
        f"/memory/docs/{doc_id}/soft-forget",
        json={"session_id": "session-1", "reason": "test"},
    )
    assert forgotten.status_code == 200
    updated = client.put(
        f"/memory/docs/{doc_id}",
        json={"text": "会话一可以修改", "session_id": "session-1"},
    )
    assert updated.status_code == 200
    restored = client.post(
        f"/memory/docs/{doc_id}/restore",
        json={"session_id": "session-1"},
    )
    assert restored.status_code == 200


def test_workspace_memory_keeps_legacy_mutation_behavior() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state, get_active_workspace_id=lambda: "ws-1"))
    client = TestClient(app)
    created = client.post(
        "/memory/docs",
        json={"text": "workspace mutation", "scope": "workspace", "workspace_id": "ws-1", "dedupe": False},
    )
    assert created.status_code == 200
    doc_id = created.json()["id"]
    response = client.post(f"/memory/docs/{doc_id}/soft-forget", json={"reason": "legacy"})
    assert response.status_code == 200


def test_legacy_rag_query_alias_is_explicitly_deprecated() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    response = client.post("/memory/rag/query", json={"query": "本地偏好"})

    assert response.status_code == 200
    assert response.headers["deprecation"] == "true"
    assert response.headers["link"] == '</memory/query>; rel="successor-version"'


def test_pipeline_query_adapter_is_explicitly_deprecated() -> None:
    app = FastAPI()
    received: dict[str, object] = {}

    def query_handler(**kwargs):
        received.update(kwargs)
        return {"query": kwargs["query"], "results": []}

    app.include_router(
        create_memory_pipeline_router(
            query_handler,
        )
    )
    client = TestClient(app)

    response = client.get("/api/memory/pipeline/query", params={"query": "旧客户端查询"})

    assert response.status_code == 200
    assert response.json() == {"query": "旧客户端查询", "results": []}
    assert response.headers["deprecation"] == "true"
    assert response.headers["link"] == '</memory/query>; rel="successor-version"'

    normalized = client.get(
        "/api/memory/pipeline/query",
        params={"query": "会话记忆", "scope": " session ", "session_id": " session-1 "},
    )
    assert normalized.status_code == 200
    assert received["scope"] == "session"
    assert received["session_id"] == "session-1"

    missing_session = client.get(
        "/api/memory/pipeline/query",
        params={"query": "会话记忆", "scope": "session"},
    )
    assert missing_session.status_code == 400
    assert missing_session.json()["detail"] == "session_id is required for session scope"


def test_session_scope_reads_require_session_id() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    read_requests = [
        client.get("/memory/docs", params={"scope": "session"}),
        client.get("/memory/export", params={"scope": "session"}),
        client.get("/memory/overview", params={"scope": "session"}),
        client.get("/memory/candidates", params={"scope": "session"}),
        client.post(
            "/memory/maintenance/preview",
            json={"scope": "session"},
        ),
        client.post(
            "/memory/query",
            json={"query": "会话记忆", "scope": "session"},
        ),
    ]

    assert [response.status_code for response in read_requests] == [400] * len(read_requests)
    assert all(response.json()["detail"] == "session_id is required for session scope" for response in read_requests)


def test_session_scope_writes_require_session_id() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state))
    client = TestClient(app)

    direct = client.post(
        "/memory/docs",
        json={"text": "无 owner 的会话记忆", "scope": "session", "dedupe": False},
    )
    compatibility = client.post(
        "/memory/memory/add",
        json={"text": "无 owner 的兼容记忆", "scope": "session", "importance": 0.8, "dedupe": False},
    )
    imported = client.post(
        "/memory/import",
        json={
            "format": "yuizaki-memory-export",
            "version": 1,
            "scope": "session",
            "docs": [{"text": "无 owner 的导入记忆"}],
        },
    )

    assert [response.status_code for response in (direct, compatibility, imported)] == [400, 400, 400]
    assert all(response.json()["detail"] == "session_id is required for session scope" for response in (direct, compatibility, imported))


def test_session_ids_are_normalized_across_memory_boundaries() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state, get_active_workspace_id=lambda: "ws-1"))
    client = TestClient(app)

    created = client.post(
        "/memory/docs",
        json={
            "text": "带空白的会话记忆",
            "scope": "session",
            "workspace_id": " ws-1 ",
            "session_id": " session-1 ",
            "dedupe": False,
        },
    )
    assert created.status_code == 200
    doc_id = created.json()["id"]

    docs = client.get(
        "/memory/docs",
        params={"scope": "session", "workspace_id": " ws-1 ", "session_id": " session-1 "},
    )
    assert docs.status_code == 200
    assert len(docs.json()["docs"]) == 1
    metadata = docs.json()["docs"][0]["metadata"]
    assert metadata["session_id"] == "session-1"
    assert metadata["workspace_id"] == "ws-1"

    operations = client.get(
        "/memory/operations",
        params={"scope": "session", "workspace_id": " ws-1 ", "session_id": " session-1 "},
    )
    assert operations.status_code == 200
    assert operations.json()["session_id"] == "session-1"
    assert operations.json()["count"] == 1

    query = client.post(
        "/memory/query",
        json={
            "query": "带空白的会话记忆",
            "scope": "session",
            "workspace_id": " ws-1 ",
            "session_id": " session-1 ",
        },
    )
    assert query.status_code == 200
    assert query.json()["results"]

    updated = client.put(
        f"/memory/docs/{doc_id}",
        json={"text": "规范化后的会话记忆", "session_id": " session-1 "},
    )
    assert updated.status_code == 200
    forgotten = client.post(
        f"/memory/docs/{doc_id}/soft-forget",
        json={"session_id": " session-1 ", "reason": "test"},
    )
    assert forgotten.status_code == 200
    restored = client.post(
        f"/memory/docs/{doc_id}/restore",
        json={"session_id": " session-1 "},
    )
    assert restored.status_code == 200

    exported = client.get(
        "/memory/export",
        params={"scope": "session", "workspace_id": " ws-1 ", "session_id": " session-1 "},
    )
    assert exported.status_code == 200
    assert exported.json()["session_id"] == "session-1"


def test_candidates_default_to_workspace_without_leaking_session_memory() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state, get_active_workspace_id=lambda: "ws-1"))
    client = TestClient(app)

    created = client.post(
        "/memory/memory/add",
        json={
            "text": "会话权限候选",
            "scope": "session",
            "workspace_id": "ws-1",
            "session_id": "session-1",
            "memory_role": "tool_permission",
            "importance": 0.9,
            "dedupe": False,
        },
    )
    assert created.status_code == 200

    default_scope = client.get("/memory/candidates")
    assert default_scope.status_code == 200
    assert default_scope.json()["count"] == 0

    owning_session = client.get(
        "/memory/candidates",
        params={"scope": "session", "session_id": "session-1", "workspace_id": "ws-1"},
    )
    assert owning_session.status_code == 200
    assert owning_session.json()["count"] == 1


def test_backend_scope_filter_normalizes_legacy_ids() -> None:
    document = Document(
        id="legacy-session-doc",
        text="旧格式 session 记忆",
        metadata={"scope": "session", "session_id": " session-1 ", "workspace_id": " ws-1 "},
    )
    filters = MemorySearchFilters(
        scope="session",
        session_id=" session-1 ",
        workspace_id=" ws-1 ",
    )
    assert is_memory_recallable(document, filters=filters)


def test_session_import_preserves_soft_forgotten_state() -> None:
    state = MemoryState(store=VectorStore(embedding_service=_Embedding()))
    app = FastAPI()
    app.include_router(create_memory_router(state, get_active_workspace_id=lambda: "ws-1"))
    client = TestClient(app)

    imported = client.post(
        "/memory/import",
        json={
            "format": "yuizaki-memory-export",
            "version": 1,
            "scope": "session",
            "workspace_id": "ws-1",
            "session_id": "session-1",
            "docs": [{
                "id": "forgotten-import",
                "text": "导入后仍应停止召回",
                "metadata": {"soft_forgotten": True},
            }],
        },
    )
    assert imported.status_code == 200
    assert imported.json()["imported_count"] == 1
    assert imported.json()["restored_soft_forgotten_count"] == 1
    assert imported.json()["skipped_count"] == 0

    active = client.get(
        "/memory/docs",
        params={"scope": "session", "workspace_id": "ws-1", "session_id": "session-1"},
    )
    assert active.status_code == 200
    assert active.json()["docs"] == []

    forgotten = client.get(
        "/memory/docs",
        params={
            "scope": "session",
            "workspace_id": "ws-1",
            "session_id": "session-1",
            "include_state": "forgotten",
        },
    )
    assert forgotten.status_code == 200
    assert [doc["id"] for doc in forgotten.json()["docs"]] == ["forgotten-import"]
