from __future__ import annotations

import pytest
from modules.agent.turn_service import TurnClaimLostError, TurnIdentityConflictError
from routes.ai_api import _stream_error_contract


def test_stream_error_contract_marks_identity_conflicts_non_retryable() -> None:
    payload = _stream_error_contract(
        TurnIdentityConflictError("different semantic input"),
        request_id="request-1",
        turn_id="turn-1",
    )

    assert payload["code"] == "turn_identity_conflict"
    assert payload["retryable"] is False
    assert payload["request_id"] == "request-1"
    assert payload["turn_id"] == "turn-1"


def test_stream_error_contract_distinguishes_timeout_and_claim_loss() -> None:
    timeout = _stream_error_contract(
        TimeoutError(), request_id="request-1", turn_id="turn-1"
    )
    claim_lost = _stream_error_contract(
        TurnClaimLostError("claim expired"), request_id="request-1", turn_id="turn-1"
    )

    assert timeout["code"] == "upstream_timeout"
    assert timeout["retryable"] is True
    assert claim_lost["code"] == "turn_claim_lost"
    assert claim_lost["retryable"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("repeated_interrupt", [False, True])
async def test_disconnect_after_generation_replacement_finishes_durable_commit(repeated_interrupt):
    import asyncio
    import logging
    from types import SimpleNamespace

    import fastapi.routing
    from modules.agent.context import AgentPipelineResult
    from modules.agent.turn_service import TurnPorts, TurnService
    from modules.core.state import GenerationManager
    from routes.ai_api import create_ai_router
    from state.schemas import ChatCompletionRequest

    manager = GenerationManager()
    persisting, release = asyncio.Event(), asyncio.Event()
    commits, write_cancelled = [], []

    async def run(ctx):
        return AgentPipelineResult(reply="synthetic")

    async def run_streaming(ctx, adapter, generation):
        await adapter.send_json({"type": "token", "content": "first"})
        await adapter.send_json({"type": "token", "content": "second"})
        return AgentPipelineResult(reply="firstsecond")

    async def persist(commit):
        persisting.set()
        try:
            await release.wait()
            commits.append(commit)
        except asyncio.CancelledError:
            write_cancelled.append(True)
            raise

    pipeline = SimpleNamespace(run=run, run_streaming=run_streaming)
    runtime = SimpleNamespace(agent_pipeline=pipeline, turn_service=TurnService(TurnPorts.from_pipeline(pipeline, persist=persist)),
        tool_registry=None, tool_executor=None, step_executor=None, trace_store=None, plugin_manager=None, scheduler=None)
    router = create_ai_router(
        get_config=lambda: None, get_generation_mgr=lambda: manager, get_llm_client=lambda: object(),
        get_svc_client=lambda: None, get_agent_runtime=lambda: runtime, get_db_repo=lambda: None,
        get_relationship_writer=lambda: None, get_relationship_history=list, get_relationship_summary=dict,
        logger=logging.getLogger("synthetic-sse-disconnect"))
    iterator = getattr(fastapi.routing, "iter_route_contexts", lambda routes: routes)
    endpoint = next(route.endpoint for route in iterator(router.routes) if route.path == "/v1/chat/completions")
    response = await endpoint(ChatCompletionRequest(model="synthetic", messages=[{"role": "user", "content": "synthetic"}],
        session_id="session", request_id="old", stream=True))
    await asyncio.wait_for(anext(response.body_iterator), 1)
    await asyncio.wait_for(persisting.wait(), 1)
    previous = manager.get("session")
    if repeated_interrupt:
        manager.interrupt("session", request_id="old")
        await asyncio.sleep(0.01)
        manager.interrupt("session", request_id="old")
    newer = manager.start("session", request_id="new")
    # The first cancellation is being handled by TurnService's durable write.
    await asyncio.sleep(0.01)
    closing = asyncio.create_task(response.body_iterator.aclose())
    try:
        await asyncio.sleep(0.01)
    finally:
        release.set()
        await asyncio.wait_for(closing, 1)
    assert not write_cancelled
    assert len(commits) == 1 and commits[0].persisted
    assert previous.llm_task is None
    assert not newer.invalidated
