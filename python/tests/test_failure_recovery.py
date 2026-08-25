import importlib
from types import SimpleNamespace

import pytest

recovery = importlib.import_module("modules.agent.failure_recovery")
planner = importlib.import_module("modules.agent.planner")
context = importlib.import_module("modules.agent.context")
step_executor = importlib.import_module("modules.agent.step_executor")
tool_result = importlib.import_module("modules.agent.tool_result")

ToolStep = planner.ToolStep
ScheduleStep = planner.ScheduleStep
FailureRecoveryManager = recovery.FailureRecoveryManager
ResumeTokenCodec = recovery.ResumeTokenCodec
ResumeTokenExpired = recovery.ResumeTokenExpired
ResumeTokenScopeMismatch = recovery.ResumeTokenScopeMismatch
ResumeTokenTampered = recovery.ResumeTokenTampered
StepFailure = recovery.StepFailure
AgentRequestContext = context.AgentRequestContext
StepExecutor = step_executor.StepExecutor
ToolResultEnvelope = tool_result.ToolResultEnvelope


def _steps():
    return [
        ToolStep(id="a", title="upstream", tool_name="one"),
        ToolStep(id="b", title="failed", depends_on=["a"], tool_name="two"),
        ToolStep(id="c", title="downstream", depends_on=["b"], tool_name="three"),
        ToolStep(id="independent", title="independent", tool_name="three"),
    ]


def test_failure_taxonomy_is_closed_and_classifies_execution_signals():
    assert recovery.classify_failure(status="permission_denied") == "permission"
    assert recovery.classify_failure(status="policy_blocked") == "policy"
    assert recovery.classify_failure(error="provider rate limit") == "provider"
    assert recovery.classify_failure(status="error") == "tool"
    assert recovery.classify_failure(error="unexpected invariant") == "internal"
    with pytest.raises(ValueError):
        StepFailure(step_id="x", kind="new_kind", message="bad")


def test_resume_token_round_trip_binds_scope_and_plan():
    now = [1000.0]
    codec = ResumeTokenCodec("test-secret", clock=lambda: now[0])
    steps = _steps()
    token = codec.encode(
        workspace_id="workspace",
        session_id="session",
        turn_id="turn",
        plan_hash_value=recovery.plan_hash(steps),
        failed_step_id="b",
        ttl_seconds=30,
    )
    payload = codec.decode(
        token,
        workspace_id="workspace",
        session_id="session",
        turn_id="turn",
        plan_hash_value=recovery.plan_hash(steps),
        failed_step_id="b",
    )
    assert payload["failed_step_id"] == "b"
    with pytest.raises(ResumeTokenScopeMismatch):
        codec.decode(token, workspace_id="other", session_id="session", turn_id="turn", plan_hash_value=recovery.plan_hash(steps), failed_step_id="b")
    with pytest.raises(ResumeTokenScopeMismatch):
        codec.decode(token, workspace_id="workspace", session_id="session", turn_id="turn", plan_hash_value="wrong", failed_step_id="b")
    with pytest.raises(ResumeTokenScopeMismatch):
        codec.decode(token, workspace_id="workspace", session_id="session", turn_id="turn", plan_hash_value=recovery.plan_hash(steps), failed_step_id="a")
    now[0] = 1030
    with pytest.raises(ResumeTokenExpired):
        codec.decode(token, workspace_id="workspace", session_id="session", turn_id="turn", plan_hash_value=recovery.plan_hash(steps), failed_step_id="b")


def test_resume_token_rejects_tampering():
    codec = ResumeTokenCodec("test-secret", clock=lambda: 1000)
    token = codec.encode(workspace_id="w", session_id="s", turn_id="t", plan_hash_value="p", failed_step_id="b")
    body, signature = token.split(".")
    replacement = ("A" if body[0] != "A" else "B") + body[1:]
    with pytest.raises(ResumeTokenTampered):
        codec.decode(f"{replacement}.{signature}", workspace_id="w", session_id="s", turn_id="t", plan_hash_value="p", failed_step_id="b")


def test_retry_closure_contains_failed_step_and_transitive_downstream_only():
    assert recovery.retry_closure(_steps(), "b") == {"b", "c"}
    manager = FailureRecoveryManager("secret", clock=lambda: 1000)
    failure = StepFailure(step_id="b", kind="tool", message="failed")
    token = manager.create_resume_token(failure, workspace_id="w", session_id="s", turn_id="t", steps=_steps())
    assert manager.validate_resume_token(token, workspace_id="w", session_id="s", turn_id="t", steps=_steps(), failed_step_id="b")["plan_hash"] == recovery.plan_hash(_steps())


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
def test_plan_hash_rejects_non_canonical_json(arguments):
    step = ToolStep(
        id="strict",
        title="strict",
        tool_name="one",
        arguments=arguments,
    )
    with pytest.raises(planner.PlanValidationError):
        recovery.plan_hash([step])


class _FakeToolExecutor:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []
        self.registry = self

    revision = 0

    def get(self, name):
        if name not in self.outcomes:
            return None
        return type("Definition", (), {
            "parameters": {"type": "object", "additionalProperties": True},
            "risk_level": "safe",
            "require_confirm": False,
        })()

    def preview_policy(self, tool_name, _args, **_kwargs):
        if self.get(tool_name) is None:
            raise RuntimeError(f"unknown test tool: {tool_name}")
        return type("Decision", (), {"allowed": True, "require_confirm": False, "reason": "test_safe"})()

    async def execute(self, tool_name, args, **kwargs):
        self.calls.append(tool_name)
        outcome = self.outcomes[tool_name]
        if isinstance(outcome, list):
            current = outcome.pop(0) if len(outcome) > 1 else outcome[0]
        else:
            current = outcome
        return current


def _envelope(name, success, error=None, receipt=None):
    return ToolResultEnvelope(success=success, content=name, source="builtin", tool_name=name, error=error, permission_receipt=receipt)


@pytest.mark.asyncio
async def test_resume_executes_failed_downstream_closure_without_replaying_upstream():
    steps = _steps()[:3]
    executor = _FakeToolExecutor({
        "one": _envelope("one", True),
        "two": [_envelope("two", False, "temporary"), _envelope("two", True)],
        "three": _envelope("three", True),
    })
    ctx = AgentRequestContext(sid="sid", session_id="session", workspace_id="workspace", request_id="turn-1", messages=[], tool_executor=executor)
    runner = StepExecutor()

    first = await runner.execute_plan(ctx, steps)
    assert first["resume_token"]
    # Rehydrate the records exactly as a transport caller would.
    models = importlib.import_module("modules.agent.models")
    prior = [models.StepResultRecord(**item) for item in first["step_results"]]
    resumed = await runner.resume_immediate_steps(ctx, steps, first["resume_token"], "b", prior)

    assert executor.calls == ["one", "two", "two", "three"]
    assert [item["step_id"] for item in resumed["step_results"]] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_permission_resume_rechecks_tool_executor_policy_boundary():
    steps = [ToolStep(id="permission", title="permission", tool_name="sensitive")]
    executor = _FakeToolExecutor({"sensitive": [_envelope("sensitive", False, "approval required"), _envelope("sensitive", True)]})
    ctx = AgentRequestContext(sid="sid", session_id="session", workspace_id="workspace", request_id="turn-2", messages=[], tool_executor=executor)
    runner = StepExecutor()
    first = await runner.execute_plan(ctx, steps)
    assert first["failure"]["kind"] == "tool"
    prior = [importlib.import_module("modules.agent.models").StepResultRecord(**item) for item in first["step_results"]]
    resumed = await runner.resume_immediate_steps(ctx, steps, first["resume_token"], "permission", prior)
    assert executor.calls == ["sensitive", "sensitive"]
    assert resumed["step_results"][0]["success"] is True


@pytest.mark.asyncio
async def test_resume_token_is_single_use_with_zero_replay_effects():
    steps = [ToolStep(id="retry", title="retry", tool_name="retry")]
    executor = _FakeToolExecutor({
        "retry": [_envelope("retry", False, "temporary"), _envelope("retry", True)],
    })
    ctx = AgentRequestContext(
        sid="sid", session_id="resume-replay", request_id="turn", messages=[], tool_executor=executor
    )
    runner = StepExecutor()
    first = await runner.execute_plan(ctx, steps)
    token = first["resume_token"]

    resumed = await runner.resume_immediate_steps(ctx, steps, token, "retry")
    replay = await runner.resume_immediate_steps(ctx, steps, token, "retry")

    assert resumed["step_results"][0]["success"] is True
    assert replay["error"] == "invalid_resume_capability"
    assert executor.calls == ["retry", "retry"]


@pytest.mark.asyncio
async def test_unordered_dag_resume_uses_canonical_plan_hash():
    a = ToolStep(id="a", title="a", tool_name="one")
    b = ToolStep(id="b", title="b", tool_name="two", depends_on=[a.id])
    c = ToolStep(id="c", title="c", tool_name="three", depends_on=[b.id])
    submitted = [c, b, a]
    executor = _FakeToolExecutor({
        "one": _envelope("one", True),
        "two": [_envelope("two", False, "temporary"), _envelope("two", True)],
        "three": _envelope("three", True),
    })
    ctx = AgentRequestContext(
        sid="sid", session_id="unordered", request_id="turn", messages=[], tool_executor=executor
    )
    runner = StepExecutor()

    first = await runner.execute_plan(ctx, submitted)
    resumed = await runner.resume_immediate_steps(
        ctx, submitted, first["resume_token"], "b"
    )

    assert [item["step_id"] for item in resumed["step_results"]] == ["a", "b", "c"]
    assert executor.calls == ["one", "two", "two", "three"]


@pytest.mark.asyncio
async def test_resume_recreates_rolled_back_schedule_before_downstream_retry():
    class Scheduler:
        def __init__(self):
            self.created: list[str] = []
            self.removed: list[str] = []

        async def add_once(self, **_kwargs):
            task_id = f"task-{len(self.created) + 1}"
            self.created.append(task_id)
            return SimpleNamespace(id=task_id)

        async def remove_task(self, task_id):
            self.removed.append(task_id)

    scheduler = Scheduler()
    schedule = ScheduleStep(id="schedule", title="schedule")
    tool = ToolStep(
        id="tool", title="tool", tool_name="tool", depends_on=[schedule.id]
    )
    executor = _FakeToolExecutor({
        "tool": [_envelope("tool", False, "temporary"), _envelope("tool", True)],
    })
    ctx = AgentRequestContext(
        sid="sid",
        session_id="rollback-resume",
        request_id="turn",
        messages=[],
        scheduler=scheduler,
        tool_executor=executor,
    )
    runner = StepExecutor()

    first = await runner.execute_plan(ctx, [schedule, tool])
    assert first["step_results"][0]["status"] == "rolled_back"
    resumed = await runner.resume_immediate_steps(
        ctx, [schedule, tool], first["resume_token"], "tool"
    )

    assert scheduler.created == ["task-1", "task-2"]
    assert scheduler.removed == ["task-1"]
    assert resumed["step_results"][0]["status"] == "created"
    assert resumed["step_results"][0]["task_id"] == "task-2"


@pytest.mark.asyncio
async def test_resume_accepts_semantically_equivalent_dependency_order() -> None:
    a = ToolStep(id="a", title="a", tool_name="one")
    b = ToolStep(id="b", title="b", tool_name="two")
    c = ToolStep(
        id="c", title="c", tool_name="three", depends_on=[a.id, b.id]
    )
    executor = _FakeToolExecutor({
        "one": _envelope("one", True),
        "two": _envelope("two", True),
        "three": [_envelope("three", False, "temporary"), _envelope("three", True)],
    })
    ctx = AgentRequestContext(
        sid="sid", session_id="dependency-order", request_id="turn", messages=[], tool_executor=executor
    )
    runner = StepExecutor()

    first = await runner.execute_plan(ctx, [c, b, a])
    equivalent_c = ToolStep(
        id="c", title="c", tool_name="three", depends_on=[b.id, a.id]
    )
    resumed = await runner.resume_immediate_steps(
        ctx, [equivalent_c, a, b], first["resume_token"], "c"
    )

    assert resumed["step_results"][-1]["success"] is True
    assert set(executor.calls[:2]) == {"one", "two"}
    assert executor.calls[2:] == ["three", "three"]
