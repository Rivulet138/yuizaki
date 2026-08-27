import asyncio
import threading

import pytest
from modules.agent.context_prefetch import ContextPrefetchCoordinator


class _Retrieval:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def recall(self, request):
        self.queries.append(request.query)
        return {"results": [{"doc": {"text": request.query, "metadata": {}}}]}


@pytest.mark.asyncio
async def test_retrieval_prefetch_respects_workspace_and_partial_query():
    retrieval = _Retrieval()
    coordinator = ContextPrefetchCoordinator(retrieval)  # type: ignore[arg-type]
    assert coordinator.schedule_retrieval_prefetch(
        cache_key="k", query="昨天的约定", session_id="s", workspace_id="w"
    )
    await asyncio.sleep(0)
    assert await coordinator.take_retrieval_prefetch(
        cache_key="k", final_query="昨天的约定是什么", workspace_id="w"
    ) == {"results": [{"doc": {"text": "昨天的约定", "metadata": {}}}]}
    assert retrieval.queries == ["昨天的约定"]


@pytest.mark.asyncio
async def test_retrieval_prefetch_propagates_caller_cancellation():
    started = threading.Event()
    release = threading.Event()

    class _BlockingRetrieval:
        def recall(self, _request):
            started.set()
            release.wait(timeout=2)
            return {"results": []}

    coordinator = ContextPrefetchCoordinator(_BlockingRetrieval())  # type: ignore[arg-type]
    assert coordinator.schedule_retrieval_prefetch(
        cache_key="cancelled", query="等待中的召回", session_id="s", workspace_id="w"
    )
    assert await asyncio.to_thread(started.wait, 1)
    consumer = asyncio.create_task(coordinator.take_retrieval_prefetch(
        cache_key="cancelled", final_query="等待中的召回结果", workspace_id="w"
    ))
    await asyncio.sleep(0)
    consumer.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await consumer
    finally:
        release.set()
        coordinator.cancel_retrieval_prefetch("cancelled")


def test_speculative_context_requires_confirmation_and_preserves_visual_frame():
    class _Registry:
        def rank_candidates(self, query, limit=8):
            return []

    coordinator = ContextPrefetchCoordinator()
    assert coordinator.schedule_speculative_context_prefetch(
        cache_key="k", query="看看屏幕", workspace_id="w", tool_registry=_Registry(), visual_frame_id="f1"
    )
    assert coordinator.speculative_visual_requested("k") is True
    assert coordinator.confirm_speculative_context_prefetch(
        cache_key="k", final_query="看看屏幕内容", workspace_id="w", tool_registry=_Registry()
    )
    value = coordinator.take_speculative_context_prefetch(
        cache_key="k", final_query="看看屏幕内容", workspace_id="w"
    )
    assert value is not None
    assert value["visual_frame_id"] == "f1"
    assert value["partial_match"] is True
