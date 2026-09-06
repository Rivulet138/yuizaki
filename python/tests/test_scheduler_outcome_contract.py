from __future__ import annotations

from modules.agent.schedule_store import ScheduledTask
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
