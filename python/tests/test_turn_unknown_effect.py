from __future__ import annotations

import asyncio
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

import pytest

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.pipeline import AgentPipeline
from modules.agent.planner import PlanResult, ToolStep
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_loop import run_streaming_tool_loop, run_tool_loop
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore


def _registry(handler: Any) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo.write",
        description="write once",
        source="builtin",
        parameters={"type": "object"},
        handler=handler,
        risk_level="safe",
    ))
    return registry


@pytest.mark.asyncio
async def test_async_cancellation_after_dispatch_is_unknown_and_nonretryable() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    cancel = asyncio.Event()
    effects: list[str] = []

    async def handler(_args: dict[str, Any]) -> ToolResultEnvelope:
        effects.append("dispatched")
        started.set()
        await release.wait()
        return ToolResultEnvelope(
            success=True, content="done", source="builtin", tool_name="demo.write"
        )

    registry = _registry(handler)
    executor = ToolExecutor(registry)
    task = asyncio.create_task(executor.execute(
        "demo.write", {}, cancellation_signal=cancel,
    ))
    await started.wait()
    cancel.set()
    outcome = await asyncio.wait_for(task, timeout=1)
    release.set()

    assert effects == ["dispatched"]
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False
    assert outcome.success is False


@pytest.mark.asyncio
async def test_provider_failure_before_dispatch_stays_known_and_retryable() -> None:
    effects: list[str] = []
    registry = _registry(lambda _args: effects.append("dispatched"))

    class BrokenPolicy:
        def evaluate_tool(self, _tool: Any, **_kwargs: Any) -> Any:
            raise OSError("provider unavailable")

    outcome = await ToolExecutor(registry, BrokenPolicy()).execute(  # type: ignore[arg-type]
        "demo.write", {},
    )

    assert effects == []
    assert outcome.outcome == "known_failure"
    assert outcome.retryable is True
    assert outcome.data == {"code": "TOOL_PRE_DISPATCH_FAILURE"}


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [RuntimeError, asyncio.TimeoutError])
async def test_effect_then_exception_replays_durable_unknown_turn_without_duplicate_effect(
    tmp_path: Path,
    exception_type: type[Exception],
) -> None:
    effects: list[str] = []

    async def handler(_args: dict[str, Any]) -> ToolResultEnvelope:
        effects.append("external-effect")
        raise exception_type("handler failed after effect")

    executor = ToolExecutor(_registry(handler))
    store = TurnCommitStore(tmp_path / f"{exception_type.__name__}-turns.sqlite3")

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        tool_result = await executor.execute("demo.write", {})
        assert tool_result.outcome == "unknown_effect"
        return AgentPipelineResult(
            reply="manual recovery required",
            tool_calls=[{
                "tool": "demo.write",
                "outcome": tool_result.outcome,
                "retryable": tool_result.retryable,
            }],
            outcome="unknown_effect",
            retryable=False,
            configured_budget={"tool_budget": 1},
            consumed_usage={"tool_calls": 1, "stop_reason": "unknown_effect"},
        )

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    request = SemanticTurnRequest(
        session_id="unknown-effect-session",
        request_id="unknown-effect-request",
        turn_id="unknown-effect-turn",
        generation_id="unknown-effect-generation",
        messages=[{"role": "user", "content": "write exactly once"}],
    )

    first = await service().execute_http(request)
    replay = await service().execute_http(request)

    assert first.persisted is True
    assert first.replayed is False
    assert first.outcome == "unknown_effect"
    assert first.retryable is False
    assert replay.replayed is True
    assert replay.outcome == "unknown_effect"
    assert replay.retryable is False
    assert replay.result.tool_calls == first.result.tool_calls
    assert effects == ["external-effect"]


class _UnknownExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.registry = _registry(lambda _args: None)

    def preview_policy(self, _name: str, _args: dict[str, Any], **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(allowed=True, require_confirm=False, reason="test_safe")

    async def execute(self, name: str, _args: dict[str, Any], **_kwargs: Any) -> ToolResultEnvelope:
        self.calls += 1
        return ToolResultEnvelope(
            success=False,
            content="",
            source="builtin",
            tool_name=name,
            error="effect may have happened",
            outcome="unknown_effect",
            retryable=False,
        )


@pytest.mark.asyncio
async def test_unknown_step_executes_once_stops_plan_and_has_no_resume_token() -> None:
    executor = _UnknownExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], tool_executor=executor,
    )
    steps = [
        ToolStep(
            id="first", title="first", tool_name="demo.write",
            arguments={}, retry_budget=1, retry_owner="step_executor",
        ),
        ToolStep(
            id="second", title="second", tool_name="demo.write",
            arguments={}, depends_on=["first"],
        ),
    ]

    result = await StepExecutor().execute_plan(ctx, steps)

    assert executor.calls == 1
    assert result["step_results"][0]["status"] == "unknown_effect"
    assert result["execution_summary"]["stopped_reason"] == "unknown_effect"
    assert result["failure"]["retryable"] is False
    assert "resume_token" not in result
    assert result["consumed_usage"] == {
        "iterations": 0,
        "output_tokens": 0,
        "retries": 0,
        "tool_calls": 1,
        "attempts": 1,
        "stop_reason": "unknown_effect",
    }


class _LoopExecutor:
    async def execute(self, name: str, _args: dict[str, Any], **_kwargs: Any) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            success=True, content="ok", source="builtin", tool_name=name,
        )


class _NonStreamingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_chat(self, _messages: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "reply": "",
                "usage": {"completion_tokens": 3},
                "tool_calls": [{
                    "id": "one",
                    "function": {"name": "demo_write", "arguments": "{}"},
                }],
            }
        return {"reply": "done", "tool_calls": [], "usage": {"completion_tokens": 5}}


class _StreamingClient:
    streaming_tool_calls_supported = True

    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat_with_tools(
        self, _messages: list[dict[str, Any]], **_kwargs: Any,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "reply": "",
                "usage": {"completion_tokens": 3},
                "tool_calls": [{
                    "id": "one",
                    "function": {"name": "demo_write", "arguments": "{}"},
                }],
            }
        return {"reply": "done", "tool_calls": [], "usage": {"completion_tokens": 5}}


@pytest.mark.asyncio
async def test_streaming_and_nonstreaming_budget_records_have_exact_parity() -> None:
    registry = _registry(lambda _args: None)
    budget = {
        "max_iterations": 2,
        "max_output_tokens": 64,
        "retry_budget": 1,
        "tool_budget": 2,
    }
    nonstream = await run_tool_loop(
        _NonStreamingClient(), [], tool_registry=registry,
        tool_executor=_LoopExecutor(), **budget,
    )
    streaming = await run_streaming_tool_loop(
        _StreamingClient(), [], tool_registry=registry,
        tool_executor=_LoopExecutor(), **budget,
    )

    assert streaming is not None
    assert streaming["configured_budget"] == nonstream["configured_budget"]
    assert streaming["consumed_usage"] == nonstream["consumed_usage"] == {
        "iterations": 2,
        "output_tokens": 8,
        "retries": 0,
        "tool_calls": 1,
        "attempts": 1,
        "stop_reason": "completed",
    }


@pytest.mark.asyncio
async def test_pipeline_projects_unknown_effect_and_budget_without_translation() -> None:
    step = ToolStep(id="unknown", title="unknown", tool_name="demo.write", arguments={})
    plan = PlanResult(
        goal="write", steps=[step], immediate_steps=[step], mode="immediate",
    )
    payload = {
        "reply": "uncertain",
        "pet_control": None,
        "tool_calls": [{"tool": "demo.write", "outcome": "unknown_effect"}],
        "step_results": [{"step_id": "unknown", "status": "unknown_effect"}],
        "execution_summary": {"status": "failed", "stopped_reason": "unknown_effect"},
        "configured_budget": {
            "max_iterations": 0, "output_tokens": 32,
            "retry_budget": 0, "tool_budget": 1,
        },
        "consumed_usage": {
            "iterations": 0, "output_tokens": 0, "retries": 0,
            "tool_calls": 1, "attempts": 1, "stop_reason": "unknown_effect",
        },
    }

    class StubStepExecutor:
        max_tool_retries = 0

        async def execute_plan(self, _ctx: AgentRequestContext, _steps: list[Any]) -> dict[str, Any]:
            return payload

    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], max_tokens=32,
        step_executor=StubStepExecutor(),  # type: ignore[arg-type]
    )
    pipeline = AgentPipeline()

    async def prepare(_self: AgentPipeline, candidate: AgentRequestContext) -> tuple[AgentRequestContext, PlanResult]:
        return candidate, plan

    pipeline.prepare_context = MethodType(prepare, pipeline)  # type: ignore[method-assign]
    result: AgentPipelineResult = await pipeline.run(ctx)

    assert result.outcome == "unknown_effect"
    assert result.retryable is False
    assert result.configured_budget == payload["configured_budget"]
    assert result.consumed_usage == payload["consumed_usage"]
