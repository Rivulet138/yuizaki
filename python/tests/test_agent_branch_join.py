import importlib
from types import SimpleNamespace
from typing import ClassVar

pytest = importlib.import_module("pytest")

context_module = importlib.import_module("modules.agent.context")
planner_module = importlib.import_module("modules.agent.planner")
step_executor_module = importlib.import_module("modules.agent.step_executor")
tool_result_module = importlib.import_module("modules.agent.tool_result")
trace_store_module = importlib.import_module("modules.agent.agent_trace_store")
pipeline_module = importlib.import_module("modules.agent.pipeline")
state_module = importlib.import_module("modules.core.state")
models_module = importlib.import_module("modules.agent.models")


def _safe_policy_preview(*_args, **_kwargs):
    return SimpleNamespace(allowed=True, require_confirm=False, reason="test_safe")

AgentRequestContext = context_module.AgentRequestContext
Planner = planner_module.Planner
PlanResult = planner_module.PlanResult
StepCondition = planner_module.StepCondition
StepExecutor = step_executor_module.StepExecutor
ToolResultEnvelope = tool_result_module.ToolResultEnvelope
AgentTraceStore = trace_store_module.AgentTraceStore
AgentPipeline = pipeline_module.AgentPipeline
Generation = state_module.Generation
StepResultRecord = models_module.StepResultRecord


class _PermissiveDefinition:
    parameters: ClassVar[dict[str, object]] = {"type": "object", "additionalProperties": True}
    risk_level = "safe"
    require_confirm = False


class _PermissiveRegistry:
    revision = 0

    def get(self, _name):
        return _PermissiveDefinition()


def PlanStep(*, kind="agent", **kwargs):
    variants = {
        "analysis": planner_module.AnalysisStep,
        "agent": planner_module.AgentStep,
        "join": planner_module.JoinStep,
        "schedule": planner_module.ScheduleStep,
    }
    if kind != "tool":
        return variants[kind](**kwargs)
    payload = kwargs.get("payload") or {}
    prompt = str(payload.get("prompt") or kwargs.get("description") or "")
    if "http" in prompt:
        url = next((token for token in prompt.split() if token.startswith("http")), "https://example.invalid")
        kwargs.update(tool_name="browser.open_page", arguments={"url": url})
    elif "good-app" in prompt or "bad-app" in prompt:
        name = "bad-app" if "bad-app" in prompt else "good-app"
        kwargs.update(tool_name="system.open_app", arguments={"name": name})
    else:
        kwargs.update(tool_name="test.tool", arguments={})
    if "payload" in kwargs:
        kwargs.setdefault("plan_version", 1)
    return planner_module.ToolStep(**kwargs)


def test_conditional_planner_adds_join_and_synthesis_step():
    plan = Planner().plan("读取文件 C:/tmp/a.txt，如果成功，总结内容，否则，说明失败原因")

    kinds = [step.kind for step in plan.steps]
    titles = [step.title for step in plan.steps]

    assert "join" in kinds
    assert titles[-2] == "Merge conditional branches"
    assert titles[-1] == "Synthesize conditional result"
    assert plan.steps[-1].condition is not None
    assert plan.steps[-1].condition.source_step_id == plan.steps[-2].id
    assert plan.steps[-1].condition.status_in == ["ok"]


def test_one_sided_conditional_planner_adds_noop_fallback_branch():
    plan = Planner().plan("读取文件 C:/tmp/a.txt，如果成功，总结内容")

    titles = [step.title for step in plan.steps]

    assert "Continue without conditional branch" in titles
    assert titles[-2] == "Merge conditional branches"
    assert titles[-1] == "Synthesize conditional result"


def test_planner_parses_content_condition_filter():
    plan = Planner().plan("执行检查，如果成功且输出包含 ready，总结结果")

    conditional_step = next(step for step in plan.steps if step.title == "Execute success branch")

    assert conditional_step.condition is not None
    assert conditional_step.condition.status_in == ["ok"]
    assert conditional_step.condition.content_contains == ["ready"]


def test_trace_store_preserves_join_step_metadata(tmp_path):
    trace_store = AgentTraceStore(path=str(tmp_path / "agent_trace.json"), max_entries=10)

    trace_store.append("steps", {
        "timestamp": "2026-01-01T00:00:00",
        "kind": "join",
        "status": "ok",
        "step_id": "join",
        "title": "Join",
        "depends_on": ["success", "else"],
        "condition": {
            "source_step_id": "success",
            "mode": "continue_if",
            "status_in": ["ok"],
        },
        "owner_agent_id": "yuizaki.companion-orchestrator",
        "owner_agent_role": "orchestrator",
        "route_reason": "Branch merge and final synthesis stay in orchestrator",
    })

    snapshot = trace_store.snapshot(limit=1)
    item = snapshot["steps"][0]

    assert item["step_id"] == "join"
    assert item["title"] == "Join"
    assert item["depends_on"] == ["success", "else"]
    assert item["condition"]["source_step_id"] == "success"
    assert item["condition"]["mode"] == "continue_if"
    assert item["condition"]["status_in"] == ["ok"]
    assert item["owner_agent_role"] == "orchestrator"


def test_trace_store_coerces_planner_steps_to_frontend_contract(tmp_path):
    trace_store = AgentTraceStore(path=str(tmp_path / "agent_trace.json"), max_entries=10)

    trace_store.append("planner", {
        "timestamp": "2026-01-01T00:00:00",
        "session_id": "session-1",
        "goal": "demo",
        "mode": "structured",
        "steps": [
            {
                "step_id": "legacy-step-id",
                "title": "Read file",
                "kind": "tool",
                "description": "Read a file",
                "depends_on": ["root"],
                "condition": {"source_step_id": "root", "status_in": ["ok"]},
            },
            {"unexpected": "shape"},
        ],
    })

    stored_steps = trace_store.snapshot()["planner"][0]["steps"]
    assert stored_steps[0]["id"] == "legacy-step-id"
    assert stored_steps[0]["title"] == "Read file"
    assert stored_steps[0]["kind"] == "tool"
    assert stored_steps[0]["description"] == "Read a file"
    assert stored_steps[0]["depends_on"] == ["root"]
    assert stored_steps[0]["condition"]["source_step_id"] == "root"
    assert stored_steps[0]["condition"]["status_in"] == ["ok"]
    assert stored_steps[1] == {
        "id": "",
        "title": "",
        "kind": "",
        "description": "",
        "depends_on": [],
        "condition": None,
    }


def test_trace_store_preserves_scheduler_route_metadata(tmp_path):
    trace_store = AgentTraceStore(path=str(tmp_path / "agent_trace.json"), max_entries=10)

    trace_store.append("scheduler", {
        "timestamp": "2026-01-01T00:00:00",
        "task_id": "task-1",
        "task_name": "Demo task",
        "mode": "once",
        "status": "ok",
        "run_id": "schedrun-1",
        "job_id": "schedjob-1",
        "request_id": "req-1",
        "owner_agent_id": "yuizaki.task-router",
        "owner_agent_role": "router",
        "route_reason": "Scheduled task owned by task-router",
    })

    stored = trace_store.snapshot()["scheduler"][0]
    assert stored["owner_agent_id"] == "yuizaki.task-router"
    assert stored["run_id"] == "schedrun-1"
    assert stored["job_id"] == "schedjob-1"
    assert stored["owner_agent_role"] == "router"
    assert stored["route_reason"] == "Scheduled task owned by task-router"


def test_trace_store_preserves_nested_condition_metadata(tmp_path):
    trace_store = AgentTraceStore(path=str(tmp_path / "agent_trace.json"), max_entries=10)

    trace_store.append("steps", {
        "timestamp": "2026-01-01T00:00:00",
        "kind": "agent",
        "status": "ok",
        "step_id": "conditional",
        "title": "Conditional",
        "condition": {
            "mode": "continue_if",
            "all_of": [
                {"source_step_id": "a", "status_in": ["ok"], "content_contains": ["ready"]},
                {"source_step_id": "b", "status_not_in": ["error"]},
            ],
            "none_of": [
                {"source_step_id": "c", "error_contains": ["fatal"]},
            ],
        },
    })

    condition = trace_store.snapshot(limit=1)["steps"][0]["condition"]

    assert condition["all_of"][0]["content_contains"] == ["ready"]
    assert condition["all_of"][1]["status_not_in"] == ["error"]
    assert condition["none_of"][0]["error_contains"] == ["fatal"]


@pytest.mark.asyncio
async def test_immediate_executor_merges_success_branch_and_skips_else(monkeypatch):
    calls = []

    async def fake_run_tool_loop(*_args, **_kwargs):
        calls.append(True)
        return {"reply": f"reply-{len(calls)}", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(id="primary", title="Primary", kind="agent", description="primary")
    success_branch = PlanStep(
        id="success",
        title="Success branch",
        kind="agent",
        description="success",
        depends_on=[primary.id],
        condition=StepCondition(source_step_id=primary.id, mode="continue_if", status_in=["ok"]),
    )
    else_branch = PlanStep(
        id="else",
        title="Else branch",
        kind="agent",
        description="else",
        depends_on=[primary.id],
        condition=StepCondition(source_step_id=primary.id, mode="skip_if", status_in=["ok"]),
    )
    join = PlanStep(id="join", title="Join", kind="join", depends_on=[success_branch.id, else_branch.id])
    final = PlanStep(
        id="final",
        title="Final",
        kind="agent",
        description="final",
        depends_on=[join.id],
        condition=StepCondition(source_step_id=join.id, mode="continue_if", status_in=["ok"]),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=object(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, success_branch, else_branch, join, final])

    statuses = {item["step_id"]: item["status"] for item in result["step_results"]}
    assert result["reply"] == "reply-3"
    assert len(calls) == 3
    assert statuses == {
        "primary": "ok",
        "success": "ok",
        "else": "skipped",
        "join": "ok",
        "final": "ok",
    }


@pytest.mark.asyncio
async def test_immediate_executor_can_join_handled_failure_branch(monkeypatch):
    agent_calls = []

    class FailingToolExecutor:
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, _args, **_kwargs):
            return ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=tool_name,
                error="boom",
            )

    async def fake_run_tool_loop(*_args, **_kwargs):
        agent_calls.append(True)
        return {"reply": f"handled-{len(agent_calls)}", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(
        id="primary",
        title="Primary tool",
        kind="tool",
        description="打开网页 https://example.invalid",
        payload={"prompt": "打开网页 https://example.invalid"},
    )
    failure_branch = PlanStep(
        id="failure",
        title="Failure branch",
        kind="agent",
        description="handle failure",
        depends_on=[primary.id],
        condition=StepCondition(source_step_id=primary.id, mode="continue_if", status_in=["error"]),
    )
    success_branch = PlanStep(
        id="success",
        title="Success branch",
        kind="agent",
        description="handle success",
        depends_on=[primary.id],
        condition=StepCondition(source_step_id=primary.id, mode="skip_if", status_in=["error"]),
    )
    join = PlanStep(id="join", title="Join", kind="join", depends_on=[failure_branch.id, success_branch.id])
    final = PlanStep(
        id="final",
        title="Final",
        kind="agent",
        description="final",
        depends_on=[join.id],
        condition=StepCondition(source_step_id=join.id, mode="continue_if", status_in=["ok"]),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=FailingToolExecutor(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, failure_branch, success_branch, join, final])

    statuses = {item["step_id"]: item["status"] for item in result["step_results"]}
    assert result["reply"] == "handled-2"
    assert len(agent_calls) == 2
    assert statuses["primary"] == "error"
    assert statuses["failure"] == "ok"
    assert statuses["success"] == "skipped"
    assert statuses["join"] == "ok"
    assert statuses["final"] == "ok"


@pytest.mark.asyncio
async def test_unmatched_error_contains_condition_does_not_handle_tool_failure(monkeypatch):
    agent_calls = []

    class FailingToolExecutor:
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, _args, **_kwargs):
            return ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=tool_name,
                error="boom",
            )

    async def fake_run_tool_loop(*_args, **_kwargs):
        agent_calls.append(True)
        return {"reply": "should not run", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(
        id="primary",
        title="Primary tool",
        kind="tool",
        description="打开网页 https://example.invalid",
        payload={"prompt": "打开网页 https://example.invalid"},
    )
    failure_branch = PlanStep(
        id="failure",
        title="Failure branch",
        kind="agent",
        description="handle specific failure",
        depends_on=[primary.id],
        condition=StepCondition(
            source_step_id=primary.id,
            status_in=["error"],
            error_contains=["not-found"],
        ),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=FailingToolExecutor(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, failure_branch])

    assert [item["step_id"] for item in result["step_results"]] == ["primary"]
    assert result["execution_summary"]["status"] == "failed"
    assert result["execution_summary"]["pending_steps"] == [
        {"step_id": "failure", "title": "Failure branch", "kind": "agent"},
    ]
    assert len(agent_calls) == 0


@pytest.mark.asyncio
async def test_one_sided_conditional_still_reaches_synthesis_when_branch_not_selected(monkeypatch):
    agent_calls = []

    class FailingToolExecutor:
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, _args, **_kwargs):
            return ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=tool_name,
                error="boom",
            )

    async def fake_run_tool_loop(*_args, **_kwargs):
        agent_calls.append(True)
        return {"reply": "fallback synthesis", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    plan = Planner().plan("读取文件 C:/tmp/a.txt，如果成功，总结内容")
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=FailingToolExecutor(),
    )

    executor = StepExecutor()
    capability = executor.preflight_plan(ctx, plan.steps)
    immediate_ids = {step.id for step in plan.immediate_steps}
    await executor.execute_analysis_steps(
        ctx,
        [step for step in plan.steps if step.kind == "analysis" and step.id not in immediate_ids],
        validation_capability=capability,
    )
    result = await executor.execute_immediate_steps(
        ctx,
        plan.immediate_steps,
        validation_capability=capability,
    )

    statuses = {item["title"]: item["status"] for item in result["step_results"]}
    assert result["reply"] == "fallback synthesis"
    assert len(agent_calls) == 1
    assert statuses["Execute success branch"] == "skipped"
    assert statuses["Continue without conditional branch"] == "ok"
    assert statuses["Merge conditional branches"] == "ok"
    assert statuses["Synthesize conditional result"] == "ok"


@pytest.mark.asyncio
async def test_immediate_executor_stops_on_unhandled_tool_failure(monkeypatch):
    agent_calls = []

    class FailingToolExecutor:
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, _args, **_kwargs):
            return ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=tool_name,
                error="boom",
            )

    async def fake_run_tool_loop(*_args, **_kwargs):
        agent_calls.append(True)
        return {"reply": "should not run", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(
        id="primary",
        title="Primary tool",
        kind="tool",
        description="打开网页 https://example.invalid",
        payload={"prompt": "打开网页 https://example.invalid"},
    )
    unguarded_followup = PlanStep(
        id="followup",
        title="Unguarded followup",
        kind="agent",
        description="should not run",
        depends_on=[primary.id],
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=FailingToolExecutor(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, unguarded_followup])

    assert result["reply"] == "已执行工具步骤。"
    assert len(agent_calls) == 0
    assert [item["step_id"] for item in result["step_results"]] == ["primary"]
    assert result["step_results"][0]["status"] == "error"
    assert result["execution_summary"] == {
        "status": "failed",
        "total_steps": 2,
        "completed_steps": 0,
        "failed_steps": 1,
        "skipped_steps": 0,
        "pending_steps": [{"step_id": "followup", "title": "Unguarded followup", "kind": "agent"}],
        "stopped_reason": "unhandled_step_error:primary",
    }


@pytest.mark.asyncio
async def test_immediate_executor_reports_partial_completion_after_late_failure(monkeypatch):
    class SelectivelyFailingToolExecutor:
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, args, **_kwargs):
            name = str(args.get("name") or "")
            if name == "bad-app":
                return ToolResultEnvelope(
                    success=False,
                    content="",
                    source="builtin",
                    tool_name=tool_name,
                    error="boom",
                )
            return ToolResultEnvelope(
                success=True,
                content=f"opened {name}",
                source="builtin",
                tool_name=tool_name,
            )

    async def fake_run_tool_loop(*_args, **_kwargs):
        return {"reply": "should not run", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    first = PlanStep(
        id="first",
        title="Open first app",
        kind="tool",
        description="打开 good-app",
        payload={"prompt": "打开 good-app"},
    )
    second = PlanStep(
        id="second",
        title="Open second app",
        kind="tool",
        description="打开 bad-app",
        payload={"prompt": "打开 bad-app"},
        depends_on=[first.id],
    )
    followup = PlanStep(
        id="followup",
        title="Followup",
        kind="agent",
        description="should not run",
        depends_on=[second.id],
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=SelectivelyFailingToolExecutor(),
    )

    result = await StepExecutor().execute_plan(ctx, [first, second, followup])

    assert [item["step_id"] for item in result["step_results"]] == ["first", "second"]
    assert result["execution_summary"]["status"] == "partial"
    assert result["execution_summary"]["completed_steps"] == 1
    assert result["execution_summary"]["failed_steps"] == 1
    assert result["execution_summary"]["pending_steps"] == [
        {"step_id": "followup", "title": "Followup", "kind": "agent"},
    ]
    assert result["execution_summary"]["stopped_reason"] == "unhandled_step_error:second"


@pytest.mark.asyncio
async def test_condition_dsl_matches_content_and_error_filters(monkeypatch):
    calls = []

    async def fake_run_tool_loop(*_args, **_kwargs):
        calls.append(True)
        return {"reply": "ready for next step", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(id="primary", title="Primary", kind="agent", description="primary")
    content_branch = PlanStep(
        id="content",
        title="Content branch",
        kind="agent",
        description="content branch",
        depends_on=[primary.id],
        condition=StepCondition(
            source_step_id=primary.id,
            status_in=["ok"],
            content_contains=["ready"],
        ),
    )
    missing_content_branch = PlanStep(
        id="missing-content",
        title="Missing content branch",
        kind="agent",
        description="missing content branch",
        depends_on=[primary.id],
        condition=StepCondition(
            source_step_id=primary.id,
            status_in=["ok"],
            content_contains=["absent-token"],
        ),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=object(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, content_branch, missing_content_branch])

    statuses = {item["step_id"]: item["status"] for item in result["step_results"]}
    assert statuses["primary"] == "ok"
    assert statuses["content"] == "ok"
    assert statuses["missing-content"] == "skipped"


@pytest.mark.asyncio
async def test_condition_dsl_content_contains_uses_full_agent_reply(monkeypatch):
    replies = ["x" * 140 + " late-token", "matched branch"]

    async def fake_run_tool_loop(*_args, **_kwargs):
        return {"reply": replies.pop(0), "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    primary = PlanStep(id="primary", title="Primary", kind="agent", description="primary")
    branch = PlanStep(
        id="branch",
        title="Late token branch",
        kind="agent",
        description="branch",
        depends_on=[primary.id],
        condition=StepCondition(
            source_step_id=primary.id,
            status_in=["ok"],
            content_contains=["late-token"],
        ),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=object(),
    )

    result = await StepExecutor().execute_plan(ctx, [primary, branch])

    statuses = {item["step_id"]: item["status"] for item in result["step_results"]}
    assert statuses == {"primary": "ok", "branch": "ok"}
    assert "late-token" in result["step_results"][0]["content"]
    assert "late-token" not in result["step_results"][0]["reply_preview"]


@pytest.mark.asyncio
async def test_condition_dsl_supports_all_any_none_and_status_not_in(monkeypatch):
    calls = []

    async def fake_run_tool_loop(*_args, **_kwargs):
        calls.append(True)
        return {"reply": f"reply-{len(calls)} ready", "tool_calls": [], "pet_control": None}

    monkeypatch.setattr(step_executor_module, "run_tool_loop", fake_run_tool_loop)

    source_a = PlanStep(id="a", title="A", kind="agent", description="a")
    source_b = PlanStep(id="b", title="B", kind="agent", description="b", depends_on=[source_a.id])
    branch = PlanStep(
        id="branch",
        title="Composite branch",
        kind="agent",
        description="branch",
        depends_on=[source_a.id, source_b.id],
        condition=StepCondition(
            all_of=[
                StepCondition(source_step_id="a", status_in=["ok"], content_contains=["ready"]),
                StepCondition(source_step_id="b", status_not_in=["error"]),
            ],
            any_of=[
                StepCondition(source_step_id="a", content_contains=["ready"]),
                StepCondition(source_step_id="b", content_contains=["fallback"]),
            ],
            none_of=[
                StepCondition(source_step_id="b", error_contains=["fatal"]),
            ],
        ),
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        llm_client=object(),
        tool_registry=_PermissiveRegistry(),
        tool_executor=object(),
    )

    result = await StepExecutor().execute_plan(ctx, [source_a, source_b, branch])

    statuses = {item["step_id"]: item["status"] for item in result["step_results"]}
    assert statuses == {"a": "ok", "b": "ok", "branch": "ok"}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_streaming_pipeline_uses_structured_executor_for_join_steps():
    class FakeStepExecutor:
        max_tool_retries = 1

        def __init__(self):
            self.called = False

        def preflight_plan(self, _ctx, _steps):
            return object()

        async def execute_immediate_steps(self, _ctx, _steps, **_kwargs):
            self.called = True
            return {
                "reply": "structured reply",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [{
                    "step_id": "join",
                    "kind": "join",
                    "status": "ok",
                    "title": "Join",
                    "description": "",
                    "depends_on": [],
                }],
            }

    class FakeWS:
        def __init__(self):
            self.messages = []

        async def send_json(self, msg):
            self.messages.append(msg)

    pipeline = AgentPipeline()
    join_step = PlanStep(id="join", title="Join", kind="join")
    plan = PlanResult(goal="test", steps=[join_step], immediate_steps=[join_step])

    async def fake_prepare_context(ctx):
        return ctx, plan

    pipeline.prepare_context = fake_prepare_context
    step_executor = FakeStepExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        step_executor=step_executor,
    )
    generation = Generation(generation_id="gen", session_id="sid")
    ws = FakeWS()

    result = await pipeline.run_streaming(ctx, ws, generation)

    assert step_executor.called is True
    assert result.reply == "structured reply"
    assert generation.full_text == "structured reply"
    assert [message["type"] for message in ws.messages] == ["token", "done"]
    assert result.action_envelope is not None


@pytest.mark.asyncio
async def test_pipeline_action_envelope_includes_execution_summary():
    class FakeStepExecutor:
        max_tool_retries = 1

        def preflight_plan(self, _ctx, _steps):
            return object()

        async def execute_plan(self, _ctx, _steps):
            return {
                "reply": "partially done",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [{
                    "step_id": "first",
                    "kind": "tool",
                    "status": "ok",
                    "title": "First",
                    "description": "",
                    "depends_on": [],
                }],
                "execution_summary": {
                    "status": "partial",
                    "total_steps": 2,
                    "completed_steps": 1,
                    "failed_steps": 1,
                    "skipped_steps": 0,
                    "pending_steps": [{"step_id": "second", "title": "Second", "kind": "tool"}],
                    "stopped_reason": "unhandled_step_error:second",
                },
            }

    pipeline = AgentPipeline()
    step = PlanStep(id="first", title="First", kind="tool")
    plan = PlanResult(goal="test", steps=[step], immediate_steps=[step])

    async def fake_prepare_context(ctx):
        return ctx, plan

    pipeline.prepare_context = fake_prepare_context
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        step_executor=FakeStepExecutor(),
    )

    result = await pipeline.run(ctx)

    tool_trace_actions = [
        action for action in result.action_envelope["actions"]
        if action["type"] == "tool_trace"
    ]
    payload = tool_trace_actions[0]["payload"][0]
    assert payload["execution_summary"]["status"] == "partial"
    assert payload["execution_summary"]["pending_steps"] == [
        {"step_id": "second", "title": "Second", "kind": "tool"},
    ]


@pytest.mark.asyncio
async def test_immediate_executor_preserves_partial_summary_on_missing_agent_runtime():
    class SuccessfulToolExecutor:
        registry = _PermissiveRegistry()
        preview_policy = staticmethod(_safe_policy_preview)

        async def execute(self, tool_name, args, **_kwargs):
            return ToolResultEnvelope(
                success=True,
                content=f"opened {args.get('name')}",
                source="builtin",
                tool_name=tool_name,
            )

    first = PlanStep(
        id="first",
        title="Open app",
        kind="tool",
        description="打开 good-app",
        payload={"prompt": "打开 good-app"},
    )
    followup = PlanStep(
        id="followup",
        title="Followup",
        kind="agent",
        description="requires agent runtime",
        depends_on=[first.id],
    )
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        tool_registry=None,
        tool_executor=SuccessfulToolExecutor(),
    )

    result = await StepExecutor().execute_plan(ctx, [first, followup])

    assert [item["step_id"] for item in result["step_results"]] == ["first"]
    assert result["execution_summary"]["status"] == "partial"
    assert result["execution_summary"]["completed_steps"] == 1
    assert result["execution_summary"]["pending_steps"] == [
        {"step_id": "followup", "title": "Followup", "kind": "agent"},
    ]
    assert result["execution_summary"]["stopped_reason"] == "tool_registry_not_available"


@pytest.mark.asyncio
async def test_pipeline_does_not_rollback_schedule_for_normal_condition_skip():
    class FakeStepExecutor:
        max_tool_retries = 1

        def __init__(self):
            self.rollback_called = False

        def preflight_plan(self, _ctx, _steps):
            return object()

        async def execute_plan(self, _ctx, _steps):
            return {
                "reply": "done",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [
                    StepResultRecord(
                        step_id="schedule",
                        kind="schedule",
                        status="created",
                        title="Schedule",
                        task_id="task-1",
                        mode="once",
                        success=True,
                    ).to_dict(),
                    {
                        "step_id": "skipped",
                        "kind": "agent",
                        "status": "skipped",
                        "title": "Skipped branch",
                        "description": "",
                        "depends_on": [],
                        "error": "condition_not_met",
                    },
                ],
                "execution_summary": {
                    "status": "completed",
                    "total_steps": 1,
                    "completed_steps": 0,
                    "failed_steps": 0,
                    "skipped_steps": 1,
                    "pending_steps": [],
                    "stopped_reason": None,
                },
            }

        async def rollback_schedule_results(self, _ctx, _results):
            self.rollback_called = True
            return []

    pipeline = AgentPipeline()
    scheduled = PlanStep(id="schedule", title="Schedule", kind="schedule")
    immediate = PlanStep(id="immediate", title="Immediate", kind="agent")
    plan = PlanResult(
        goal="test",
        mode="mixed",
        steps=[scheduled, immediate],
        scheduled_steps=[scheduled],
        immediate_steps=[immediate],
    )

    async def fake_prepare_context(ctx):
        return ctx, plan

    pipeline.prepare_context = fake_prepare_context
    step_executor = FakeStepExecutor()
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        step_executor=step_executor,
        scheduler=object(),
    )

    result = await pipeline.run(ctx)

    assert step_executor.rollback_called is False
    assert "已为你创建计划任务" in result.reply
    payload = result.action_envelope["actions"][-1]["payload"][0]
    assert payload["execution_summary"]["status"] == "completed"


@pytest.mark.asyncio
async def test_streaming_envelope_includes_summary_without_step_results():
    class FakeStepExecutor:
        max_tool_retries = 1

        def preflight_plan(self, _ctx, _steps):
            return object()

        async def execute_immediate_steps(self, _ctx, _steps, **_kwargs):
            return {
                "reply": "silent summary",
                "tool_calls": [],
                "pet_control": None,
                "step_results": [],
                "execution_summary": {
                    "status": "failed",
                    "total_steps": 1,
                    "completed_steps": 0,
                    "failed_steps": 0,
                    "skipped_steps": 0,
                    "pending_steps": [{"step_id": "a", "title": "A", "kind": "agent"}],
                    "stopped_reason": "silent_autonomy_mode",
                },
            }

    pipeline = AgentPipeline()
    step = PlanStep(id="a", title="A", kind="agent", condition=StepCondition(source_step_id="x", status_in=["ok"]))
    plan = PlanResult(goal="test", steps=[step], immediate_steps=[step])

    async def fake_prepare_context(ctx):
        return ctx, plan

    pipeline.prepare_context = fake_prepare_context
    ctx = AgentRequestContext(
        sid="sid",
        session_id="sid",
        messages=[{"role": "user", "content": "test"}],
        step_executor=FakeStepExecutor(),
    )
    generation = Generation(generation_id="gen", session_id="sid")

    result = await pipeline.run_streaming(ctx, None, generation)

    payload = result.action_envelope["actions"][-1]["payload"][0]
    assert payload["step_results"] == []
    assert payload["execution_summary"]["status"] == "failed"
    assert payload["execution_summary"]["pending_steps"] == [
        {"step_id": "a", "title": "A", "kind": "agent"},
    ]
