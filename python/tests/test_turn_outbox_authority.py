from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from modules.agent.agent_trace_store import AgentTraceStore
from modules.agent.companion_events import CompanionJobEventLog
from modules.agent.runtime import create_agent_runtime
from modules.agent.runtime_context import RuntimeContext, RuntimeContextRegistry
from modules.agent.turn_outbox import TurnOutboxDispatcher, TurnProjection
from modules.agent.turn_store import TurnCommitStore


def _commit(
    key: str,
    *,
    workspace_id: str = "workspace-a",
    session_id: str = "session-shared",
    turn_id: str = "turn:job-shared",
    trigger: str = "http",
    outcome: str = "completed",
    user_text: str = "hello",
) -> SimpleNamespace:
    context = SimpleNamespace(
        workspace_id=workspace_id,
        session_id=session_id,
        request_id="request-shared",
        turn_id=turn_id,
        generation_id="generation-shared",
        interruption_epoch=3,
        autonomy_mode="assistant",
        model="test-model",
        messages=[{"role": "user", "content": user_text}],
        extra={
            "turn_id": turn_id,
            "generation_id": "generation-shared",
            "interruption_epoch": 3,
        },
    )
    result = SimpleNamespace(
        reply=f"reply:{workspace_id}",
        pet_control=None,
        tool_calls=[{"name": "read_file", "success": True}],
        action_envelope=None,
        outcome=outcome,
        retryable=False,
        configured_budget={"max_tool_calls": 4},
        consumed_usage={"tool_calls": 1},
    )
    return SimpleNamespace(
        idempotency_key=key,
        semantic_fingerprint=f"fingerprint:{key}",
        trigger=trigger,
        context=context,
        result=result,
        claim_owner=None,
    )


def test_commit_dispatch_barrier_fails_when_older_event_blocks_target(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    older = _commit("turn:older")
    target = _commit("turn:target")
    store.persist(older)
    store.persist(target)
    allow_older = False
    calls: list[str] = []

    def projection(event, _context):
        nonlocal allow_older
        key = str(event["idempotency_key"])
        calls.append(key)
        if key == older.idempotency_key and not allow_older:
            raise RuntimeError("older projection is unavailable")

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("ordered", projection)],
        base_retry_seconds=0.01,
        max_retry_seconds=0.01,
    )

    with pytest.raises(RuntimeError, match="did not acknowledge commit turn:target"):
        asyncio.run(dispatcher(target))

    assert [item["idempotency_key"] for item in store.pending_outbox()] == [
        "turn:older",
        "turn:target",
    ]
    allow_older = True
    asyncio.run(asyncio.sleep(0.02))
    result = asyncio.run(dispatcher(target))

    assert result["target_delivered"] is True
    assert result["delivered_idempotency_keys"] == ["turn:older", "turn:target"]
    assert store.pending_outbox() == []
    assert calls == ["turn:older", "turn:older", "turn:target"]


def test_runtime_projects_http_chat_trace_and_workspace_scoped_job_terminal(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YUIZAKI_DATA_DIR", str(tmp_path / "runtime-data"))
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    trace_store = AgentTraceStore(tmp_path / "agent-trace.json")
    job_log = CompanionJobEventLog()
    saved: list[dict[str, object]] = []

    class Repository:
        def __init__(self, workspace_id: str) -> None:
            self.workspace_id = workspace_id

        def save_message_pair(self, session_id, user_text, assistant_text, **kwargs):
            saved.append({
                "repository_workspace": self.workspace_id,
                "session_id": session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                **kwargs,
            })
            return ({"id": len(saved) * 2 - 1}, {"id": len(saved) * 2})

    registry = RuntimeContextRegistry()
    for workspace_id in ("workspace-a", "workspace-b"):
        registry.register(RuntimeContext(
            workspace_id=workspace_id,
            db_repo=Repository(workspace_id),
        ))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        trace_store=trace_store,
        job_event_log=job_log,
        runtime_context_registry=registry,
        turn_store=store,
    )
    first = _commit("turn:http-a", workspace_id="workspace-a")
    second = _commit("turn:http-b", workspace_id="workspace-b")
    scheduled = _commit(
        "turn:scheduler",
        workspace_id="workspace-a",
        turn_id="turn:scheduler-job",
        trigger="schedule",
        outcome="failed",
    )
    scheduled.result.retryable = True
    scheduled.result.failure = {
        "step_id": "write-output",
        "kind": "tool",
        "message": "temporary failure",
        "retryable": True,
        "completed_steps": ["inspect-input"],
        "resume_token": "must-not-cross-projection",
        "metadata": {"payload": "must-not-cross-projection"},
    }
    scheduled.result.recovery = {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "write-output",
        "retryable": True,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
        "handle": "rh_opaque",
        "resume_token": "must-not-cross-projection",
    }
    for commit in (first, second, scheduled):
        store.persist(commit)

    active_wrong_workspace = SimpleNamespace(workspace_id="workspace-b", extra={})
    result = asyncio.run(
        runtime.turn_outbox_dispatcher.dispatch_pending(context=active_wrong_workspace)
    )

    assert result["delivered"] == 3
    assert [(item["repository_workspace"], item["workspace_id"]) for item in saved] == [
        ("workspace-a", "workspace-a"),
        ("workspace-b", "workspace-b"),
    ]
    traces = trace_store.snapshot()["runtime_loop"]
    committed = [item for item in traces if item["stage"] == "turn_commit"]
    assert [item["data"]["workspace_id"] for item in committed] == [
        "workspace-a",
        "workspace-b",
        "workspace-a",
    ]
    jobs = job_log.snapshot()
    assert len(jobs) == 3
    assert [item["workspaceId"] for item in jobs[:2]] == ["workspace-a", "workspace-b"]
    assert jobs[0]["jobId"] == jobs[1]["jobId"] == "turn:job-shared"
    assert job_log.contains("turn:job-shared", "workspace-a")
    assert job_log.contains("turn:job-shared", "workspace-b")
    assert jobs[2]["jobId"] == "scheduler-job"
    assert jobs[2]["source"] == "scheduler"
    assert jobs[2]["status"] == "failed"
    assert jobs[2]["data"]["failure"] == {
        "step_id": "write-output",
        "kind": "tool",
        "message": "temporary failure",
        "retryable": True,
        "completed_steps": ["inspect-input"],
    }
    assert jobs[2]["data"]["recovery"] == {
        "available": True,
        "action": "resume_failed_step",
        "failed_step_id": "write-output",
        "retryable": True,
        "scope": "turn",
        "single_use": True,
        "ttl_seconds": 900,
        "handle": "rh_opaque",
    }
    assert jobs[2]["data"]["failureCategory"] == "tool"
    assert jobs[2]["data"]["failedStep"] == "write-output"
    assert jobs[2]["data"]["completedSteps"] == ["inspect-input"]
    assert "resume_token" not in str(jobs[2])


def test_projection_retry_after_effect_before_ack_does_not_duplicate_destinations(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    trace_store = AgentTraceStore(tmp_path / "trace.json")
    job_log = CompanionJobEventLog()
    commit = _commit("turn:effect-before-ack")
    store.persist(commit)
    attempts = 0

    def projection(event, _context):
        nonlocal attempts
        attempts += 1
        key = str(event["idempotency_key"])
        trace_store.append_once(
            "runtime_loop",
            {
                "timestamp": "2026-08-16T00:00:00+00:00",
                "session_id": "session-shared",
                "request_id": "request-shared",
                "stage": "turn_commit",
                "status": "completed",
                "summary": "done",
                "data": {"workspace_id": "workspace-a"},
            },
            projection_key=f"{key}:trace",
        )
        job_log.append(
            workspace_id="workspace-a",
            session_id="session-shared",
            turn_id="turn:job-shared",
            job_id="job-shared",
            request_id="request-shared",
            interruption_epoch=0,
            source="http",
            timestamp=1.0,
            status="completed",
            idempotency_key=f"{key}:job",
        )
        if attempts == 1:
            raise RuntimeError("crash after destinations committed")

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("durable-destinations", projection)],
        base_retry_seconds=0.01,
        max_retry_seconds=0.01,
    )
    first = asyncio.run(dispatcher.dispatch_pending())
    asyncio.run(asyncio.sleep(0.02))
    second = asyncio.run(dispatcher.dispatch_pending())

    assert first["delivered"] == 0
    assert second["delivered"] == 1
    assert attempts == 2
    assert len(trace_store.snapshot()["runtime_loop"]) == 1
    assert len(AgentTraceStore(tmp_path / "trace.json").snapshot()["runtime_loop"]) == 1
    assert len(job_log.snapshot()) == 1
    assert store.pending_outbox() == []
