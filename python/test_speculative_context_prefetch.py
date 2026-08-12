from __future__ import annotations

from typing import Any

import pytest

from modules.agent.pipeline import AgentPipeline, visual_context_requested
from modules.agent.tool_loop import run_tool_loop
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


def _tool(name: str, description: str, calls: list[str]) -> ToolDefinition:
    def handler(_args: dict[str, Any]) -> ToolResultEnvelope:
        calls.append(name)
        return ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name=name)

    return ToolDefinition(
        name=name,
        description=description,
        source="builtin",
        parameters={"type": "object", "properties": {}},
        handler=handler,
    )


def test_speculative_prefetch_ranks_tools_without_executing_handlers() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(_tool("weather_lookup", "Look up current weather", calls))
    registry.register(_tool("browser_open_page", "Open a browser page or URL", calls))
    pipeline = AgentPipeline()

    assert pipeline.schedule_speculative_context_prefetch(
        cache_key="sid-1",
        query="帮我打开浏览器",
        workspace_id="workspace-1",
        tool_registry=registry,
        visual_frame_id="frame-1",
    ) is True
    assert pipeline.confirm_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="帮我打开浏览器并访问这个网址",
        workspace_id="workspace-1",
        tool_registry=registry,
    ) is True

    prepared = pipeline.take_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="帮我打开浏览器并访问这个网址",
        workspace_id="workspace-1",
    )

    assert prepared is not None
    assert prepared["tool_candidates"][0] == "browser_open_page"
    assert prepared["partial_match"] is True
    assert prepared["visual_requested"] is False
    assert prepared["visual_frame_id"] == "frame-1"
    assert calls == []


def test_final_query_rejects_mismatched_partial_visual_candidate() -> None:
    registry = ToolRegistry()
    pipeline = AgentPipeline()
    pipeline.schedule_speculative_context_prefetch(
        cache_key="sid-1",
        query="看看屏幕上的窗口",
        workspace_id="workspace-1",
        tool_registry=registry,
        visual_frame_id="frame-screen",
    )

    pipeline.confirm_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="今天天气怎么样",
        workspace_id="workspace-1",
        tool_registry=registry,
    )
    prepared = pipeline.take_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="今天天气怎么样",
        workspace_id="workspace-1",
    )

    assert prepared is not None
    assert prepared["partial_match"] is False
    assert prepared["visual_requested"] is False
    assert prepared["visual_frame_id"] is None


def test_confirmed_visual_query_preserves_candidate_frame_id() -> None:
    registry = ToolRegistry()
    pipeline = AgentPipeline()
    pipeline.schedule_speculative_context_prefetch(
        cache_key="sid-1",
        query="看看屏幕",
        workspace_id="workspace-1",
        tool_registry=registry,
        visual_frame_id="frame-screen",
    )
    pipeline.confirm_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="看看屏幕上的窗口怎么了",
        workspace_id="workspace-1",
        tool_registry=registry,
    )

    prepared = pipeline.take_speculative_context_prefetch(
        cache_key="sid-1",
        final_query="看看屏幕上的窗口怎么了",
        workspace_id="workspace-1",
    )

    assert prepared is not None
    assert prepared["visual_requested"] is True
    assert prepared["visual_frame_id"] == "frame-screen"


@pytest.mark.parametrize("query", [
    "如何开发 desktop app",
    "窗口函数是什么",
    "Explain the browser window lifecycle",
    "screen reader accessibility patterns",
])
def test_visual_request_detection_ignores_technical_discussion(query: str) -> None:
    assert visual_context_requested(query) is False


@pytest.mark.parametrize("query", [
    "帮我看看屏幕上显示了什么",
    "检查一下这个窗口",
    "Can you see my screen?",
    "Tell me what is on this screenshot",
])
def test_visual_request_detection_requires_explicit_observation(query: str) -> None:
    assert visual_context_requested(query) is True


@pytest.mark.asyncio
async def test_preferred_tools_are_reordered_without_removing_other_tools() -> None:
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(_tool("weather_lookup", "Look up weather", calls))
    registry.register(_tool("browser_open_page", "Open browser page", calls))
    registry.register(_tool("note_create", "Create a note", calls))

    class FakeLlm:
        def __init__(self) -> None:
            self.tool_names: list[str] = []

        async def complete_chat(self, _messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
            self.tool_names = [item["function"]["name"] for item in kwargs["tools"]]
            return {"reply": "ok", "tool_calls": []}

    llm = FakeLlm()
    await run_tool_loop(
        llm,
        [{"role": "user", "content": "open it"}],
        tool_registry=registry,
        tool_executor=object(),  # No execution occurs when the model returns no tool call.
        preferred_tool_names=["browser_open_page"],
    )

    assert llm.tool_names == ["browser_open_page", "weather_lookup", "note_create"]
    assert calls == []
