from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from modules.agent.context import AgentPipelineResult
from modules.agent.pipeline_contracts import terminal_contract
from modules.agent.projection_stage import ProjectionStage
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_loop import run_streaming_tool_loop
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope
from modules.agent.turn_outbox import TurnOutboxDispatcher, TurnProjection
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore


def _request() -> SemanticTurnRequest:
    return SemanticTurnRequest(
        session_id="session-cancel",
        workspace_id="workspace-cancel",
        request_id="request-cancel",
        turn_id="turn-cancel",
        generation_id="generation-cancel",
        interruption_epoch=3,
        messages=[{"role": "user", "content": "cancel me"}],
        context_options={"max_tokens": 128},
        extra={"max_iterations": 4, "retry_limit": 1, "tool_budget": 2},
    )


def test_caller_cancellation_stops_runner_and_persists_one_authoritative_terminal():
    started = asyncio.Event()
    runner_cancelled = asyncio.Event()
    persisted = []
    dispatched = []

    async def run(_ctx):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            runner_cancelled.set()
            raise

    async def scenario():
        service = TurnService(TurnPorts(
            run=run,
            persist=lambda commit: persisted.append(commit),
            dispatch=lambda commit: dispatched.append(commit),
        ))
        task = asyncio.create_task(service.execute_http(_request()))
        await started.wait()
        task.cancel()
        return await task

    commit = asyncio.run(scenario())

    assert runner_cancelled.is_set()
    assert persisted == [commit]
    assert dispatched == [commit]
    assert commit.outcome == "cancelled"
    assert commit.retryable is False
    assert commit.configured_budget == {
        "max_iterations": 4,
        "output_tokens": 128,
        "retry_limit": 1,
        "tool_budget": 2,
    }


def test_stream_discards_stale_generation_before_late_delta_and_terminal():
    events: list[str] = []
    persisted: list[object] = []
    dispatched: list[object] = []

    class Adapter:
        async def send_json(self, event):
            events.append(str(event["type"]))

    generation = SimpleNamespace(
        session_id="session-cancel",
        generation_id="generation-cancel",
        interruption_epoch=3,
        cancel=asyncio.Event(),
        invalidated=False,
        tokens=[],
    )

    async def run(_ctx):
        raise AssertionError("non-streaming runner must not run")

    async def run_streaming(_ctx, adapter, _generation):
        await adapter.send_json({"type": "token", "content": "accepted"})
        generation.invalidated = True
        await adapter.send_json({"type": "token", "content": "late"})
        await adapter.send_json({"type": "done", "content": "accepted late"})
        return AgentPipelineResult(reply="accepted late")

    service = TurnService(TurnPorts(
        run=run,
        run_streaming=run_streaming,
        persist=lambda commit: persisted.append(commit),
        dispatch=lambda commit: dispatched.append(commit),
    ))
    ctx = service.build_context("socket", _request())

    commit = asyncio.run(
        service.execute_streaming_context("socket", ctx, Adapter(), generation)
    )

    assert events == ["token"]
    assert persisted == [commit]
    assert dispatched == [commit]


def test_runner_that_suppresses_cancellation_commits_unknown_effect_nonretryable():
    started = asyncio.Event()
    persisted = []

    async def run(_ctx):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return AgentPipelineResult(
                reply="effect may already have happened",
                tool_calls=[{"name": "external_effect"}],
            )

    async def scenario():
        service = TurnService(TurnPorts(
            run=run,
            persist=lambda commit: persisted.append(commit),
        ))
        task = asyncio.create_task(service.execute_http(_request()))
        await started.wait()
        task.cancel()
        return await task

    commit = asyncio.run(scenario())

    assert persisted == [commit]
    assert commit.outcome == "unknown_effect"
    assert commit.retryable is False


def test_unknown_effect_cannot_be_marked_retryable():
    with pytest.raises(ValueError, match="cannot be retryable"):
        AgentPipelineResult(
            reply="uncertain",
            outcome="unknown_effect",
            retryable=True,
        )


def test_cancellation_during_dispatch_returns_durable_commit_without_reexecution():
    persisted = []
    dispatch_started = asyncio.Event()

    async def dispatch(_commit):
        dispatch_started.set()
        await asyncio.Event().wait()

    async def run(_ctx):
        return AgentPipelineResult(reply="durable", outcome="completed")

    async def scenario():
        service = TurnService(TurnPorts(
            run=run,
            persist=lambda commit: persisted.append(commit),
            dispatch=dispatch,
        ))
        task = asyncio.create_task(service.execute_http(_request()))
        await dispatch_started.wait()
        task.cancel()
        return await task

    commit = asyncio.run(scenario())
    assert commit.result.reply == "durable"
    assert commit.outcome == "completed"
    assert commit.persisted is True
    assert len(persisted) == 1


def test_cancellation_during_persist_waits_for_durable_write_then_returns_commit():
    persist_started = asyncio.Event()
    release_persist = asyncio.Event()
    persisted = []

    async def persist(commit):
        persist_started.set()
        await release_persist.wait()
        persisted.append(commit)
        return {"stored": True}

    async def run(_ctx):
        return AgentPipelineResult(reply="persisted", outcome="completed")

    async def scenario():
        service = TurnService(TurnPorts(run=run, persist=persist))
        task = asyncio.create_task(service.execute_http(_request()))
        await persist_started.wait()
        task.cancel()
        release_persist.set()
        return await task

    commit = asyncio.run(scenario())
    assert commit.persisted is True
    assert commit.persistence_result == {"stored": True}
    assert commit.outcome == "completed"
    assert persisted == [commit]


@pytest.mark.asyncio
async def test_high_impact_tool_cancellation_persists_unknown_effect_and_replays_once(
    tmp_path,
) -> None:
    tool_started = asyncio.Event()
    generation_cancel = asyncio.Event()
    effects: list[str] = []
    runner_calls = 0
    projection_calls = 0

    async def send_message(_args):
        effects.append("message-dispatched")
        tool_started.set()
        await asyncio.Event().wait()
        return ToolResultEnvelope(
            success=True,
            content="sent",
            source="builtin",
            tool_name="send_message",
        )

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="send_message",
        description="send one message",
        source="builtin",
        parameters={"type": "object"},
        handler=send_message,
        risk_level="low",
    ))
    executor = ToolExecutor(registry)

    class Client:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            return {
                "reply": "",
                "tool_calls": [{
                    "id": "send-once",
                    "function": {
                        "name": "send_message",
                        "arguments": '{"text":"hello"}',
                    },
                }],
            }

    generation = SimpleNamespace(cancel=generation_cancel, invalidated=False)

    async def run(_ctx):
        nonlocal runner_calls
        runner_calls += 1
        payload = await run_streaming_tool_loop(
            Client(),
            [{"role": "user", "content": "send hello"}],
            tool_registry=registry,
            tool_executor=executor,
            generation=generation,
            max_iterations=2,
        )
        assert payload is not None
        outcome, retryable = terminal_contract(payload)
        return AgentPipelineResult(
            reply=str(payload.get("reply") or ""),
            tool_calls=list(payload.get("tool_calls") or []),
            outcome=outcome,
            retryable=retryable,
            configured_budget=dict(payload.get("configured_budget") or {}),
            consumed_usage=dict(payload.get("consumed_usage") or {}),
        )

    async def project(_event, _context):
        nonlocal projection_calls
        projection_calls += 1

    store = TurnCommitStore(tmp_path / "cancel-chain.sqlite3")
    dispatcher = TurnOutboxDispatcher(
        store,
        [TurnProjection("terminal", project)],
    )

    def service() -> TurnService:
        return TurnService(TurnPorts(
            run=run,
            persist=store.persist,
            load=store.load,
            dispatch=dispatcher,
        ))

    executing = asyncio.create_task(service().execute_http(_request()))
    await asyncio.wait_for(tool_started.wait(), timeout=1)
    generation_cancel.set()
    first = await asyncio.wait_for(executing, timeout=1)
    replay = await service().execute_http(_request())

    assert first.outcome == "unknown_effect"
    assert first.retryable is False
    assert first.persisted is True
    assert replay.replayed is True
    assert replay.outcome == "unknown_effect"
    assert runner_calls == 1
    assert effects == ["message-dispatched"]
    assert projection_calls == 1
    assert store.pending_outbox() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled_hook", ["after_llm", "before_dispatch"])
async def test_projection_hook_cancellation_persists_nonretryable_unknown_effect(
    tmp_path,
    cancelled_hook: str,
) -> None:
    class Plugin:
        async def after_llm(self, result, _ctx):
            if cancelled_hook == "after_llm":
                raise asyncio.CancelledError
            return result

        async def before_dispatch(self, result, _ctx):
            if cancelled_hook == "before_dispatch":
                raise asyncio.CancelledError
            return result

    async def bind_context(ctx):
        ctx.plugin_manager = Plugin()
        return ctx

    async def finalize(ctx, result):
        return await ProjectionStage().run(
            ctx,
            result,
            append_runtime_loop=lambda *_args, **_kwargs: None,
        )

    store = TurnCommitStore(tmp_path / f"projection-{cancelled_hook}.sqlite3")
    service = TurnService(TurnPorts(
        run=lambda _ctx: AgentPipelineResult(reply="draft"),
        finalize=finalize,
        persist=store.persist,
        load=store.load,
        bind_context=bind_context,
    ))

    commit = await service.execute_http(_request())
    stored = store.load(commit.idempotency_key)

    assert commit.outcome == "unknown_effect"
    assert commit.retryable is False
    assert commit.persisted is True
    assert stored is not None
    assert stored["result"]["outcome"] == "unknown_effect"
    assert stored["result"]["retryable"] is False
