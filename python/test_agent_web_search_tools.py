from __future__ import annotations

from typing import Any

import pytest

from modules.agent.default_tools import register_default_tools
from modules.agent.tool_executor import ToolExecutor
from modules.agent.tool_loop import run_tool_loop
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


class _CapturingLlm:
    def __init__(self) -> None:
        self.tool_names: list[str] = []

    async def complete_chat(self, _messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        tools = kwargs.get("tools") or []
        self.tool_names = [
            str((tool.get("function") or {}).get("name"))
            for tool in tools
            if isinstance(tool, dict)
        ]
        return {"reply": "ok", "tool_calls": [], "pet_control": None}


@pytest.mark.asyncio
async def test_web_search_tool_is_hidden_until_enabled() -> None:
    registry = ToolRegistry()
    register_default_tools(registry)
    executor = ToolExecutor(registry)

    disabled_llm = _CapturingLlm()
    await run_tool_loop(
        disabled_llm,
        [{"role": "user", "content": "今天有什么新闻？"}],
        tool_registry=registry,
        tool_executor=executor,
    )

    enabled_llm = _CapturingLlm()
    await run_tool_loop(
        enabled_llm,
        [{"role": "user", "content": "今天有什么新闻？"}],
        tool_registry=registry,
        tool_executor=executor,
        include_web_search_tools=True,
    )

    assert "web_search" not in disabled_llm.tool_names
    assert "web_search" in enabled_llm.tool_names


@pytest.mark.asyncio
async def test_registered_model_without_tools_receives_no_tool_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ToolRegistry()
    register_default_tools(registry)
    executor = ToolExecutor(registry)
    llm = _CapturingLlm()
    monkeypatch.setattr(
        "modules.agent.tool_loop.infer_model_capability_support",
        lambda _provider, _model, capability: "unsupported" if capability == "tools" else "unknown",
    )

    await run_tool_loop(
        llm,
        [{"role": "user", "content": "hello"}],
        tool_registry=registry,
        tool_executor=executor,
    )

    assert llm.tool_names == []


class _ToolCallingLlm:
    def __init__(self) -> None:
        self.tool_names: list[str] = []
        self.iteration = 0

    async def complete_chat(self, _messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        tools = kwargs.get("tools") or []
        self.tool_names = [
            str((tool.get("function") or {}).get("name"))
            for tool in tools
            if isinstance(tool, dict)
        ]
        self.iteration += 1
        if self.iteration == 1:
            return {
                "reply": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "browser_open_page", "arguments": '{"url":"https://example.com"}'},
                    }
                ],
                "pet_control": None,
            }
        return {"reply": "done", "tool_calls": [], "pet_control": None}


@pytest.mark.asyncio
async def test_tool_loop_sanitizes_openai_tool_names_and_maps_calls_back() -> None:
    registry = ToolRegistry()
    calls: list[tuple[str, dict[str, Any]]] = []

    registry.register(ToolDefinition(
        name="browser.open_page",
        description="Open a browser page",
        source="mcp",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content="opened",
            source="mcp",
            tool_name="browser.open_page",
        ),
    ))
    registry.register(ToolDefinition(
        name="plugin.alpha.beta",
        description="Plugin tool with dotted name",
        source="plugin",
        parameters={"type": "object", "properties": {}},
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content="plugin-ok",
            source="plugin",
            tool_name="plugin.alpha.beta",
        ),
    ))
    executor = ToolExecutor(registry)
    original_execute = executor.execute

    async def capture_execute(tool_name: str, args: dict[str, Any], **kwargs: Any) -> ToolResultEnvelope:
        calls.append((tool_name, args))
        return await original_execute(tool_name, args, **kwargs)

    executor.execute = capture_execute  # type: ignore[method-assign]

    llm = _ToolCallingLlm()
    result = await run_tool_loop(
        llm,
        [{"role": "user", "content": "open https://example.com"}],
        tool_registry=registry,
        tool_executor=executor,
        include_mcp_tools=True,
    )

    assert result["reply"] == "done"
    assert "browser.open_page" not in llm.tool_names
    assert "plugin.alpha.beta" not in llm.tool_names
    assert "browser_open_page" in llm.tool_names
    assert "plugin_alpha_beta" in llm.tool_names
    assert calls == [("browser.open_page", {"url": "https://example.com"})]


@pytest.mark.asyncio
async def test_tool_loop_passes_request_context_to_permission_execution() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="context.tool",
        description="Context test tool",
        source="builtin",
        parameters={"type": "object", "properties": {}},
        handler=lambda _args: ToolResultEnvelope(success=True, content="ok", source="builtin"),
    ))
    executor = ToolExecutor(registry)
    captured: dict[str, Any] = {}

    async def capture_execute(_tool_name: str, _args: dict[str, Any], **kwargs: Any) -> ToolResultEnvelope:
        captured.update(kwargs)
        return ToolResultEnvelope(success=True, content="ok", source="builtin", tool_name=_tool_name)

    executor.execute = capture_execute  # type: ignore[method-assign]
    llm = _ToolCallingLlm()
    llm.iteration = 0

    async def call_context_tool(_messages: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        llm.iteration += 1
        if llm.iteration == 1:
            return {"reply": "", "tool_calls": [{
                "id": "call-context",
                "type": "function",
                "function": {"name": "context_tool", "arguments": "{}"},
            }]}
        return {"reply": "done", "tool_calls": []}

    llm.complete_chat = call_context_tool  # type: ignore[method-assign]
    request_context = object()
    plugin_manager = object()
    await run_tool_loop(
        llm,
        [{"role": "user", "content": "run"}],
        tool_registry=registry,
        tool_executor=executor,
        ctx=request_context,
        plugin_manager=plugin_manager,
    )

    assert captured["ctx"] is request_context
    assert captured["plugin_manager"] is plugin_manager
