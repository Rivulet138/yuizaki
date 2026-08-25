from __future__ import annotations

import asyncio

import pytest

from modules.agent.perception import (
    CallablePerceptionProvider,
    PerceptionPermissionError,
    PerceptionProviderRegistry,
    PerceptionProviderSpec,
    PerceptionRequest,
)
from modules.agent.runtime_context import (
    RuntimeContext,
    RuntimeContextConflictError,
    RuntimeContextRegistry,
)
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.runtime import create_agent_runtime
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService


def test_runtime_context_swap_is_atomic_and_revision_guarded() -> None:
    registry = RuntimeContextRegistry()
    first = registry.register(RuntimeContext(workspace_id="alpha", extras={"generation": "old"}))
    second = registry.swap(
        RuntimeContext(workspace_id="alpha", extras={"generation": "new"}),
        expected_revision=first.revision,
    )

    assert second.revision > first.revision
    assert first.extras["generation"] == "old"  # in-flight snapshot remains stable
    assert registry.require("alpha") is second
    with pytest.raises(RuntimeContextConflictError):
        registry.swap(RuntimeContext(workspace_id="alpha"), expected_revision=first.revision)


def test_runtime_context_reusing_source_object_still_creates_unique_committed_identity() -> None:
    registry = RuntimeContextRegistry()
    source = RuntimeContext(workspace_id="alpha")

    first = registry.register(source)
    second = registry.swap(source, expected_revision=first.revision)

    assert first.context_id != second.context_id
    assert registry.require("alpha") is second


def test_runtime_context_bind_request_scopes_dependencies() -> None:
    registry = RuntimeContextRegistry()
    repository = object()
    context = registry.register(
        RuntimeContext(
            workspace_id="alpha",
            db_repo=repository,
            relationship_history_provider=lambda: [{"event": "hello"}],
            relationship_summary_provider=lambda: {"trust": 0.5},
        )
    )
    request = type("Request", (), {"workspace_id": "alpha", "extra": {}})()
    registry.bind_request(request)

    assert request.extra["runtime_context"] is context
    assert request.extra["db_repo"] is repository
    assert request.extra["relationship_history"] == [{"event": "hello"}]
    assert request.extra["relationship_summary"] == {"trust": 0.5}


@pytest.mark.asyncio
async def test_runtime_context_hot_swap_defers_exactly_once_disposal_until_inflight_turn_finishes() -> None:
    registry = RuntimeContextRegistry()
    old_turn_entered = asyncio.Event()
    release_old_turn = asyncio.Event()
    disposed: list[str] = []

    async def dispose_old() -> None:
        disposed.append("old")

    first = registry.register(
        RuntimeContext(workspace_id="alpha", extras={"generation": "old"}, disposer=dispose_old)
    )

    async def run(ctx: AgentRequestContext) -> AgentPipelineResult:
        generation = str(ctx.extra["generation"])
        if generation == "old":
            old_turn_entered.set()
            await release_old_turn.wait()
        return AgentPipelineResult(reply=generation)

    service = TurnService(
        TurnPorts(run=run, bind_context=registry.bind_request),
    )
    old_turn = asyncio.create_task(
        service.execute_http(
            SemanticTurnRequest(
                session_id="session-old",
                request_id="request-old",
                workspace_id="alpha",
                messages=({"role": "user", "content": "old"},),
            )
        )
    )
    await old_turn_entered.wait()

    registry.swap(
        RuntimeContext(workspace_id="alpha", extras={"generation": "new"}),
        expected_revision=first.revision,
    )
    assert disposed == []

    new_turn = await service.execute_http(
        SemanticTurnRequest(
            session_id="session-new",
            request_id="request-new",
            workspace_id="alpha",
            messages=({"role": "user", "content": "new"},),
        )
    )
    assert new_turn.result.reply == "new"
    assert disposed == []

    release_old_turn.set()
    assert (await old_turn).result.reply == "old"
    assert disposed == ["old"]
    await registry.aclose()
    assert disposed == ["old"]


def test_agent_runtime_turn_service_uses_registered_context_without_breaking_legacy() -> None:
    registry = RuntimeContextRegistry()
    context = registry.register(RuntimeContext(workspace_id="alpha", extras={"marker": "injected"}))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _task: AgentRequestContext(
            sid="scheduler", session_id="s", messages=[], workspace_id="alpha",
        ),
        runtime_context_registry=registry,
    )
    assert runtime.turn_service is not None
    binder = runtime.turn_service.ports.bind_context
    assert binder is not None
    bound = binder(AgentRequestContext(sid="http", session_id="s", messages=[], workspace_id="alpha"))
    assert bound.runtime_context is context
    assert bound.extra["marker"] == "injected"
    legacy = binder(AgentRequestContext(sid="http", session_id="s", messages=[]))
    assert legacy.runtime_context is None


@pytest.mark.asyncio
async def test_perception_provider_requires_explicit_permission_and_bounds_evidence() -> None:
    requests: list[str] = []
    registry = PerceptionProviderRegistry(permission_checker=lambda request, _spec: request.workspace_id == "alpha")
    registry.register(CallablePerceptionProvider(
        PerceptionProviderSpec(
            name="window-shot",
            capability="screenshot",
            ttl_seconds=3,
            max_payload_bytes=100,
            supports_redaction=True,
        ),
        lambda request: requests.append(request.turn_id) or {"payload": {"title": "Editor"}},
    ))
    evidence = await registry.collect(
        "window-shot",
        PerceptionRequest(workspace_id="alpha", session_id="s1", turn_id="t1", capability="screenshot"),
    )

    assert evidence.workspace_id == "alpha"
    assert evidence.turn_id == "t1"
    assert evidence.redacted is False
    assert evidence.expired is False
    assert requests == ["t1"]

    with pytest.raises(PerceptionPermissionError):
        await registry.collect(
            "window-shot",
            PerceptionRequest(workspace_id="beta", session_id="s1", turn_id="t2", capability="screenshot"),
        )


@pytest.mark.asyncio
async def test_perception_provider_rejects_oversized_payload_and_wrong_capability() -> None:
    registry = PerceptionProviderRegistry(permission_checker=lambda *_args: True)
    registry.register(CallablePerceptionProvider(
        PerceptionProviderSpec(name="clipboard", capability="clipboard", max_payload_bytes=4),
        lambda _request: {"payload": "too large"},
    ))
    with pytest.raises(Exception, match="exceeds"):
        await registry.collect(
            "clipboard",
            PerceptionRequest(workspace_id="alpha", session_id="s", turn_id="t", capability="clipboard"),
        )
    with pytest.raises(Exception, match="does not support"):
        await registry.collect(
            "clipboard",
            PerceptionRequest(workspace_id="alpha", session_id="s", turn_id="t", capability="ocr"),
        )
