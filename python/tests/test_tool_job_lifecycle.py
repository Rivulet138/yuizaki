from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
    risk_level: str = "safe",
    effect_kind: str = "unknown",
    postcondition_verifier: object = None,
    recheck_handler: object = None,
    verification_timeout_seconds: float = 5.0,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        source=source,  # type: ignore[arg-type]
        parameters={"type": "object"},
        handler=handler,  # type: ignore[arg-type]
        effect_kind=effect_kind,  # type: ignore[arg-type]
        risk_level=risk_level,  # type: ignore[arg-type]
        postcondition_verifier=postcondition_verifier,  # type: ignore[arg-type]
        recheck_handler=recheck_handler,  # type: ignore[arg-type]
        verification_timeout_seconds=verification_timeout_seconds,
    )


@pytest.mark.asyncio
async def test_legacy_positional_tool_fields_preserve_confirmation_contract() -> None:
    calls = 0

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        nonlocal calls
        calls += 1
        return ToolResultEnvelope(
            success=True,
            content="should not run",
            source="plugin",
            tool_name="legacy_plugin_write",
        )

    definition = ToolDefinition(
        "legacy_plugin_write",
        "legacy positional plugin tool",
        "plugin",
        {"type": "object"},
        _handler,
        True,
        "high",
    )
    assert definition.require_confirm is True
    assert definition.risk_level == "high"
    assert definition.effect_kind == "unknown"

    registry = ToolRegistry()
    registry.register(definition)
    outcome = await ToolExecutor(registry).execute("legacy_plugin_write", {})

    assert outcome.success is False
    assert calls == 0


def test_invalid_effect_kind_is_rejected_at_registration_boundary() -> None:
    with pytest.raises(ValueError, match="effect_kind"):
        _tool("invalid_effect", lambda _args: None, effect_kind="invalid")


@pytest.mark.asyncio
async def test_recheck_uses_probe_without_repeating_primary_handler() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(_tool(
        "write_like",
        lambda _args: (calls.append("primary"), ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name="write_like"))[1],
        recheck_handler=lambda _args, _ctx: {"status": "verified", "evidence": ["state matches"]},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute("write_like", {"value": "x"}, request_id="r", run_id="run", job_id="job")
    calls.clear()
    result = await executor.recheck("write_like", {"value": "x"}, ctx=None, request_id="r", run_id="run", job_id="job")
    assert result["status"] == "verified"
    assert calls == []
    assert events.snapshot()[-1]["data"]["recheck"] is True


@pytest.mark.asyncio
async def test_unknown_effect_job_can_be_rechecked_without_repeating_primary_handler() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(_tool(
        "uncertain_write",
        lambda _args: (calls.append("primary"), ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="uncertain_write",
        ))[1],
        effect_kind="write",
        recheck_handler=lambda _args, _ctx: {
            "status": "verified",
            "evidence": ["effect exists"],
        },
    ))
    events = CompanionJobEventLog()
    events.append(
        workspace_id="default",
        session_id="tool",
        turn_id="turn:r-unknown",
        job_id="job-unknown",
        run_id="run-unknown",
        request_id="r-unknown",
        interruption_epoch=0,
        source="desktop",
        timestamp=1.0,
        status="cancelled",
        data={
            "toolName": "uncertain_write",
            "args": {"target": "alpha"},
            "effectOutcome": "unknown_effect",
            "recheckAvailable": True,
        },
    )
    executor = ToolExecutor(registry, job_event_log=events)

    result = await executor.recheck(
        "uncertain_write",
        {"target": "alpha"},
        ctx=None,
        request_id="r-unknown",
        run_id="run-unknown",
        job_id="job-unknown",
    )

    assert result["status"] == "verified"
    assert calls == []
    assert events.snapshot()[-1]["data"]["effectOutcome"] == "known_success"


@pytest.mark.asyncio
async def test_recheck_failure_keeps_original_job_completed_and_probe_available() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "probe_tool",
        lambda _args: ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name="probe_tool"),
        recheck_handler=lambda _args, _ctx: {"status": "unverified", "evidence": ["not observable"]},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute("probe_tool", {}, request_id="r2", run_id="run2", job_id="job2")
    result = await executor.recheck(
        "probe_tool", {}, ctx=None, request_id="r2", run_id="run2", job_id="job2",
    )
    assert result["status"] == "unverified"
    terminal = events.snapshot()[-1]
    assert terminal["status"] == "completed"
    assert terminal["data"]["verificationStatus"] == "unverified"
    assert terminal["data"]["recheckAvailable"] is True


@pytest.mark.asyncio
async def test_recheck_normalizes_provider_success_alias_to_closed_status() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "alias_probe",
        lambda _args: ToolResultEnvelope(
            success=True, content="ok", source="builtin", tool_name="alias_probe",
        ),
        recheck_handler=lambda _args, _ctx: {"status": "success", "evidence": ["matched"]},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute("alias_probe", {}, request_id="ra", run_id="runa", job_id="joba")

    result = await executor.recheck(
        "alias_probe", {}, ctx=None, request_id="ra", run_id="runa", job_id="joba",
    )

    assert result["status"] == "verified"
    assert events.snapshot()[-1]["data"]["verificationStatus"] == "verified"


@pytest.mark.asyncio
async def test_recheck_timeout_is_bounded_and_keeps_original_job_completed() -> None:
    async def _never_returns(*_args: object) -> None:
        await asyncio.Event().wait()

    registry = ToolRegistry()
    registry.register(_tool(
        "slow_probe",
        lambda _args: ToolResultEnvelope(
            success=True, content="ok", source="builtin", tool_name="slow_probe",
        ),
        recheck_handler=_never_returns,
        verification_timeout_seconds=0.02,
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute("slow_probe", {}, request_id="rt", run_id="runt", job_id="jobt")

    result = await asyncio.wait_for(executor.recheck(
        "slow_probe", {}, ctx=None, request_id="rt", run_id="runt", job_id="jobt",
    ), timeout=0.5)

    assert result["status"] == "error"
    assert result["reason"] == "status_probe_timeout"
    terminal = events.snapshot()[-1]
    assert terminal["status"] == "completed"
    assert terminal["data"]["verificationStatus"] == "error"
    assert terminal["data"]["recheckError"] == "status_probe_timeout"


@pytest.mark.asyncio
async def test_recheck_appends_evidence_to_an_existing_terminal_job() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "terminal_probe",
        lambda _args: ToolResultEnvelope(success=True, content="done", source="builtin", tool_name="terminal_probe"),
        recheck_handler=lambda _args, _ctx: {"status": "verified", "evidence": ["still present"]},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute(
        "terminal_probe", {"target": "alpha"}, request_id="same-request", run_id="run", job_id="job",
        )
    result = await executor.recheck(
        "terminal_probe", {"target": "alpha"}, ctx=None, request_id="same-request", run_id="run", job_id="job",
    )
    assert result["status"] == "verified"
    snapshot = events.snapshot()
    assert [event["status"] for event in snapshot] == ["created", "running", "completed", "completed"]
    assert snapshot[-1]["data"]["verificationEvidence"] == ["still present"]
    assert snapshot[-1]["data"]["args"] == {"target": "alpha"}


@pytest.mark.asyncio
async def test_recheck_rejects_cross_tool_changed_args_and_failed_jobs() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "original",
        lambda _args: ToolResultEnvelope(success=True, content="done", source="builtin", tool_name="original"),
        recheck_handler=lambda args, _ctx: {"status": "verified", "evidence": [str(args)]},
    ))
    registry.register(_tool(
        "other",
        lambda _args: ToolResultEnvelope(success=True, content="done", source="builtin", tool_name="other"),
        recheck_handler=lambda args, _ctx: {"status": "verified", "evidence": [str(args)]},
    ))
    registry.register(_tool(
        "failed",
        lambda _args: ToolResultEnvelope(success=False, content="", source="builtin", tool_name="failed", error="no"),
        recheck_handler=lambda _args, _ctx: {"status": "verified"},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    await executor.execute("original", {"target": "safe"}, request_id="r", run_id="run", job_id="job")
    assert (await executor.recheck("other", {"target": "safe"}, ctx=None, request_id="r", run_id="run", job_id="job"))["reason"] == "job_identity_mismatch"
    assert (await executor.recheck("original", {"target": "changed"}, ctx=None, request_id="r", run_id="run", job_id="job"))["reason"] == "job_identity_mismatch"
    await executor.execute("failed", {}, request_id="rf", run_id="runf", job_id="jobf")
    assert (await executor.recheck("failed", {}, ctx=None, request_id="rf", run_id="runf", job_id="jobf"))["reason"] == "job_identity_mismatch"


@pytest.mark.asyncio
async def test_recheck_preserves_original_session_turn_and_interruption_identity() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "identity_probe",
        lambda _args: ToolResultEnvelope(success=True, content="done", source="builtin", tool_name="identity_probe"),
        recheck_handler=lambda _args, _ctx: {"status": "verified"},
    ))
    events = CompanionJobEventLog()
    executor = ToolExecutor(registry, job_event_log=events)
    original_ctx = SimpleNamespace(
        session_id="conversation-42", request_id="req", workspace_id="default",
        permission_scope=None, generation_mgr=None,
        extra={"turn_id": "turn-real-99", "interruption_epoch": 7},
    )
    await executor.execute(
        "identity_probe", {}, ctx=original_ctx, request_id="req", run_id="run", job_id="job",
    )
    recheck_ctx = SimpleNamespace(
        session_id="socket-A", request_id="req", workspace_id="default",
        extra={"turn_id": "turn:req", "interruption_epoch": 0},
    )
    assert (await executor.recheck(
        "identity_probe", {}, ctx=recheck_ctx, request_id="req", run_id="run", job_id="job",
    ))["status"] == "verified"
    latest = events.snapshot()[-1]
    assert latest["sessionId"] == "conversation-42"
    assert latest["turnId"] == "turn-real-99"
    assert latest["interruptionEpoch"] == 7


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
    registry.register(_tool(
        "write_effect",
        _handler,
        recheck_handler=lambda _args, _ctx: {"status": "verified"},
    ))
    events = CompanionJobEventLog()

    outcome = await ToolExecutor(registry, job_event_log=events).execute(
        "write_effect", {}, request_id="request-effect", run_id="run-effect", job_id="job-effect",
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
    assert snapshot[-1]["data"]["recheckAvailable"] is True


@pytest.mark.asyncio
async def test_read_only_exception_after_dispatch_is_known_and_retryable() -> None:
    async def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        raise OSError("read unavailable")

    registry = ToolRegistry()
    registry.register(_tool(
        "read_file", _handler, risk_level="low", effect_kind="read"
    ))
    events = CompanionJobEventLog()

    outcome = await ToolExecutor(registry, job_event_log=events).execute(
        "read_file", {}, request_id="request-read-failure",
    )

    assert outcome.outcome == "known_failure"
    assert outcome.retryable is True
    assert outcome.error == "Read-only tool execution failed after dispatch"
    terminal = events.snapshot()[-1]
    assert terminal["status"] == "failed"
    assert terminal["data"]["effectOutcome"] == "known_failure"


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
async def test_optional_postcondition_verifier_adds_evidence_without_confirmation() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "verified_tool",
        lambda _args: ToolResultEnvelope(
            success=True, content="done", source="builtin", tool_name="verified_tool",
        ),
        postcondition_verifier=lambda _args, _result, _ctx: {
            "status": "verified", "evidence": ["file exists", {"api_key": "secret-value", "size": 12}],
        },
    ))
    events = CompanionJobEventLog()
    outcome = await ToolExecutor(registry, job_event_log=events).execute("verified_tool", {})

    assert outcome.success is True
    terminal = events.snapshot()[-1]["data"]
    assert terminal["verificationStatus"] == "verified"
    assert terminal["verificationEvidence"][0] == "file exists"
    assert "secret-value" not in terminal["verificationEvidence"][1]
    assert "REDACTED" in terminal["verificationEvidence"][1]


@pytest.mark.asyncio
async def test_verifier_failure_keeps_handler_completion_and_marks_unverified() -> None:
    registry = ToolRegistry()
    registry.register(_tool(
        "unverified_tool",
        lambda _args: ToolResultEnvelope(
            success=True, content="done", source="builtin", tool_name="unverified_tool",
        ),
        postcondition_verifier=lambda *_args: (_ for _ in ()).throw(RuntimeError("probe unavailable")),
    ))
    events = CompanionJobEventLog()
    outcome = await ToolExecutor(registry, job_event_log=events).execute("unverified_tool", {})

    assert outcome.success is True
    assert events.snapshot()[-1]["data"]["verificationStatus"] == "error"


@pytest.mark.asyncio
async def test_postcondition_timeout_keeps_handler_success_and_closes_job() -> None:
    async def _never_returns(*_args: object) -> None:
        await asyncio.Event().wait()

    registry = ToolRegistry()
    registry.register(_tool(
        "slow_verifier",
        lambda _args: ToolResultEnvelope(
            success=True, content="done", source="builtin", tool_name="slow_verifier",
        ),
        postcondition_verifier=_never_returns,
        verification_timeout_seconds=0.02,
    ))
    events = CompanionJobEventLog()

    outcome = await asyncio.wait_for(
        ToolExecutor(registry, job_event_log=events).execute("slow_verifier", {}),
        timeout=0.5,
    )

    assert outcome.success is True
    terminal = events.snapshot()[-1]
    assert terminal["status"] == "completed"
    assert terminal["data"]["verificationStatus"] == "error"
    assert terminal["data"]["verificationError"] == "verification_timeout"
    assert events.active_job_ids() == []


@pytest.mark.asyncio
async def test_verifier_event_cancellation_keeps_completed_handler_result() -> None:
    handler_calls = 0
    verifier_started = asyncio.Event()
    verifier_cancelled = asyncio.Event()

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        nonlocal handler_calls
        handler_calls += 1
        return ToolResultEnvelope(
            success=True,
            content="effect completed",
            source="builtin",
            tool_name="verified_write",
        )

    async def _verifier(*_args: object) -> dict[str, object]:
        verifier_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            verifier_cancelled.set()
            raise

    registry = ToolRegistry()
    registry.register(_tool(
        "verified_write",
        _handler,
        postcondition_verifier=_verifier,
    ))
    events = CompanionJobEventLog()
    signal = asyncio.Event()
    execution = asyncio.create_task(ToolExecutor(
        registry,
        job_event_log=events,
    ).execute(
        "verified_write",
        {},
        request_id="request-verifier-event-cancel",
        run_id="run-verifier-event-cancel",
        job_id="job-verifier-event-cancel",
        cancellation_signal=signal,
    ))

    await asyncio.wait_for(verifier_started.wait(), timeout=1)
    signal.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert handler_calls == 1
    assert verifier_cancelled.is_set()
    assert outcome.success is True
    assert outcome.outcome == "known_success"
    snapshot = events.snapshot()
    assert [event["status"] for event in snapshot] == ["created", "running", "completed"]
    assert snapshot[-1]["data"]["verificationStatus"] == "cancelled"
    assert snapshot[-1]["data"]["verificationError"] == "verification_cancelled"
    assert events.active_job_ids() == []


@pytest.mark.asyncio
async def test_verifier_direct_task_cancel_keeps_completed_handler_result() -> None:
    handler_calls = 0
    verifier_started = asyncio.Event()
    verifier_cancelled = asyncio.Event()

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        nonlocal handler_calls
        handler_calls += 1
        return ToolResultEnvelope(
            success=True,
            content="effect completed",
            source="builtin",
            tool_name="verified_write",
        )

    async def _verifier(*_args: object) -> dict[str, object]:
        verifier_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            verifier_cancelled.set()
            raise

    registry = ToolRegistry()
    registry.register(_tool(
        "verified_write",
        _handler,
        postcondition_verifier=_verifier,
    ))
    events = CompanionJobEventLog()
    execution = asyncio.create_task(ToolExecutor(
        registry,
        job_event_log=events,
    ).execute(
        "verified_write",
        {},
        request_id="request-verifier-task-cancel",
        run_id="run-verifier-task-cancel",
        job_id="job-verifier-task-cancel",
    ))

    await asyncio.wait_for(verifier_started.wait(), timeout=1)
    execution.cancel()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert handler_calls == 1
    assert verifier_cancelled.is_set()
    assert outcome.success is True
    assert outcome.outcome == "known_success"
    snapshot = events.snapshot()
    assert [event["status"] for event in snapshot] == ["created", "running", "completed"]
    assert snapshot[-1]["data"]["verificationStatus"] == "cancelled"
    assert snapshot[-1]["data"]["verificationError"] == "verification_cancelled"
    assert events.active_job_ids() == []


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
    registry.register(_tool(
        "slow_tool", _handler, source="mcp", risk_level="high"
    ))
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
    registry.register(_tool(
        "sync_tool", _handler, source="plugin", risk_level="high"
    ))
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
async def test_direct_task_cancel_waits_for_sync_worker_terminal_state() -> None:
    import threading
    import time

    started = threading.Event()
    release = threading.Event()
    effects: list[str] = []

    def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        started.set()
        while not release.is_set():
            time.sleep(0.01)
        effects.append("completed")
        return ToolResultEnvelope(
            success=True,
            content="done",
            source="plugin",
            tool_name="write_sync",
        )

    registry = ToolRegistry()
    registry.register(_tool(
        "write_sync", _handler, source="plugin", risk_level="high"
    ))
    execution = asyncio.create_task(ToolExecutor(registry).execute(
        "write_sync", {}, request_id="req-direct-sync",
    ))

    await asyncio.to_thread(started.wait, 1)
    execution.cancel()
    await asyncio.sleep(0.03)
    assert not execution.done()
    release.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert effects == ["completed"]
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False


@pytest.mark.asyncio
async def test_low_risk_read_cancellation_is_known_and_retryable() -> None:
    started = asyncio.Event()
    handler_cancelled = asyncio.Event()

    async def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            handler_cancelled.set()
            raise

    registry = ToolRegistry()
    registry.register(_tool(
        "read_file", _handler, risk_level="low", effect_kind="read"
    ))
    events = CompanionJobEventLog()
    signal = asyncio.Event()
    execution = asyncio.create_task(ToolExecutor(
        registry, job_event_log=events,
    ).execute("read_file", {}, cancellation_signal=signal))

    await asyncio.wait_for(started.wait(), timeout=1)
    signal.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert handler_cancelled.is_set()
    assert outcome.outcome == "known_failure"
    assert outcome.retryable is True
    assert outcome.error == "Tool execution cancelled after read dispatch"
    assert events.snapshot()[-1]["data"]["effectOutcome"] == "known_failure"


@pytest.mark.asyncio
async def test_unknown_effect_kind_is_not_retried_after_dispatch() -> None:
    started = asyncio.Event()
    effects: list[str] = []

    async def _handler(_args: dict[str, object]) -> ToolResultEnvelope:
        effects.append("moved")
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    registry = ToolRegistry()
    registry.register(_tool("move_file", _handler, risk_level="low"))
    signal = asyncio.Event()
    execution = asyncio.create_task(ToolExecutor(registry).execute(
        "move_file",
        {},
        cancellation_signal=signal,
    ))

    await asyncio.wait_for(started.wait(), timeout=1)
    signal.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert effects == ["moved"]
    assert outcome.outcome == "unknown_effect"
    assert outcome.retryable is False


@pytest.mark.asyncio
async def test_sync_callable_returning_awaitable_remains_cancellable() -> None:
    inner_started = asyncio.Event()
    inner_cancelled = asyncio.Event()

    async def _inner() -> ToolResultEnvelope:
        inner_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            inner_cancelled.set()
            raise

    def _handler(_args: dict[str, object]) -> object:
        return _inner()

    registry = ToolRegistry()
    registry.register(_tool(
        "read_deferred", _handler, risk_level="low", effect_kind="read"
    ))
    events = CompanionJobEventLog()
    signal = asyncio.Event()
    execution = asyncio.create_task(ToolExecutor(
        registry,
        job_event_log=events,
    ).execute("read_deferred", {}, cancellation_signal=signal))

    await asyncio.wait_for(inner_started.wait(), timeout=1)
    signal.set()
    outcome = await asyncio.wait_for(execution, timeout=1)

    assert inner_cancelled.is_set()
    assert outcome.outcome == "known_failure"
    assert outcome.retryable is True
    assert [event["status"] for event in events.snapshot()] == [
        "created",
        "running",
        "cancelled",
    ]
    assert events.active_job_ids() == []


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
