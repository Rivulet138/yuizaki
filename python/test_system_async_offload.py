from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.pipeline import AgentPipeline
from modules.agent.scheduler import AgentScheduler
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope
from modules.memory.backend import MemoryBackendStatus
from modules.memory.routes import MemoryRagQueryPayload, MemoryState, create_memory_pipeline_router, create_memory_router
from modules.memory.schema import MemorySearchFilters
from modules.memory.vector_store import Document
from routes.companion_api import create_companion_router
from routes.database_api import create_database_router
from modules.system.health_providers import build_app_runtime_health_providers
from modules.system.runtime_endpoints import (
    build_create_once_schedule_endpoint,
    build_mcp_state_endpoint,
    build_permissions_state_endpoint,
    build_system_status_endpoint,
    build_toggle_mcp_endpoint,
)
from routes.system_api import create_system_router


def _endpoint(router: Any, path: str) -> Any:
    return next(item.endpoint for item in router.routes if getattr(item, "path", "") == path)


async def _assert_event_loop_responsive(coro: Any) -> Any:
    slow_task = asyncio.create_task(coro)
    started = time.perf_counter()
    await asyncio.sleep(0.01)
    latency_ms = (time.perf_counter() - started) * 1000
    result = await slow_task

    assert latency_ms < 50
    return result


@pytest.mark.asyncio
async def test_companion_runtime_handler_is_offloaded_from_event_loop() -> None:
    router = create_system_router(
        health_handler=lambda: {"status": "ok"},
        readiness_handler=lambda: {"ready": True},
        system_status_handler=lambda: {"status": "ok"},
        companion_runtime_handler=lambda limit: (time.sleep(0.08) or {"limit": limit}),
    )
    endpoint = _endpoint(router, "/api/system/companion-runtime")
    result = await _assert_event_loop_responsive(endpoint(limit=4))

    assert result == {"limit": 4}


@pytest.mark.asyncio
async def test_database_health_provider_offloads_sync_stats() -> None:
    class SlowRepository:
        def get_database_stats(self) -> dict[str, int]:
            time.sleep(0.08)
            return {"total_messages": 7}

    providers = build_app_runtime_health_providers(
        llm_client_provider=lambda: object(),
        tts_client_provider=lambda: object(),
        asr_manager_provider=lambda: None,
        ocr_client_provider=lambda: None,
        database_repository_provider=lambda: SlowRepository(),
        memory_state_provider=lambda: None,
    )

    result = await _assert_event_loop_responsive(providers.database())

    assert result == (True, "Database healthy (7 messages)")


@pytest.mark.asyncio
async def test_database_router_offloads_sync_repository_calls() -> None:
    class SlowRepository:
        def get_database_stats(self) -> dict[str, int]:
            time.sleep(0.08)
            return {"total_sessions": 3}

    endpoint = _endpoint(create_database_router(lambda: SlowRepository()), "/api/database/stats")

    result = await _assert_event_loop_responsive(endpoint())

    assert result == {"total_sessions": 3}


@pytest.mark.asyncio
async def test_companion_router_offloads_sync_repository_calls() -> None:
    class SlowRepository:
        def list_companions(self) -> list[dict[str, str]]:
            time.sleep(0.08)
            return [{"id": "comp-1", "name": "Demo"}]

    endpoint = _endpoint(create_companion_router(lambda: SlowRepository()), "/api/companions")

    result = await _assert_event_loop_responsive(endpoint())

    assert result == {"companions": [{"id": "comp-1", "name": "Demo"}]}


@pytest.mark.asyncio
async def test_memory_rag_query_offloads_sync_vector_search() -> None:
    class SlowMemoryStore:
        backend_name = "slow"
        last_filters: MemorySearchFilters | None = None

        def list_documents(self) -> list[Document]:
            return []

        def add_document(self, _doc: Document) -> None:
            return None

        def rebuild_index(self) -> dict[str, Any]:
            return {"status": "rebuilt"}

        def search(self, query: str, top_k: int = 5, filters: MemorySearchFilters | None = None) -> list[tuple[Document, float]]:
            self.last_filters = filters
            time.sleep(0.08)
            return []

        def search_with_rerank(self, *args: Any, **kwargs: Any) -> list[tuple[Document, float]]:
            self.last_filters = kwargs.get("filters")
            time.sleep(0.08)
            return []

        def get_status(self) -> MemoryBackendStatus:
            return MemoryBackendStatus(backend="slow", healthy=True, message="ok", document_count=0)

    store = SlowMemoryStore()
    endpoint = _endpoint(create_memory_router(MemoryState(store=store)), "/memory/rag/query")

    result = await _assert_event_loop_responsive(endpoint(MemoryRagQueryPayload(query="hello")))

    assert result["query"] == "hello"
    assert store.last_filters is not None


@pytest.mark.asyncio
async def test_memory_pipeline_router_offloads_sync_query_handler() -> None:
    def slow_handler(**kwargs: object) -> dict[str, object]:
        time.sleep(0.08)
        return {"ok": True, "query": kwargs.get("query")}

    endpoint = _endpoint(create_memory_pipeline_router(slow_handler), "/api/memory/pipeline/query")

    result = await _assert_event_loop_responsive(endpoint(query="hello"))

    assert result == {"ok": True, "query": "hello"}


@pytest.mark.asyncio
async def test_permissions_runtime_endpoint_offloads_sync_policy_snapshot() -> None:
    class SlowPolicyEngine:
        def get_remembered_decisions(self) -> dict[str, bool]:
            time.sleep(0.08)
            return {"web_search::default": True}

        def get_audit_log(self, limit: int) -> list[dict[str, int]]:
            return [{"limit": limit}]

    endpoint = build_permissions_state_endpoint(SlowPolicyEngine())

    result = await _assert_event_loop_responsive(endpoint())

    assert result == {
        "remembered": {"web_search::default": True},
        "audit": [{"limit": 200}],
    }


@pytest.mark.asyncio
async def test_mcp_runtime_endpoint_offloads_sync_snapshot() -> None:
    class SlowMcpManager:
        def snapshot(self) -> dict[str, list[object]]:
            time.sleep(0.08)
            return {"servers": []}

    endpoint = build_mcp_state_endpoint(SlowMcpManager())

    result = await _assert_event_loop_responsive(endpoint())

    assert result == {"servers": []}


@pytest.mark.asyncio
async def test_mcp_toggle_endpoint_offloads_sync_config_write_before_refresh() -> None:
    class SlowMcpManager:
        def __init__(self) -> None:
            self.refreshed: list[str] = []

        def set_enabled(self, server_name: str, enabled: bool) -> dict[str, object]:
            time.sleep(0.08)
            return {"name": server_name, "enabled": enabled}

        async def refresh_one(self, server_name: str, timeout_seconds: float | None = None) -> dict[str, object]:
            self.refreshed.append(server_name)
            return {"name": server_name, "ok": True, "timeout": timeout_seconds}

    manager = SlowMcpManager()
    endpoint = build_toggle_mcp_endpoint(manager)

    result = await _assert_event_loop_responsive(endpoint("memory", True))

    assert result == {"ok": True, "server": {"name": "memory", "enabled": True}}
    assert manager.refreshed == ["memory"]


@pytest.mark.asyncio
async def test_system_status_endpoint_offloads_sync_status_aggregation() -> None:
    class SlowServiceManager:
        def get_status(self) -> dict[str, str]:
            time.sleep(0.08)
            return {"api": "running"}

    class HealthChecker:
        def get_status(self) -> dict[str, str]:
            return {"health": "ok"}

    endpoint = build_system_status_endpoint(
        service_manager=SlowServiceManager(),
        health_checker=HealthChecker(),
        config_snapshot_provider=lambda: {"debug": False},
        memory_status_provider=lambda: SimpleNamespace(backend="memory", healthy=True),
    )

    result = await _assert_event_loop_responsive(endpoint())

    assert result == {
        "services": {"api": "running"},
        "health": {"health": "ok"},
        "config": {"debug": False},
        "memory": {"backend": "memory", "healthy": True},
    }


@pytest.mark.asyncio
async def test_schedule_creation_offloads_sync_schedule_store_write() -> None:
    class SlowScheduleStore:
        def __init__(self) -> None:
            self.tasks: dict[str, Any] = {}

        def upsert(self, task: Any) -> Any:
            time.sleep(0.08)
            self.tasks[task.id] = task
            return task

        def remove(self, task_id: str) -> None:
            self.tasks.pop(task_id, None)

        def list(self) -> list[Any]:
            return list(self.tasks.values())

    scheduler = AgentScheduler(
        store=SlowScheduleStore(),
        pipeline=AgentPipeline(),
        context_factory=lambda _task: AgentRequestContext(sid="s1", session_id="s1", messages=[]),
    )
    endpoint = build_create_once_schedule_endpoint(scheduler)

    result = await _assert_event_loop_responsive(endpoint("Review", "summarize", 30))

    assert result["ok"] is True
    assert result["task"]["name"] == "Review"


@pytest.mark.asyncio
async def test_agent_pipeline_offloads_sync_retrieval_recall() -> None:
    class SlowRetrievalPipeline:
        def recall(self, request: Any) -> dict[str, object]:
            time.sleep(0.08)
            return {
                "results": [
                    {
                        "doc": {
                            "text": "remembered context",
                            "metadata": {"relationship_event": {"kind": "support_request"}},
                        }
                    }
                ]
            }

    pipeline = AgentPipeline(SlowRetrievalPipeline())
    ctx = AgentRequestContext(
        sid="s1",
        session_id="s1",
        workspace_id="ws-main",
        messages=[{"role": "user", "content": "hello"}],
    )

    result_ctx = await _assert_event_loop_responsive(pipeline.enrich_context(ctx))

    assert result_ctx.extra["retrieved_chunks"] == ["remembered context"]
    assert result_ctx.extra["recent_signal_docs"] == [{"kind": "support_request"}]


@pytest.mark.asyncio
async def test_tool_executor_offloads_sync_policy_and_tool_handler() -> None:
    class SlowPolicyEngine:
        def evaluate_tool(self, _tool: Any, **_kwargs: Any) -> SimpleNamespace:
            time.sleep(0.08)
            return SimpleNamespace(allowed=True, require_confirm=False, request_id=None, reason="ok")

        def register_pending(self, _request_id: str) -> None:
            raise AssertionError("no confirmation expected")

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="slow_tool",
            description="Slow sync tool",
            source="builtin",
            parameters={"type": "object", "properties": {}},
            handler=lambda _args: (time.sleep(0.08) or ToolResultEnvelope(
                success=True,
                content="done",
                source="builtin",
                tool_name="slow_tool",
            )),
        )
    )
    executor = ToolExecutor(registry, SlowPolicyEngine())

    result = await _assert_event_loop_responsive(executor.execute("slow_tool", {}))

    assert result.success is True
    assert result.content == "done"
