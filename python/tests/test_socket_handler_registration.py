from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from socket_events import (
    AgentEvents,
    AudioEvents,
    LLMEvents,
    MemoryEvents,
    PetEvents,
    ScreenshotEvents,
    SVCEvents,
    SystemEvents,
    ToolEvents,
)
from socket_server import DesktopPetSocketServer


@dataclass
class _Generation:
    generation_id: str = "generation-late"


class _GenerationManager:
    def __init__(self) -> None:
        self.sessions: list[str] = []

    def interrupt(self, session_id: str) -> _Generation:
        self.sessions.append(session_id)
        return _Generation()


def test_socket_handler_registration_keeps_protocol_surface() -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    handlers = cast(dict[str, Any], cast(Any, server.sio).handlers)["/"]

    expected = {
        SystemEvents.HEARTBEAT,
        SystemEvents.INTERRUPT,
        SystemEvents.CLIENT_TIMING,
        SystemEvents.PERMISSION_RESPONSE,
        AudioEvents.CHUNK,
        LLMEvents.REQUEST,
        ToolEvents.CALL,
        SVCEvents.CONVERT,
        ScreenshotEvents.REQUEST,
        PetEvents.STATE,
        MemoryEvents.QUERY,
        AgentEvents.CHAT,
    }
    assert expected <= set(handlers)


def test_socket_llm_handler_is_owned_by_narrow_handler_module() -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    handlers = cast(dict[str, Any], cast(Any, server.sio).handlers)["/"]

    assert handlers[LLMEvents.REQUEST].__module__ == "socket_handlers.llm"


def test_socket_llm_handler_reads_runtime_dependencies_after_registration() -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    handlers = cast(dict[str, Any], cast(Any, server.sio).handlers)["/"]
    emitted: list[tuple[str, dict[str, object], str | None]] = []

    async def _emit(event: str, data: dict[str, object], to: str | None = None) -> None:
        emitted.append((event, data, to))

    server.sio.emit = cast(Any, _emit)
    asyncio.run(handlers[LLMEvents.REQUEST]("sid-late", {
        "session_id": "session-late",
        "generation_id": "generation-late",
        "turn_id": "turn-late",
        "request_id": "request-late",
        "interruption_epoch": 3,
        "version": 2,
    }))

    assert emitted == [(SystemEvents.ERROR, {
        "code": "LLM_NOT_READY",
        "message": "LLM client not initialized",
        "session_id": "session-late",
        "generation_id": "generation-late",
        "turn_id": "turn-late",
        "request_id": "request-late",
        "interruption_epoch": 3,
        "version": 2,
    }, "sid-late")]


def test_socket_interrupt_uses_generation_manager_injected_after_registration() -> None:
    server = DesktopPetSocketServer(allow_legacy_turn_pipeline=False)
    handlers = cast(dict[str, Any], cast(Any, server.sio).handlers)["/"]
    manager = _GenerationManager()
    server.generation_mgr = cast(Any, manager)

    asyncio.run(handlers[SystemEvents.INTERRUPT]("sid-late", {
        "session_id": "session-late",
        "request_id": "request-late",
        "source": "manual",
    }))

    assert manager.sessions == ["session-late"]
