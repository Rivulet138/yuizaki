from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from modules.agent.tool_loop import run_streaming_tool_loop
from modules.agent.tool_executor import ToolExecutor
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("effect_kind", "expected_outcome", "expected_retryable", "expected_recovery"),
    [
        ("read", "failed", True, True),
        ("write", "unknown_effect", False, False),
        ("unknown", "unknown_effect", False, False),
    ],
)
async def test_streaming_adapter_handles_provider_disconnect_after_tool_by_effect_kind(
    effect_kind: str,
    expected_outcome: str,
    expected_retryable: bool,
    expected_recovery: bool,
) -> None:
    class DisconnectAfterTool(_StreamingClient):
        async def stream_chat_with_tools(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"reply": "", "tool_calls": [{
                    "id": "call-1",
                    "function": {"name": "demo", "arguments": "{}"},
                }]}
            raise ConnectionRefusedError("offline")

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo",
        description="demo",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: None,
        effect_kind=effect_kind,  # type: ignore[arg-type]
    ))

    result = await run_streaming_tool_loop(
        DisconnectAfterTool(),
        [{"role": "user", "content": "go"}],
        tool_registry=registry,
        tool_executor=_Executor(),
        max_iterations=2,
    )

    assert result is not None
    assert result["outcome"] == expected_outcome
    assert result["retryable"] is expected_retryable
    assert result["failure"]["kind"] == "provider"
    assert result["recovery"]["available"] is expected_recovery
    assert result["persist_history"] is False


@pytest.mark.asyncio
async def test_streaming_adapter_provider_disconnect_before_tool_is_retryable() -> None:
    class OfflineClient:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            raise ConnectionRefusedError("offline")

    result = await run_streaming_tool_loop(
        OfflineClient(),
        [{"role": "user", "content": "go"}],
        tool_registry=ToolRegistry(),
        tool_executor=_Executor(),
        max_iterations=2,
    )

    assert result is not None
    assert result["outcome"] == "failed"
    assert result["retryable"] is True
    assert result["failure"]["message"] == "provider_unavailable"
    assert result["recovery"]["action"] == "retry_turn"


@pytest.mark.asyncio
async def test_streaming_adapter_cancels_provider_inflight_before_tool() -> None:
    started = asyncio.Event()
    provider_cancelled = asyncio.Event()

    class WaitingClient:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                provider_cancelled.set()
                raise

    generation = SimpleNamespace(cancel=asyncio.Event(), invalidated=False)
    executor = _Executor()
    running = asyncio.create_task(run_streaming_tool_loop(
        WaitingClient(),
        [{"role": "user", "content": "stop"}],
        tool_registry=ToolRegistry(),
        tool_executor=executor,
        generation=generation,
    ))

    await asyncio.wait_for(started.wait(), timeout=1)
    generation.cancel.set()
    result = await asyncio.wait_for(running, timeout=1)

    assert result is not None
    assert result["outcome"] == "cancelled"
    assert result["retryable"] is False
    assert result["consumed_usage"]["stop_reason"] == "cancelled"
    assert provider_cancelled.is_set()
    assert executor.calls == []


@pytest.mark.asyncio
async def test_streaming_adapter_normalizes_direct_task_cancel_during_provider() -> None:
    started = asyncio.Event()
    provider_cancelled = asyncio.Event()

    class WaitingClient:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                provider_cancelled.set()
                raise

    executor = _Executor()
    running = asyncio.create_task(run_streaming_tool_loop(
        WaitingClient(),
        [{"role": "user", "content": "stop"}],
        tool_registry=ToolRegistry(),
        tool_executor=executor,
    ))

    await asyncio.wait_for(started.wait(), timeout=1)
    running.cancel()
    result = await asyncio.wait_for(running, timeout=1)

    assert result is not None
    assert result["outcome"] == "cancelled"
    assert result["retryable"] is False
    assert result["consumed_usage"]["stop_reason"] == "cancelled"
    assert provider_cancelled.is_set()
    assert executor.calls == []


@pytest.mark.asyncio
async def test_streaming_adapter_stops_between_tools_in_same_provider_turn() -> None:
    generation = SimpleNamespace(cancel=asyncio.Event(), invalidated=False)

    class TwoCallClient:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            return {
                "reply": "",
                "tool_calls": [
                    {"id": "one", "function": {"name": "demo", "arguments": "{}"}},
                    {"id": "two", "function": {"name": "demo", "arguments": "{}"}},
                ],
            }

    class CancellingExecutor(_Executor):
        async def execute(self, name, args, **kwargs):
            outcome = await super().execute(name, args, **kwargs)
            generation.cancel.set()
            return outcome

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="demo",
        description="read demo",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: None,
    ))
    executor = CancellingExecutor()

    result = await run_streaming_tool_loop(
        TwoCallClient(),
        [{"role": "user", "content": "two reads"}],
        tool_registry=registry,
        tool_executor=executor,
        generation=generation,
    )

    assert result is not None
    assert result["outcome"] == "cancelled"
    assert len(executor.calls) == 1
    assert len(result["tool_calls"]) == 1


@pytest.mark.asyncio
async def test_streaming_adapter_direct_task_cancel_stops_after_read_dispatch() -> None:
    started = asyncio.Event()
    read_cancelled = asyncio.Event()

    async def read_file(_args):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            read_cancelled.set()
            raise

    class OneReadClient:
        streaming_tool_calls_supported = True

        async def stream_chat_with_tools(self, _messages, **_kwargs):
            return {
                "reply": "",
                "tool_calls": [{
                    "id": "read",
                    "function": {"name": "read_file", "arguments": "{}"},
                }],
            }

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_file",
        description="read",
        source="builtin",
        parameters={"type": "object"},
        handler=read_file,
        effect_kind="read",
        risk_level="low",
    ))
    running = asyncio.create_task(run_streaming_tool_loop(
        OneReadClient(),
        [{"role": "user", "content": "read"}],
        tool_registry=registry,
        tool_executor=ToolExecutor(registry),
        max_iterations=2,
    ))

    await asyncio.wait_for(started.wait(), timeout=1)
    running.cancel()
    result = await asyncio.wait_for(running, timeout=1)

    assert result is not None
    assert result["outcome"] == "cancelled"
    assert result["tool_calls"] == [{
        "tool": "read_file",
        "success": False,
        "outcome": "known_failure",
        "retryable": True,
        "error": "Tool execution cancelled after read dispatch",
    }]
    assert read_cancelled.is_set()


@pytest.mark.asyncio
async def test_streaming_adapter_treats_real_low_risk_read_tools_as_non_mutating() -> None:
    class DisconnectAfterRead(_StreamingClient):
        async def stream_chat_with_tools(self, _messages, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"reply": "", "tool_calls": [{
                    "id": "call-read",
                    "function": {"name": "read_file", "arguments": "{}"},
                }]}
            raise ConnectionRefusedError("offline")

    registry = ToolRegistry()
    registry.register(ToolDefinition(
        name="read_file",
        description="read only",
        source="builtin",
        parameters={"type": "object"},
        handler=lambda _args: None,
        effect_kind="read",
        risk_level="low",
    ))

    result = await run_streaming_tool_loop(
        DisconnectAfterRead(),
        [{"role": "user", "content": "read"}],
        tool_registry=registry,
        tool_executor=_Executor(),
        max_iterations=2,
    )

    assert result is not None
    assert result["outcome"] == "failed"
    assert result["retryable"] is True
    assert result["recovery"]["action"] == "retry_turn"
