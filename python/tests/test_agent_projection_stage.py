from __future__ import annotations

from typing import Any

import pytest
from modules.agent.action_compiler import compile_action_envelope
from modules.agent.context import (
    AgentPipelineResult,
    AgentRequestContext,
    bind_runtime_bindings,
)
from modules.agent.projection_stage import ProjectionStage


@pytest.mark.asyncio
async def test_projection_stage_preserves_trace_suffix_memory_sources_and_reflection() -> None:
    original_calls = [{"name": "read"}]
    suffix = {"execution_summary": {"status": "completed"}}
    result = AgentPipelineResult(
        reply="done",
        tool_calls=original_calls,
        action_envelope=compile_action_envelope(
            reply="done",
            pet_control=None,
            tool_calls=[*original_calls, suffix],
            request_id="request-1",
        ),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        request_id="request-1",
        messages=[],
        extra={"memory_sources": [{"id": "memory-1", "text": "preference"}]},
    )
    bind_runtime_bindings(
        ctx,
        relationship_summary={"relationship_stage": "trusted", "proactive_budget": 2},
        relationship_history=[{"kind": "gratitude"}],
        retrieved_chunks=["preference"],
    )
    events: list[dict[str, Any]] = []

    projected = await ProjectionStage().run(
        ctx,
        result,
        append_runtime_loop=lambda _ctx, **payload: events.append(payload),
    )

    assert projected.action_envelope is not None
    tool_trace = next(action for action in projected.action_envelope["actions"] if action["type"] == "tool_trace")
    memory_trace = next(action for action in projected.action_envelope["actions"] if action["type"] == "memory_trace")
    assert tool_trace["payload"] == [*original_calls, suffix]
    assert memory_trace["payload"] == [{"id": "memory-1", "text": "preference"}]
    assert [event["stage"] for event in events] == ["ask_act", "reflect", "update_relationship"]
    assert events[1]["data"]["relationship_stage"] == "trusted"
    assert events[2]["data"] == {"relationship_history_count": 1, "retrieved_chunk_count": 1}


@pytest.mark.asyncio
async def test_projection_stage_never_makes_unknown_effect_retryable() -> None:
    result = AgentPipelineResult(reply="uncertain", outcome="unknown_effect")
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[])

    projected = await ProjectionStage().run(
        ctx,
        result,
        append_runtime_loop=lambda *_args, **_kwargs: None,
    )

    assert projected.retryable is False


@pytest.mark.asyncio
async def test_projection_stage_reapplies_unknown_effect_invariant_after_plugin() -> None:
    class Plugin:
        async def after_llm(self, _result: AgentPipelineResult, _ctx: AgentRequestContext) -> AgentPipelineResult:
            result = AgentPipelineResult(reply="uncertain", outcome="unknown_effect")
            result.retryable = True
            return result

        async def before_dispatch(self, result: AgentPipelineResult, _ctx: AgentRequestContext) -> AgentPipelineResult:
            return result

    result = AgentPipelineResult(reply="draft")
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        plugin_manager=Plugin(),  # type: ignore[arg-type]
    )

    projected = await ProjectionStage().run(
        ctx,
        result,
        append_runtime_loop=lambda *_args, **_kwargs: None,
    )

    assert projected.outcome == "unknown_effect"
    assert projected.retryable is False
