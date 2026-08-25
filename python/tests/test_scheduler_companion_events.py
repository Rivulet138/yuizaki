from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.policy_engine import PolicyEngine
from modules.agent.schedule_store import ScheduleStore
from modules.agent.scheduler import AgentScheduler, _ScheduledRun
from modules.agent.tool_registry import ToolDefinition
from modules.agent.tool_result import ToolResultEnvelope
from modules.agent.turn_outbox import TurnOutboxDispatcher, TurnProjection
from modules.agent.turn_service import TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore
from modules.system.runtime_endpoints import (
    build_cancel_schedule_endpoint,
    build_run_schedule_now_endpoint,
)


@pytest.fixture(autouse=True)
def _enable_explicit_legacy_turn_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUIZAKI_ALLOW_LEGACY_TURN_PIPELINE", "1")


class _ControlledPipeline:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, _ctx: AgentRequestContext):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return SimpleNamespace(reply="scheduled result")


def _context(task) -> AgentRequestContext:
    return AgentRequestContext(
        sid="scheduler",
        session_id=f"schedule:{task.id}",
        workspace_id="workspace-test",
        messages=[{"role": "user", "content": task.prompt}],
    )


def _job_event_fields(job_id: str, *, workspace_id: str = "workspace-test") -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "session_id": f"session:{job_id}",
        "turn_id": f"turn:{job_id}",
        "job_id": job_id,
        "run_id": f"run:{job_id}",
        "request_id": f"request:{job_id}",
        "interruption_epoch": 0,
        "source": "scheduler",
    }


def test_scheduler_run_history_trims_all_terminal_statuses_and_preserves_active(tmp_path):
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
        allow_legacy_pipeline=True,
    )
    statuses = ["interrupted", "unknown_effect", "completed", "failed", "cancelled"]
    runs: list[_ScheduledRun] = []
    for index, status in enumerate(statuses):
        run = _ScheduledRun(
            task_id=f"task-{index}",
            run_id=f"run-{index}",
            job_id=f"job-{index}",
            request_id=f"request-{index}",
            workspace_id="workspace-test",
            session_id=f"session-{index}",
            turn_id=f"turn-{index}",
            status=status,
        )
        runs.append(run)
        scheduler._runs_by_id[run.run_id] = run
        scheduler._runs_by_job[run.job_id] = run
        scheduler._latest_runs_by_task[run.task_id] = run
    active = _ScheduledRun(
        task_id="task-active",
        run_id="run-active",
        job_id="job-active",
        request_id="request-active",
        workspace_id="workspace-test",
        session_id="session-active",
        turn_id="turn-active",
        status="running",
    )
    scheduler._runs_by_id[active.run_id] = active
    scheduler._runs_by_job[active.job_id] = active
    scheduler._runs_by_task[active.task_id] = active
    scheduler._latest_runs_by_task[active.task_id] = active

    scheduler._trim_run_history(max_runs=2)

    assert list(scheduler._runs_by_id) == ["run-4", "run-active"]
    assert set(scheduler._runs_by_job) == {"job-4", "job-active"}
    assert scheduler._runs_by_task == {"task-active": active}
    assert scheduler._latest_runs_by_task == {"task-4": runs[4], "task-active": active}


@pytest.mark.asyncio
async def test_scheduler_emits_versioned_companion_job_lifecycle(tmp_path):
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_once("Review", "summarize", 60)

    await scheduler.run_now(task.id)
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)
    pipeline.release.set()
    await scheduler.wait_for_task(task.id, timeout=1)

    events = scheduler.snapshot_job_events()
    assert [event["type"] for event in events] == [
        "AgentJobCreated",
        "AgentJobRunning",
        "AgentJobCompleted",
    ]
    assert [event["revision"] for event in events] == [1, 2, 3]
    assert {event["jobId"] for event in events} == {events[0]["jobId"]}
    assert {event["runId"] for event in events} == {events[0]["runId"]}
    assert {event["requestId"] for event in events} == {events[0]["requestId"]}
    assert {event["data"]["runId"] for event in events} == {events[0]["data"]["runId"]}
    assert events[0]["runId"] == events[0]["data"]["runId"]
    assert events[0]["data"]["runId"].startswith("schedrun_")
    assert all(event["workspaceId"] == "workspace-test" for event in events)
    assert events[-1]["data"]["taskId"] == task.id


@pytest.mark.asyncio
async def test_scheduler_uses_current_interruption_epoch_for_run_events(tmp_path):
    pipeline = _ControlledPipeline()
    epoch = 7
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        interruption_epoch_provider=lambda: epoch,
    )
    task = await scheduler.add_once("Epoch", "check", 60)
    await scheduler.run_now(task.id)
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)
    pipeline.release.set()
    await scheduler.wait_for_task(task.id, timeout=1)

    assert all(event["interruptionEpoch"] == epoch for event in scheduler.snapshot_job_events())


@pytest.mark.asyncio
async def test_scheduler_cancel_by_task_id_emits_terminal_event(tmp_path):
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_interval("Background", "work", 60)

    await scheduler.run_now(task.id)
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)

    assert await scheduler.cancel(task.id) is True
    assert pipeline.cancelled.is_set()
    assert scheduler.active_job_ids() == []
    assert scheduler.store.tasks[task.id].last_status == "cancelled"
    assert [event["type"] for event in scheduler.snapshot_job_events()] == [
        "AgentJobCreated",
        "AgentJobRunning",
        "AgentJobCancelled",
    ]


@pytest.mark.parametrize("identifier_key", ["taskId", "jobId", "runId"])
@pytest.mark.asyncio
async def test_scheduler_cancel_resolves_task_job_and_run_identity(tmp_path, identifier_key):
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / f"schedules-{identifier_key}.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_interval("Background", "work", 60)
    await scheduler.run_now(task.id)
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)
    run = scheduler.get_run(task.id)
    assert run is not None

    assert await scheduler.cancel(run[identifier_key]) is True
    assert await scheduler.cancel(run[identifier_key]) is False
    assert scheduler.get_run(run["runId"])["status"] == "cancelled"  # type: ignore[index]
    assert await scheduler.cancel("unrelated-identity") is False


@pytest.mark.asyncio
async def test_scheduler_cancel_by_run_id_and_rerun_uses_fresh_identity(tmp_path):
    first_pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=first_pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_interval("Background", "work", 60)

    await scheduler.run_now(task.id)
    await asyncio.wait_for(first_pipeline.started.wait(), timeout=1)
    first_run = scheduler.get_run(task.id)
    assert first_run is not None
    assert await scheduler.cancel(first_run["runId"]) is True
    assert await scheduler.cancel(first_run["runId"]) is False
    assert scheduler.get_run(first_run["runId"])["status"] == "cancelled"  # type: ignore[index]

    second_pipeline = _ControlledPipeline()
    scheduler.pipeline = second_pipeline  # type: ignore[assignment]
    await scheduler.run_now(task.id)
    await asyncio.wait_for(second_pipeline.started.wait(), timeout=1)
    second_run = scheduler.get_run(task.id)
    assert second_run is not None
    assert second_run["runId"] != first_run["runId"]
    assert second_run["jobId"] != first_run["jobId"]
    assert scheduler.get_run(first_run["runId"])["status"] == "cancelled"  # type: ignore[index]
    assert await scheduler.cancel(first_run["runId"]) is False
    assert scheduler.get_run(second_run["runId"])["status"] in {"created", "running"}  # type: ignore[index]

    second_pipeline.release.set()
    await scheduler.wait_for_task(second_run["runId"], timeout=1)
    assert scheduler.get_run(second_run["jobId"])["status"] == "completed"  # type: ignore[index]


@pytest.mark.asyncio
async def test_failed_run_remains_queryable_and_explicit_rerun_does_not_revive_it(tmp_path):
    class _FailingPipeline:
        async def run(self, _ctx: AgentRequestContext):
            raise RuntimeError("boom")

    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=_FailingPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_once("Review", "summarize", 60)
    await scheduler.run_now(task.id)
    failed_run = scheduler.get_run(task.id)
    assert failed_run is not None
    await scheduler.wait_for_task(failed_run["runId"], timeout=1)
    assert scheduler.get_run(failed_run["runId"])["status"] == "failed"  # type: ignore[index]

    succeeding = _ControlledPipeline()
    scheduler.pipeline = succeeding  # type: ignore[assignment]
    await scheduler.run_now(task.id)
    await asyncio.wait_for(succeeding.started.wait(), timeout=1)
    rerun = scheduler.get_run(task.id)
    assert rerun is not None
    assert rerun["runId"] != failed_run["runId"]
    assert scheduler.get_run(failed_run["runId"])["status"] == "failed"  # type: ignore[index]
    succeeding.release.set()
    await scheduler.wait_for_task(rerun["runId"], timeout=1)


@pytest.mark.asyncio
async def test_new_due_task_wakes_scheduler_without_fixed_poll_delay(tmp_path):
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    await scheduler.start()
    try:
        task = await scheduler.add_once("Immediate", "run", 0)
        await asyncio.wait_for(pipeline.started.wait(), timeout=0.25)
        pipeline.release.set()
        await scheduler.wait_for_task(task.id, timeout=1)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_schedule_runtime_endpoints_return_correlated_run_identity(tmp_path):
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "schedules.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
    )
    task = await scheduler.add_interval("Background", "work", 60)

    started = await build_run_schedule_now_endpoint(scheduler)(task.id)
    assert started["run"]["runId"] == scheduler.store.tasks[task.id].last_run_id
    assert started["run"]["jobId"] == scheduler.store.tasks[task.id].last_job_id
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)

    cancelled = await build_cancel_schedule_endpoint(scheduler)(started["run"]["runId"])
    assert cancelled["ok"] is True
    assert cancelled["run"]["runId"] == started["run"]["runId"]
    assert cancelled["run"]["jobId"] == started["run"]["jobId"]
    assert cancelled["run"]["status"] == "cancelled"
    assert cancelled["run"]["finishedAt"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["once", "interval"])
async def test_scheduler_restart_does_not_replay_ambiguous_persisted_run(tmp_path, mode):
    store_path = tmp_path / f"restart-{mode}.json"
    original = AgentScheduler(
        store=ScheduleStore(path=str(store_path)),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
    )
    if mode == "once":
        task = await original.add_once("Review", "summarize", 60)
    else:
        task = await original.add_interval("Review", "summarize", 60)
    task.last_status = "running"
    task.last_run_id = "schedrun_interrupted"
    task.last_job_id = "schedjob_interrupted"
    task.last_request_id = "schedreq_interrupted"
    task.next_run_at = 1.0
    original.store.upsert(task)

    recovered_pipeline = _ControlledPipeline()
    recovered = AgentScheduler(
        store=ScheduleStore(path=str(store_path)),
        pipeline=recovered_pipeline,  # type: ignore[arg-type]
        context_factory=_context,
    )
    await recovered.start()
    try:
        await asyncio.sleep(0.1)
        restored = recovered.store.tasks[task.id]
        assert recovered_pipeline.started.is_set() is False
        interrupted_events = [event for event in recovered.snapshot_job_events() if event["jobId"] == "schedjob_interrupted"]
        assert len(interrupted_events) == 1
        assert interrupted_events[0]["type"] == "AgentJobInterrupted"
        assert interrupted_events[0]["status"] == "interrupted"
        assert interrupted_events[0]["data"]["retryable"] is True
        assert restored.last_status == "interrupted:manual_rerun_required"
        assert restored.last_run_summary == "Previous scheduler run was interrupted; run manually to retry."
        if mode == "once":
            assert restored.enabled is False
            assert restored.next_run_at is None
        else:
            assert restored.enabled is True
            assert restored.next_run_at is not None
            assert restored.next_run_at > time.time()

        await recovered.run_now(task.id)
        await asyncio.wait_for(recovered_pipeline.started.wait(), timeout=1)
        fresh = recovered.get_run(task.id)
        assert fresh is not None
        assert fresh["runId"] != "schedrun_interrupted"
        assert fresh["jobId"] != "schedjob_interrupted"
        recovered_pipeline.release.set()
        await recovered.wait_for_task(fresh["runId"], timeout=1)
    finally:
        await recovered.stop()


@pytest.mark.asyncio
async def test_scheduler_capacity_refusal_leaks_no_run_and_loop_recovers(tmp_path):
    events = CompanionJobEventLog(max_jobs=1)
    events.append(
        workspace_id="workspace-test",
        session_id="other",
        turn_id="turn:other",
        job_id="other-active-job",
        request_id="other-request",
        interruption_epoch=0,
        source="chat",
        timestamp=time.time(),
        status="created",
    )
    pipeline = _ControlledPipeline()
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "capacity.json")),
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
        job_event_log=events,
    )
    await scheduler.start()
    try:
        task = await scheduler.add_once("Immediate", "run", 0)
        for _ in range(20):
            if scheduler.store.tasks[task.id].last_status == "blocked:job_capacity":
                break
            await asyncio.sleep(0.01)

        assert scheduler.store.tasks[task.id].last_status == "blocked:job_capacity"
        assert scheduler.store.tasks[task.id].last_run_summary == "Scheduler job capacity is full; the task has not started."
        assert task.id not in scheduler._active_task_ids
        assert task.id not in scheduler._runs_by_task
        assert scheduler._runs_by_job == {}
        assert scheduler._runs_by_id == {}
        assert pipeline.started.is_set() is False
        assert scheduler._task is not None and not scheduler._task.done()

        events.append(
            workspace_id="workspace-test",
            session_id="other",
            turn_id="turn:other",
            job_id="other-active-job",
            request_id="other-request",
            interruption_epoch=0,
            source="chat",
            timestamp=time.time(),
            status="completed",
        )
        await scheduler.run_now(task.id)
        await asyncio.wait_for(pipeline.started.wait(), timeout=1)
        admitted = scheduler.get_run(task.id)
        assert admitted is not None
        assert admitted["status"] in {"created", "running"}
        pipeline.release.set()
        await scheduler.wait_for_task(admitted["runId"], timeout=1)
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_context_factory_failure_emits_one_failed_terminal(tmp_path):
    turn_store = TurnCommitStore(tmp_path / "context-failure-turns.sqlite3")

    def broken_context(_task):
        raise RuntimeError("context factory failed")

    service = TurnService(TurnPorts(
        run=lambda _ctx: AgentPipelineResult(reply="must not run"),
        persist=turn_store.persist,
        load=turn_store.load,
    ))
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "context-failure-schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=broken_context,
        workspace_id_provider=lambda: "workspace-test",
        turn_service=service,
        allow_legacy_pipeline=False,
    )
    task = await scheduler.add_once("Broken context", "run", 60)

    await scheduler.run_now(task.id)
    run = scheduler.get_run(task.id)
    assert run is not None
    await scheduler.wait_for_task(run["runId"], timeout=1)

    events = scheduler.snapshot_job_events()
    assert [event["status"] for event in events] == ["created", "running", "failed"]
    assert sum(event["status"] == "failed" for event in events) == 1
    assert scheduler.active_job_ids() == []
    assert turn_store.pending_outbox() == []


@pytest.mark.asyncio
async def test_scheduler_turn_failure_before_persist_emits_one_failed_terminal(tmp_path):
    turn_store = TurnCommitStore(tmp_path / "pre-persist-turns.sqlite3")

    async def fail_before_persist(_ctx: AgentRequestContext) -> AgentPipelineResult:
        raise RuntimeError("turn failed before persistence")

    service = TurnService(TurnPorts(
        run=fail_before_persist,
        persist=turn_store.persist,
        load=turn_store.load,
    ))
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "pre-persist-schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
        turn_service=service,
        allow_legacy_pipeline=False,
    )
    task = await scheduler.add_once("Pre-persist failure", "run", 60)

    await scheduler.run_now(task.id)
    run = scheduler.get_run(task.id)
    assert run is not None
    await scheduler.wait_for_task(run["runId"], timeout=1)

    events = scheduler.snapshot_job_events()
    assert [event["status"] for event in events] == ["created", "running", "failed"]
    assert sum(event["status"] == "failed" for event in events) == 1
    assert scheduler.active_job_ids() == []
    assert turn_store.pending_outbox() == []


@pytest.mark.asyncio
async def test_scheduler_dispatch_failure_leaves_terminal_to_durable_outbox(tmp_path):
    turn_store = TurnCommitStore(tmp_path / "dispatch-failure-turns.sqlite3")
    job_events = CompanionJobEventLog()
    projection_available = False

    def project_job_terminal(event: dict[str, object], _ctx: object | None) -> None:
        nonlocal projection_available
        if not projection_available:
            raise RuntimeError("job projection unavailable")
        payload = dict(event["payload"])  # type: ignore[arg-type]
        terminal = dict(payload.get("job_terminal") or {})
        job_events.append(
            workspace_id=str(payload["workspace_id"]),
            session_id=str(payload["session_id"]),
            turn_id=str(payload["turn_id"]),
            job_id=str(terminal["job_id"]),
            run_id=str(terminal["run_id"]),
            request_id=str(payload["request_id"]),
            interruption_epoch=int(payload.get("interruption_epoch") or 0),
            source="scheduler",
            timestamp=float(payload["committed_at"]),
            status=str(terminal["status"]),
            data=terminal,
            idempotency_key=f"{event['idempotency_key']}:job-terminal",
        )

    dispatcher = TurnOutboxDispatcher(
        turn_store,
        [TurnProjection("job.terminal", project_job_terminal)],
        base_retry_seconds=0.01,
        max_retry_seconds=0.01,
    )
    pipeline_calls = 0

    def run_once(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return AgentPipelineResult(
            reply="committed result",
            configured_budget={"tool_budget": 3},
            consumed_usage={"output_tokens": 7},
        )

    service = TurnService(TurnPorts(
        run=run_once,
        persist=turn_store.persist,
        load=turn_store.load,
        dispatch=dispatcher,
    ))
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "dispatch-failure-schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
        job_event_log=job_events,
        turn_service=service,
        allow_legacy_pipeline=False,
    )
    task = await scheduler.add_once("Dispatch failure", "run", 60)

    await scheduler.run_now(task.id)
    run = scheduler.get_run(task.id)
    assert run is not None
    await scheduler.wait_for_task(run["runId"], timeout=1)

    assert [event["status"] for event in job_events.snapshot()] == ["created", "running"]
    assert job_events.active_job_ids() == [run["jobId"]]
    assert len(turn_store.pending_outbox()) == 1
    authoritative = scheduler.get_run(run["runId"])
    assert authoritative is not None
    assert authoritative["status"] == "completed"
    assert authoritative["outcome"] == "completed"
    assert authoritative["retryable"] is False
    assert authoritative["summary"] == "committed result"
    assert authoritative["configuredBudget"] == {"tool_budget": 3}
    assert authoritative["consumedUsage"] == {"output_tokens": 7}
    assert authoritative["finishedAt"] is not None
    assert scheduler.store.tasks[task.id].last_status == "ok"
    assert scheduler.store.tasks[task.id].last_run_summary == "committed result"
    endpoint_snapshot = await build_cancel_schedule_endpoint(scheduler)(run["runId"])
    assert endpoint_snapshot["ok"] is False
    assert endpoint_snapshot["run"] == authoritative
    assert pipeline_calls == 1

    projection_available = True
    await asyncio.sleep(0.02)
    retry = await dispatcher.dispatch_pending()

    assert retry["delivered"] == 1
    assert turn_store.pending_outbox() == []
    assert [event["status"] for event in job_events.snapshot()] == ["created", "running", "completed"]
    assert sum(event["status"] in {"completed", "failed", "cancelled"} for event in job_events.snapshot()) == 1
    assert job_events.active_job_ids() == []
    assert scheduler.get_run(run["runId"]) == authoritative
    assert scheduler.store.tasks[task.id].last_status == "ok"
    assert pipeline_calls == 1


@pytest.mark.asyncio
async def test_scheduler_cancellation_after_persist_keeps_durable_outcome(tmp_path):
    turn_store = TurnCommitStore(tmp_path / "post-persist-cancel-turns.sqlite3")
    job_events = CompanionJobEventLog()
    dispatch_started = asyncio.Event()
    pipeline_calls = 0

    def run_once(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal pipeline_calls
        pipeline_calls += 1
        return AgentPipelineResult(
            reply="durable before cancellation",
            configured_budget={"max_iterations": 4},
            consumed_usage={"iterations": 1},
        )

    async def wait_in_dispatch(_commit: object) -> None:
        dispatch_started.set()
        await asyncio.Event().wait()

    service = TurnService(TurnPorts(
        run=run_once,
        persist=turn_store.persist,
        load=turn_store.load,
        dispatch=wait_in_dispatch,
    ))
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "post-persist-cancel-schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=_context,
        workspace_id_provider=lambda: "workspace-test",
        job_event_log=job_events,
        turn_service=service,
        allow_legacy_pipeline=False,
    )
    task = await scheduler.add_once("Post-persist cancellation", "run", 60)
    await scheduler.run_now(task.id)
    await asyncio.wait_for(dispatch_started.wait(), timeout=1)
    run = scheduler.get_run(task.id)
    assert run is not None

    cancelled = await build_cancel_schedule_endpoint(scheduler)(run["runId"])

    assert cancelled["ok"] is True
    authoritative = cancelled["run"]
    assert authoritative["status"] == "completed"
    assert authoritative["outcome"] == "completed"
    assert authoritative["retryable"] is False
    assert authoritative["summary"] == "durable before cancellation"
    assert authoritative["configuredBudget"] == {"max_iterations": 4}
    assert authoritative["consumedUsage"] == {"iterations": 1}
    assert authoritative["finishedAt"] is not None
    assert scheduler.store.tasks[task.id].last_status == "ok"
    assert scheduler.store.tasks[task.id].last_run_summary == "durable before cancellation"
    assert [event["status"] for event in job_events.snapshot()] == ["created", "running"]
    assert len(turn_store.pending_outbox()) == 1
    assert pipeline_calls == 1

    def project_job_terminal(event: dict[str, object], _ctx: object | None) -> None:
        payload = dict(event["payload"])  # type: ignore[arg-type]
        terminal = dict(payload.get("job_terminal") or {})
        job_events.append(
            workspace_id=str(payload["workspace_id"]),
            session_id=str(payload["session_id"]),
            turn_id=str(payload["turn_id"]),
            job_id=str(terminal["job_id"]),
            run_id=str(terminal["run_id"]),
            request_id=str(payload["request_id"]),
            interruption_epoch=int(payload.get("interruption_epoch") or 0),
            source="scheduler",
            timestamp=float(payload["committed_at"]),
            status=str(terminal["status"]),
            data=terminal,
            idempotency_key=f"{event['idempotency_key']}:job-terminal",
        )

    dispatcher = TurnOutboxDispatcher(
        turn_store,
        [TurnProjection("job.terminal", project_job_terminal)],
    )
    recovered = await dispatcher.dispatch_pending()

    assert recovered["delivered"] == 1
    assert turn_store.pending_outbox() == []
    assert [event["status"] for event in job_events.snapshot()] == ["created", "running", "completed"]
    assert sum(event["status"] in {"completed", "failed", "cancelled"} for event in job_events.snapshot()) == 1
    assert scheduler.get_run(run["runId"]) == authoritative
    assert scheduler.store.tasks[task.id].last_status == "ok"
    assert pipeline_calls == 1


@pytest.mark.asyncio
async def test_scheduler_permission_scope_is_stable_and_workspace_isolated(tmp_path):
    captured: list[AgentRequestContext] = []

    async def capture_then_fail(ctx: AgentRequestContext) -> AgentPipelineResult:
        captured.append(ctx)
        raise RuntimeError("stop after scope capture")

    service = TurnService(TurnPorts(run=capture_then_fail))
    scheduler = AgentScheduler(
        store=ScheduleStore(path=str(tmp_path / "scope-schedules.json")),
        pipeline=_ControlledPipeline(),  # type: ignore[arg-type]
        context_factory=lambda task: AgentRequestContext(
            sid="scheduler",
            session_id=f"schedule:{task.id}",
            workspace_id="workspace-a",
            messages=[{"role": "user", "content": task.prompt}],
        ),
        turn_service=service,
        allow_legacy_pipeline=False,
    )
    task = await scheduler.add_once("Scoped", "run", 60)

    await scheduler.run_now(task.id)
    run = scheduler.get_run(task.id)
    assert run is not None
    await scheduler.wait_for_task(run["runId"], timeout=1)

    assert captured[0].permission_scope == "scheduler:workspace-a"
    assert captured[0].extra["permission_scope"] == "scheduler:workspace-a"

    policy = PolicyEngine(store_file=tmp_path / "permissions.json")
    tool = ToolDefinition(
        name="scoped_tool",
        description="scope test",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: ToolResultEnvelope(
            success=True,
            content="ok",
            source="builtin",
            tool_name="scoped_tool",
        ),
        require_confirm=True,
    )
    policy._remembered["scoped_tool::scheduler:workspace-a"] = True

    assert policy.preview_tool(tool, permission_scope="scheduler:workspace-a").reason == "remembered"
    assert policy.preview_tool(tool, permission_scope="scheduler:workspace-b").reason == "permission_required"
    assert policy.preview_tool(tool).reason == "permission_required"


def test_companion_job_log_bounds_history_and_preserves_terminal_identity():
    log = CompanionJobEventLog(max_jobs=2, max_events_per_job=5)
    fields = _job_event_fields("long-job")
    log.append(**fields, timestamp=1.0, status="created")  # type: ignore[arg-type]
    log.append(**fields, timestamp=2.0, status="running")  # type: ignore[arg-type]
    for index in range(20):
        log.append(
            **fields,  # type: ignore[arg-type]
            timestamp=3.0 + index,
            status="progress",
            data={"progress": index},
            idempotency_key=f"long-job:{index}",
        )
    terminal = log.append(
        **fields,  # type: ignore[arg-type]
        timestamp=30.0,
        status="completed",
        data={"summary": "done"},
        idempotency_key="long-job:terminal",
    )

    retained = [event for event in log.snapshot() if event["jobId"] == "long-job"]
    assert len(retained) == 5
    assert retained[0]["status"] == "created"
    assert retained[-1] == terminal
    assert retained[-1]["revision"] == 23
    assert retained[-1]["requestId"] == fields["request_id"]
    assert retained[-1]["runId"] == fields["run_id"]
    assert len(log._projection_events) == 5
    duplicate_terminal = log.append(
        **fields,  # type: ignore[arg-type]
        timestamp=30.0,
        status="completed",
        idempotency_key="long-job:terminal",
    )
    assert duplicate_terminal == {**terminal, "duplicate": True}
    assert log.active_job_ids() == []


def test_companion_job_log_projection_dedupe_tracks_terminal_retention():
    log = CompanionJobEventLog(max_jobs=2, max_events_per_job=4)
    first = _job_event_fields("job-1")
    second = _job_event_fields("job-2")
    third = _job_event_fields("job-3")
    log.append(**first, timestamp=1.0, status="created")  # type: ignore[arg-type]
    terminal = log.append(
        **first,  # type: ignore[arg-type]
        timestamp=2.0,
        status="completed",
        idempotency_key="projection:terminal-1",
    )
    duplicate = log.append(
        **first,  # type: ignore[arg-type]
        timestamp=2.0,
        status="completed",
        idempotency_key="projection:terminal-1",
    )
    assert duplicate == {**terminal, "duplicate": True}

    log.append(**second, timestamp=3.0, status="created")  # type: ignore[arg-type]
    log.append(**third, timestamp=4.0, status="created")  # type: ignore[arg-type]

    assert not log.contains("job-1")
    assert log.active_job_ids() == ["job-2", "job-3"]
    reused = log.append(
        **third,  # type: ignore[arg-type]
        timestamp=5.0,
        status="running",
        idempotency_key="projection:terminal-1",
    )
    assert "duplicate" not in reused
    assert len(log._projection_events) == 1
