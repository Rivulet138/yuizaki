from __future__ import annotations

from typing import Any

import pytest
from modules.agent.context import AgentRequestContext
from modules.agent.execution_stage import ExecutionStage
from modules.agent.planner import PlanResult, PlanStep
from modules.core.state import Generation


class _Executor:
    max_tool_retries = 2

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result
        self.executed_steps: list[Any] = []

    def adapt_legacy_plan(self, steps: list[PlanStep]) -> list[PlanStep]:
        return steps

    async def execute_plan(self, _ctx: AgentRequestContext, steps: list[Any]) -> dict[str, object]:
        self.executed_steps = steps
        return self.result


class _StreamingExecutor:
    max_tool_retries = 1

    def __init__(self, result: dict[str, object] | None = None) -> None:
        self.result = result or {}

    def adapt_legacy_plan(self, steps: list[PlanStep]) -> list[PlanStep]:
        return steps

    def preflight_plan(self, _ctx: AgentRequestContext, _steps: list[Any]) -> object:
        return object()

    async def execute_immediate_steps(
        self,
        _ctx: AgentRequestContext,
        _steps: list[Any],
        **_kwargs: Any,
    ) -> dict[str, object]:
        return self.result


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


def test_execution_stage_shares_autonomy_slicing_with_streaming_path() -> None:
    schedule = PlanStep(id="schedule", title="Later", kind="schedule")
    immediate = PlanStep(id="agent", title="Now", kind="agent")
    plan = PlanResult(goal="mixed", mode="scheduled_once", steps=[schedule, immediate])
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        autonomy_mode="assistant",
        step_executor=_Executor({}),  # type: ignore[arg-type]
    )

    prepared = ExecutionStage.prepare_plan(ctx, plan)

    assert [step.id for step in prepared.steps] == ["agent"]
    assert [step.id for step in prepared.immediate_steps] == ["agent"]
    assert prepared.scheduled_steps == []
    assert prepared.mode == "immediate"


@pytest.mark.asyncio
async def test_execution_stage_projects_schedule_and_terminal_metadata() -> None:
    schedule = PlanStep(id="schedule", title="Reminder", kind="schedule")
    plan = PlanResult(
        goal="remind",
        mode="scheduled_once",
        delay_seconds=60,
        steps=[schedule],
    )
    executor = _Executor({
        "reply": "",
        "tool_calls": [],
        "step_results": [{
            "step_id": "schedule",
            "kind": "schedule",
            "status": "created",
            "task_id": "task-1",
        }],
        "execution_summary": {"status": "completed"},
        "configured_budget": {"tool_budget": 4},
        "consumed_usage": {"tool_calls": 0},
    })
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        request_id="request",
        messages=[],
        step_executor=executor,  # type: ignore[arg-type]
    )

    result = await ExecutionStage().run(
        ctx,
        plan,
        append_runtime_loop=lambda *_args, **_kwargs: None,
    )

    assert result.reply == "已为你创建一次性任务，将在 60 秒后执行。"
    assert result.outcome == "completed"
    assert result.configured_budget == {"tool_budget": 4}
    assert result.action_envelope is not None
    trace = result.action_envelope["actions"][-1]["payload"][0]
    assert trace["scheduled_tasks"] == ["task-1"]
    assert trace["execution_policy"]["tool_retry_limit"] == 2


@pytest.mark.asyncio
async def test_execution_stage_refuses_tool_plan_in_reflector_mode() -> None:
    tool = PlanStep(id="tool", title="Write", kind="tool")
    plan = PlanResult(goal="write", steps=[tool])
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        autonomy_mode="reflector",
        step_executor=_Executor({}),  # type: ignore[arg-type]
    )
    events: list[dict[str, Any]] = []

    result = await ExecutionStage().run(
        ctx,
        plan,
        append_runtime_loop=lambda _ctx, **payload: events.append(payload),
    )

    assert result.reply == "reflector_mode_cannot_execute_tools"
    assert events[0]["stage"] == "decide"
    assert events[0]["status"] == "stopped"


@pytest.mark.asyncio
async def test_streaming_stage_emits_structured_result_in_transport_order() -> None:
    step = PlanStep(id="join", title="Join", kind="join")
    plan = PlanResult(goal="join", steps=[step])
    executor = _StreamingExecutor({
        "reply": "已完成",
        "pet_control": {"emotion_id": "happy"},
        "tool_calls": [],
        "step_results": [{
            "step_id": "join",
            "kind": "join",
            "status": "ok",
            "title": "Join",
            "description": "",
            "depends_on": [],
        }],
        "execution_summary": {"status": "completed"},
    })
    history: list[tuple[str, str, str]] = []
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        step_executor=executor,  # type: ignore[arg-type]
        generation_mgr=type("History", (), {
            "append_history": lambda _self, *args: history.append(args),
        })(),
    )
    generation = Generation(generation_id="generation", session_id="session")
    ws = _WebSocket()

    stage_result = await ExecutionStage().run_streaming(
        ctx,
        plan,
        ws_adapter=ws,
        generation=generation,
    )
    result = stage_result.result

    assert result.reply == "已完成"
    assert generation.full_text == "已完成"
    assert generation.pet_control == {"emotion_id": "happy"}
    assert ws.messages == []
    assert history == []
    assert stage_result.reply_emitted is False
    assert stage_result.persist_history is True


@pytest.mark.asyncio
async def test_streaming_stage_falls_back_to_plain_llm_stream() -> None:
    class _LLM:
        async def stream_chat(
            self,
            ws: Any,
            generation: Generation,
            _generation_mgr: Any,
            _messages: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> None:
            assert callable(getattr(ws, "send_json", None))
            generation.tokens = ["自然回复"]

    step = PlanStep(id="agent", title="Reply", kind="agent")
    plan = PlanResult(goal="reply", steps=[step])
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "你好"}],
        step_executor=_StreamingExecutor(),  # type: ignore[arg-type]
        llm_client=_LLM(),
        generation_mgr=object(),
    )
    generation = Generation(generation_id="generation", session_id="session")

    stage_result = await ExecutionStage().run_streaming(
        ctx,
        plan,
        ws_adapter=None,
        generation=generation,
    )
    result = stage_result.result

    assert result.reply == "自然回复"
    assert result.configured_budget["max_iterations"] == 1
    assert result.consumed_usage["output_tokens"] == 1
