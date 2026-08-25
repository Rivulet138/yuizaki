from __future__ import annotations

import asyncio

import pytest

from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


def _tool(
    name: str,
    handler: object,
    *,
    source: str = "builtin",
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        source=source,  # type: ignore[arg-type]
        parameters={"type": "object"},
        handler=handler,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_tool_job_converges_from_created_to_running_to_terminal(success: bool) -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "job_tool",
        lambda _args: ToolResultEnvelope(
            success=success,
            content="ok" if success else "",
            source="builtin",
            tool_name="job_tool",
            error=None if success else "failed",
        ),
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)

    outcome = await executor.execute(
        "job_tool",
        {"path": "readme.txt"},
        request_id="request-1",
        run_id="run-1",
        job_id="job-1",
    )

    assert outcome.success is success
    snapshot = events.snapshot()
    assert [event["status"] for event in snapshot] == [
        "created",
        "running",
        "completed" if success else "failed",
    ]
    assert snapshot[-1]["data"]["args"] == {"path": "readme.txt"}
    assert snapshot[-1]["data"]["retryable"] is True
    assert snapshot[-1]["data"]["durationMs"] >= 0
    assert snapshot[-1]["data"]["artifactCount"] == 0
    if success:
        assert snapshot[-1]["data"]["resultSummary"] == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("exception_type", [RuntimeError, asyncio.TimeoutError])
async def test_tool_job_exception_after_dispatch_is_unknown_effect(
    exception_type: type[Exception],
) -> None:
    effects: list[str] = []

    async def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        effects.append("external-effect")
        raise exception_type("handler failed after effect")

    registry = ToolRegistry()
    registry.register(_tool("effect_tool", _handler))
    events = CompanionJobEventLog()

    outcome = await ToolExecutor(registry, job_event_log=events).execute(
        "effect_tool", {}, request_id="request-effect", run_id="run-effect", job_id="job-effect",
    )

    assert effects == ["external-effect"]
    assert outcome.success is False
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False
    assert outcome.data == {"code": "TOOL_OUTCOME_UNKNOWN"}
    snapshot = events.snapshot()
    assert [event["status"] for event in snapshot] == ["created", "running", "failed"]
    assert snapshot[-1]["data"]["effectOutcome"] == "unknown_effect"
    assert snapshot[-1]["data"]["retryable"] is False


@pytest.mark.asyncio
async def test_post_handler_failure_preserves_explicit_known_outcome() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "known_tool",
        lambda _args: ToolResultEnvelope(
            success=True,
            content="effect completed",
            source="builtin",
            tool_name="known_tool",
        ),
    ))
    events = CompanionJobEventLog()

    class BrokenPluginManager:
        async def before_tool(
            self,
            _name: str,
            args: dict[str, object],
            _ctx: object,
        ) -> dict[str, object]:
            return args

        async def after_tool(self, *_args: object) -> ToolResultEnvelope:
            raise RuntimeError("post-handler projection failed")

    outcome = await ToolExecutor(registry, job_event_log=events).execute(
        "known_tool", {}, plugin_manager=BrokenPluginManager(),
    )

    assert outcome.success is True
    assert outcome.outcome == "known_success"
    assert [event["status"] for event in events.snapshot()] == ["created", "running", "completed"]


@pytest.mark.asyncio
async def test_tool_job_result_summary_is_bounded_and_normalized() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "verbose_tool",
        lambda _args: ToolResultEnvelope(
            success=True,
            content="  " + ("line\n" * 200),
            source="builtin",
            tool_name="verbose_tool",
        ),
    ))
    events = CompanionJobEventLog()
    outcome = await ToolExecutor(registry, job_event_log=events).execute(
        "verbose_tool", {}, request_id="request-summary", run_id="run-summary", job_id="job-summary",
    )

    assert outcome.success is True
    summary = events.snapshot()[-1]["data"]["resultSummary"]
    assert len(summary) <= 360
    assert "\n" not in summary
    assert summary.endswith("...")


@pytest.mark.asyncio
async def test_tool_job_cancellation_stops_async_handler_and_converges() -> None:
    started = asyncio.Event()
    handler_cancelled = asyncio.Event()

    async def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise
        raise AssertionError("unreachable")

    registry = ToolRegistry()
    registry.register(_tool("slow_tool", _handler, source="mcp"))
    events = CompanionJobEventLog()
    signal = asyncio.Event()
    executor = ToolExecutor(registry, job_event_log=events)

    execution = asyncio.create_task(executor.execute(
        "slow_tool",
        {},
        request_id="request-cancel",
        run_id="run-cancel",
        job_id="job-cancel",
        cancellation_signal=signal,
    ))
    await asyncio.wait_for(started.wait(), timeout=1)
    signal.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert outcome.success is False
    assert outcome.error == "Tool execution cancelled after dispatch; effect is unknown"
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False
    assert handler_cancelled.is_set()
    assert [event["status"] for event in events.snapshot()] == ["created", "running", "cancelled"]
    assert events.active_job_ids() == []


@pytest.mark.asyncio
async def test_sync_tool_cancellation_waits_for_worker_terminal_state() -> None:
    import threading
    import time

    started = threading.Event()
    release = threading.Event()

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        started.set()
        while not release.is_set():
            time.sleep(0.01)
        return ToolResultEnvelope(success=True, content="done", source="plugin", tool_name="sync_tool")

    registry = ToolRegistry()
    registry.register(_tool("sync_tool", _handler, source="plugin"))
    events = CompanionJobEventLog()
    signal = asyncio.Event()
    executor = ToolExecutor(registry, job_event_log=events)
    execution = asyncio.create_task(executor.execute("sync_tool", {}, request_id="req-sync", cancellation_signal=signal))
    await asyncio.to_thread(started.wait, 1)
    signal.set()
    await asyncio.sleep(0.03)
    assert not execution.done()
    release.set()
    outcome = await asyncio.wait_for(execution, timeout=1)
    assert outcome.error == "Tool execution cancelled after dispatch; effect is unknown"
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False
    assert [event["status"] for event in events.snapshot()] == ["created", "running", "cancelled"]


@pytest.mark.asyncio
async def test_tool_job_retry_gets_new_identity_and_links_previous_job() -> None:
    calls = 0

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        nonlocal calls
        calls += 1
        return ToolResultEnvelope(
            success=calls > 1,
            content="ok" if calls > 1 else "",
            source="plugin",
            tool_name="skill_tool",
            error=None if calls > 1 else "try again",
        )

    registry = ToolRegistry()
    registry.register(_tool("skill_tool", _handler, source="plugin"))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)

    first = await executor.execute(
        "skill_tool", {"value": 1}, request_id="request-1", run_id="run-1", job_id="job-1",
    )
    retried = await executor.execute(
        "skill_tool",
        {"value": 1},
        request_id="request-2",
        run_id="run-1",
        job_id="job-1",
        retry=True,
    )

    assert first.success is False
    assert retried.success is True
    created = [event for event in events.snapshot() if event["status"] == "created"]
    assert len(created) == 2
    assert created[1]["jobId"] != "job-1"
    assert created[1]["runId"].startswith("run-1:retry:")
    assert created[1]["data"]["retryOfJobId"] == "job-1"
    assert created[1]["data"]["retryOfRunId"] == "run-1"
    assert events.active_job_ids() == []


@pytest.mark.asyncio
async def test_tool_job_capacity_rejects_before_handler_execution() -> None:
    calls = 0

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        nonlocal calls
        calls += 1
        return ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name="capacity_tool")

    registry = ToolRegistry()
    registry.register(_tool("capacity_tool", _handler))
    events = CompanionJobEventLog(max_jobs=1)
    events.append(
        workspace_id="default",
        session_id="active",
        turn_id="turn-active",
        job_id="job-active",
        run_id="run-active",
        request_id="request-active",
        interruption_epoch=0,
        source="builtin",
        timestamp=1,
        status="created",
    )
    executor = ToolExecutor(registry, job_event_log=events)

    outcome = await executor.execute(
        "capacity_tool", {}, request_id="request-new", run_id="run-new", job_id="job-new",
    )

    assert outcome.success is False
    assert outcome.data == {"code": "TOOL_JOB_CAPACITY_EXCEEDED"}
    assert calls == 0
    assert events.active_job_ids() == ["job-active"]


@pytest.mark.asyncio
async def test_tool_job_permission_emit_failure_converges_to_failed() -> None:
    registry = ToolRegistry()
    tool = _tool(
        "confirmed_tool",
        lambda _args: ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="confirmed_tool",
        ),
    )
    tool.require_confirm = True
    registry.register(tool)
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)

    async def _permission_request(**_payload: object) -> None:
        raise RuntimeError("permission channel unavailable")

    with pytest.raises(RuntimeError, match="permission channel unavailable"):
        await executor.execute(
            "confirmed_tool",
            {},
            permission_request_cb=_permission_request,
            request_id="request-permission",
            run_id="run-permission",
            job_id="job-permission",
        )

    assert [event["status"] for event in events.snapshot()] == ["created", "failed"]
    assert events.active_job_ids() == []
