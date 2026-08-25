from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from modules.agent import step_executor as step_executor_module
from modules.agent.context import AgentRequestContext
from modules.agent.models import StepResultRecord
from modules.agent.pipeline import AgentPipeline
from modules.agent.planner import (
    AgentStep,
    AnalysisStep,
    JoinStep,
    Planner,
    PlanResult,
    PlanStep,
    PlanStepUnion,
    PlanValidationError,
    PredicateNode,
    ScheduleStep,
    StepCondition,
    ToolStep,
    validate_plan,
)
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_result import ToolResultEnvelope


def test_plan_accepts_all_typed_kinds_and_serializes_tool_contract() -> None:
    steps = [
        PlanStep(id="analysis", title="Analyze", kind="analysis"),
        PlanStep(id="agent", title="Agent", kind="agent", depends_on=["analysis"]),
        PlanStep(
            id="tool",
            title="Tool",
            kind="tool",
            tool_name="browser.open_page",
            arguments={"url": "https://example.com"},
            depends_on=["agent"],
        ),
        PlanStep(id="schedule", title="Schedule", kind="schedule", depends_on=["tool"]),
        PlanStep(id="join", title="Join", kind="join", depends_on=["schedule"]),
    ]
    validate_plan(steps)
    assert steps[2].to_dict()["tool_name"] == "browser.open_page"
    assert steps[2].to_dict()["arguments"] == {"url": "https://example.com"}


def test_predicate_rejects_unknown_fields_and_executable_eval() -> None:
    step = PlanStep(
        id="a",
        title="A",
        kind="agent",
        success_criteria={"op": "status_in", "values": ["ok"], "eval": "__import__('os')"},
    )
    with pytest.raises(PlanValidationError):
        validate_plan([step])

    with pytest.raises(PlanValidationError):
        validate_plan([PlanStep(id="a", title="A", kind="agent", success_criteria=PredicateNode(op="eval"))])


def test_plan_rejects_dependency_cycles_and_budget_overruns() -> None:
    cycle = [
        PlanStep(id="a", title="A", kind="agent", depends_on=["b"]),
        PlanStep(id="b", title="B", kind="agent", depends_on=["a"]),
    ]
    with pytest.raises(PlanValidationError, match="cycle"):
        validate_plan(cycle)

    with pytest.raises(PlanValidationError, match="step budget"):
        validate_plan([PlanStep(id=str(index), title="step", kind="analysis") for index in range(2)], max_steps=1)

    with pytest.raises(PlanValidationError, match="retry budget"):
        validate_plan([PlanStep(id="a", title="A", kind="tool", retry_budget=2)], max_retry_budget=1)

    with pytest.raises(PlanValidationError, match="timeout budget"):
        validate_plan([PlanStep(id="a", title="A", kind="tool", timeout_seconds=10)], max_timeout_seconds=5)


def test_legacy_prompt_is_adapted_to_typed_browser_contract() -> None:
    prompt = "open https://example.com"
    plan = Planner().plan(prompt)
    tool_steps = [step for step in plan.steps if step.kind == "tool"]
    assert tool_steps
    assert tool_steps[0].payload is None
    assert tool_steps[0].plan_version == 2
    assert tool_steps[0].compatibility_trace is None
    assert tool_steps[0].tool_name == "browser.open_page"
    assert tool_steps[0].arguments == {"url": "https://example.com"}


class _RecordingToolExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.run_ids: list[str | None] = []
        self.registry = _Registry(SimpleNamespace(
            name="browser.open_page",
            description="Open a browser page",
            parameters={"type": "object", "additionalProperties": True},
            risk_level="safe",
            require_confirm=False,
        ))

    def preview_policy(
        self,
        tool_name: str,
        _args: dict[str, Any],
        **_kwargs: Any,
    ) -> SimpleNamespace:
        definition = self.registry.get(tool_name)
        if definition is None:
            raise RuntimeError(f"unknown test tool: {tool_name}")
        require_confirm = bool(
            getattr(definition, "require_confirm", False)
            or getattr(definition, "risk_level", "safe") in {"medium", "high", "critical"}
        )
        return SimpleNamespace(
            allowed=not require_confirm,
            require_confirm=require_confirm,
            reason="permission_required" if require_confirm else "test_safe",
        )

    async def execute(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> ToolResultEnvelope:
        self.calls.append((tool_name, args))
        self.run_ids.append(kwargs.get("run_id"))
        # The real ToolExecutor is the policy boundary. This fake models its
        # envelope while proving StepExecutor forwards the typed request.
        assert "permission_request_cb" in kwargs
        return ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name=tool_name)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": {"not", "json"}},
        {"value": b"not-json"},
        {1: "non-string-key"},
    ],
)
async def test_non_canonical_tool_arguments_fail_closed_before_handler(
    arguments: object,
) -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="strict-json",
        messages=[],
        tool_executor=tool_executor,
    )
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        arguments=arguments,  # type: ignore[arg-type]
    )

    result = await StepExecutor().execute_plan(ctx, [step])

    assert result["error"].startswith("invalid_plan:")
    assert result["step_results"] == []
    assert tool_executor.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("retry_budget", True),
        ("retry_budget", 1.0),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", "30"),
        ("idempotency_key", ""),
        ("idempotency_key", 7),
    ],
)
async def test_invalid_tool_control_fields_fail_closed_before_handler(
    field: str,
    value: object,
) -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="strict-controls",
        messages=[],
        tool_executor=tool_executor,
    )
    kwargs: dict[str, Any] = {
        "id": "tool",
        "title": "Tool",
        "tool_name": "browser.open_page",
        field: value,
    }
    step = ToolStep(**kwargs)

    result = await StepExecutor().execute_plan(ctx, [step])

    assert result["error"].startswith("invalid_plan:")
    assert result["step_results"] == []
    assert tool_executor.calls == []


@pytest.mark.asyncio
async def test_typed_tool_uses_tool_executor_and_does_not_infer_prompt() -> None:
    tool_executor = _RecordingToolExecutor()
    step_executor = StepExecutor()
    step_executor._infer_tool_call = lambda _prompt: (_ for _ in ()).throw(AssertionError("legacy inference used"))  # type: ignore[method-assign]
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        tool_executor=tool_executor,
    )
    step = ToolStep(
        id="tool",
        title="Open",
        description="untrusted prompt",
        tool_name="browser.open_page",
        arguments={"url": "https://example.com"},
    )
    capability = step_executor.preflight_plan(ctx, [step])
    result = (await step_executor.execute_tool_steps(
        ctx, [step], validation_capability=capability
    ))[0]
    assert result.success is True
    assert tool_executor.calls == [("browser.open_page", {"url": "https://example.com"})]


@pytest.mark.asyncio
async def test_tool_run_id_is_canonical_and_context_scoped() -> None:
    tool_executor = _RecordingToolExecutor()

    async def execute(
        arguments: dict[str, Any],
        turn_id: str,
        *,
        workspace_id: str = "workspace",
        session_id: str = "session",
    ) -> str | None:
        ctx = AgentRequestContext(
            sid="sid",
            workspace_id=workspace_id,
            session_id=session_id,
            request_id=f"request-{len(tool_executor.run_ids)}",
            turn_id=turn_id,
            messages=[],
            tool_executor=tool_executor,
        )
        step = ToolStep(
            id="tool",
            title="Open",
            tool_name="browser.open_page",
            arguments=arguments,
        )
        runner = StepExecutor()
        capability = runner.preflight_plan(ctx, [step])
        await runner.execute_tool_steps(ctx, [step], validation_capability=capability)
        return tool_executor.run_ids[-1]

    first = await execute({"url": "https://example.com", "options": {"b": 2, "a": 1}}, "turn-1")
    reordered = await execute({"options": {"a": 1, "b": 2}, "url": "https://example.com"}, "turn-1")
    next_turn = await execute({"url": "https://example.com", "options": {"a": 1, "b": 2}}, "turn-2")
    next_session = await execute(
        {"url": "https://example.com", "options": {"a": 1, "b": 2}},
        "turn-1",
        session_id="session-2",
    )
    next_workspace = await execute(
        {"url": "https://example.com", "options": {"a": 1, "b": 2}},
        "turn-1",
        workspace_id="workspace-2",
    )

    assert first == reordered
    assert first != next_turn
    assert first != next_session
    assert first != next_workspace
    assert first is not None and first.startswith("plan-v2:")


@pytest.mark.asyncio
async def test_batch_typed_tool_uses_contract_before_prompt_fallback() -> None:
    tool_executor = _RecordingToolExecutor()
    step_executor = StepExecutor()
    step_executor._infer_tool_call = lambda _prompt: (_ for _ in ()).throw(AssertionError("legacy inference used"))  # type: ignore[method-assign]
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        tool_executor=tool_executor,
    )
    step = ToolStep(
        id="tool",
        title="Open",
        description="untrusted prompt",
        tool_name="browser.open_page",
        arguments={"url": "https://example.com"},
    )

    capability = step_executor.preflight_plan(ctx, [step])
    results = await step_executor.execute_tool_steps(
        ctx, [step], validation_capability=capability
    )

    assert results[0].success is True
    assert tool_executor.calls == [("browser.open_page", {"url": "https://example.com"})]


class _FailingToolExecutor:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.registry = _Registry(SimpleNamespace(
            name="browser.open_page",
            description="Open a browser page",
            parameters={"type": "object", "additionalProperties": True},
            risk_level="safe",
            require_confirm=False,
        ))

    def preview_policy(
        self,
        tool_name: str,
        _args: dict[str, Any],
        **_kwargs: Any,
    ) -> SimpleNamespace:
        if self.registry.get(tool_name) is None:
            raise RuntimeError(f"unknown test tool: {tool_name}")
        return SimpleNamespace(allowed=True, require_confirm=False, reason="test_safe")

    async def execute(self, tool_name: str, _args: dict[str, Any], **_kwargs: Any) -> ToolResultEnvelope:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return ToolResultEnvelope(
            success=False,
            content="",
            source="builtin",
            tool_name=tool_name,
            error="failed",
        )


@pytest.mark.asyncio
async def test_zero_retry_budget_executes_tool_only_once() -> None:
    tool_executor = _FailingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        tool_executor=tool_executor,
    )
    step = ToolStep(
        id="tool",
        title="No retry",
        tool_name="write_file",
        arguments={"path": "x"},
        retry_budget=0,
    )

    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])
    result = (await runner.execute_tool_steps(
        ctx, [step], validation_capability=capability
    ))[0]

    assert result.success is False
    assert result.retry_count == 0
    assert tool_executor.calls == 1


@pytest.mark.asyncio
async def test_timed_out_tool_is_not_automatically_retried() -> None:
    tool_executor = _FailingToolExecutor(delay=0.05)
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        tool_executor=tool_executor,
    )
    step = ToolStep(
        id="tool",
        title="Timeout",
        tool_name="write_file",
        arguments={"path": "x"},
        timeout_seconds=0.001,
        retry_budget=3,
    )

    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])
    result = (await runner.execute_tool_steps(
        ctx, [step], validation_capability=capability
    ))[0]

    assert result.error == "tool_timeout"
    assert result.retry_count == 0
    assert tool_executor.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("step_count", range(1, 6))
async def test_valid_one_to_five_step_fixtures_complete(step_count: int) -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    steps = [
        ToolStep(
            id=f"tool-{index}",
            title=f"步骤 {index}",
            tool_name="browser.open_page",
            arguments={"url": f"https://example.com/{index}"},
            depends_on=[f"tool-{index - 1}"] if index else [],
        )
        for index in range(step_count)
    ]

    response = await StepExecutor().execute_plan(ctx, steps)

    assert response["execution_summary"]["status"] == "completed"
    assert len(tool_executor.calls) == step_count


class _Registry:
    def __init__(self, definition: object | None) -> None:
        self.definition = definition

    def get(self, _name: str) -> object | None:
        return self.definition

    def list(self) -> list[object]:
        return [self.definition] if self.definition is not None else []


class _RegistryToolExecutor(_RecordingToolExecutor):
    def __init__(self, definition: object | None) -> None:
        super().__init__()
        self.registry = _Registry(definition)


@pytest.mark.asyncio
async def test_unknown_and_schema_invalid_tools_execute_zero_handlers() -> None:
    unknown_executor = _RegistryToolExecutor(None)
    unknown_ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=unknown_executor)
    unknown = ToolStep(id="unknown", title="Unknown", tool_name="missing.tool")
    response = await StepExecutor().execute_plan(unknown_ctx, [unknown])
    assert response["error"].startswith("invalid_plan:unknown tool")
    assert unknown_executor.calls == []

    definition = SimpleNamespace(
        parameters={
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
            "additionalProperties": False,
        },
        risk_level="high",
        require_confirm=True,
    )
    schema_executor = _RegistryToolExecutor(definition)
    schema_ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=schema_executor)
    invalid = ToolStep(id="invalid", title="Invalid", tool_name="write_file", arguments={"path": 3})
    response = await StepExecutor().execute_plan(schema_ctx, [invalid])
    assert response["error"].startswith("invalid_plan:tool write_file arguments.path has invalid type")
    assert schema_executor.calls == []


@pytest.mark.asyncio
async def test_ambiguous_dangerous_plan_executes_zero_tools() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    plan = Planner().plan("删除文件")
    response = await StepExecutor().execute_plan(ctx, plan.steps)
    assert plan.outcome == "clarification_required"
    assert response["tool_calls"] == []
    assert tool_executor.calls == []


@pytest.mark.asyncio
async def test_non_executor_retry_owner_cannot_multiply_attempts() -> None:
    definition = SimpleNamespace(parameters={}, risk_level="safe", require_confirm=False)
    tool_executor = _RegistryToolExecutor(definition)
    failing = _FailingToolExecutor()
    tool_executor.execute = failing.execute  # type: ignore[method-assign]
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    step = ToolStep(
        id="tool",
        title="Single owner",
        tool_name="browser.open_page",
        arguments={"url": "https://example.com"},
        retry_budget=3,
        retry_owner="provider",
    )
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])
    result = (await runner.execute_tool_steps(
        ctx, [step], validation_capability=capability
    ))[0]
    assert result.retry_count == 0
    assert failing.calls == 1


class _TraceStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def append(self, category: str, record: dict[str, Any]) -> None:
        self.records.append((category, record))


@pytest.mark.asyncio
async def test_legacy_execution_emits_compatibility_trace() -> None:
    trace_store = _TraceStore()
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], tool_executor=tool_executor, trace_store=trace_store
    )
    legacy_step = PlanStep(
        id="legacy", title="兼容执行", kind="tool", payload={"prompt": "open https://example.com"},
        tool_name="browser.open_page", arguments={"url": "https://example.com"},
    )
    runner = StepExecutor()
    step = runner.adapt_legacy_plan([legacy_step])[0]
    capability = runner.preflight_plan(ctx, [step])
    await runner.execute_tool_steps(ctx, [step], validation_capability=capability)
    compatibility = [record for category, record in trace_store.records if category == "compatibility"]
    assert compatibility[0]["adapter"] == "legacy_plan_step"
    assert compatibility[0]["plan_version"] == 2


@pytest.mark.asyncio
async def test_false_predicate_ast_skips_tool_without_side_effect() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    analysis = AnalysisStep(id="analysis", title="分析")
    tool = ToolStep(
        id="tool",
        title="不应执行",
        tool_name="browser.open_page",
        arguments={"url": "https://example.com"},
        depends_on=[analysis.id],
        condition=StepCondition(
            predicate=PredicateNode(op="status_in", source_step_id=analysis.id, values=["error"]),
        ),
    )
    response = await StepExecutor().execute_plan(ctx, [analysis, tool])
    assert response["step_results"][-1]["status"] == "skipped"
    assert tool_executor.calls == []


def test_predicate_ast_rejects_unknown_source_and_invalid_shape() -> None:
    step = AnalysisStep(
        id="analysis",
        title="分析",
        condition=StepCondition(predicate={"op": "status_in", "source_step_id": "missing", "values": ["ok"]}),
    )
    with pytest.raises(PlanValidationError, match="unknown step"):
        validate_plan([step])
    with pytest.raises(PlanValidationError, match="combinators"):
        validate_plan([
            AnalysisStep(
                id="a",
                title="A",
                condition=StepCondition(predicate={"op": "all", "values": ["ok"], "children": []}),
            )
        ])


@pytest.mark.asyncio
async def test_external_dependency_requires_validated_completed_predecessor_proof() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    analysis = AnalysisStep(id="analysis", title="Analyze")
    tool = ToolStep(
        id="tool", title="Tool", tool_name="browser.open_page",
        arguments={"url": "https://example.com"}, depends_on=[analysis.id],
    )
    rejected = await StepExecutor().execute_plan(ctx, [tool])
    assert rejected["error"].startswith("invalid_plan:step tool depends on unknown step")
    assert tool_executor.calls == []

    executor = StepExecutor()
    capability = executor.preflight_plan(ctx, [analysis, tool])
    await executor.execute_analysis_steps(
        ctx, [analysis], validation_capability=capability
    )
    accepted = await executor.execute_immediate_steps(
        ctx, [tool], validation_capability=capability
    )
    assert accepted["execution_summary"]["status"] == "completed"
    assert len(tool_executor.calls) == 1


@pytest.mark.asyncio
async def test_nested_schema_constraints_fail_before_handler() -> None:
    definition = SimpleNamespace(
        parameters={
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object", "required": ["name", "count"],
                        "properties": {
                            "name": {"type": "string", "pattern": "^[a-z]+$", "enum": ["safe"]},
                            "count": {"type": "integer", "minimum": 1, "maximum": 3},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        risk_level="safe",
        require_confirm=False,
    )
    tool_executor = _RegistryToolExecutor(definition)
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    step = ToolStep(id="tool", title="Nested", tool_name="nested", arguments={"items": [{"name": "BAD", "count": 5}]})
    response = await StepExecutor().execute_plan(ctx, [step])
    assert response["error"].startswith("invalid_plan:")
    assert tool_executor.calls == []


class _RecordingScheduler:
    def __init__(self) -> None:
        self.calls = 0

    async def add_once(self, **_kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(id="task")


@pytest.mark.asyncio
async def test_pipeline_preflights_full_plan_before_schedule_side_effect() -> None:
    scheduler = _RecordingScheduler()
    unknown_executor = _RegistryToolExecutor(None)
    schedule = ScheduleStep(
        id="schedule", title="Schedule", run_after_seconds=1, prompt="later"
    )
    dangerous = ToolStep(id="tool", title="Unknown", tool_name="missing.tool")
    plan = PlanResult(
        goal="test", mode="mixed", steps=[schedule, dangerous],
        scheduled_steps=[schedule], immediate_steps=[dangerous],
    )
    pipeline = AgentPipeline()

    async def prepare(ctx: AgentRequestContext) -> tuple[AgentRequestContext, PlanResult]:
        return ctx, plan

    pipeline.prepare_context = prepare  # type: ignore[method-assign]
    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], scheduler=scheduler,
        tool_executor=unknown_executor, step_executor=StepExecutor(),
    )
    result = await pipeline.run(ctx)
    assert result.reply.startswith("invalid_plan:unknown tool")
    assert scheduler.calls == 0
    assert unknown_executor.calls == []


@pytest.mark.asyncio
async def test_pipeline_consumes_clarification_outcome_without_preflight() -> None:
    plan = PlanResult(
        goal="删除文件", outcome="clarification_required",
        clarification_question="请明确文件路径。", refusal_reason="destructive_scope_ambiguous",
    )
    pipeline = AgentPipeline()

    async def prepare(ctx: AgentRequestContext) -> tuple[AgentRequestContext, PlanResult]:
        return ctx, plan

    pipeline.prepare_context = prepare  # type: ignore[method-assign]
    result = await pipeline.run(AgentRequestContext(sid="sid", session_id="session", messages=[]))
    assert result.reply == "请明确文件路径。"
    trace = next(action for action in result.action_envelope["actions"] if action["type"] == "tool_trace")
    assert trace["payload"][0]["plan_outcome"] == "clarification_required"


@pytest.mark.asyncio
async def test_forged_capability_and_post_preflight_schema_mutation_call_zero_tools() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    runner = StepExecutor()
    step = ToolStep(
        id="tool",
        title="Open",
        tool_name="browser.open_page",
        arguments={"url": "https://example.com"},
    )
    capability = runner.preflight_plan(ctx, [step])
    forged = step_executor_module._PlanCapability(capability.payload, "forged")
    with pytest.raises(PlanValidationError, match="capability seal"):
        await runner.execute_tool_steps(ctx, [step], validation_capability=forged)
    assert tool_executor.calls == []

    step.arguments["url"] = 3
    response = await runner.execute_immediate_steps(
        ctx, [step], validation_capability=capability
    )
    assert response["error"].startswith("invalid_plan:step tool changed")
    assert tool_executor.calls == []


@pytest.mark.asyncio
async def test_registry_description_mutation_invalidates_capability() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="registry-description", messages=[], tool_executor=tool_executor
    )
    runner = StepExecutor()
    step = ToolStep(id="tool", title="Tool", tool_name="browser.open_page")
    capability = runner.preflight_plan(ctx, [step])
    definition = tool_executor.registry.definition
    assert definition is not None
    cast(Any, definition).description = "Changed after preflight"

    with pytest.raises(PlanValidationError, match="registry binding changed"):
        await runner.execute_tool_steps(ctx, [step], validation_capability=capability)
    assert tool_executor.calls == []


@pytest.mark.asyncio
async def test_agent_slice_missing_dependency_calls_zero_tool_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_run_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"reply": "unexpected", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[],
        llm_client=object(),
        tool_registry=_Registry(SimpleNamespace(parameters={}, risk_level="safe", require_confirm=False)),
        tool_executor=_RecordingToolExecutor(),
    )
    analysis = AnalysisStep(id="analysis", title="Analyze")
    agent = AgentStep(id="agent", title="Answer", depends_on=[analysis.id])
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [analysis, agent])
    with pytest.raises(PlanValidationError, match="completed predecessor"):
        await runner.execute_agent_steps(
            ctx, [agent], validation_capability=capability
        )
    assert calls == 0


@pytest.mark.asyncio
async def test_public_legacy_trace_is_deduplicated_by_authenticated_plan() -> None:
    trace_store = _TraceStore()
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], tool_executor=tool_executor, trace_store=trace_store
    )
    runner = StepExecutor()
    legacy = PlanStep(
        id="legacy", title="Legacy", kind="tool",
        tool_name="browser.open_page", arguments={"url": "https://example.com"},
    )
    step = runner.adapt_legacy_plan([legacy])[0]
    capability = runner.preflight_plan(ctx, [step])
    await runner.execute_tool_steps(ctx, [step], validation_capability=capability)
    with pytest.raises(PlanValidationError, match="replay is forbidden"):
        await runner.execute_tool_steps(ctx, [step], validation_capability=capability)
    traces = [record for category, record in trace_store.records if category == "compatibility"]
    assert len(traces) == 1


@pytest.mark.asyncio
async def test_predicate_ast_failure_handler_executes_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list[str] = []

    async def fake_run_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        replies.append("handled")
        return {"reply": "handled", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)
    failing = _FailingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="session", messages=[], llm_client=object(),
        tool_registry=failing.registry, tool_executor=failing,
    )
    tool = ToolStep(id="tool", title="Fail", tool_name="browser.open_page")
    handler = AgentStep(
        id="handler",
        title="Handle",
        depends_on=[tool.id],
        condition=StepCondition(
            predicate=PredicateNode(
                op="status_in", source_step_id=tool.id, values=["error"]
            )
        ),
    )
    response = await StepExecutor().execute_plan(ctx, [tool, handler])
    assert replies == ["handled"]
    assert response["reply"] == "handled"


@pytest.mark.asyncio
async def test_capability_boundary_and_ledger_attestation_are_fail_closed() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    runner = StepExecutor()
    first = ToolStep(id="first", title="First", tool_name="browser.open_page", arguments={"url": "https://example.com"})
    second = ToolStep(
        id="second", title="Second", tool_name="browser.open_page",
        arguments={"url": "https://example.org"}, depends_on=[first.id],
    )
    capability = runner.preflight_plan(ctx, [first, second])
    await runner.execute_tool_steps(ctx, [first], validation_capability=capability)
    isolated_ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], tool_executor=tool_executor)
    with pytest.raises(PlanValidationError, match="callback boundary"):
        await runner.execute_tool_steps(isolated_ctx, [second], validation_capability=capability)

    # A caller-mutated result copy cannot turn a failed predecessor into proof.
    failing = _FailingToolExecutor()
    failed_ctx = AgentRequestContext(sid="sid", session_id="failed", messages=[], tool_executor=failing)
    failed = ToolStep(id="failed", title="Failed", tool_name="browser.open_page")
    dependent = ToolStep(
        id="dependent", title="Dependent", tool_name="browser.open_page",
        depends_on=[failed.id],
    )
    failed_capability = runner.preflight_plan(failed_ctx, [failed, dependent])
    returned = await runner.execute_tool_steps(
        failed_ctx, [failed], validation_capability=failed_capability
    )
    returned[0].success = True
    returned[0].status = "ok"
    with pytest.raises(PlanValidationError, match="completed predecessor"):
        await runner.execute_tool_steps(
            failed_ctx, [dependent], validation_capability=failed_capability
        )


def test_forged_typed_discriminant_is_rejected_before_execution() -> None:
    step = ToolStep(id="tool", title="Tool", tool_name="browser.open_page")
    object.__setattr__(step, "kind", "agent")
    with pytest.raises(PlanValidationError, match="concrete type"):
        validate_plan([step])


@pytest.mark.asyncio
async def test_schedule_rollback_requires_attested_result_and_is_one_shot() -> None:
    class Scheduler:
        def __init__(self) -> None:
            self.removed: list[str] = []

        async def add_once(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(id="task-1")

        async def remove_task(self, task_id: str) -> None:
            self.removed.append(task_id)

    scheduler = Scheduler()
    ctx = AgentRequestContext(sid="sid", session_id="session", messages=[], scheduler=scheduler)
    step = ScheduleStep(
        id="schedule", title="Schedule",
        prompt="later", run_after_seconds=1,
    )
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])
    created = await runner.execute_schedule_steps(
        ctx, [step], validation_capability=capability
    )
    forged = StepResultRecord(**created[0].to_dict())
    forged.task_id = "task-forged"
    with pytest.raises(PlanValidationError, match="does not match ledger"):
        await runner.rollback_schedule_results(
            ctx, [forged], validation_capability=capability
        )
    await runner.rollback_schedule_results(
        ctx, created, validation_capability=capability
    )
    with pytest.raises(PlanValidationError, match="already completed"):
        await runner.rollback_schedule_results(
            ctx, created, validation_capability=capability
        )
    assert scheduler.removed == ["task-1"]


@pytest.mark.asyncio
async def test_unsatisfied_success_criteria_blocks_dependent_side_effect() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(sid="sid", session_id="criteria", messages=[], tool_executor=tool_executor)
    first = ToolStep(
        id="first", title="First", tool_name="browser.open_page",
        success_criteria={"op": "content_contains", "values": ["required-output"]},
    )
    second = ToolStep(
        id="second", title="Second", tool_name="browser.open_page",
        depends_on=[first.id],
    )
    response = await StepExecutor().execute_plan(ctx, [first, second])
    assert tool_executor.calls == [("browser.open_page", {})]
    assert response["step_results"][0]["status"] == "error"
    assert response["step_results"][0]["error"] == "success_criteria_not_met"


@pytest.mark.asyncio
async def test_transient_schedule_rollback_can_retry_once() -> None:
    class Scheduler:
        def __init__(self) -> None:
            self.attempts = 0

        async def add_once(self, **_kwargs: Any) -> Any:
            return SimpleNamespace(id="task-1")

        async def remove_task(self, _task_id: str) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transient")

    scheduler = Scheduler()
    ctx = AgentRequestContext(sid="sid", session_id="rollback-retry", messages=[], scheduler=scheduler)
    step = ScheduleStep(id="schedule", title="Schedule")
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])
    created = await runner.execute_schedule_steps(ctx, [step], validation_capability=capability)
    with pytest.raises(RuntimeError, match="transient"):
        await runner.rollback_schedule_results(ctx, created, validation_capability=capability)
    await runner.rollback_schedule_results(ctx, created, validation_capability=capability)
    assert scheduler.attempts == 2


class _OrderedScheduler:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.removed: list[str] = []

    async def add_once(self, **_kwargs: Any) -> Any:
        self.events.append("schedule")
        return SimpleNamespace(id=f"task-{len(self.events)}")

    async def add_interval(self, **_kwargs: Any) -> Any:
        self.events.append("schedule")
        return SimpleNamespace(id=f"task-{len(self.events)}")

    async def remove_task(self, task_id: str) -> None:
        self.removed.append(task_id)


class _OrderedToolExecutor(_RecordingToolExecutor):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def execute(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> ToolResultEnvelope:
        self.events.append("tool")
        return await super().execute(tool_name, args, **kwargs)


def _mixed_context(events: list[str]) -> AgentRequestContext:
    return AgentRequestContext(
        sid="sid",
        session_id="mixed-dag",
        messages=[],
        tool_executor=_OrderedToolExecutor(events),
        scheduler=_OrderedScheduler(events),
    )


@pytest.mark.asyncio
async def test_execute_plan_orders_tool_before_dependent_schedule() -> None:
    events: list[str] = []
    tool = ToolStep(id="tool", title="Tool", tool_name="browser.open_page")
    schedule = ScheduleStep(
        id="schedule", title="Schedule", depends_on=[tool.id]
    )

    result = await StepExecutor().execute_plan(_mixed_context(events), [schedule, tool])

    assert events == ["tool", "schedule"]
    assert [item["step_id"] for item in result["step_results"]] == ["tool", "schedule"]


@pytest.mark.asyncio
async def test_execute_plan_orders_schedule_before_dependent_tool() -> None:
    events: list[str] = []
    schedule = ScheduleStep(id="schedule", title="Schedule")
    tool = ToolStep(
        id="tool", title="Tool", tool_name="browser.open_page", depends_on=[schedule.id]
    )

    result = await StepExecutor().execute_plan(_mixed_context(events), [tool, schedule])

    assert events == ["schedule", "tool"]
    assert [item["step_id"] for item in result["step_results"]] == ["schedule", "tool"]


@pytest.mark.asyncio
async def test_execute_plan_orders_analysis_tool_schedule_chain() -> None:
    events: list[str] = []
    analysis = AnalysisStep(id="analysis", title="Analysis")
    tool = ToolStep(
        id="tool", title="Tool", tool_name="browser.open_page", depends_on=[analysis.id]
    )
    schedule = ScheduleStep(
        id="schedule", title="Schedule", depends_on=[tool.id]
    )

    result = await StepExecutor().execute_plan(
        _mixed_context(events), [schedule, tool, analysis]
    )

    assert events == ["tool", "schedule"]
    assert [item["step_id"] for item in result["step_results"]] == [
        "analysis", "tool", "schedule",
    ]


@pytest.mark.asyncio
async def test_execute_plan_mixed_join_is_deterministic() -> None:
    events: list[str] = []
    tool = ToolStep(id="tool", title="Tool", tool_name="browser.open_page")
    schedule = ScheduleStep(id="schedule", title="Schedule")
    join = JoinStep(id="join", title="Join", depends_on=[tool.id, schedule.id])

    result = await StepExecutor().execute_plan(_mixed_context(events), [join, tool, schedule])

    assert events == ["tool", "schedule"]
    assert [item["step_id"] for item in result["step_results"]] == ["tool", "schedule", "join"]
    assert result["step_results"][-1]["status"] == "ok"


@pytest.mark.asyncio
async def test_step_trace_uses_finalized_success_criteria_result() -> None:
    trace_store = _TraceStore()
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="trace-finalized",
        messages=[],
        tool_executor=tool_executor,
        trace_store=trace_store,
    )
    step = ToolStep(
        id="tool",
        title="Tool",
        tool_name="browser.open_page",
        success_criteria={"op": "content_contains", "values": ["missing"]},
    )

    result = await StepExecutor().execute_plan(ctx, [step])
    finalized = result["step_results"][0]
    trace = next(record for category, record in trace_store.records if category == "steps")

    assert (trace["status"], trace["success"], trace["error"]) == (
        finalized["status"], finalized["success"], finalized["error"],
    )


@pytest.mark.asyncio
async def test_private_schedule_helper_requires_active_step_lease() -> None:
    events: list[str] = []
    ctx = _mixed_context(events)
    step = ScheduleStep(id="schedule", title="Schedule")
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])

    with pytest.raises(PlanValidationError, match="execution lease"):
        await runner._execute_schedule_step(ctx, step, capability, None)
    assert events == []


@pytest.mark.asyncio
async def test_private_agent_helper_requires_active_step_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"reply": "unexpected", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_tool_loop)
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="agent-lease",
        messages=[],
        llm_client=object(),
        tool_registry=tool_executor.registry,
        tool_executor=tool_executor,
    )
    step = AgentStep(id="agent", title="Agent")
    runner = StepExecutor()
    capability = runner.preflight_plan(ctx, [step])

    with pytest.raises(PlanValidationError, match="execution lease"):
        await runner._execute_agent_step(ctx, step, [], capability, None)
    assert calls == 0


@pytest.mark.asyncio
async def test_scheduler_and_llm_swaps_invalidate_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events_a: list[str] = []
    events_b: list[str] = []
    schedule_ctx = _mixed_context(events_a)
    schedule = ScheduleStep(id="schedule", title="Schedule")
    runner = StepExecutor()
    schedule_capability = runner.preflight_plan(schedule_ctx, [schedule])
    schedule_ctx.scheduler = cast(Any, _OrderedScheduler(events_b))
    with pytest.raises(PlanValidationError, match="callback boundary"):
        await runner.execute_schedule_steps(
            schedule_ctx, [schedule], validation_capability=schedule_capability
        )
    assert events_a == events_b == []

    loop_calls = 0

    async def fake_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal loop_calls
        loop_calls += 1
        return {"reply": "unexpected", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_tool_loop)
    tool_executor = _RecordingToolExecutor()
    agent_ctx = AgentRequestContext(
        sid="sid",
        session_id="llm-swap",
        messages=[],
        llm_client=object(),
        tool_registry=tool_executor.registry,
        tool_executor=tool_executor,
    )
    agent = AgentStep(id="agent", title="Agent")
    agent_capability = runner.preflight_plan(agent_ctx, [agent])
    agent_ctx.llm_client = object()
    with pytest.raises(PlanValidationError, match="callback boundary"):
        await runner.execute_agent_steps(
            agent_ctx, [agent], validation_capability=agent_capability
        )
    assert loop_calls == 0


@pytest.mark.asyncio
async def test_failure_handler_does_not_release_unguarded_dependent_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handled = 0

    async def fake_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal handled
        handled += 1
        return {"reply": "handled", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_tool_loop)
    failing = _FailingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="handler-isolation",
        messages=[],
        llm_client=object(),
        tool_registry=failing.registry,
        tool_executor=failing,
    )
    failed = ToolStep(id="failed", title="Failed", tool_name="browser.open_page")
    sibling = ToolStep(
        id="sibling", title="Sibling", tool_name="browser.open_page", depends_on=[failed.id]
    )
    handler = AgentStep(
        id="handler",
        title="Handler",
        depends_on=[failed.id],
        condition=StepCondition(
            predicate=PredicateNode(
                op="status_in", source_step_id=failed.id, values=["error"]
            )
        ),
    )

    result = await StepExecutor().execute_plan(ctx, [failed, sibling, handler])

    assert failing.calls == 1
    assert handled == 1
    assert next(item for item in result["step_results"] if item["step_id"] == "sibling")[
        "error"
    ].startswith("predecessor_not_completed")


@pytest.mark.asyncio
async def test_pipeline_enforces_autonomy_from_authoritative_plan_steps() -> None:
    class CapturingExecutor:
        max_tool_retries = 0

        def __init__(self) -> None:
            self.plans: list[list[PlanStepUnion]] = []

        async def execute_plan(self, _ctx: AgentRequestContext, steps: list[PlanStepUnion]):
            self.plans.append(steps)
            return {
                "reply": "",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [],
                "execution_summary": None,
            }

    assistant_executor = CapturingExecutor()
    schedule = ScheduleStep(id="schedule", title="Schedule")
    assistant_plan = PlanResult(goal="schedule", steps=[schedule], scheduled_steps=[])
    assistant_pipeline = AgentPipeline()

    async def prepare_assistant(ctx: AgentRequestContext):
        return ctx, assistant_plan

    assistant_pipeline.prepare_context = prepare_assistant  # type: ignore[method-assign]
    await assistant_pipeline.run(AgentRequestContext(
        sid="sid",
        session_id="assistant-authority",
        messages=[],
        autonomy_mode="assistant",
        step_executor=cast(Any, assistant_executor),
    ))
    assert assistant_executor.plans == [[]]

    reflector_executor = CapturingExecutor()
    tool = ToolStep(id="tool", title="Tool", tool_name="browser.open_page")
    reflector_plan = PlanResult(goal="tool", steps=[tool], immediate_steps=[])
    reflector_pipeline = AgentPipeline()

    async def prepare_reflector(ctx: AgentRequestContext):
        return ctx, reflector_plan

    reflector_pipeline.prepare_context = prepare_reflector  # type: ignore[method-assign]
    result = await reflector_pipeline.run(AgentRequestContext(
        sid="sid",
        session_id="reflector-authority",
        messages=[],
        autonomy_mode="reflector",
        step_executor=cast(Any, reflector_executor),
    ))
    assert result.reply == "reflector_mode_cannot_execute_tools"
    assert reflector_executor.plans == []


@pytest.mark.asyncio
async def test_success_criteria_rejects_unknown_or_other_step_source_preflight() -> None:
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid", session_id="criteria-source", messages=[], tool_executor=tool_executor
    )
    unknown = ToolStep(
        id="unknown",
        title="Unknown",
        tool_name="browser.open_page",
        success_criteria={
            "op": "status_in", "source_step_id": "missing", "values": ["ok"],
        },
    )
    unknown_result = await StepExecutor().execute_plan(ctx, [unknown])
    assert unknown_result["error"].startswith("invalid_plan:")

    first = AnalysisStep(id="first", title="First")
    other = ToolStep(
        id="other",
        title="Other",
        tool_name="browser.open_page",
        depends_on=[first.id],
        success_criteria={
            "op": "status_in", "source_step_id": first.id, "values": ["ok"],
        },
    )
    other_result = await StepExecutor().execute_plan(ctx, [first, other])
    assert other_result["error"].startswith("invalid_plan:")
    assert tool_executor.calls == []


@pytest.mark.asyncio
async def test_failure_condition_waives_only_explicitly_matched_predecessors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_tool_loop(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"reply": "handled", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_tool_loop)
    tool_executor = _RecordingToolExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="multi-failure-handler",
        messages=[],
        llm_client=object(),
        tool_registry=tool_executor.registry,
        tool_executor=tool_executor,
    )
    a = AnalysisStep(
        id="a", title="A", success_criteria={"op": "status_in", "values": ["error"]}
    )
    b = AnalysisStep(
        id="b", title="B", success_criteria={"op": "status_in", "values": ["error"]}
    )
    partial_handler = AgentStep(
        id="partial",
        title="Partial",
        depends_on=[a.id, b.id],
        condition=StepCondition(
            predicate=PredicateNode(op="status_in", source_step_id=a.id, values=["error"])
        ),
    )

    partial = await StepExecutor().execute_plan(ctx, [a, b, partial_handler])
    assert calls == 0
    assert partial["step_results"][-1]["error"].startswith("predecessor_not_completed: b")

    full_handler = AgentStep(
        id="full",
        title="Full",
        depends_on=[a.id, b.id],
        condition=StepCondition(
            predicate=PredicateNode(
                op="all",
                children=[
                    PredicateNode(op="status_in", source_step_id=a.id, values=["error"]),
                    PredicateNode(op="status_in", source_step_id=b.id, values=["error"]),
                ],
            )
        ),
    )
    full = await StepExecutor().execute_plan(ctx, [a, b, full_handler])
    assert calls == 1
    assert full["reply"] == "handled"
