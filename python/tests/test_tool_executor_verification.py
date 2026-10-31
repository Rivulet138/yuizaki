from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.context import AgentRequestContext
from modules.agent.policy_engine import PolicyEngine
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_loop import _bounded_tool_result_text
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


def test_state_changing_tool_without_probe_reports_unverified_status(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo.write",
        description="test state-changing tool",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: ToolResultEnvelope(
            success=True,
            content="provider accepted",
            source="builtin",
            tool_name="demo.write",
        ),
        effect_kind="write",
    ))
    job_log = CompanionJobEventLog()
    executor = ToolExecutor(
        registry,
        PolicyEngine(store_file=tmp_path / "permissions.json"),
        job_event_log=job_log,
    )

    result = asyncio.run(executor.execute("demo.write", {"value": "x"}))

    assert result.outcome == "known_success"
    events = job_log.snapshot()
    completed = [event for event in events if event["status"] == "completed"][-1]
    assert completed["data"]["verificationStatus"] == "unverified"
    assert completed["data"]["unknownEffect"] is False


def test_tool_result_text_is_bounded_before_reinjection() -> None:
    bounded = _bounded_tool_result_text("x" * 20_000)

    assert len(bounded) < 20_000
    assert bounded.endswith("…[tool result truncated]")


def _retry_test_executor(tmp_path, handler, *, effect_kind="read", require_confirm=False):
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo.retry",
        description="retry boundary test tool",
        source="builtin",
        parameters={"type": "object"},
        handler=handler,
        effect_kind=effect_kind,
        require_confirm=require_confirm,
    ))
    registry.register(ToolDefinition(
        name="demo.other",
        description="second retry boundary test tool",
        source="builtin",
        parameters={"type": "object"},
        handler=handler,
        effect_kind=effect_kind,
        require_confirm=require_confirm,
    ))
    log = CompanionJobEventLog()
    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    executor = ToolExecutor(registry, policy, job_event_log=log)
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace-a",
        request_id="request-a",
        messages=[],
        permission_scope="workspace",
        extra={"job_event_log": log},
    )
    return executor, policy, log, ctx


@pytest.mark.asyncio
async def test_retry_requires_server_owned_job_identity_before_dispatch(tmp_path):
    calls = []

    def handler(args):
        calls.append(args)
        return ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="demo.retry",
        )

    executor, _policy, log, ctx = _retry_test_executor(tmp_path, handler)

    result = await executor.execute(
        "demo.retry",
        {"value": "x"},
        ctx=ctx,
        retry=True,
        job_id="job:not-server-owned",
        run_id="run:not-server-owned",
    )

    assert not result.success
    assert result.data == {
        "code": "TOOL_RETRY_NOT_AUTHORIZED",
        "reason": "retry_job_not_found",
    }
    assert calls == []
    assert log.snapshot() == []


@pytest.mark.asyncio
async def test_retry_rejects_tool_args_run_and_workspace_mismatches(tmp_path):
    calls = []

    def handler(args):
        calls.append(args)
        return ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="demo.retry",
        )

    executor, _policy, log, ctx = _retry_test_executor(tmp_path, handler)
    first = await executor.execute("demo.retry", {"value": "x"}, ctx=ctx)
    assert first.success
    original = log.snapshot()[-1]
    job_id = original["jobId"]
    run_id = original["runId"]

    cases = [
        ("demo.retry", {"value": "different"}, ctx, run_id, "retry_job_identity_mismatch"),
        ("demo.retry", {"value": "x"}, ctx, "run:wrong", "retry_job_identity_mismatch"),
        ("demo.other", {"value": "x"}, ctx, run_id, "retry_job_identity_mismatch"),
        (
            "demo.retry",
            {"value": "x"},
            SimpleNamespace(
                workspace_id="workspace-b",
                request_id="request-b",
                messages=[],
                permission_scope="workspace",
                extra={"job_event_log": log},
            ),
            run_id,
            "retry_job_not_found",
        ),
    ]
    for tool_name, args, retry_ctx, retry_run_id, reason in cases:
        result = await executor.execute(
            tool_name,
            args,
            ctx=retry_ctx,
            retry=True,
            job_id=job_id,
            run_id=retry_run_id,
        )
        assert not result.success
        assert result.data == {"code": "TOOL_RETRY_NOT_AUTHORIZED", "reason": reason}

    assert calls == [{"value": "x"}]
    assert len(log.snapshot()) == 3


@pytest.mark.asyncio
async def test_authorized_retry_uses_new_job_and_run_ids(tmp_path):
    calls = []

    def handler(args):
        calls.append(args)
        return ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="demo.retry",
        )

    executor, _policy, log, ctx = _retry_test_executor(tmp_path, handler)
    first = await executor.execute("demo.retry", {"value": "x"}, ctx=ctx, request_id="request-first")
    original = log.snapshot()[-1]

    retried = await executor.execute(
        "demo.retry",
        {"value": "x"},
        ctx=ctx,
        request_id="request-second",
        retry=True,
        job_id=original["jobId"],
        run_id=original["runId"],
    )

    assert first.success and retried.success
    assert calls == [{"value": "x"}, {"value": "x"}]
    completed = [event for event in log.snapshot() if event["status"] == "completed"]
    assert len(completed) == 2
    assert completed[0]["jobId"] != completed[1]["jobId"]
    assert completed[0]["runId"] != completed[1]["runId"]
    assert completed[1]["data"]["retry"] is True
    assert completed[1]["data"]["retryOfJobId"] == completed[0]["jobId"]


@pytest.mark.asyncio
async def test_unknown_effect_retry_requires_fresh_confirmation(tmp_path):
    calls = []

    def handler(_args):
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("transport lost after dispatch")
        return ToolResultEnvelope(
            success=True,
            content="recovered",
            source="builtin",
            tool_name="demo.retry",
        )

    executor, policy, log, ctx = _retry_test_executor(tmp_path, handler, effect_kind="write")
    first = await executor.execute("demo.retry", {"value": "x"}, ctx=ctx)
    original = log.snapshot()[-1]
    assert first.outcome == "unknown_effect"

    confirmations = []

    async def allow(**request):
        confirmations.append(request)
        policy.resolve_pending(request["request_id"], True, False, "demo.retry", ctx.permission_scope)

    retried = await executor.execute(
        "demo.retry",
        {"value": "x"},
        ctx=ctx,
        permission_request_cb=allow,
        retry=True,
        job_id=original["jobId"],
        run_id=original["runId"],
    )

    assert retried.success
    assert len(confirmations) == 1
    assert confirmations[0]["tool_name"] == "demo.retry"
    assert calls == [True, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["disconnected", "cancelled_callback", "cancelled_wait", "cancelled_task"])
@pytest.mark.parametrize("sensitive", [False, True])
async def test_permission_interruption_replay_matches_available_args(tmp_path, failure, sensitive):
    calls = []

    def handler(args):
        calls.append(args)
        return ToolResultEnvelope(True, "ok", "builtin", "demo.retry")

    executor, policy, log, ctx = _retry_test_executor(tmp_path, handler, require_confirm=True)
    args = {"api_key": "synthetic-secret-value"} if sensitive else {"value": "x"}
    cancellation = asyncio.Event()
    waiting = asyncio.Event()

    async def interrupt(**_request):
        if failure == "cancelled_callback":
            raise asyncio.CancelledError()
        if failure == "disconnected":
            raise RuntimeError("socket disconnected")
        if failure == "cancelled_task":
            waiting.set()
            return
        cancellation.set()

    if failure == "cancelled_task":
        task = asyncio.create_task(executor.execute(
            "demo.retry", args, ctx=ctx, permission_request_cb=interrupt,
        ))
        await asyncio.wait_for(waiting.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif failure == "cancelled_wait":
        result = await executor.execute(
            "demo.retry", args, ctx=ctx, permission_request_cb=interrupt,
            cancellation_signal=cancellation,
        )
        assert not result.success
    else:
        exception = asyncio.CancelledError if failure == "cancelled_callback" else RuntimeError
        with pytest.raises(exception):
            await executor.execute("demo.retry", args, ctx=ctx, permission_request_cb=interrupt)

    original = log.snapshot()[-1]
    assert not calls
    assert original["data"]["retryable"] is (not sensitive)
    assert original["data"]["replayArgsAvailable"] is (not sensitive)
    approvals = []

    async def allow(**request):
        approvals.append(request)
        policy.resolve_pending(request["request_id"], True, False, "demo.retry", ctx.permission_scope)

    retried = await executor.execute(
        "demo.retry", original["data"]["args"], ctx=ctx, permission_request_cb=allow,
        retry=True, job_id=original["jobId"], run_id=original["runId"],
    )
    assert retried.success is (not sensitive)
    assert len(approvals) == (0 if sensitive else 1)
    assert calls == ([] if sensitive else [args])
