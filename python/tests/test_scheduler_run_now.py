from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.schedule_store import ScheduleStore
from modules.agent.scheduler import AgentScheduler


@pytest.fixture(autouse=True)
def _enable_explicit_legacy_turn_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YUIZAKI_ALLOW_LEGACY_TURN_PIPELINE", "1")


class _SlowPipeline:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.run_count = 0

    async def run(self, ctx: AgentRequestContext):
        self.run_count += 1
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(reply="queued run finished")


@pytest.mark.asyncio
async def test_run_now_queues_background_execution_without_waiting(tmp_path):
    store = ScheduleStore(path=str(tmp_path / "schedules.json"))
    pipeline = _SlowPipeline()
    scheduler = AgentScheduler(
        store=store,
        pipeline=pipeline,  # type: ignore[arg-type]
        context_factory=lambda task: AgentRequestContext(
            sid="sid",
            session_id="session",
            request_id=f"req-{task.id}",
            messages=[{"role": "user", "content": task.prompt}],
        ),
    )
    task = await scheduler.add_once("Review", "summarize", 60)

    returned = await scheduler.run_now(task.id)

    assert returned is task
    assert store.tasks[task.id].last_status == "queued"
    assert store.tasks[task.id].last_run_id is not None
    assert store.tasks[task.id].last_run_id.startswith("schedrun_")
    assert store.tasks[task.id].last_job_id is not None
    assert store.tasks[task.id].last_job_id.startswith("schedjob_")
    await asyncio.wait_for(pipeline.started.wait(), timeout=1)
    assert pipeline.run_count == 1

    pipeline.release.set()
    for _ in range(20):
        if store.tasks[task.id].last_status == "ok":
            break
        await asyncio.sleep(0.05)

    assert store.tasks[task.id].last_status == "ok"
    assert store.tasks[task.id].last_request_id is not None
    assert store.tasks[task.id].last_request_id.startswith("schedreq_")
    assert store.tasks[task.id].enabled is False
