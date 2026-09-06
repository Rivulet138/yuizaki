from __future__ import annotations

import asyncio

from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.policy_engine import PolicyEngine
from modules.agent.tool_executor import ToolExecutor
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
