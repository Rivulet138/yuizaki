from __future__ import annotations

from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.responses import JSONResponse
import modules.system.runtime_endpoints as system_runtime_endpoints
from modules.agent.tool_registry import ToolRegistry, ToolDefinition
from modules.agent.tool_result import ToolResultEnvelope

from modules.system.runtime_endpoints import (
    build_experience_metrics_endpoint,
    build_health_endpoint,
    build_memory_query_request_payload,
    build_readiness_endpoint,
)


class _FakeRepo:
    def get_workspace_companion(self, workspace_id: str):
        return {"id": f"companion-{workspace_id}", "support_style": "gentle"}


def test_build_experience_metrics_endpoint_returns_store_snapshot():
    store = SimpleNamespace(snapshot=lambda: {"window": {"generation_samples": 3}})
    endpoint = build_experience_metrics_endpoint(store)

    assert endpoint() == {"window": {"generation_samples": 3}}


_heartbeat_builder = cast(
    Callable[..., Callable[[], JSONResponse | dict[str, Any]]],
    getattr(system_runtime_endpoints, "build_heartbeat_status_endpoint"),
)

_active_workspace_builder = cast(
    Callable[..., Callable[[dict[str, Any]], JSONResponse | dict[str, Any]]],
    getattr(system_runtime_endpoints, "build_active_workspace_endpoint"),
)

_capabilities_builder = cast(
    Callable[..., Callable[[], dict[str, Any]]],
    getattr(system_runtime_endpoints, "build_capabilities_state_endpoint"),
)

_orchestration_builder = cast(
    Callable[..., Callable[[], dict[str, Any]]],
    getattr(system_runtime_endpoints, "build_orchestration_state_endpoint"),
)

_memory_pipeline_query_builder = cast(
    Callable[..., Callable[..., JSONResponse | Any]],
    getattr(system_runtime_endpoints, "build_memory_pipeline_query_endpoint"),
)


class _FakeActiveWorkspaceState:
    def __init__(self):
        self.value = "default"

    def set(self, workspace_id: str) -> str:
        self.value = workspace_id
        return workspace_id


def test_build_heartbeat_status_endpoint_returns_503_when_scheduler_missing():
    endpoint = _heartbeat_builder(
        heartbeat_scheduler_provider=lambda: None,
        active_workspace_id_provider=lambda: "ws-main",
        db_repo_provider=lambda: _FakeRepo(),
    )

    result = endpoint()

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert result.body == b'{"error":"heartbeat_scheduler_not_initialized"}'


def test_build_heartbeat_status_endpoint_returns_snapshot_payload():
    scheduler = SimpleNamespace(
        state=SimpleNamespace(
            running=True,
            interval_seconds=30,
            tick_count=7,
            last_tick_at="2026-04-23T09:00:00Z",
            persona={"mood": "steady"},
            events=[{"kind": "heartbeat_tick"}],
            behavior_events=[{"kind": "care_signal"}],
        )
    )
    endpoint = _heartbeat_builder(
        heartbeat_scheduler_provider=lambda: scheduler,
        active_workspace_id_provider=lambda: "ws-main",
        db_repo_provider=lambda: _FakeRepo(),
    )

    result = endpoint()

    assert isinstance(result, dict)
    assert result["running"] is True
    assert result["interval_seconds"] == 30
    assert result["tick_count"] == 7
    assert result["last_tick_at"] == "2026-04-23T09:00:00Z"
    assert result["persona"] == {"mood": "steady"}
    assert result["events"] == [{"kind": "heartbeat_tick"}]
    assert result["behavior_events"] == [{"kind": "care_signal"}]
    assert result["active_workspace_id"] == "ws-main"
    assert result["active_companion"] == {"id": "companion-ws-main", "support_style": "gentle"}


def test_build_active_workspace_endpoint_normalizes_workspace_id_and_returns_companion():
    state = _FakeActiveWorkspaceState()
    endpoint = _active_workspace_builder(
        active_workspace_state=state,
        db_repo_provider=lambda: _FakeRepo(),
    )

    result = endpoint({"workspace_id": "  ws-focus  "})

    assert state.value == "ws-focus"
    assert result == {
        "ok": True,
        "workspace_id": "ws-focus",
        "companion": {"id": "companion-ws-focus", "support_style": "gentle"},
    }


def test_build_active_workspace_endpoint_falls_back_to_default_when_blank():
    state = _FakeActiveWorkspaceState()
    endpoint = _active_workspace_builder(
        active_workspace_state=state,
        db_repo_provider=lambda: None,
    )

    result = endpoint({"workspace_id": "   "})

    assert state.value == "default"
    assert result == {
        "ok": True,
        "workspace_id": "default",
        "companion": None,
    }


def test_build_active_workspace_endpoint_rejects_unknown_database_workspace():
    class _WorkspaceRepo(_FakeRepo):
        def list_workspaces(self):
            return [{"id": "default"}, {"id": "ws-main"}]

    state = _FakeActiveWorkspaceState()
    endpoint = _active_workspace_builder(
        active_workspace_state=state,
        db_repo_provider=lambda: _WorkspaceRepo(),
    )

    result = endpoint({"workspace_id": "missing"})

    assert isinstance(result, JSONResponse)
    assert result.status_code == 404
    assert result.body == b'{"error":"workspace_not_found","workspace_id":"missing"}'
    assert state.value == "default"


def test_build_capabilities_state_endpoint_returns_empty_snapshot_when_registry_missing():
    endpoint = _capabilities_builder(
        tool_registry_provider=lambda: None,
        capability_snapshot_builder=lambda registry: {"capabilities": [], "summary": {"total": len(registry.list_definitions())}},
    )

    result = endpoint()

    assert result == {
        "capabilities": [],
        "summary": {
            "total": 0,
            "builtin": 0,
            "plugin": 0,
            "mcp": 0,
            "skill": 0,
            "command": 0,
            "approval_required": 0,
        },
    }


def test_build_capabilities_state_endpoint_returns_capability_registry_snapshot():
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="builtin.demo.echo",
            description="Demo echo tool",
            source="builtin",
            parameters={"type": "object", "properties": {}},
            handler=lambda args: ToolResultEnvelope(
                success=True,
                content="ok",
                source="builtin",
                tool_name="builtin.demo.echo",
            ),
            tags=["demo"],
        )
    )
    endpoint = _capabilities_builder(
        tool_registry_provider=lambda: registry,
        capability_snapshot_builder=lambda current_registry: __import__("modules.agent.capability_registry", fromlist=["CapabilityRegistry"]).CapabilityRegistry(current_registry).snapshot(),
    )

    result = endpoint()

    assert result["summary"]["total"] >= 1
    assert result["summary"]["builtin"] >= 1
    capability = next(item for item in result["capabilities"] if item["id"] == "builtin.demo.echo")
    assert capability["source"] == "builtin"
    assert capability["owner"] == "yuizaki.builtin-tools"
    assert capability["requiresApproval"] is False


def test_build_orchestration_state_endpoint_returns_snapshot_passthrough():
    endpoint = _orchestration_builder(
        orchestration_snapshot_builder=lambda: {
            "skills": [{"id": "skill.observe"}],
            "commands": [{"id": "command.schedule"}],
            "hooks": [{"id": "hook.before_pipeline"}],
        }
    )

    result = endpoint()

    assert result == {
        "skills": [{"id": "skill.observe"}],
        "commands": [{"id": "command.schedule"}],
        "hooks": [{"id": "hook.before_pipeline"}],
    }


def test_build_memory_pipeline_query_endpoint_returns_503_when_pipeline_missing():
    endpoint = _memory_pipeline_query_builder(
        retrieval_pipeline_provider=lambda: None,
        active_workspace_id_provider=lambda: "ws-main",
        db_repo_provider=lambda: _FakeRepo(),
        relationship_summary_provider=lambda: {},
        companion_runtime_provider=lambda _limit: {},
        build_memory_query_request=lambda **kwargs: kwargs,
    )

    result = endpoint("总结一下")

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert result.body == b'{"error":"retrieval_pipeline_not_initialized"}'


def test_build_memory_pipeline_query_endpoint_builds_request_and_calls_recall():
    captured: dict[str, object] = {}

    class _FakeRetrievalPipeline:
        def recall(self, request: object) -> dict[str, object]:
            captured["request"] = request
            return {"results": [{"doc": {"id": "mem-1"}}], "trace": {"query": "总结一下"}}

    endpoint = _memory_pipeline_query_builder(
        retrieval_pipeline_provider=lambda: _FakeRetrievalPipeline(),
        active_workspace_id_provider=lambda: "ws-main",
        db_repo_provider=lambda: _FakeRepo(),
        relationship_summary_provider=lambda: {
            "relationship_stage": "stable",
            "milestone_salience": "high",
        },
        companion_runtime_provider=lambda _limit: {
            "memory_state": {
                "recent_signals": [{"kind": "support_request"}],
            }
        },
        build_memory_query_request=lambda **kwargs: kwargs,
    )

    result = endpoint(
        "总结一下",
        "sess-1",
        "ws-explicit",
        "workspace",
        "relationship,reflective",
        7,
    )

    assert result == {"results": [{"doc": {"id": "mem-1"}}], "trace": {"query": "总结一下"}}
    request = cast(dict[str, object], captured["request"])
    assert request["query"] == "总结一下"
    assert request["session_id"] == "sess-1"
    assert request["workspace_id"] == "ws-explicit"
    assert request["scope"] == "workspace"
    assert request["layers"] == "relationship,reflective"
    assert request["top_k"] == 7
    assert request["support_style"] == "gentle"
    assert request["relationship_stage"] == "stable"
    assert request["milestone_salience"] == "high"
    assert request["recent_signal_kinds"] == ["support_request"]


@pytest.mark.asyncio
async def test_build_health_endpoint_delegates_to_health_handler():
    async def _health_handler():
        return {"status": "healthy", "components": []}

    endpoint: Callable[[], Coroutine[Any, Any, dict[str, Any]]] = build_health_endpoint(health_handler=_health_handler)

    assert await endpoint() == {"status": "healthy", "components": []}


@pytest.mark.asyncio
async def test_build_readiness_endpoint_treats_optional_services_as_non_blocking():
    async def _ok(message: str):
        return True, message

    async def _optional_down(message: str):
        return False, message

    endpoint = build_readiness_endpoint(
        llm_health_provider=lambda: _ok("llm ok"),
        tts_health_provider=lambda: _ok("tts ok"),
        database_health_provider=lambda: _ok("db ok"),
        asr_health_provider=lambda: _optional_down("asr optional"),
        ocr_health_provider=lambda: _optional_down("ocr optional"),
        memory_health_provider=lambda: _ok("memory ok"),
        generation_manager_provider=lambda: object(),
        svc_client_provider=lambda: None,
    )

    result = await cast(Coroutine[Any, Any, dict[str, Any]], cast(object, endpoint()))

    assert result["ready"] is True
    assert result["checks"]["svc"]["required"] is False
    assert result["checks"]["asr"]["ok"] is False
    assert result["checks"]["ocr"]["required"] is False
    assert result["checks"]["ocr"]["ok"] is False
    assert result["checks"]["generation_manager"]["ok"] is True


@pytest.mark.asyncio
async def test_build_readiness_endpoint_blocks_when_required_service_is_down():
    async def _ok(message: str):
        return True, message

    async def _down(message: str):
        return False, message

    endpoint = build_readiness_endpoint(
        llm_health_provider=lambda: _ok("llm ok"),
        tts_health_provider=lambda: _ok("tts ok"),
        database_health_provider=lambda: _ok("db ok"),
        asr_health_provider=lambda: _ok("asr ok"),
        ocr_health_provider=lambda: _ok("ocr ok"),
        memory_health_provider=lambda: _down("memory offline"),
        generation_manager_provider=lambda: object(),
        svc_client_provider=lambda: object(),
    )

    result = await cast(Coroutine[Any, Any, dict[str, Any]], cast(object, endpoint()))

    assert result["ready"] is False
    assert result["checks"]["memory"] == {
        "ok": False,
        "message": "memory offline",
        "required": True,
    }


def test_build_memory_query_request_payload_injects_companion_and_recent_signal_context():
    captured: dict[str, object] = {}

    def _build_memory_query_request(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return kwargs

    payload = build_memory_query_request_payload(
        query="总结一下",
        session_id="sess-1",
        workspace_id=None,
        scope="workspace",
        layers=None,
        top_k=6,
        active_workspace_id_provider=lambda: "ws-main",
        db_repo_provider=lambda: _FakeRepo(),
        relationship_summary_provider=lambda: {
            "relationship_stage": "stable",
            "milestone_salience": "high",
        },
        companion_runtime_provider=lambda _limit: {
            "memory_state": {
                "recent_signals": [
                    {"kind": "support_request"},
                    {"kind": "task_completed"},
                    {"kind": None},
                ]
            }
        },
        build_memory_query_request=_build_memory_query_request,
    )

    assert payload["support_style"] == "gentle"
    assert payload["relationship_stage"] == "stable"
    assert payload["milestone_salience"] == "high"
    assert payload["recent_signal_kinds"] == ["support_request", "task_completed", ""]
    assert captured["workspace_id"] is None
