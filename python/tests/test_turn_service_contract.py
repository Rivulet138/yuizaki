from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.prompt_assembly import PromptBlock
from modules.agent.turn_service import (
    SemanticTurnRequest,
    TurnIdentityConflictError,
    TurnPorts,
    TurnService,
)
from modules.agent.turn_store import TurnCommitStore


def _request() -> SemanticTurnRequest:
    return SemanticTurnRequest(
        session_id="session-1",
        workspace_id="workspace-1",
        request_id="request-1",
        turn_id="turn-1",
        generation_id="generation-1",
        interruption_epoch=2,
        messages=[{"role": "user", "content": "hello"}],
    )


def test_all_transport_triggers_share_identity_but_have_distinct_projection_fingerprints():
    seen: list[tuple[str, str, str]] = []

    async def run(ctx):
        seen.append((ctx.session_id, ctx.request_id or "", str(ctx.extra["turn_id"])))
        return AgentPipelineResult(reply="same result")

    commits = []
    for trigger in ("http", "socket", "voice", "scheduler", "heartbeat"):
        service = TurnService(TurnPorts(run=run))
        commits.append(asyncio.run(service.execute(trigger, _request())))

    assert [commit.result.reply for commit in commits] == ["same result"] * 5
    assert len({commit.semantic_fingerprint for commit in commits}) == 5
    assert len({commit.idempotency_key for commit in commits}) == 1
    assert seen == [("session-1", "request-1", "turn-1")] * 5


def test_duplicate_requests_commit_once_even_when_calls_are_concurrent():
    calls = {"run": 0, "finalize": 0, "persist": 0}

    async def run(_ctx):
        calls["run"] += 1
        await asyncio.sleep(0)
        return AgentPipelineResult(reply="raw")

    async def finalize(_ctx, result):
        calls["finalize"] += 1
        return AgentPipelineResult(reply=result.reply + " finalized")

    async def persist(commit):
        calls["persist"] += 1
        return {"stored": commit.idempotency_key}

    service = TurnService(TurnPorts(run=run, finalize=finalize, persist=persist))

    async def execute_twice():
        return await asyncio.gather(
            service.execute_http(_request()),
            service.execute_http(_request()),
        )

    first, second = asyncio.run(execute_twice())

    assert first is second
    assert first.result.reply == "raw finalized"
    assert first.persisted is True
    assert first.persistence_result == {"stored": first.idempotency_key}
    assert calls == {"run": 1, "finalize": 1, "persist": 1}


def test_context_identity_and_trigger_are_normalized_without_transport_objects():
    async def run(ctx):
        return AgentPipelineResult(reply=ctx.extra["turn_trigger"])

    service = TurnService(TurnPorts(run=run))
    commit = asyncio.run(service.execute(
        "heartbeat",
        {
            "sessionId": "session-2",
            "workspaceId": "workspace-2",
            "requestId": "request-2",
            "messages": [{"role": "user", "content": "ping"}],
            "interruptionEpoch": 9,
        },
    ))

    assert commit.context.sid == "heartbeat"
    assert commit.context.session_id == "session-2"
    assert commit.context.extra["turn_id"] == "turn:request-2"
    assert commit.context.extra["generation_id"] == "generation:turn:request-2"
    assert commit.context.extra["interruption_epoch"] == 9
    assert commit.result.reply == "heartbeat"


def test_failed_persistence_does_not_leave_a_false_commit_and_can_retry():
    calls = {"persist": 0}

    async def run(_ctx):
        return AgentPipelineResult(reply="retryable")

    async def persist(_commit):
        calls["persist"] += 1
        if calls["persist"] == 1:
            raise RuntimeError("storage unavailable")
        return "ok"

    service = TurnService(TurnPorts(run=run, persist=persist))
    try:
        asyncio.run(service.execute_http(_request()))
    except RuntimeError as exc:
        assert str(exc) == "storage unavailable"
    else:
        raise AssertionError("first persistence attempt should fail")

    commit = asyncio.run(service.execute_http(_request()))
    assert commit.persisted is True
    assert commit.persistence_result == "ok"
    assert calls["persist"] == 2


def test_reusing_a_turn_identity_with_different_semantics_is_rejected():
    async def run(_ctx):
        return AgentPipelineResult(reply="one")

    service = TurnService(TurnPorts(run=run))
    asyncio.run(service.execute_http(_request()))
    conflicting = SemanticTurnRequest(
        **{**_request().__dict__, "messages": [{"role": "user", "content": "different"}]}
    )

    try:
        asyncio.run(service.execute_socket(conflicting))
    except TurnIdentityConflictError as exc:
        assert "semantic turn identity" in str(exc)
    else:
        raise AssertionError("conflicting semantic input should not reuse a commit")


_SEMANTIC_EXTRA_VALUES = {
    "additional_prompt_blocks": [PromptBlock(
        block_id="policy",
        source="test",
        trust="trusted",
        authority="system",
        order=1,
        content="Use concise answers.",
    )],
    "allowed_mcp_server_names": ["calendar"],
    "allowed_tool_names": ["time.now"],
    "configured_budget": {"tool_budget": 2},
    "execution_mode": "tool_loop",
    "force_tool_loop": True,
    "max_iterations": 4,
    "max_retries": 2,
    "max_tool_calls": 6,
    "memory_sources": ["profile"],
    "model_provider": "openai",
    "preferred_tool_names": ["time.now"],
    "prefetched_tool_candidates": ["time.now"],
    "provider": "openai",
    "provider_name": "primary",
    "recent_signal_docs": [{"kind": "commitment"}],
    "relationship_history": [{"kind": "support", "text": "remember this"}],
    "relationship_summary": {"relationship_stage": "warming"},
    "retrieved_chunks": ["relevant memory"],
    "retry_budget": 2,
    "retry_limit": 2,
    "route": "task-router",
    "routing_mode": "agentic",
    "runtime_revision": 3,
    "streaming_tool_max_iterations": 4,
    "system_prompt": "Workspace policy",
    "system_prompt_modifier": "Prefer direct answers",
    "tool_budget": 5,
    "workspace_mcp_preset": ["calendar"],
    "workspace_tool_preset": ["time.now"],
}


@pytest.mark.parametrize("semantic_field", sorted(_SEMANTIC_EXTRA_VALUES))
def test_each_execution_extra_change_conflicts_before_runner(
    semantic_field: str,
) -> None:
    assert set(_SEMANTIC_EXTRA_VALUES) == TurnService._SEMANTIC_EXTRA_FIELDS
    calls = 0
    claims = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="once")

    def claim(_key: str, _fingerprint: str, _owner: str, _lease: float) -> dict[str, object]:
        nonlocal claims
        claims += 1
        return {"status": "claimed", "fencing_token": claims}

    service = TurnService(TurnPorts(
        run=run,
        claim=claim,
        release_claim=lambda *_args: True,
    ))
    asyncio.run(service.execute_http(_request()))
    conflicting = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {
            semantic_field: _SEMANTIC_EXTRA_VALUES[semantic_field],
        }}
    )

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service.execute_http(conflicting))
    assert calls == 1
    assert claims == 1


def test_changed_tool_budget_conflicts_with_durable_commit_before_rerun(
    tmp_path: Path,
) -> None:
    calls = 0
    store = TurnCommitStore(tmp_path / "semantic-budget.sqlite3")

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="committed")

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    first = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {"tool_budget": 1}}
    )
    changed = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {"tool_budget": 2}}
    )
    asyncio.run(service().execute_http(first))

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service().execute_http(changed))
    assert calls == 1


def test_permission_scope_change_conflicts_before_runner() -> None:
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="once")

    service = TurnService(TurnPorts(run=run))
    first = SemanticTurnRequest(
        **{**_request().__dict__, "context_options": {"permission_scope": "local:read"}}
    )
    changed = SemanticTurnRequest(
        **{**_request().__dict__, "context_options": {"permission_scope": "local:write"}}
    )
    asyncio.run(service.execute_http(first))

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service.execute_http(changed))
    assert calls == 1


def test_runtime_handles_do_not_change_semantic_fingerprint_or_reexecute() -> None:
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="once")

    service = TurnService(TurnPorts(run=run))

    def request_with_runtime_handles() -> SemanticTurnRequest:
        return SemanticTurnRequest(
            **{
                **_request().__dict__,
                "context_options": {
                    "llm_client": object(),
                    "generation_mgr": object(),
                    "trace_store": object(),
                    "permission_request_cb": lambda **_kwargs: None,
                },
                "extra": {
                    "runtime_bindings": object(),
                    "db_repo": object(),
                    "cancellation_signal": object(),
                    "relationship_event_writer": lambda _event: None,
                },
            }
        )

    first = asyncio.run(service.execute_http(request_with_runtime_handles()))
    replay = asyncio.run(service.execute_http(request_with_runtime_handles()))

    assert replay is first
    assert calls == 1


def test_semantic_fingerprint_is_unicode_stable_and_mapping_order_independent() -> None:
    service = TurnService(TurnPorts(run=lambda _ctx: AgentPipelineResult(reply="unused")))
    first = service.build_context("http", SemanticTurnRequest(
        **{
            **_request().__dict__,
            "extra": {"configured_budget": {"tool_budget": 2, "备注": "桌宠"}},
        }
    ))
    reordered = service.build_context("http", SemanticTurnRequest(
        **{
            **_request().__dict__,
            "extra": {"configured_budget": {"备注": "桌宠", "tool_budget": 2}},
        }
    ))

    assert service.semantic_fingerprint(first) == service.semantic_fingerprint(reordered)


@pytest.mark.parametrize("invalid", [object(), {"nested": object()}, float("nan")])
def test_non_json_semantic_input_fails_before_runner(invalid: object) -> None:
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="must not run")

    request = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {"configured_budget": invalid}}
    )

    with pytest.raises(TypeError, match="semantic execution input"):
        asyncio.run(TurnService(TurnPorts(run=run)).execute_http(request))
    assert calls == 0


_PROJECTION_FLAT_VALUES = {
    "acceptance_id": "heartbeat-accept:job-a:request-a",
    "conversation_id": "conversation-a",
    "goal_id": "goal-a",
    "heartbeat_opportunity_id": "heartbeat-opportunity-a",
    "invocation_source": "accepted-heartbeat",
    "job_id": "job-a",
    "operation_id": "operation-a",
    "opportunity_id": "opportunity-a",
    "owner_agent_id": "yuizaki.scheduler",
    "owner_agent_role": "scheduler",
    "route_reason": "scheduled_task",
    "run_id": "run-a",
    "source": "scheduler",
    "source_id": "activity-frame-a",
    "source_kind": "completed_turn_followup",
    "task_id": "task-a",
    "task_mode": "once",
    "task_name": "Daily check-in",
}

_PROJECTION_NESTED_VALUES = {
    "heartbeat_opportunity": {
        "goal_id": "goal-a",
        "job_id": "job-a",
        "opportunity_id": "opportunity-a",
        "request_id": "request-1",
        "session_id": "session-1",
        "source_id": "activity-frame-a",
        "source_kind": "completed_turn_followup",
        "workspace_id": "workspace-1",
    },
    "job_outcome": {
        "conversation_id": "conversation-a",
        "job_id": "job-a",
        "operation_id": "operation-a",
        "owner_agent_id": "yuizaki.scheduler",
        "owner_agent_role": "scheduler",
        "route_reason": "scheduled_task",
        "run_id": "run-a",
        "status": "completed",
        "task_id": "task-a",
        "task_mode": "once",
        "task_name": "Daily check-in",
    },
    "job_terminal": {
        "conversation_id": "conversation-a",
        "job_id": "job-a",
        "operation_id": "operation-a",
        "owner_agent_id": "yuizaki.scheduler",
        "owner_agent_role": "scheduler",
        "route_reason": "scheduled_task",
        "run_id": "run-a",
        "status": "completed",
        "task_id": "task-a",
        "task_mode": "once",
        "task_name": "Daily check-in",
    },
}


@pytest.mark.parametrize("projection_field", sorted(_PROJECTION_FLAT_VALUES))
def test_each_flat_projection_identity_change_conflicts_before_runner(
    projection_field: str,
) -> None:
    assert set(_PROJECTION_FLAT_VALUES) == TurnService._PROJECTION_EXTRA_FIELDS
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="once")

    service = TurnService(TurnPorts(run=run))
    asyncio.run(service.execute_http(_request()))
    changed = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {
            projection_field: _PROJECTION_FLAT_VALUES[projection_field],
        }}
    )

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service.execute_http(changed))
    assert calls == 1


@pytest.mark.parametrize(
    ("container_name", "projection_field"),
    [
        (container_name, projection_field)
        for container_name, values in _PROJECTION_NESTED_VALUES.items()
        for projection_field in values
    ],
)
def test_each_nested_projection_identity_change_conflicts_before_runner(
    container_name: str,
    projection_field: str,
) -> None:
    assert {
        name: frozenset(values)
        for name, values in _PROJECTION_NESTED_VALUES.items()
    } == TurnService._PROJECTION_NESTED_FIELDS
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="once")

    service = TurnService(TurnPorts(run=run))
    asyncio.run(service.execute_http(_request()))
    changed = SemanticTurnRequest(
        **{**_request().__dict__, "extra": {
            container_name: {
                projection_field: _PROJECTION_NESTED_VALUES[container_name][projection_field],
            },
        }}
    )

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service.execute_http(changed))
    assert calls == 1


@pytest.mark.parametrize("shape", ["scheduler", "heartbeat"])
def test_projection_identity_change_conflicts_with_durable_commit(
    tmp_path: Path,
    shape: str,
) -> None:
    calls = 0
    store = TurnCommitStore(tmp_path / f"projection-{shape}.sqlite3")

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="project once")

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    if shape == "scheduler":
        original_extra = {
            "job_id": "job-a",
            "run_id": "run-a",
            "task_id": "task-a",
            "task_name": "Daily check-in",
            "task_mode": "once",
            "owner_agent_id": "yuizaki.scheduler",
            "owner_agent_role": "scheduler",
            "route_reason": "scheduled_task",
        }
        changed_extra = {**original_extra, "run_id": "run-b"}
        trigger = "scheduler"
    else:
        original_extra = {
            "job_id": "heartbeat-job-a",
            "invocation_source": "accepted-heartbeat",
            "heartbeat_opportunity": {
                "job_id": "heartbeat-job-a",
                "request_id": "request-1",
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "goal_id": "goal-a",
                "source_kind": "completed_turn_followup",
                "source_id": "activity-frame-a",
            },
        }
        changed_extra = {
            **original_extra,
            "heartbeat_opportunity": {
                **original_extra["heartbeat_opportunity"],
                "source_id": "activity-frame-b",
            },
        }
        trigger = "heartbeat"
    original = SemanticTurnRequest(**{**_request().__dict__, "extra": original_extra})
    changed = SemanticTurnRequest(**{**_request().__dict__, "extra": changed_extra})
    asyncio.run(service().execute(trigger, original))

    with pytest.raises(TurnIdentityConflictError):
        asyncio.run(service().execute(trigger, changed))
    assert calls == 1


def test_same_canonical_projection_identity_replays_from_durable_store(
    tmp_path: Path,
) -> None:
    calls = 0
    store = TurnCommitStore(tmp_path / "projection-replay.sqlite3")

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="project once")

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    first_extra = {
        "job_id": "job-a",
        "run_id": "run-a",
        "job_terminal": {"operation_id": "operation-a", "conversation_id": "conversation-a"},
    }
    reordered_extra = {
        "job_terminal": {"conversation_id": "conversation-a", "operation_id": "operation-a"},
        "run_id": "run-a",
        "job_id": "job-a",
    }
    first = asyncio.run(service().execute_scheduler(SemanticTurnRequest(
        **{**_request().__dict__, "extra": first_extra}
    )))
    replay = asyncio.run(service().execute_scheduler(SemanticTurnRequest(
        **{**_request().__dict__, "extra": reordered_extra}
    )))

    assert replay.replayed is True
    assert replay.semantic_fingerprint == first.semantic_fingerprint
    assert calls == 1


@pytest.mark.parametrize(
    "projection_extra",
    [
        {"job_id": object()},
        {"job_terminal": {"operation_id": object()}},
        {"heartbeat_opportunity": []},
    ],
)
def test_non_json_projection_identity_fails_before_runner(
    projection_extra: dict[str, object],
) -> None:
    calls = 0

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="must not run")

    request = SemanticTurnRequest(
        **{**_request().__dict__, "extra": projection_extra}
    )

    with pytest.raises(TypeError, match="semantic projection identity|semantic execution input"):
        asyncio.run(TurnService(TurnPorts(run=run)).execute_heartbeat(request))
    assert calls == 0


def test_volatile_projection_metadata_and_callbacks_do_not_change_fingerprint(
    tmp_path: Path,
) -> None:
    calls = 0
    store = TurnCommitStore(tmp_path / "projection-volatile.sqlite3")

    async def run(_ctx: AgentRequestContext) -> AgentPipelineResult:
        nonlocal calls
        calls += 1
        return AgentPipelineResult(reply="project once")

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=store.renew_claim,
            release_claim=store.release_claim,
        ))

    def request(created_at: float) -> SemanticTurnRequest:
        return SemanticTurnRequest(
            **{
                **_request().__dict__,
                "extra": {
                    "job_id": "heartbeat-job-a",
                    "heartbeat_opportunity": {
                        "job_id": "heartbeat-job-a",
                        "request_id": "request-1",
                        "workspace_id": "workspace-1",
                        "session_id": "session-1",
                        "source_kind": "completed_turn_followup",
                        "source_id": "activity-frame-a",
                        "created_at": created_at,
                        "expires_at": created_at + 60,
                        "on_complete": lambda: None,
                    },
                },
            }
        )

    first = asyncio.run(service().execute_heartbeat(request(1.0)))
    replay = asyncio.run(service().execute_heartbeat(request(2.0)))

    assert replay.replayed is True
    assert replay.semantic_fingerprint == first.semantic_fingerprint
    assert calls == 1


def test_existing_context_adapter_preserves_runtime_dependencies_and_semantic_identity():
    llm = object()
    registry = object()
    runtime_marker = object()
    seen = []

    async def run(ctx):
        seen.append(ctx)
        return AgentPipelineResult(reply="adapted")

    service = TurnService(TurnPorts(run=run))
    context = AgentRequestContext(
        sid="socket-sid",
        session_id="session-3",
        request_id="request-3",
        workspace_id="workspace-3",
        messages=[{"role": "user", "content": "same"}],
        llm_client=llm,
        tool_registry=registry,
        extra={
            "turn_id": "turn-3",
            "generation_id": "generation-3",
            "interruption_epoch": 4,
            "runtime_marker": runtime_marker,
        },
    )

    projected = service.request_from_context(context, trigger="voice")
    rebuilt = service.build_context("voice", projected)
    commit = asyncio.run(service.execute_context("voice", context))

    assert rebuilt.llm_client is llm
    assert rebuilt.tool_registry is registry
    assert rebuilt.extra["runtime_marker"] is runtime_marker
    assert rebuilt.extra["turn_id"] == "turn-3"
    assert rebuilt.extra["interruption_epoch"] == 4
    assert commit.context is context
    assert commit.semantic_fingerprint == service.semantic_fingerprint(rebuilt)
    assert seen == [context]


def test_streaming_context_uses_stream_runner_without_rebuilding_runtime_context():
    stream_calls = []

    async def run(_ctx):
        raise AssertionError("non-streaming runner must not be selected")

    async def run_streaming(ctx, adapter, generation):
        stream_calls.append((ctx, adapter, generation))
        return AgentPipelineResult(reply="streamed")

    service = TurnService(TurnPorts(run=run, run_streaming=run_streaming))
    context = AgentRequestContext(
        sid="voice",
        session_id="session-stream",
        request_id="request-stream",
        messages=[{"role": "user", "content": "speak"}],
        extra={"turn_id": "turn-stream", "generation_id": "gen-stream"},
    )
    adapter = object()
    generation = object()
    commit = asyncio.run(service.execute_streaming_context("voice", context, adapter, generation))

    assert commit.result.reply == "streamed"
    assert stream_calls == [(context, adapter, generation)]


def test_context_binder_runs_before_semantic_key_and_claim():
    observed: dict[str, object] = {}

    async def bind_context(ctx):
        observed["bound"] = True
        ctx.workspace_id = "workspace-bound"
        ctx.request_id = "request-bound"
        return ctx

    def claim(key, fingerprint, _owner, _lease_seconds):
        assert observed.get("bound") is True
        observed["key"] = key
        observed["fingerprint"] = fingerprint
        return {"status": "claimed", "fencing_token": 1}

    async def run(_ctx):
        return AgentPipelineResult(reply="bound")

    service = TurnService(TurnPorts(
        run=run,
        bind_context=bind_context,
        claim=claim,
        release_claim=lambda *_args: True,
    ))
    request = SemanticTurnRequest(
        session_id="session-bind",
        workspace_id="workspace-unbound",
        request_id="request-unbound",
        turn_id="turn-bind",
        generation_id="generation-bind",
        messages=[{"role": "user", "content": "bind first"}],
    )

    commit = asyncio.run(service.execute_http(request))

    assert commit.context.workspace_id == "workspace-bound"
    assert commit.context.request_id == "request-bound"
    assert observed["key"] == service.idempotency_key(commit.context)
    assert observed["fingerprint"] == service.semantic_fingerprint(commit.context)


def test_terminal_outcome_and_budget_usage_replay_with_legacy_defaults():
    request = _request()
    context = TurnService(TurnPorts(run=lambda _ctx: AgentPipelineResult(reply="unused"))).build_context(
        "http", request,
    )
    key = TurnService.idempotency_key(context)
    fingerprint = TurnService.semantic_fingerprint(context)
    stored = {
        "semantic_fingerprint": fingerprint,
        "result": {
            "reply": "manual recovery required",
            "pet_control": None,
            "tool_calls": [],
            "action_envelope": None,
            "outcome": "unknown_effect",
            "retryable": False,
            "configured_budget": {"output_tokens": 256, "tool_budget": 1},
            "consumed_usage": {"output_tokens": 42, "tool_calls": 1},
        },
    }

    service = TurnService(TurnPorts(
        run=lambda _ctx: AgentPipelineResult(reply="must not rerun"),
        load=lambda candidate: stored if candidate == key else None,
    ))
    replay = asyncio.run(service.execute_http(request))

    assert replay.replayed is True
    assert replay.outcome == "unknown_effect"
    assert replay.retryable is False
    assert replay.configured_budget == {"output_tokens": 256, "tool_budget": 1}
    assert replay.consumed_usage == {"output_tokens": 42, "tool_calls": 1}

    legacy = dict(stored)
    legacy["result"] = {
        "reply": "legacy",
        "pet_control": None,
        "tool_calls": [],
        "action_envelope": None,
    }
    legacy_service = TurnService(TurnPorts(
        run=lambda _ctx: AgentPipelineResult(reply="must not rerun"),
        load=lambda _candidate: legacy,
    ))
    legacy_replay = asyncio.run(legacy_service.execute_http(request))
    assert legacy_replay.outcome == "completed"
    assert legacy_replay.retryable is False
    assert legacy_replay.configured_budget == {}
    assert legacy_replay.consumed_usage == {}
