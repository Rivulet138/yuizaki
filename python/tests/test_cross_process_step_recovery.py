from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.planner import ToolStep
from modules.agent.recovery_store import SQLiteStepRecoveryStore
from modules.agent.step_executor import StepExecutor
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope
from modules.agent.turn_service import TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore


class _ReadExecutor:
    def __init__(self, registry: ToolRegistry, calls: list[str]) -> None:
        self.registry = registry
        self.calls = calls

    def preview_policy(self, _tool_name: str, _args: dict, *, ctx=None, force_confirmation=False):
        return SimpleNamespace(allowed=True, require_confirm=False, reason="ok")

    async def execute(self, tool_name: str, _args: dict, **_kwargs):
        self.calls.append(tool_name)
        return ToolResultEnvelope(
            success=True,
            content="read-result",
            source="builtin",
            tool_name=tool_name,
        )


def _step() -> ToolStep:
    return ToolStep(
        id="read-step",
        title="Read a value",
        tool_name="read_probe",
        arguments={"key": "status"},
        timeout_seconds=5,
        retry_budget=0,
        retry_owner="step_executor",
        idempotency_key="plan:read-step",
        success_criteria={"op": "status_in", "values": ["ok"]},
    )


@pytest.mark.asyncio
async def test_restart_safe_read_recovery_commits_new_turn_and_outbox(tmp_path: Path) -> None:
    recovery_store = SQLiteStepRecoveryStore(tmp_path / "recoveries.sqlite3")
    turn_store = TurnCommitStore(tmp_path / "turns.sqlite3")
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_probe",
        description="Read-only test probe",
        source="builtin",
        parameters={"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]},
        handler=lambda _args: None,
        effect_kind="read",
    ))
    calls: list[str] = []
    executor_binding = _ReadExecutor(registry, calls)
    runtime_context = SimpleNamespace(revision=7)
    binder = lambda ctx: ctx
    service = TurnService(TurnPorts(
        run=lambda _ctx: None,
        persist=turn_store.persist,
        load=turn_store.load,
        bind_context=binder,
    ))

    def factory(snapshot: dict) -> AgentRequestContext:
        return AgentRequestContext(
            sid=str(snapshot["sid"]),
            session_id=str(snapshot["session_id"]),
            workspace_id=str(snapshot["workspace_id"]),
            request_id=str(snapshot["request_id"]),
            turn_id=str(snapshot["turn_id"]),
            generation_id=str(snapshot["generation_id"]),
            messages=[],
            runtime_context=runtime_context,
            tool_registry=registry,
            tool_executor=executor_binding,
            turn_service=service,
            step_executor=executor,
            extra={"runtime_revision": runtime_context.revision},
        )

    executor = StepExecutor(
        recovery_store=recovery_store,
        recovery_context_factory=factory,
    )
    recovery_store.put(
        "rh_restart_read",
        _step(),
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        failed_step_id="read-step",
        context_snapshot={
            "recovery_id": "rh_restart_read",
            "sid": "sid-1",
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "request_id": "request-1",
            "turn_id": "turn-1",
            "generation_id": "generation-1",
            "runtime_revision": 7,
        },
    )

    result = await executor.resume_recovery_handle(
        "rh_restart_read",
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        failed_step_id="read-step",
    )

    assert result["ok"] is True
    assert result["recovery_id"] == "rh_restart_read"
    assert calls == ["read_probe"]
    committed = turn_store.load(result["idempotency_key"])
    assert committed is not None
    assert committed["trigger"] == "recovery"
    assert turn_store.pending_outbox()
    assert recovery_store.get_recovery("rh_restart_read")["status"] == "succeeded"


@pytest.mark.asyncio
async def test_restart_recovery_rejects_write_without_invoking_handler(tmp_path: Path) -> None:
    recovery_store = SQLiteStepRecoveryStore(tmp_path / "recoveries.sqlite3")
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="write_probe",
        description="State-changing test probe",
        source="builtin",
        parameters={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        handler=lambda _args: None,
        effect_kind="write",
    ))
    calls: list[str] = []
    executor_binding = _ReadExecutor(registry, calls)

    def factory(snapshot: dict) -> AgentRequestContext:
        return AgentRequestContext(
            sid=str(snapshot["sid"]),
            session_id=str(snapshot["session_id"]),
            workspace_id=str(snapshot["workspace_id"]),
            request_id=str(snapshot["request_id"]),
            turn_id=str(snapshot["turn_id"]),
            generation_id=str(snapshot["generation_id"]),
            messages=[],
            tool_registry=registry,
            tool_executor=executor_binding,
            runtime_context=SimpleNamespace(revision=1),
        )

    executor = StepExecutor(recovery_store=recovery_store, recovery_context_factory=factory)
    recovery_store.put(
        "rh_restart_write",
        ToolStep(
            id="write-step",
            title="Write a value",
            tool_name="write_probe",
            arguments={"value": "x"},
            timeout_seconds=5,
            retry_budget=0,
            retry_owner="step_executor",
            idempotency_key="plan:write-step",
            success_criteria={"op": "status_in", "values": ["ok"]},
        ),
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        failed_step_id="write-step",
        context_snapshot={
            "sid": "sid-1",
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "request_id": "request-1",
            "turn_id": "turn-1",
            "generation_id": "generation-1",
        },
    )

    result = await executor.resume_recovery_handle(
        "rh_restart_write",
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        failed_step_id="write-step",
    )

    assert result["error"] == "durable_recovery_not_allowed"
    assert calls == []
