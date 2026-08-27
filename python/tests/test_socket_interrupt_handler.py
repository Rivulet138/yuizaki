from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from socket_events import SystemEvents
from socket_handlers.interrupt import register_interrupt_handler


class _Sio:
    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}
        self.events: list[tuple[str, dict[str, object], str]] = []

    def on(self, event: str, *, handler: Any) -> None:
        self.handlers[event] = handler

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


@dataclass
class _Generation:
    generation_id: str = "generation-1"


class _GenerationManager:
    def __init__(self, generation: _Generation | None) -> None:
        self.generation = generation
        self.sessions: list[str] = []

    def interrupt(self, session_id: str) -> _Generation | None:
        self.sessions.append(session_id)
        return self.generation


def _register(
    *,
    generation: _Generation | None = None,
    events: list[str] | None = None,
    tool_hit: bool = True,
) -> tuple[_Sio, _GenerationManager, list[tuple[bool, str]], list[int]]:
    sio = _Sio()
    metrics: list[tuple[bool, str]] = []
    epochs: list[int] = []
    order = events if events is not None else []
    if generation is None and tool_hit:
        generation = _Generation()
    manager = _GenerationManager(generation)

    def advance() -> int:
        value = len(epochs) + 1
        epochs.append(value)
        order.append("epoch")
        return value

    def cancel_visual(sid: str, request_id: str | None, reason: str) -> None:
        assert sid == "sid-1"
        assert request_id in {None, "request-1"}
        assert reason == "agent_interrupted"
        order.append("visual")

    def cancel_tools(sid: str, request_id: str | None) -> bool:
        assert sid == "sid-1"
        assert request_id in {None, "request-1"}
        order.append("tool")
        return tool_hit

    def record(hit: bool, source: str) -> None:
        metrics.append((hit, source))
        order.append("metrics")

    register_interrupt_handler(
        sio=sio,
        generation_manager_provider=lambda: manager,
        advance_interruption_epoch=advance,
        cancel_visual_turn=cancel_visual,
        cancel_direct_tool_calls=cancel_tools,
        record_interrupt=record,
        clock=lambda: 10.0,
    )
    return sio, manager, metrics, epochs


def test_interrupt_resolves_generation_manager_after_handler_registration() -> None:
    sio = _Sio()
    manager: _GenerationManager | None = None
    metrics: list[tuple[bool, str]] = []
    register_interrupt_handler(
        sio=sio,
        generation_manager_provider=lambda: manager,
        advance_interruption_epoch=lambda: 1,
        cancel_visual_turn=lambda _sid, _request_id, _reason: None,
        cancel_direct_tool_calls=lambda _sid, _request_id: False,
        record_interrupt=lambda hit, source: metrics.append((hit, source)),
        clock=lambda: 10.0,
    )
    manager = _GenerationManager(_Generation())

    asyncio.run(sio.handlers[SystemEvents.INTERRUPT]("sid-1", {
        "session_id": "session-late",
        "source": "manual",
    }))

    assert manager.sessions == ["session-late"]
    assert metrics == [(True, "manual")]
    assert sio.events[-1][1]["hit_active_generation"] is True


def test_interrupt_cancels_visual_tool_generation_before_ack() -> None:
    order: list[str] = []
    sio, manager, metrics, epochs = _register(events=order)

    asyncio.run(sio.handlers[SystemEvents.INTERRUPT]("sid-1", {
        "session_id": "session-1",
        "request_id": "request-1",
        "source": "voice",
    }))

    assert order == ["epoch", "visual", "tool", "metrics"]
    assert epochs == [1]
    assert manager.sessions == ["session-1"]
    assert metrics == [(True, "voice")]
    assert sio.events == [(SystemEvents.INTERRUPT_ACK, {
        "request_id": "request-1",
        "session_id": "session-1",
        "source": "voice",
        "generation_id": "generation-1",
        "hit_active_generation": True,
        "hit_active_tool": True,
        "server_processing_ms": 0.0,
    }, "sid-1")]


def test_interrupt_without_active_work_still_acks_and_normalizes_identity() -> None:
    order: list[str] = []
    sio, manager, metrics, epochs = _register(
        generation=None,
        events=order,
        tool_hit=False,
    )

    asyncio.run(sio.handlers[SystemEvents.INTERRUPT]("sid-1", {
        "source": "unknown-source",
    }))

    assert order == ["epoch", "visual", "tool", "metrics"]
    assert epochs == [1]
    assert manager.sessions == ["sid-1"]
    assert metrics == [(False, "other")]
    assert sio.events[0][0] == SystemEvents.INTERRUPT_ACK
    assert sio.events[0][1]["session_id"] == "sid-1"
    assert sio.events[0][1]["request_id"] == ""
    assert sio.events[0][1]["source"] == "other"
    assert sio.events[0][1]["hit_active_generation"] is False
    assert sio.events[0][1]["hit_active_tool"] is False
