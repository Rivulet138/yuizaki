from __future__ import annotations

from pathlib import Path

import pytest
from modules.agent.context import AgentPipelineResult, AgentRequestContext
from modules.agent.turn_service import TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore


def _context() -> AgentRequestContext:
    return AgentRequestContext(
        sid="sid-1",
        session_id="session-1",
        workspace_id="workspace-1",
        request_id="request-1",
        turn_id="turn-1",
        generation_id="generation-1",
        messages=[{"role": "user", "content": "perform the action"}],
    )


@pytest.mark.asyncio
async def test_runner_exception_after_effect_is_durable_unknown_effect(tmp_path: Path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    effects: list[str] = []

    async def runner(_ctx: AgentRequestContext) -> AgentPipelineResult:
        effects.append("external-call")
        raise RuntimeError("provider response arrived after the side effect")

    ports = TurnPorts(run=runner, persist=store.persist, load=store.load)
    first = await TurnService(ports).execute_context("http", _context())

    assert first.result.outcome == "unknown_effect"
    assert first.result.retryable is False
    assert first.result.failure == {
        "kind": "turn_runner_exception",
        "exception_type": "RuntimeError",
        "message": "turn runner failed after execution began; external effect is unknown",
    }
    assert store.load(first.idempotency_key) is not None

    replay = await TurnService(ports).execute_context("http", _context())
    assert replay.result.outcome == "unknown_effect"
    assert replay.replayed is True
    assert effects == ["external-call"]


@pytest.mark.asyncio
async def test_finalizer_exception_is_durable_unknown_effect(tmp_path: Path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    async def runner(_ctx: AgentRequestContext) -> AgentPipelineResult:
        return AgentPipelineResult(reply="completed", outcome="completed")

    async def finalizer(_ctx: AgentRequestContext, _result: AgentPipelineResult) -> AgentPipelineResult:
        raise RuntimeError("finalizer failed")

    service = TurnService(TurnPorts(
        run=runner,
        finalize=finalizer,
        persist=store.persist,
        load=store.load,
    ))
    commit = await service.execute_context("http", _context())

    assert commit.result.outcome == "unknown_effect"
    assert commit.result.retryable is False
    assert commit.result.failure["kind"] == "turn_finalizer_exception"
    assert store.load(commit.idempotency_key) is not None
