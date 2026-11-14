from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from modules.agent.context import AgentRequestContext
from modules.agent.schedule_store import ScheduledTask, ScheduleStore
from modules.agent.scheduler import AgentScheduler, _ScheduledRun


def test_authoritative_unknown_effect_cannot_be_retryable() -> None:
    run = _ScheduledRun(
        task_id="task-1",
        run_id="run-1",
        job_id="job-1",
        request_id="request-1",
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
    )
    task = ScheduledTask(
        id="task-1",
        name="test",
        source="test",
        prompt="test",
        enabled=True,
        mode="once",
        created_at=1.0,
    )

    AgentScheduler._apply_authoritative_result(
        run,
        task,
        {"outcome": "unknown_effect", "retryable": True, "reply": ""},
    )

    assert run.outcome == "unknown_effect"
    assert run.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["once", "interval"])
@pytest.mark.parametrize("cancel_by", ["task_id", "job_id", "run_id"])
async def test_cancel_before_first_execution_persists_and_allows_requeue(
    tmp_path: Path, mode: str, cancel_by: str,
) -> None:
    store = ScheduleStore(tmp_path / "schedules.json")
    context_factory = Mock(side_effect=AssertionError("cancelled run must not start"))
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(), context_factory=context_factory,
    )
    task = await (
        scheduler.add_once("test", "test", 60)
        if mode == "once" else scheduler.add_interval("test", "test", 60)
    )
    first_background = await scheduler._queue_task(task)
    first_run = scheduler._runs_by_task[task.id]
    assert first_background is not None
    assert first_run.status == "created"
    try:
        # Do not yield between queueing and cancelling: _run_task must never enter.
        assert await scheduler.cancel(getattr(first_run, cancel_by)) is True
        context_factory.assert_not_called()
        assert first_background.cancelled()
        assert first_run.status == "cancelled"
        assert first_run.finished_at is not None
        assert task.id not in scheduler._active_task_ids
        assert task.id not in scheduler._runs_by_task
        assert scheduler.active_job_ids() == []
        events = scheduler.snapshot_job_events()
        assert [event["status"] for event in events] == ["created", "cancelled"]
        persisted = ScheduleStore(store.path).tasks[task.id]
        assert persisted.last_status == "cancelled"
        assert persisted.last_run_summary == "cancelled"
        assert persisted.last_run_at is not None
        assert persisted.last_run_id == first_run.run_id
        assert persisted.last_job_id == first_run.job_id
        assert persisted.last_request_id == first_run.request_id
        assert persisted.enabled is (mode == "interval")
        if mode == "once":
            assert persisted.next_run_at is None
        else:
            assert persisted.next_run_at > persisted.last_run_at

        # A real second execution must reach the local stub and finish normally.
        context_factory.side_effect = None
        context_factory.return_value = SimpleNamespace(request_id="stub-request")
        scheduler.turn_service = SimpleNamespace(
            execute_context=_completed_turn,
        )
        second_background = await scheduler._queue_task(task)
        second_run = scheduler._runs_by_task[task.id]
        assert second_background is not None
        assert second_background is not first_background
        assert second_run.run_id != first_run.run_id
        await second_background
        context_factory.assert_called_once_with(task)
        assert second_run.status == "completed"
        assert first_run.status == "cancelled"
        assert ScheduleStore(store.path).tasks[task.id].last_status == "ok"
        assert task.id not in scheduler._active_task_ids
    finally:
        await scheduler.stop()


async def _completed_turn(_source: str, _ctx: object) -> SimpleNamespace:
    return SimpleNamespace(
        outcome="completed",
        result=SimpleNamespace(reply="done"),
        idempotency_key="test-key",
        semantic_fingerprint="test-fingerprint",
        context=SimpleNamespace(generation_id="test-generation"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("already_cancelled", [False, True])
async def test_stop_cancels_all_runs_before_first_execution(
    tmp_path: Path, already_cancelled: bool,
) -> None:
    store = ScheduleStore(tmp_path / "schedules.json")
    context_factory = Mock(side_effect=AssertionError("cancelled run must not start"))
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(), context_factory=context_factory,
    )
    tasks = [
        await scheduler.add_once("once", "test", 60),
        await scheduler.add_interval("interval", "test", 60),
    ]
    backgrounds = [await scheduler._queue_task(task) for task in tasks]
    runs = [scheduler._runs_by_task[task.id] for task in tasks]
    if already_cancelled:
        for background in backgrounds:
            assert background is not None
            background.cancel()
        await asyncio.gather(*backgrounds, return_exceptions=True)
    # stop() must cancel the whole batch before yielding to any queued coroutine.
    await scheduler.stop()

    context_factory.assert_not_called()
    assert all(background is not None and background.cancelled() for background in backgrounds)
    assert all(run.status == "cancelled" and run.finished_at is not None for run in runs)
    assert scheduler._active_task_ids == set()
    assert scheduler._runs_by_task == {}
    assert scheduler._background_runs == set()
    assert scheduler.active_job_ids() == []
    persisted = ScheduleStore(store.path).tasks
    assert all(persisted[task.id].last_status == "cancelled" for task in tasks)
    assert persisted[tasks[0].id].enabled is False
    assert persisted[tasks[0].id].next_run_at is None
    assert persisted[tasks[1].id].enabled is True
    assert persisted[tasks[1].id].next_run_at is not None
    events = scheduler.snapshot_job_events()
    for run in runs:
        assert [event["status"] for event in events if event["runId"] == run.run_id] == [
            "created", "cancelled",
        ]
    await scheduler.stop()
    assert scheduler.snapshot_job_events() == events


@pytest.mark.asyncio
async def test_repeated_old_run_finalization_cannot_clear_requeued_run(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "schedules.json")
    context_factory = Mock(side_effect=AssertionError("cancelled run must not start"))
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(), context_factory=context_factory,
    )
    task = await scheduler.add_once("test", "test", 60)
    await scheduler._queue_task(task)
    old_run = scheduler._runs_by_task[task.id]
    try:
        assert await scheduler.cancel(old_run.run_id) is True
        terminal_state = asdict(task)
        events = scheduler.snapshot_job_events()
        await scheduler._finalize_run(task, old_run, cancelled=True)
        assert await scheduler.cancel(old_run.job_id) is False
        assert asdict(task) == terminal_state
        assert scheduler.snapshot_job_events() == events

        new_background = await scheduler._queue_task(task)
        new_run = scheduler._runs_by_task[task.id]
        new_state = asdict(task)
        new_events = scheduler.snapshot_job_events()
        disk_state = store.path.read_text(encoding="utf-8")
        await scheduler._finalize_run(task, old_run, cancelled=True)
        assert await scheduler.cancel(old_run.run_id) is False
        assert asdict(task) == new_state
        assert store.path.read_text(encoding="utf-8") == disk_state
        assert scheduler.snapshot_job_events() == new_events
        assert scheduler._runs_by_task[task.id] is new_run
        assert task.id in scheduler._active_task_ids
        assert new_background is not None and not new_background.done()
        assert new_run.status == "created"
        assert scheduler.active_job_ids() == [new_run.job_id]
        assert await scheduler.cancel(new_run.run_id) is True
        assert ScheduleStore(store.path).tasks[task.id].last_run_id == new_run.run_id
        context_factory.assert_not_called()
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_concurrent_cancel_of_started_run_is_idempotent(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def blocked_turn(_source: str, _ctx: object) -> None:
        started.set()
        await asyncio.Event().wait()

    store = ScheduleStore(tmp_path / "schedules.json")
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(),
        context_factory=lambda _task: SimpleNamespace(request_id="stub-request"),
        turn_service=SimpleNamespace(execute_context=blocked_turn),
    )
    task = await scheduler.add_interval("test", "test", 60)
    background = await scheduler._queue_task(task)
    run = scheduler._runs_by_task[task.id]
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert run.status == "running"
        assert await asyncio.gather(
            scheduler.cancel(task.id), scheduler.cancel(run.job_id),
        ) == [True, True]
        assert background is not None and background.cancelled()
        assert [event["status"] for event in scheduler.snapshot_job_events()] == [
            "created", "running", "cancelled",
        ]
        assert scheduler._active_task_ids == set()
        assert scheduler._runs_by_task == {}
        assert scheduler.active_job_ids() == []
        persisted = ScheduleStore(store.path).tasks[task.id]
        assert persisted.last_status == "cancelled"
        assert persisted.enabled is True
        assert persisted.next_run_at > persisted.last_run_at
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
async def test_stop_cancels_started_and_unstarted_runs_together(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def blocked_turn(_source: str, _ctx: object) -> None:
        started.set()
        await asyncio.Event().wait()

    store = ScheduleStore(tmp_path / "schedules.json")
    context_factory = Mock(return_value=SimpleNamespace(request_id="stub-request"))
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(), context_factory=context_factory,
        turn_service=SimpleNamespace(execute_context=blocked_turn),
    )
    running_task = await scheduler.add_interval("running", "test", 60)
    queued_task = await scheduler.add_once("queued", "test", 60)
    await scheduler.start()
    await scheduler._queue_task(running_task)
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        await scheduler._queue_task(queued_task)
        runs = [scheduler._runs_by_task[task.id] for task in (running_task, queued_task)]
        assert [run.status for run in runs] == ["running", "created"]
        await scheduler.stop()

        context_factory.assert_called_once_with(running_task)
        assert scheduler._task is None
        assert scheduler._running is False
        assert scheduler._active_task_ids == set()
        assert scheduler._runs_by_task == {}
        assert scheduler._background_runs == set()
        assert scheduler.active_job_ids() == []
        persisted = ScheduleStore(store.path).tasks
        assert all(run.status == "cancelled" for run in runs)
        assert all(persisted[run.task_id].last_status == "cancelled" for run in runs)
        events = scheduler.snapshot_job_events()
        assert [event["status"] for event in events if event["runId"] == runs[0].run_id] == [
            "created", "running", "cancelled",
        ]
        assert [event["status"] for event in events if event["runId"] == runs[1].run_id] == [
            "created", "cancelled",
        ]
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["completed", "unknown_effect"])
async def test_cancel_finalization_preserves_durable_outcome(tmp_path: Path, outcome: str) -> None:
    started = asyncio.Event()

    async def blocked_turn(_source: str, _ctx: object) -> None:
        started.set()
        await asyncio.Event().wait()

    stored = {
        "idempotency_key": "test-key",
        "semantic_fingerprint": "test-fingerprint",
        "created_at": 123.0,
        "result": {"outcome": outcome, "reply": "durable result", "retryable": True},
    }
    service = SimpleNamespace(
        execute_context=blocked_turn,
        ports=SimpleNamespace(load=Mock(return_value=stored)),
        idempotency_key=lambda _ctx: "test-key",
        semantic_fingerprint=lambda _ctx: "test-fingerprint",
    )
    store = ScheduleStore(tmp_path / "schedules.json")
    scheduler = AgentScheduler(
        store=store, pipeline=Mock(),
        context_factory=lambda _task: AgentRequestContext(sid="test", session_id="test", messages=[]),
        turn_service=service,
    )
    task = await scheduler.add_once("test", "test", 60)
    await scheduler._queue_task(task)
    run = scheduler._runs_by_task[task.id]
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert await scheduler.cancel(task.id) is True
        assert run.status == outcome
        assert run.outcome == outcome
        assert run.finished_at == 123.0
        if outcome == "unknown_effect":
            assert run.retryable is False
        persisted = ScheduleStore(store.path).tasks[task.id]
        assert persisted.last_status == ("ok" if outcome == "completed" else outcome)
        assert persisted.last_run_summary == "durable result"
        assert scheduler._active_task_ids == set()
        assert scheduler._runs_by_task == {}
        assert not any(event["status"] == "cancelled" for event in scheduler.snapshot_job_events())
        service.ports.load.assert_called_once_with("test-key")
    finally:
        await scheduler.stop()
