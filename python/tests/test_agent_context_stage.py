from __future__ import annotations

from typing import Any, cast

import pytest
from modules.agent.context import AgentRequestContext
from modules.agent.context_stage import ContextStage
from modules.agent.planner import Planner
from modules.agent.planning_stage import PlanningStage
from modules.agent.tool_registry import ToolRegistry
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest


class _RetrievalStub:
    def __init__(self, result: dict[str, Any] | None = None, *, error: Exception | None = None) -> None:
        self.result = result or {"results": []}
        self.error = error
        self.requests: list[RetrievalRequest] = []

    def recall(self, request: RetrievalRequest) -> dict[str, Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


class _WorkspaceRepo:
    def list_workspaces(self) -> list[dict[str, str]]:
        return [{
            "id": "workspace-1",
            "tool_preset": '["time.now", "calendar.read", "time.now"]',
            "mcp_preset_id": "playwright",
        }]


async def _run_stage(
    ctx: AgentRequestContext,
    *,
    retrieval: _RetrievalStub | None = None,
    prefetched: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    async def take_prefetch(**_kwargs: Any) -> dict[str, Any] | None:
        return prefetched

    await ContextStage().run(
        ctx,
        retrieval_pipeline=(
            cast(RetrievalPipeline, retrieval)
            if retrieval is not None
            else None
        ),
        take_retrieval_prefetch=take_prefetch,
        append_runtime_loop=lambda _ctx, **payload: events.append(payload),
    )
    return events


@pytest.mark.asyncio
async def test_prefetch_populates_memory_sources_recent_signals_and_prompt() -> None:
    prefetched = {
        "results": [{
            "score": 0.92,
            "doc": {
                "id": "memory-1",
                "text": "用户偏好低打扰提醒",
                "layer": "profile",
                "source": "user_message",
                "metadata": {"relationship_event": {"kind": "preference_confirmed"}},
            },
        }],
    }
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace-1",
        messages=[{"role": "user", "content": "提醒设置是什么"}],
    )

    events = await _run_stage(ctx, retrieval=_RetrievalStub(), prefetched=prefetched)

    assert ctx.extra["retrieval_prefetch_hit"] is True
    assert ctx.extra["retrieved_chunks"] == ["用户偏好低打扰提醒"]
    assert ctx.extra["memory_sources"] == [{
        "id": "memory-1",
        "text": "用户偏好低打扰提醒",
        "layer": "profile",
        "source": "user_message",
        "score": 0.92,
    }]
    assert ctx.extra["recent_signal_docs"] == [{"kind": "preference_confirmed"}]
    assert any("id=retrieved_memory" in str(message["content"]) for message in ctx.messages)
    assert [event["stage"] for event in events] == ["recall", "decide"]


@pytest.mark.asyncio
async def test_recall_failure_keeps_text_prompt_and_records_error() -> None:
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "继续处理这个任务"}],
    )

    events = await _run_stage(
        ctx,
        retrieval=_RetrievalStub(error=RuntimeError("memory unavailable")),
    )

    assert ctx.extra["rag_error"] == "memory unavailable"
    assert ctx.messages[-1] == {"role": "user", "content": "继续处理这个任务"}
    assert any("id=core_policy" in str(message["content"]) for message in ctx.messages)
    assert events[0]["stage"] == "recall"
    assert events[0]["status"] == "error"
    assert events[-1]["stage"] == "decide"


@pytest.mark.asyncio
async def test_workspace_presets_load_before_empty_text_early_return() -> None:
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        workspace_id="workspace-1",
        messages=[],
        tool_registry=ToolRegistry(),
        extra={"db_repo": _WorkspaceRepo()},
    )

    events = await _run_stage(ctx)

    assert ctx.extra["workspace_tool_preset"] == ["calendar.read", "time.now"]
    assert ctx.extra["workspace_mcp_preset"] == ["playwright"]
    assert events == []


@pytest.mark.asyncio
async def test_ambiguous_visual_request_is_in_final_prompt_before_planning() -> None:
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "你看到这个了吗"}],
    )

    await _run_stage(ctx)

    assert ctx.extra["visual_context_requested"] is False
    assert ctx.extra["visual_confirmation_required"] is True
    assert any(
        "id=visual_confirmation_required" in str(message["content"])
        for message in ctx.messages
    )


@pytest.mark.asyncio
async def test_planning_reuses_interpretation_created_before_prompt_assembly() -> None:
    ctx = AgentRequestContext(
        sid="sid",
        session_id="session",
        messages=[{"role": "user", "content": "帮我整理今天的安排"}],
    )
    await _run_stage(ctx)
    context_interpretation = ctx.extra["interpret_result"]

    PlanningStage().run(
        ctx,
        user_text="帮我整理今天的安排",
        planner=Planner(),
        append_runtime_loop=lambda *_args, **_kwargs: None,
    )

    assert ctx.extra["interpret_result"] is context_interpretation
