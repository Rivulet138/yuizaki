import asyncio

import pytest

from modules.agent.context import AgentRequestContext
from modules.agent.pipeline import AgentPipeline
from modules.agent.tool_registry import ToolRegistry


class _RetrievalPipeline:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def recall(self, request):
        self.queries.append(request.query)
        return {"results": [{"doc": {"text": f"memory:{request.query}", "metadata": {}}}]}


@pytest.mark.asyncio
async def test_matching_partial_asr_prefetch_is_reused_after_final_text_validation() -> None:
    retrieval = _RetrievalPipeline()
    pipeline = AgentPipeline(retrieval)  # type: ignore[arg-type]
    assert pipeline.schedule_retrieval_prefetch(
        cache_key="socket-1",
        query="帮我找一下昨天的约定",
        session_id="session-1",
        workspace_id="workspace-1",
    ) is True
    await asyncio.sleep(0)

    ctx = AgentRequestContext(
        sid="socket-1",
        session_id="session-1",
        workspace_id="workspace-1",
        messages=[{"role": "user", "content": "帮我找一下昨天的约定是什么"}],
    )
    await pipeline.enrich_context(ctx)

    assert retrieval.queries == ["帮我找一下昨天的约定"]
    assert ctx.extra["retrieval_prefetch_hit"] is True
    assert ctx.extra["retrieved_chunks"] == ["memory:帮我找一下昨天的约定"]


@pytest.mark.asyncio
async def test_changed_final_text_discards_partial_prefetch_and_recalls_again() -> None:
    retrieval = _RetrievalPipeline()
    pipeline = AgentPipeline(retrieval)  # type: ignore[arg-type]
    pipeline.schedule_retrieval_prefetch(
        cache_key="socket-1",
        query="打开音乐",
        session_id="session-1",
        workspace_id="workspace-1",
    )

    ctx = AgentRequestContext(
        sid="socket-1",
        session_id="session-1",
        workspace_id="workspace-1",
        messages=[{"role": "user", "content": "不要打开音乐，查一下日程"}],
    )
    await pipeline.enrich_context(ctx)

    assert retrieval.queries == ["打开音乐", "不要打开音乐，查一下日程"]
    assert ctx.extra["retrieval_prefetch_hit"] is False


@pytest.mark.asyncio
async def test_workspace_tool_and_mcp_presets_are_loaded_into_runtime_context() -> None:
    class _WorkspaceRepo:
        def list_workspaces(self):
            return [{
                "id": "workspace-1",
                "tool_preset": '["time.now"]',
                "mcp_preset_id": "playwright",
            }]

    pipeline = AgentPipeline()
    ctx = AgentRequestContext(
        sid="socket-1",
        session_id="session-1",
        workspace_id="workspace-1",
        messages=[],
        tool_registry=ToolRegistry(),
        extra={"db_repo": _WorkspaceRepo()},
    )

    await pipeline.enrich_context(ctx)

    assert ctx.extra["workspace_tool_preset"] == ["time.now"]
    assert ctx.extra["workspace_mcp_preset"] == ["playwright"]


@pytest.mark.asyncio
async def test_empty_workspace_tool_preset_disables_all_tools() -> None:
    class _WorkspaceRepo:
        def list_workspaces(self):
            return [{"id": "workspace-1", "tool_preset": "[]"}]

    pipeline = AgentPipeline()
    ctx = AgentRequestContext(
        sid="socket-1",
        session_id="session-1",
        workspace_id="workspace-1",
        messages=[],
        tool_registry=ToolRegistry(),
        extra={"db_repo": _WorkspaceRepo()},
    )

    await pipeline.enrich_context(ctx)

    assert ctx.extra["workspace_tool_preset"] == []
