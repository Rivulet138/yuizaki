from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import Any

import pytest
from modules.agent.agent_trace_store import AgentTraceStore
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.context import AgentPipelineResult
from modules.agent.policy_engine import PolicyEngine
from modules.agent.runtime import create_agent_runtime
from modules.agent.runtime_context import RuntimeContext, RuntimeContextRegistry
from modules.agent.tool_registry import ToolDefinition
from modules.agent.turn_outbox import TurnOutboxDispatcher, TurnProjection
from modules.agent.turn_service import TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore
from modules.system.heartbeat import (
    HeartbeatOpportunityAcceptance,
    HeartbeatOpportunityAuthorizationError,
    HeartbeatOpportunityConflictError,
    HeartbeatOpportunityTurnBridge,
    HeartbeatScheduler,
)


def _opportunity(
    scheduler: HeartbeatScheduler,
    *,
    workspace_id: str = "workspace-a",
    session_id: str = "session-a",
    job_id: str = "heartbeat-job-a",
    request_id: str = "heartbeat-request-a",
) -> HeartbeatOpportunityAcceptance:
    assert scheduler._emit_opportunity_job(
        {
            "type": "suggestion",
            "job_id": job_id,
            "request_id": request_id,
            "session_id": session_id,
            "source_kind": "completed_turn_followup",
            "source_id": "activity-frame-a",
        },
        workspace_id=workspace_id,
    )
    return HeartbeatOpportunityAcceptance(
        job_id=job_id,
        request_id=request_id,
        workspace_id=workspace_id,
        session_id=session_id,
    )


def _turn_service(calls: list[Any]) -> TurnService:
    async def run(context: Any) -> AgentPipelineResult:
        calls.append(context)
        return AgentPipelineResult(
            reply="accepted follow-up",
            configured_budget={"output_tokens": 512, "tool_budget": 2},
            consumed_usage={"output_tokens": 7, "tool_calls": 1},
        )

    return TurnService(TurnPorts(run=run))


@pytest.mark.asyncio
async def test_heartbeat_opportunity_never_runs_without_explicit_acceptance():
    calls: list[Any] = []
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    acceptance = _opportunity(scheduler)
    HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=lambda _acceptance, _pending: True,
    )

    assert calls == []
    assert acceptance.job_id in scheduler._opportunities


@pytest.mark.asyncio
async def test_authorized_acceptance_executes_once_and_replays_authoritative_commit():
    calls: list[Any] = []
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=lambda accepted, pending: (
            accepted.identity
            == (
                pending["job_id"],
                pending["request_id"],
                pending["workspace_id"],
                pending["session_id"],
            )
        ),
    )

    first = await bridge.accept(acceptance)
    replay = await bridge.accept(acceptance)

    assert len(calls) == 1
    assert first.commit is replay.commit
    assert first.commit.trigger == "heartbeat"
    assert first.commit.context.workspace_id == acceptance.workspace_id
    assert first.commit.context.session_id == acceptance.session_id
    assert first.commit.context.turn_id == f"heartbeat:{acceptance.job_id}"
    assert replay.replayed_delivery is True
    assert replay.response() == {
        "ok": True,
        "accepted": True,
        "job_id": acceptance.job_id,
        "request_id": acceptance.request_id,
        "workspace_id": acceptance.workspace_id,
        "session_id": acceptance.session_id,
        "commit_id": first.commit.idempotency_key,
        "semantic_fingerprint": first.commit.semantic_fingerprint,
        "turn_stage": "committed",
        "trigger": "heartbeat",
        "outcome": "completed",
        "retryable": False,
        "replayed": True,
        "configured_budget": {"output_tokens": 512, "tool_budget": 2},
        "consumed_usage": {"output_tokens": 7, "tool_calls": 1},
    }


@pytest.mark.asyncio
async def test_replayed_commit_retries_opportunity_outcome_projection_without_rerun():
    calls: list[Any] = []
    outcome_attempts = 0

    def observe(_pending: Any, _outcome: str) -> bool:
        nonlocal outcome_attempts
        outcome_attempts += 1
        return outcome_attempts > 1

    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    scheduler.set_proactive_outcome_observer(observe)
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=lambda _acceptance, _pending: True,
    )

    first = await bridge.accept(acceptance)
    assert acceptance.job_id in scheduler._opportunities
    replay = await bridge.accept(acceptance)

    assert replay.commit is first.commit
    assert len(calls) == 1
    assert outcome_attempts == 2
    assert acceptance.job_id not in scheduler._opportunities


@pytest.mark.asyncio
async def test_policy_denial_does_not_consume_or_execute_opportunity():
    calls: list[Any] = []
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=lambda _acceptance, _pending: False,
    )

    with pytest.raises(HeartbeatOpportunityAuthorizationError):
        await bridge.accept(acceptance)

    assert calls == []
    assert acceptance.job_id in scheduler._opportunities
    assert acceptance.job_id not in scheduler._opportunity_acceptance_claims


@pytest.mark.asyncio
async def test_expired_cancelled_and_cross_workspace_acceptance_fail_closed():
    calls: list[Any] = []
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=lambda _acceptance, _pending: True,
    )

    wrong_workspace = HeartbeatOpportunityAcceptance(
        job_id=acceptance.job_id,
        request_id=acceptance.request_id,
        workspace_id="workspace-b",
        session_id=acceptance.session_id,
    )
    with pytest.raises(HeartbeatOpportunityConflictError):
        await bridge.accept(wrong_workspace)

    pending = scheduler._opportunities[acceptance.job_id]
    assert scheduler.expire_opportunities(now=float(pending["expires_at"]) + 1.0) == 1
    with pytest.raises(HeartbeatOpportunityConflictError):
        await bridge.accept(acceptance)

    cancelled = _opportunity(
        scheduler,
        job_id="heartbeat-job-cancelled",
        request_id="heartbeat-request-cancelled",
    )
    assert scheduler.resolve_opportunity(
        job_id=cancelled.job_id,
        request_id=cancelled.request_id,
        outcome="cancelled",
        reason="user_cancelled",
    )
    with pytest.raises(HeartbeatOpportunityConflictError):
        await bridge.accept(cancelled)

    assert calls == []


@pytest.mark.asyncio
async def test_async_authorization_rechecks_expiry_fence_before_turn_execution():
    calls: list[Any] = []
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    acceptance = _opportunity(scheduler)

    async def authorize(_acceptance: Any, pending: Any) -> bool:
        scheduler.expire_opportunities(now=float(pending["expires_at"]) + 1.0)
        return True

    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=_turn_service(calls),
        authorizer=authorize,
    )

    with pytest.raises(HeartbeatOpportunityConflictError):
        await bridge.accept(acceptance)

    assert calls == []


def test_acceptance_contract_requires_complete_identity():
    with pytest.raises(ValueError):
        HeartbeatOpportunityAcceptance.from_mapping(
            "job-a",
            {"request_id": "request-a", "workspace_id": "workspace-a"},
        )

    accepted = HeartbeatOpportunityAcceptance.from_mapping(
        "job-a",
        {
            "requestId": "request-a",
            "workspaceId": "workspace-a",
            "sessionId": "session-a",
            "ignored": time.time(),
        },
    )
    assert accepted.identity == ("job-a", "request-a", "workspace-a", "session-a")


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["cancelled", "expired"])
async def test_inflight_cancel_or_expiry_produces_one_authoritative_terminal(terminal: str):
    started = asyncio.Event()
    calls = 0

    async def run(_context: Any) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled heartbeat runner resumed")

    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=TurnService(TurnPorts(run=run)),
        authorizer=lambda _acceptance, _pending: True,
    )

    accepting = asyncio.create_task(bridge.accept(acceptance))
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert scheduler.resolve_opportunity(
        job_id=acceptance.job_id,
        request_id=acceptance.request_id,
        outcome=terminal,
        reason=f"test_{terminal}",
    )
    result = await asyncio.wait_for(accepting, timeout=1.0)

    assert calls == 1
    assert result.commit.outcome in {"cancelled", "unknown_effect"}
    assert result.commit.retryable is False
    terminal_events = [
        event
        for event in job_events.snapshot()
        if event["jobId"] == acceptance.job_id
        and event["status"] in {"completed", "cancelled", "failed"}
    ]
    assert terminal_events == []
    assert acceptance.job_id not in scheduler._opportunities


@pytest.mark.asyncio
async def test_bridge_reconstruction_replays_durable_commit_without_duplicate_effect(tmp_path):
    calls = 0
    store = TurnCommitStore(tmp_path / "heartbeat-turns.sqlite3")

    async def run(_context: Any) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="durable heartbeat")

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    acceptance = _opportunity(scheduler)
    first_bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=service(),
        authorizer=lambda _acceptance, _pending: True,
    )
    first = await first_bridge.accept(acceptance)

    reconstructed = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=service(),
        authorizer=lambda _acceptance, _pending: True,
    )
    replay = await reconstructed.accept(acceptance)

    assert calls == 1
    assert replay.commit.idempotency_key == first.commit.idempotency_key
    assert replay.commit.semantic_fingerprint == first.commit.semantic_fingerprint
    assert replay.commit.replayed is True
    assert replay.replayed_delivery is True


@pytest.mark.asyncio
async def test_cancel_during_projection_ack_recovers_same_commit_without_duplicate_effect(tmp_path):
    projection_started = asyncio.Event()
    release_projection = asyncio.Event()
    store = TurnCommitStore(tmp_path / "projection-cancel.sqlite3")
    semantic_calls = 0
    projection_calls = 0

    async def run(_context: Any) -> AgentPipelineResult:
        nonlocal semantic_calls
        semantic_calls += 1
        return AgentPipelineResult(reply="effect completed")

    async def project(_event: Any, _context: Any) -> None:
        nonlocal projection_calls
        projection_calls += 1
        projection_started.set()
        await release_projection.wait()

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("required-heartbeat-terminal", project)],
    )

    turn_service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
        dispatch=dispatcher,
    ))
    job_events = CompanionJobEventLog()
    scheduler = HeartbeatScheduler(job_event_log=job_events)
    acceptance = _opportunity(scheduler)
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=turn_service,
        authorizer=lambda _acceptance, _pending: True,
    )

    accepting = asyncio.create_task(bridge.accept(acceptance))
    await asyncio.wait_for(projection_started.wait(), timeout=1.0)
    assert scheduler.resolve_opportunity(
        job_id=acceptance.job_id,
        request_id=acceptance.request_id,
        outcome="cancelled",
        reason="cancel_during_projection",
    )
    release_projection.set()
    result = await asyncio.wait_for(accepting, timeout=1.0)

    assert result.commit.outcome == "completed"
    assert result.commit.retryable is False
    assert semantic_calls == 1
    assert projection_calls == 1
    assert store.pending_outbox() == []
    assert result.commit.semantic_fingerprint
    terminal_events = [
        event
        for event in job_events.snapshot()
        if event["jobId"] == acceptance.job_id
        and event["status"] in {"completed", "cancelled", "failed"}
    ]
    assert terminal_events == []


@pytest.mark.asyncio
async def test_production_runtime_terminalizes_original_heartbeat_job_once_and_replays(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path / "runtime-data"))
    projection_acks: list[str] = []

    def barrier(phase: str, details: dict[str, Any]) -> None:
        if phase == "outbox_projection.acknowledged":
            projection_acks.append(str(details["projection_name"]))

    store = TurnCommitStore(tmp_path / "heartbeat-runtime.sqlite3", barrier=barrier)
    trace_store = AgentTraceStore(tmp_path / "heartbeat-trace.json")
    job_events = CompanionJobEventLog()
    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(workspace_id="workspace-a"))
    registry.register(RuntimeContext(workspace_id="workspace-b"))
    semantic_contexts: list[Any] = []

    async def run(context: Any) -> AgentPipelineResult:
        semantic_contexts.append(context)
        return AgentPipelineResult(reply="production heartbeat")

    def runtime_service():
        runtime = create_agent_runtime(
            schedule_context_factory=lambda _item: None,
            trace_store=trace_store,
            job_event_log=job_events,
            runtime_context_registry=registry,
            turn_store=store,
        )
        assert runtime.turn_service is not None
        runtime.turn_service.ports = replace(
            runtime.turn_service.ports,
            run=run,
            run_streaming=None,
        )
        return runtime.turn_service, runtime.turn_outbox_dispatcher

    scheduler = HeartbeatScheduler(job_event_log=job_events)
    acceptance = _opportunity(scheduler)
    service, dispatcher = runtime_service()
    bridge = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=service,
        authorizer=lambda _acceptance, _pending: True,
    )

    wrong_workspace = HeartbeatOpportunityAcceptance(
        job_id=acceptance.job_id,
        request_id=acceptance.request_id,
        workspace_id="workspace-b",
        session_id=acceptance.session_id,
    )
    with pytest.raises(HeartbeatOpportunityConflictError):
        await bridge.accept(wrong_workspace)

    first = await bridge.accept(acceptance)
    reconstructed_service, reconstructed_dispatcher = runtime_service()
    reconstructed = HeartbeatOpportunityTurnBridge(
        scheduler=scheduler,
        turn_service=reconstructed_service,
        authorizer=lambda _acceptance, _pending: True,
    )
    replay = await reconstructed.accept(acceptance)

    expected_projections = {
        "chat.exchange",
        "relationship.user-signal",
        "agent-trace.terminal",
        "job.terminal",
        "activity-frame.completed-turn-followup",
    }
    events = job_events.snapshot()
    original = [event for event in events if event["jobId"] == acceptance.job_id]
    terminals = [
        event
        for event in original
        if event["status"] in {"completed", "cancelled", "failed", "unknown_effect"}
    ]

    assert [event["data"]["phase"] for event in original[:-1]] == [
        "opportunity_requested",
        "offered",
        "accepted",
        "running",
    ]
    assert len(terminals) == 1
    assert terminals[0]["status"] == "completed"
    assert all(event["workspaceId"] == "workspace-a" for event in original)
    assert not any(event["jobId"] == f"heartbeat:{acceptance.job_id}" for event in events)
    assert not any(event["workspaceId"] == "workspace-b" for event in events)
    assert store.pending_outbox() == []
    assert set(projection_acks) == expected_projections
    assert len(projection_acks) == len(expected_projections)
    assert dispatcher is not None
    assert reconstructed_dispatcher is not None
    assert len(semantic_contexts) == 1
    assert len(trace_store.snapshot()["runtime_loop"]) == 1
    assert replay.commit.idempotency_key == first.commit.idempotency_key
    assert replay.commit.semantic_fingerprint == first.commit.semantic_fingerprint
    assert replay.commit.replayed is True


def test_heartbeat_permission_scope_is_immutable_and_workspace_isolated(tmp_path):
    policy = PolicyEngine(tmp_path / "permissions.json")
    tool = ToolDefinition(
        name="sensitive_tool",
        description="requires confirmation",
        source="builtin",
        parameters={},
        handler=lambda: None,
        require_confirm=True,
        risk_level="high",
    )
    policy.resolve_pending(
        "remember-default",
        True,
        remember=True,
        tool_name=tool.name,
        permission_scope="default",
    )
    policy.resolve_pending(
        "remember-workspace-b",
        True,
        remember=True,
        tool_name=tool.name,
        permission_scope="heartbeat:workspace-b",
    )

    decision = policy.preview_tool(tool, permission_scope="heartbeat:workspace-a")
    scheduler = HeartbeatScheduler(job_event_log=CompanionJobEventLog())
    acceptance = _opportunity(scheduler)
    pending = scheduler.claim_opportunity_acceptance(acceptance)
    assert pending is not None
    request = HeartbeatOpportunityTurnBridge._turn_request(acceptance, pending)

    assert decision.allowed is False
    assert decision.require_confirm is True
    assert request.context_options["permission_scope"] == "heartbeat:workspace-a"
    assert request.extra["permission_scope"] == "heartbeat:workspace-a"
    assert request.extra["job_id"] == acceptance.job_id
    assert request.extra["run_id"] == (
        f"heartbeat-accept:{acceptance.job_id}:{acceptance.request_id}"
    )
