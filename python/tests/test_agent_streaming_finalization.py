from __future__ import annotations

from typing import Any, cast

import pytest
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.pipeline import AgentPipeline
from modules.agent.planner import (
    PlanResult,
    PlanStep,
    PlanValidationError,
    ScheduleStep,
)
from modules.core.state import Generation


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


class _History:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def append_history(self, *args: str) -> None:
        self.items.append(cast(tuple[str, str, str], args))


class _Executor:
    max_tool_retries = 0

    def __init__(self, result: dict[str, object] | None = None, *, invalid: bool = False) -> None:
        self.result = result or {}
        self.invalid = invalid

    def adapt_legacy_plan(self, steps: list[PlanStep]) -> list[PlanStep]:
        return steps

    def preflight_plan(self, _ctx: AgentRequestContext, _steps: list[Any]) -> object:
        if self.invalid:
            raise PlanValidationError("broken dependency")
        return object()

    async def execute_immediate_steps(
        self,
        _ctx: AgentRequestContext,
        _steps: list[Any],
        **_kwargs: Any,
    ) -> dict[str, object]:
        return self.result

    async def execute_schedule_steps(self, _ctx: AgentRequestContext, steps: list[Any], **_kwargs: Any) -> list[Any]:
        return [
            type("ScheduleResult", (), {
                "to_dict": lambda _self, step=step: {
                    "step_id": step.id,
                    "title": step.title,
                    "kind": "schedule",
                    "status": "created",
                    "success": True,
                    "task_id": "task-1",
                    "mode": getattr(step, "schedule_mode", "once"),
                },
            })()
            for step in steps
        ]


def _pipeline_with_plan(plan: PlanResult) -> AgentPipeline:
    pipeline = AgentPipeline()

    async def prepare_context(ctx: AgentRequestContext) -> tuple[AgentRequestContext, PlanResult]:
        return ctx, plan

    pipeline.prepare_context = prepare_context  # type: ignore[method-assign]
    return pipeline


@pytest.mark.asyncio
async def test_pipeline_emits_only_finalized_structured_reply_and_terminal() -> None:
    class _Plugin:
        async def after_llm(
            self,
            result: AgentPipelineResult,
            _ctx: AgentRequestContext,
        ) -> AgentPipelineResult:
            result.reply = "插件最终回复"
            result.pet_control = None
            return result

        async def before_dispatch(
            self,
            result: AgentPipelineResult,
            _ctx: AgentRequestContext,
        ) -> AgentPipelineResult:
            return result

    step = PlanStep(id="join", title="Join", kind="join")
    plan = PlanResult(goal="join", steps=[step])
    history = _History()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor({
            "reply": "执行阶段回复",
            "pet_control": {"emotion_id": "happy"},
            "tool_calls": [],
            "step_results": [],
        }),  # type: ignore[arg-type]
        generation_mgr=history,
        plugin_manager=_Plugin(),  # type: ignore[arg-type]
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await _pipeline_with_plan(plan).run_streaming(ctx, ws, generation)

    assert result.reply == "插件最终回复"
    assert generation.full_text == "插件最终回复"
    assert generation.pet_control is None
    assert [event["type"] for event in ws.messages] == ["token", "done"]
    assert ws.messages[0]["content"] == "插件最终回复"
    assert ws.messages[-1]["content"] == "插件最终回复"
    assert history.items == [("session", "assistant", "插件最终回复")]


@pytest.mark.asyncio
@pytest.mark.parametrize("executor, expected_reply", [
    (None, "step_executor_not_available"),
    (_Executor(invalid=True), "invalid_plan:broken dependency"),
])
async def test_pipeline_early_execution_errors_emit_exactly_one_terminal(
    executor: _Executor | None,
    expected_reply: str,
) -> None:
    step = PlanStep(id="agent", title="Reply", kind="agent")
    plan = PlanResult(goal="reply", steps=[step])
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=executor,  # type: ignore[arg-type]
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await _pipeline_with_plan(plan).run_streaming(ctx, ws, generation)

    assert result.outcome == "failed"
    assert result.reply == expected_reply
    assert [event["type"] for event in ws.messages] == ["token", "done"]
    assert ws.messages[-1]["outcome"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(("stop_reason", "expected_outcome", "expected_retryable"), [
    ("cancelled", "cancelled", False),
    ("tool_budget_exhausted", "failed", True),
    ("max_iterations", "failed", True),
    ("invalid_stream_adapter_result", "failed", False),
])
async def test_pipeline_projects_tool_loop_stop_reason_and_one_terminal(
    monkeypatch: pytest.MonkeyPatch,
    stop_reason: str,
    expected_outcome: str,
    expected_retryable: bool,
) -> None:
    async def fake_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "reply": "",
            "tool_calls": [],
            "stopped_reason": stop_reason,
            "configured_budget": {"max_iterations": 3, "tool_budget": 8},
            "consumed_usage": {"stop_reason": stop_reason},
        }

    monkeypatch.setattr(
        "modules.agent.execution_stage.run_streaming_tool_loop",
        fake_tool_loop,
    )
    step = PlanStep(id="agent", title="Reply", kind="agent")
    plan = PlanResult(goal="reply", steps=[step])
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=object(),
        generation_mgr=_History(),
        tool_registry=cast(Any, object()),
        tool_executor=cast(Any, object()),
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await _pipeline_with_plan(plan).run_streaming(ctx, ws, generation)

    assert result.outcome == expected_outcome
    assert result.retryable is expected_retryable
    assert len([event for event in ws.messages if event["type"] == "done"]) == 1
    assert ws.messages[-1]["outcome"] == expected_outcome
    if expected_outcome == "failed":
        assert result.failure is not None
        assert result.failure["message"] == stop_reason


@pytest.mark.asyncio
async def test_pipeline_filters_llm_terminal_until_projection() -> None:
    class _LLM:
        async def stream_chat(
            self,
            ws: Any,
            generation: Generation,
            history: Any,
            _messages: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> None:
            generation.tokens = ["模型回复"]
            history.append_history("session", "assistant", "模型回复")
            await ws.send_json({"type": "token", "content": "模型回复"})
            await ws.send_json({
                "type": "pet_control",
                "pet_control": {"emotion_id": "unfiltered"},
            })
            await ws.send_json({"type": "done", "content": "模型回复"})

    step = PlanStep(id="agent", title="Reply", kind="agent")
    plan = PlanResult(goal="reply", steps=[step])
    history = _History()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=_LLM(),
        generation_mgr=history,
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await _pipeline_with_plan(plan).run_streaming(ctx, ws, generation)

    assert result.reply == "模型回复"
    assert [event["type"] for event in ws.messages] == ["token", "done"]
    assert len([event for event in ws.messages if event["type"] == "done"]) == 1
    assert history.items == [("session", "assistant", "模型回复")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exc", "expected_kind", "expected_reason"),
    [
        (ConnectionRefusedError("offline"), "provider", "provider_unavailable"),
        (TimeoutError("slow provider"), "timeout", "provider_timeout"),
    ],
)
async def test_pipeline_projects_provider_runtime_failure_without_fake_history_or_actions(
    exc: Exception,
    expected_kind: str,
    expected_reason: str,
) -> None:
    class _FailingLLM:
        async def stream_chat(self, *_args: Any, **_kwargs: Any) -> None:
            raise exc

    step = PlanStep(id="agent", title="Reply", kind="agent")
    history = _History()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "你好"}],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=_FailingLLM(),
        generation_mgr=history,
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await _pipeline_with_plan(PlanResult(goal="reply", steps=[step])).run_streaming(
        ctx, ws, generation
    )

    assert result.outcome == "failed"
    assert result.retryable is True
    assert result.failure == {
        "kind": expected_kind,
        "message": expected_reason,
        "status": "failed",
        "retryable": True,
    }
    assert result.recovery == {
        "available": True,
        "action": "retry_turn",
        "retryable": True,
        "confirmation_required": False,
        "reason": expected_reason,
    }
    assert result.pet_control is None
    assert result.tool_calls == []
    assert history.items == []
    assert [event["type"] for event in ws.messages] == ["token", "done"]
    assert len([event for event in ws.messages if event["type"] == "done"]) == 1
    assert ws.messages[-1]["outcome"] == "failed"
    assert ws.messages[-1]["retryable"] is True


@pytest.mark.asyncio
async def test_pipeline_does_not_hide_unknown_llm_programming_error() -> None:
    class _BrokenLLM:
        async def stream_chat(self, *_args: Any, **_kwargs: Any) -> None:
            raise ValueError("broken invariant")

    step = PlanStep(id="agent", title="Reply", kind="agent")
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=_BrokenLLM(),
        generation_mgr=_History(),
    )

    with pytest.raises(ValueError, match="broken invariant"):
        await _pipeline_with_plan(PlanResult(goal="reply", steps=[step])).run_streaming(
            ctx,
            _WebSocket(),
            Generation(generation_id="generation", session_id="session"),
        )


@pytest.mark.asyncio
async def test_pipeline_projects_non_retryable_provider_request_rejection() -> None:
    class _RejectedLLM:
        async def stream_chat(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("LLM API 401: unauthorized")

    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=_RejectedLLM(),
        generation_mgr=_History(),
    )
    ws = _WebSocket()

    result = await _pipeline_with_plan(
        PlanResult(goal="reply", steps=[PlanStep(id="agent", title="Reply", kind="agent")])
    ).run_streaming(ctx, ws, Generation(generation_id="generation", session_id="session"))

    assert result.outcome == "failed"
    assert result.retryable is False
    assert result.failure["message"] == "provider_request_rejected"
    assert result.recovery == {
        "available": False,
        "action": "check_provider_settings",
        "retryable": False,
        "confirmation_required": False,
        "reason": "provider_request_rejected",
    }
    assert ws.messages[-1]["outcome"] == "failed"
    assert ws.messages[-1]["retryable"] is False


@pytest.mark.asyncio
async def test_pipeline_recovers_on_next_turn_after_provider_reconnects() -> None:
    class _RecoveringLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def stream_chat(
            self,
            ws: Any,
            generation: Generation,
            _history: Any,
            _messages: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> None:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionRefusedError("offline")
            generation.tokens = ["连接已恢复"]
            await ws.send_json({"type": "token", "content": "连接已恢复"})

    step = PlanStep(id="agent", title="Reply", kind="agent")
    plan = PlanResult(goal="reply", steps=[step])
    history = _History()
    client = _RecoveringLLM()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=_Executor(),  # type: ignore[arg-type]
        llm_client=client,
        generation_mgr=history,
    )
    pipeline = _pipeline_with_plan(plan)

    first = await pipeline.run_streaming(
        ctx,
        _WebSocket(),
        Generation(generation_id="first", session_id="session"),
    )
    second_ws = _WebSocket()
    second = await pipeline.run_streaming(
        ctx,
        second_ws,
        Generation(generation_id="second", session_id="session"),
    )

    assert first.outcome == "failed"
    assert first.retryable is True
    assert second.outcome == "completed"
    assert second.reply == "连接已恢复"
    assert history.items == [("session", "assistant", "连接已恢复")]
    assert [event["type"] for event in second_ws.messages] == ["token", "done"]


@pytest.mark.asyncio
async def test_pipeline_silent_stream_emits_terminal_without_side_effects() -> None:
    pipeline = AgentPipeline()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "do not act"}],
        autonomy_mode="silent",
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    result = await pipeline.run_streaming(ctx, ws, generation)

    assert result.reply == ""
    assert generation.tokens == []
    assert ws.messages == [{
        "type": "done",
        "session_id": "session",
        "generation_id": "generation",
        "content": "",
        "outcome": "completed",
        "retryable": False,
        "stopped_reason": "silent_autonomy_mode",
    }]


@pytest.mark.asyncio
async def test_schedule_only_stream_projects_scheduler_result_without_llm() -> None:
    step = ScheduleStep(
        id="schedule",
        title="提醒",
        schedule_mode="once",
        prompt="提醒我休息",
        run_after_seconds=60,
    )
    plan = PlanResult(goal="提醒", steps=[step], mode="scheduled_once")
    executor = _Executor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=executor,  # type: ignore[arg-type]
        scheduler=object(),
        llm_client=None,
        generation_mgr=None,
    )
    generation = Generation(generation_id="generation", session_id="session")
    result = await _pipeline_with_plan(plan).run_streaming(ctx, None, generation)

    assert "已为你创建一次性任务" in result.reply
    assert result.outcome == "completed"
    payload = result.action_envelope["actions"][-1]["payload"][0]
    assert payload["execution_summary"]["completed_steps"] == 1
    assert payload["step_results"][0]["task_id"] == "task-1"
