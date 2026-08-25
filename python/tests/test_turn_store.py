from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.runtime import create_agent_runtime
from modules.agent.runtime_context import RuntimeContext, RuntimeContextRegistry
from modules.agent.turn_outbox import (
    TurnOutboxDispatcher,
    TurnOutboxWorker,
    TurnProjection,
)
from modules.agent.turn_service import (
    SemanticTurnRequest,
    TurnClaimLostError,
    TurnIdentityConflictError,
    TurnPorts,
    TurnService,
)
from modules.agent.turn_store import TurnCommitStore


class ManualClock:
    def __init__(self, value: float) -> None:
        self._value = value
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self._value

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value


class IdempotentProjectionRepository:
    def save_message_pair(self, *_args, **_kwargs):
        return ({"id": 1}, {"id": 2})


def test_turn_commit_store_is_idempotent_and_exposes_outbox(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    commit = SimpleNamespace(idempotency_key="turn:k", semantic_fingerprint="fp", trigger="http", context=context, result=result)
    store.persist(commit)
    store.persist(commit)
    stored = store.load("turn:k")
    assert stored is not None
    assert stored["result"]["outcome"] == "completed"
    assert stored["result"]["retryable"] is False
    assert stored["result"]["configured_budget"] == {}
    assert stored["result"]["consumed_usage"] == {}
    pending = store.pending_outbox()
    assert len(pending) == 1
    store.acknowledge(pending[0]["event_id"])
    assert store.pending_outbox() == []


def test_new_turn_service_replays_durable_commit_without_running_pipeline(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    request = SemanticTurnRequest(
        session_id="session-1",
        workspace_id="workspace-1",
        request_id="request-1",
        turn_id="turn-1",
        messages=[{"role": "user", "content": "remember this"}],
    )
    calls = {"first": 0, "second": 0}

    async def first_run(_ctx):
        calls["first"] += 1
        return AgentPipelineResult(reply="durable reply")

    first_service = TurnService(
        TurnPorts(run=first_run, persist=store.persist, load=store.load)
    )
    first = asyncio.run(first_service.execute_http(request))
    assert first.persisted is True

    async def second_run(_ctx):
        calls["second"] += 1
        raise AssertionError("durable replay must not execute the pipeline")

    second_service = TurnService(
        TurnPorts(run=second_run, persist=store.persist, load=store.load)
    )
    replayed = asyncio.run(second_service.execute_http(request))

    assert replayed.result.reply == "durable reply"
    assert replayed.persisted is True
    assert replayed.persistence_result["replayed"] is True
    assert calls == {"first": 1, "second": 0}


def _durable_ports(store: TurnCommitStore, run):
    return TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
    )


def test_concurrent_services_claim_before_run_and_return_authoritative_result(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    calls: list[str] = []

    async def first_run(_ctx):
        calls.append("first")
        await asyncio.sleep(0.05)
        return AgentPipelineResult(reply="authority")

    async def second_run(_ctx):
        calls.append("second")
        return AgentPipelineResult(reply="raced")

    first_service = TurnService(_durable_ports(store, first_run), claim_wait_seconds=2.0)
    second_service = TurnService(_durable_ports(store, second_run), claim_wait_seconds=2.0)

    async def run_both():
        first_task = asyncio.create_task(first_service.execute_http(_request_for_store()))
        await asyncio.sleep(0.01)
        second_task = asyncio.create_task(second_service.execute_http(_request_for_store()))
        return await asyncio.gather(first_task, second_task)

    first, second = asyncio.run(run_both())

    assert calls == ["first"]
    assert first.result.reply == second.result.reply == "authority"
    assert second.replayed is True


def _request_for_store() -> SemanticTurnRequest:
    return SemanticTurnRequest(
        session_id="session-claim",
        workspace_id="workspace-claim",
        request_id="request-claim",
        turn_id="turn-claim",
        generation_id="generation-claim",
        messages=[{"role": "user", "content": "same request"}],
    )


def test_streaming_replay_emits_token_and_done_without_running_pipeline(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    async def first_run(_ctx):
        return AgentPipelineResult(reply="replayed reply", pet_control={"expression": "happy"})

    first_service = TurnService(_durable_ports(store, first_run))
    asyncio.run(first_service.execute_socket(_request_for_store()))

    async def forbidden_stream(_ctx, _adapter, _generation):
        raise AssertionError("durable replay must not run streaming pipeline")

    second_service = TurnService(TurnPorts(
        run=first_run,
        run_streaming=forbidden_stream,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
    ))
    ctx = second_service.build_context("socket", _request_for_store())

    class Adapter:
        def __init__(self) -> None:
            self.events = []

        async def send_json(self, event):
            self.events.append(event)

    adapter = Adapter()
    generation = SimpleNamespace(
        session_id=ctx.session_id,
        generation_id="generation-claim",
        cancel=asyncio.Event(),
        invalidated=False,
        tokens=[],
    )
    commit = asyncio.run(
        second_service.execute_streaming_context("socket", ctx, adapter, generation)
    )

    assert commit.replayed is True
    assert generation.tokens == ["replayed reply"]
    assert [event["type"] for event in adapter.events] == ["token", "pet_control", "done"]
    assert all(event["replayed"] is True for event in adapter.events)


def test_outbox_retries_only_unacknowledged_projection_and_preserves_order(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        messages=[{"role": "user", "content": "hello"}],
        extra={"turn_id": "turn-r", "generation_id": "gen-r", "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    commit = SimpleNamespace(
        idempotency_key="turn:outbox",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    )
    store.persist(commit)
    calls = {"first": 0, "second": 0}

    def first_projection(_event, _context):
        calls["first"] += 1

    def second_projection(_event, _context):
        calls["second"] += 1
        if calls["second"] == 1:
            raise RuntimeError("temporary projection failure")

    dispatcher = TurnOutboxDispatcher(store, [
        TurnProjection("first", first_projection),
        TurnProjection("second", second_projection),
    ], base_retry_seconds=0.01)
    first = asyncio.run(dispatcher.dispatch_pending())
    asyncio.run(asyncio.sleep(0.02))
    second = asyncio.run(dispatcher.dispatch_pending())

    assert first["delivered"] == 0
    assert first["errors"][0]["projection"] == "second"
    assert second["delivered"] == 1
    assert calls == {"first": 1, "second": 2}
    assert store.pending_outbox() == []


def test_relationship_projection_runs_after_commit_and_conflict_has_no_side_effect(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    relationship_events = []
    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(
        workspace_id="workspace-relationship",
        db_repo=IdempotentProjectionRepository(),
        relationship_event_writer=relationship_events.append,
    ))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        runtime_context_registry=registry,
        turn_store=store,
    )

    async def run(_ctx):
        return AgentPipelineResult(reply="ok")

    service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
        dispatch=runtime.turn_outbox_dispatcher,
        bind_context=registry.bind_request,
    ))
    request = SemanticTurnRequest(
        session_id="session-relationship",
        workspace_id="workspace-relationship",
        request_id="request-relationship",
        turn_id="turn-relationship",
        messages=[{"role": "user", "content": "谢谢你"}],
    )

    asyncio.run(service.execute_http(request))
    assert len(relationship_events) == 1

    conflicting = SemanticTurnRequest(
        **{**request.__dict__, "messages": [{"role": "user", "content": "我很难过"}]}
    )
    try:
        asyncio.run(TurnService(service.ports).execute_http(conflicting))
    except TurnIdentityConflictError as exc:
        assert "semantic turn identity" in str(exc)
    else:
        raise AssertionError("conflicting durable identity must fail closed")

    assert len(relationship_events) == 1


def test_stale_fencing_owner_cannot_commit_after_lease_takeover(tmp_path) -> None:
    clock = ManualClock(100.0)
    store = TurnCommitStore(
        tmp_path / "turns.sqlite3",
        wall_clock=clock,
        monotonic_clock=clock,
    )
    first = store.claim("turn:fenced", "fp", "owner-1", 0.1)
    assert first["status"] == "claimed"
    clock.set(100.11)
    second = store.claim("turn:fenced", "fp", "owner-2", 1.0)
    assert second["status"] == "claimed"
    assert second["fencing_token"] > first["fencing_token"]

    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    stale = SimpleNamespace(
        idempotency_key="turn:fenced",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner="owner-1",
        claim_fencing_token=first["fencing_token"],
    )
    with pytest.raises(TurnClaimLostError):
        store.persist(stale)

    current = SimpleNamespace(
        **{
            **stale.__dict__,
            "claim_owner": "owner-2",
            "claim_fencing_token": second["fencing_token"],
        }
    )
    store.persist(current)
    assert store.load("turn:fenced") is not None


def test_renewal_failure_cancels_runner_and_prevents_commit(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    cancelled = asyncio.Event()

    async def run(_ctx):
        try:
            await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return AgentPipelineResult(reply="too late")

    def deny_renewal(_key, _owner, _token, _lease_seconds):
        return False

    service = TurnService(
        TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            claim=store.claim,
            renew_claim=deny_renewal,
            release_claim=store.release_claim,
        ),
        claim_lease_seconds=0.15,
    )

    with pytest.raises(TurnClaimLostError):
        asyncio.run(service.execute_http(_request_for_store()))
    assert cancelled.is_set()
    key = service.idempotency_key(service.build_context("http", _request_for_store()))
    assert store.load(key) is None


def test_renewal_failure_during_finalization_prevents_persist() -> None:
    persist_called = False

    async def run(_ctx):
        return AgentPipelineResult(reply="ready")

    async def finalize(_ctx, result):
        await asyncio.sleep(0.12)
        return result

    def claim(_key, _fingerprint, _owner, _lease_seconds):
        return {"status": "claimed", "fencing_token": 1}

    def renew(_key, _owner, _token, _lease_seconds):
        return False

    def release(_key, _owner, _token):
        return True

    def persist(_commit):
        nonlocal persist_called
        persist_called = True

    service = TurnService(
        TurnPorts(
            run=run,
            finalize=finalize,
            persist=persist,
            claim=claim,
            renew_claim=renew,
            release_claim=release,
        ),
        claim_lease_seconds=0.15,
    )

    with pytest.raises(TurnClaimLostError):
        asyncio.run(service.execute_http(_request_for_store()))
    assert persist_called is False


def test_concurrent_dispatchers_claim_each_projection_once(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    store.persist(SimpleNamespace(
        idempotency_key="turn:concurrent-outbox",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    ))
    calls = 0

    async def projection(_event, _context):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)

    first = TurnOutboxDispatcher(store, [TurnProjection("once", projection)])
    second = TurnOutboxDispatcher(store, [TurnProjection("once", projection)])

    async def dispatch_both():
        return await asyncio.gather(first.dispatch_pending(), second.dispatch_pending())

    results = asyncio.run(dispatch_both())
    assert calls == 1
    assert sum(result["delivered"] for result in results) == 1
    assert store.pending_outbox() == []


def test_slow_projection_renews_claim_and_cannot_be_taken_over(tmp_path) -> None:
    clock = ManualClock(100.0)
    renewed = threading.Event()

    def barrier(phase, _details):
        if phase == "outbox_claim.renewed":
            renewed.set()

    store = TurnCommitStore(
        tmp_path / "turns.sqlite3",
        wall_clock=clock,
        monotonic_clock=clock,
        barrier=barrier,
    )
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    store.persist(SimpleNamespace(
        idempotency_key="turn:slow-outbox",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    ))
    calls = 0
    concurrent = 0
    max_concurrent = 0

    started = threading.Event()
    release = threading.Event()

    def slow_projection(_event, _context):
        nonlocal calls, concurrent, max_concurrent
        calls += 1
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        started.set()
        assert release.wait(timeout=2.0)
        concurrent -= 1

    first = TurnOutboxDispatcher(
        store,
        [TurnProjection("slow", slow_projection)],
        claim_lease_seconds=0.1,
    )
    second = TurnOutboxDispatcher(
        store,
        [TurnProjection("slow", slow_projection)],
        claim_lease_seconds=0.1,
    )

    async def scenario():
        first_task = asyncio.create_task(first.dispatch_pending())
        assert await asyncio.to_thread(started.wait, 2.0)
        clock.set(100.05)
        assert await asyncio.to_thread(renewed.wait, 2.0)
        clock.set(100.11)
        second_result = await second.dispatch_pending()
        release.set()
        first_result = await first_task
        return first_result, second_result

    results = asyncio.run(scenario())
    assert calls == 1
    assert max_concurrent == 1
    assert sum(item["delivered"] for item in results) == 1
    assert store.pending_outbox() == []


def test_outbox_worker_retries_without_a_followup_request(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    store.persist(SimpleNamespace(
        idempotency_key="turn:worker",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    ))
    attempts = 0
    delivered = asyncio.Event()

    async def projection(_event, _context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("retry me")
        delivered.set()

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("eventual", projection)],
        base_retry_seconds=0.01,
        max_retry_seconds=0.02,
    )
    worker = TurnOutboxWorker(dispatcher, idle_poll_seconds=0.01)

    async def scenario():
        await worker.start()
        await asyncio.wait_for(delivered.wait(), timeout=1.0)
        await worker.stop()

    asyncio.run(scenario())
    assert attempts == 2
    assert worker.diagnostics()["pending"] == 0


def test_outbox_worker_stop_cleans_renewal_task_without_reentrant_projection(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    store.persist(SimpleNamespace(
        idempotency_key="turn:worker-stop",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    ))
    started = threading.Event()
    release = threading.Event()
    calls = 0
    concurrent = 0
    max_concurrent = 0

    def slow_projection(_event, _context):
        nonlocal calls, concurrent, max_concurrent
        calls += 1
        concurrent += 1
        max_concurrent = max(max_concurrent, concurrent)
        started.set()
        release.wait(timeout=1.0)
        concurrent -= 1

    async def production_shaped_projection(event, context):
        await asyncio.to_thread(slow_projection, event, context)

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("slow", production_shaped_projection)],
        claim_lease_seconds=0.2,
    )
    second_dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("slow", production_shaped_projection)],
        claim_lease_seconds=0.2,
    )
    worker = TurnOutboxWorker(
        dispatcher,
        idle_poll_seconds=0.01,
        shutdown_timeout_seconds=0.1,
    )

    async def scenario():
        await worker.start()
        assert await asyncio.to_thread(started.wait, 1.0)
        stop_task = asyncio.create_task(worker.stop())
        await asyncio.sleep(0.25)
        takeover = await second_dispatcher.dispatch_pending()
        assert takeover["delivered"] == 0
        assert calls == 1
        release.set()
        await stop_task
        renewal_tasks = [
            task.get_name()
            for task in asyncio.all_tasks()
            if not task.done() and task.get_name().startswith("turn-outbox-renew:")
        ]
        await asyncio.sleep(0)
        return renewal_tasks

    assert asyncio.run(scenario()) == []
    assert calls == 1
    assert max_concurrent == 1


def test_outbox_dead_letters_after_configured_attempt_limit(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    context = SimpleNamespace(
        workspace_id="w",
        session_id="s",
        request_id="r",
        autonomy_mode="read_only",
        model=None,
        messages=[],
        extra={"turn_id": "turn-r", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(reply="ok", pet_control=None, tool_calls=[], action_envelope=None)
    store.persist(SimpleNamespace(
        idempotency_key="turn:dead-letter",
        semantic_fingerprint="fp",
        trigger="http",
        context=context,
        result=result,
        claim_owner=None,
    ))

    def failing_projection(_event, _context):
        raise RuntimeError("permanent projection failure")

    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("always-fails", failing_projection)],
        max_attempts=2,
        base_retry_seconds=0.01,
        max_retry_seconds=0.01,
    )
    first = asyncio.run(dispatcher.dispatch_pending())
    time.sleep(0.02)
    second = asyncio.run(dispatcher.dispatch_pending())

    assert first["dead_lettered"] == 0
    assert second["dead_lettered"] == 1
    assert store.outbox_diagnostics()["dead_lettered"] == 1
    assert store.pending_outbox() == []


def test_chat_projection_is_commit_ordered_and_idempotent_on_replay(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    saved_pairs: list[dict[str, object]] = []
    run_contexts: list[AgentRequestContext] = []

    class Repository:
        def save_message_pair(self, session_id, user_text, assistant_text, **kwargs):
            saved_pairs.append({
                "session_id": session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                **kwargs,
            })
            return ({"id": 1}, {"id": 2})

    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(
        workspace_id="workspace-chat",
        db_repo=Repository(),
    ))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        runtime_context_registry=registry,
        turn_store=store,
    )

    async def run(_ctx):
        run_contexts.append(_ctx)
        return AgentPipelineResult(reply="assistant reply")

    ports = TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
        dispatch=runtime.turn_outbox_dispatcher,
        bind_context=registry.bind_request,
    )
    request = SemanticTurnRequest(
        session_id="session-chat",
        workspace_id="workspace-chat",
        request_id="request-chat",
        turn_id="turn-chat",
        messages=[{"role": "user", "content": "hello"}],
        context_options={"model": "model-chat"},
    )

    asyncio.run(TurnService(ports).execute_socket(request))
    asyncio.run(TurnService(ports).execute_socket(request))

    assert len(saved_pairs) == 1
    assert saved_pairs[0]["turn_idempotency_key"].startswith("turn:")
    assert saved_pairs[0]["model"] == "model-chat"
    assert run_contexts[0].extra["projected_message_ids"] == {
        "user_message_id": 1,
        "assistant_message_id": 2,
    }
    assert store.pending_outbox() == []


def test_pending_workspace_event_projects_to_payload_workspace_not_active_context(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    saved_pairs: list[dict[str, object]] = []
    relationship_events: list[tuple[str, dict[str, object]]] = []

    class Repository:
        def save_message_pair(self, session_id, user_text, assistant_text, **kwargs):
            saved_pairs.append({
                "session_id": session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                **kwargs,
            })
            return ({"id": 1}, {"id": 2})

    repository = Repository()
    class RelationshipWriterFactory:
        def for_workspace(self, workspace_id: str):
            return lambda event: relationship_events.append((workspace_id, event))

    writer_factory = RelationshipWriterFactory()
    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(
        workspace_id="workspace-b",
        db_repo=repository,
        relationship_event_writer=writer_factory.for_workspace("workspace-b"),
        extras={
            "shared_workspace_projection_repository": True,
            "relationship_writer_factory": writer_factory.for_workspace,
        },
    ))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        runtime_context_registry=registry,
        turn_store=store,
    )
    context = SimpleNamespace(
        workspace_id="workspace-a",
        session_id="session-a",
        request_id="request-a",
        autonomy_mode="read_only",
        model="model-a",
        messages=[{"role": "user", "content": "thank you"}],
        extra={"turn_id": "turn-a", "generation_id": None, "interruption_epoch": 0},
    )
    result = SimpleNamespace(
        reply="you are welcome",
        pet_control=None,
        tool_calls=[],
        action_envelope=None,
    )
    store.persist(SimpleNamespace(
        idempotency_key="turn:workspace-a",
        semantic_fingerprint="fp-a",
        trigger="socket",
        context=context,
        result=result,
        claim_owner=None,
    ))
    active_b_context = SimpleNamespace(
        workspace_id="workspace-b",
        extra={
            "db_repo": repository,
            "relationship_event_writer": registry.require("workspace-b").relationship_event_writer,
        },
    )

    dispatched = asyncio.run(
        runtime.turn_outbox_dispatcher.dispatch_pending(context=active_b_context)
    )

    assert dispatched["delivered"] == 1
    assert saved_pairs == [{
        "session_id": "session-a",
        "user_text": "thank you",
        "assistant_text": "you are welcome",
        "model": "model-a",
        "workspace_id": "workspace-a",
        "tool_trace": [],
        "memory_trace": [],
        "turn_idempotency_key": "turn:workspace-a",
    }]
    assert len(relationship_events) == 1
    assert relationship_events[0][0] == "workspace-a"
    assert relationship_events[0][1]["workspace_id"] == "workspace-a"
    assert relationship_events[0][1]["turn_id"] == "turn-a"


def test_async_relationship_writer_is_awaited_before_projection_ack(tmp_path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    events: list[dict[str, object]] = []

    async def writer(event):
        await asyncio.sleep(0)
        events.append(event)

    registry = RuntimeContextRegistry()
    registry.register(RuntimeContext(
        workspace_id="workspace-async-writer",
        db_repo=IdempotentProjectionRepository(),
        relationship_event_writer=writer,
    ))
    runtime = create_agent_runtime(
        schedule_context_factory=lambda _item: None,
        runtime_context_registry=registry,
        turn_store=store,
    )

    async def run(_ctx):
        return AgentPipelineResult(reply="ok")

    request = SemanticTurnRequest(
        session_id="session-async-writer",
        workspace_id="workspace-async-writer",
        request_id="request-async-writer",
        turn_id="turn-async-writer",
        messages=[{"role": "user", "content": "thank you"}],
    )
    service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
        dispatch=runtime.turn_outbox_dispatcher,
        bind_context=registry.bind_request,
    ))

    asyncio.run(service.execute_http(request))
    assert len(events) == 1
    assert events[0]["workspace_id"] == "workspace-async-writer"
    assert events[0]["turn_id"] == "turn-async-writer"
    assert store.pending_outbox() == []


def test_stream_terminal_is_emitted_only_after_persist_and_dispatch() -> None:
    order: list[str] = []

    async def run(_ctx):
        raise AssertionError("non-streaming runner must not run")

    async def run_streaming(_ctx, adapter, _generation):
        await adapter.send_json({"type": "token", "content": "hello"})
        return AgentPipelineResult(reply="hello")

    def persist(_commit):
        order.append("persist")

    async def dispatch(_commit):
        order.append("dispatch")

    class Adapter:
        async def send_json(self, event):
            order.append(str(event["type"]))

    service = TurnService(TurnPorts(
        run=run,
        run_streaming=run_streaming,
        persist=persist,
        dispatch=dispatch,
    ))
    ctx = service.build_context("socket", _request_for_store())
    generation = SimpleNamespace(
        session_id=ctx.session_id,
        generation_id="generation-claim",
        cancel=asyncio.Event(),
        invalidated=False,
        tokens=[],
    )
    asyncio.run(service.execute_streaming_context("socket", ctx, Adapter(), generation))
    assert order == ["token", "persist", "dispatch", "done"]


def test_stream_terminal_is_not_emitted_when_commit_fails() -> None:
    events: list[str] = []

    async def run(_ctx):
        raise AssertionError("non-streaming runner must not run")

    async def run_streaming(_ctx, adapter, _generation):
        await adapter.send_json({"type": "token", "content": "hello"})
        await adapter.send_json({"type": "done", "content": "hello"})
        return AgentPipelineResult(reply="hello")

    def persist(_commit):
        raise RuntimeError("commit failed")

    class Adapter:
        async def send_json(self, event):
            events.append(str(event["type"]))

    service = TurnService(TurnPorts(
        run=run,
        run_streaming=run_streaming,
        persist=persist,
    ))
    ctx = service.build_context("socket", _request_for_store())
    generation = SimpleNamespace(
        session_id=ctx.session_id,
        generation_id="generation-claim",
        cancel=asyncio.Event(),
        invalidated=False,
        tokens=[],
    )
    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(service.execute_streaming_context("socket", ctx, Adapter(), generation))
    assert events == ["token"]
