"""Socket.IO interruption coordinator.

The server owns visual frames, tool cancellation signals and generations. This
module only coordinates their cancellation order and projects the stable ACK
payload consumed by the desktop client.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from socket_events import SystemEvents

JsonDict = dict[str, object]
AdvanceEpoch = Callable[[], int]
CancelVisualTurn = Callable[[str, str | None, str], None]
CancelTools = Callable[[str, str | None], bool]
RecordInterrupt = Callable[[bool, str], None]
GenerationManagerProvider = Callable[[], Any]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def register_interrupt_handler(
    *,
    sio: Any,
    generation_manager_provider: GenerationManagerProvider,
    advance_interruption_epoch: AdvanceEpoch,
    cancel_visual_turn: CancelVisualTurn,
    cancel_direct_tool_calls: CancelTools,
    record_interrupt: RecordInterrupt,
    clock: Callable[[], float] = time.perf_counter,
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    """Register the manual/voice interruption path and return its handler."""

    log = logger or logging.getLogger("socket-server.interrupt")

    async def on_interrupt(sid: str, data: JsonDict) -> None:
        # Advance first so in-flight perception/generation work becomes stale
        # before any cancellation result is acknowledged to the client.
        advance_interruption_epoch()
        session_id = _as_text(data.get("session_id"), sid)
        request_id = _as_text(data.get("request_id")) or None
        source = _as_text(data.get("source"), "manual").strip().lower()
        source = source if source in {"manual", "voice"} else "other"
        started = clock()

        cancel_visual_turn(sid, request_id, "agent_interrupted")
        interrupted_tool = cancel_direct_tool_calls(sid, request_id)
        generation_mgr = generation_manager_provider()
        interrupted_generation = None
        if generation_mgr is not None:
            interrupted_generation = generation_mgr.interrupt(session_id)
        record_interrupt(interrupted_generation is not None or interrupted_tool, source)

        try:
            await sio.emit(
                SystemEvents.INTERRUPT_ACK,
                {
                    "request_id": request_id or "",
                    "session_id": session_id,
                    "source": source,
                    "generation_id": _as_text(
                        getattr(interrupted_generation, "generation_id", "")
                    ),
                    "hit_active_generation": interrupted_generation is not None,
                    "hit_active_tool": interrupted_tool,
                    "server_processing_ms": round((clock() - started) * 1000, 1),
                },
                to=sid,
            )
        except Exception:
            # Cleanup already happened; a disconnect race must not undo it.
            log.exception("Failed to emit interruption ACK for sid %s", sid)

    sio.on(SystemEvents.INTERRUPT, handler=on_interrupt)
    return on_interrupt


__all__ = ["register_interrupt_handler"]
