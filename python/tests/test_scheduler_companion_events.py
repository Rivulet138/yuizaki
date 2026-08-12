from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.schedule_store import ScheduleStore
from modules.agent.scheduler import AgentScheduler
from modules.system.runtime_endpoints import (
    build_cancel_schedule_endpoint,
    build_run_schedule_now_endpoint,
)


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
