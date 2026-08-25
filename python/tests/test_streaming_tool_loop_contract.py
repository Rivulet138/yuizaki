from __future__ import annotations

import pytest

from modules.agent.tool_loop import run_streaming_tool_loop
from modules.agent.tool_registry import ToolDefinition, ToolRegistry
from modules.agent.tool_result import ToolResultEnvelope


class _Executor:
    def __init__(self) -> None:
        self.calls = []

    async def execute(self, name, args, **kwargs):
        self.calls.append((name, args, kwargs))
        return ToolResultEnvelope(success=True, content="done", source="builtin", tool_name=name)


class _StreamingClient:
    streaming_tool_calls_supported = True

    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat_with_tools(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {"reply": "", "tool_calls": [{
                "id": "call-1",
                "function": {"name": "demo", "arguments": '{"value": 1}'},
            }]}
        return {"reply": "finished", "tool_calls": []}


@pytest.mark.asyncio
async def test_streaming_adapter_executes_typed_calls_and_bounds_iterations() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo",
        description="demo",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: None,
    ))
    executor = _Executor()
    client = _StreamingClient()

    result = await run_streaming_tool_loop(
        client,
        [{"role": "user", "content": "go"}],
        tool_registry=registry,
        tool_executor=executor,
        max_iterations=2,
    )

    assert result is not None
    assert result["reply"] == "finished"
    assert executor.calls[0][0:2] == ("demo", {"value": 1})
    assert client.calls == 2


@pytest.mark.asyncio
async def test_streaming_adapter_explicitly_falls_back_when_unsupported() -> None:
    class Unsupported:
        streaming_tool_calls_supported = False

    result = await run_streaming_tool_loop(
        Unsupported(), [], tool_registry=ToolRegistry(), tool_executor=_Executor()
    )

    assert result is None


@pytest.mark.asyncio
async def test_streaming_adapter_rejects_registered_tool_outside_exposed_allowlist() -> None:
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo",
        description="demo",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: None,
    ))
    executor = _Executor()

    result = await run_streaming_tool_loop(
        _StreamingClient(),
        [{"role": "user", "content": "go"}],
        tool_registry=registry,
        tool_executor=executor,
        allowed_tool_names=[],
        max_iterations=2,
    )

    assert result is not None
    assert executor.calls == []
    assert result["tool_calls"] == [{"tool": "demo", "success": False, "error": "tool_not_exposed"}]
