"""Socket.IO voice-conversion handler kept behind the server facade."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from socket_events import SVCEvents

JsonDict = dict[str, object]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_svc_convert_handler(
    *,
    sio: Any,
    svc_client_provider: Callable[[], Any],
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    log = logger or logging.getLogger("socket-server.voice")

    async def on_svc_convert(sid: str, data: JsonDict) -> None:
        svc_client = svc_client_provider()
        if svc_client is None:
            await sio.emit(SVCEvents.DONE, {
                "status": "failed",
                "error": "SVC client not initialized",
            }, to=sid)
            return

        try:
            result = await svc_client.convert(
                f"svc_{uuid.uuid4().hex[:10]}",
                _as_text(data.get("audio")),
                speaker_id=_optional_int(data.get("speaker_id")),
                pitch=_optional_int(data.get("transpose")),
            )
            await sio.emit(SVCEvents.DONE, result, to=sid)
        except Exception as exc:  # noqa: BLE001 - keep provider details out of the protocol
            log.error("[SIO] SVC convert failed: %s", exc)
            await sio.emit(SVCEvents.DONE, {
                "status": "failed",
                "error": "svc_convert_failed",
                "message": "SVC conversion failed",
            }, to=sid)

    return on_svc_convert


__all__ = ["build_svc_convert_handler"]
