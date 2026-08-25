from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from modules.agent.context import AgentPipelineResult
from modules.agent.turn_service import SemanticTurnRequest, TurnPorts, TurnService


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
