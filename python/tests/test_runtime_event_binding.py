from __future__ import annotations

from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.runtime import create_agent_runtime


def test_runtime_injects_shared_job_event_log_into_tool_executor() -> None:
    shared_log = CompanionJobEventLog()

    runtime = create_agent_runtime(
        schedule_context_factory=lambda _context: None,
        job_event_log=shared_log,
    )

    assert runtime.tool_executor.job_event_log is shared_log
