"""Socket.IO voice-conversion handler kept behind the server facade."""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from socket_events import SOCKET_PROTOCOL_VERSION, SVCEvents, protocol_version_status

JsonDict = dict[str, object]
MAX_SVC_AUDIO_BYTES = 6 * 1024 * 1024
MAX_SVC_AUDIO_B64_LENGTH = ((MAX_SVC_AUDIO_BYTES + 2) // 3) * 4


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
        _version, version_supported = protocol_version_status(data.get("version"))
        if not version_supported:
            await sio.emit(SVCEvents.DONE, {
                "status": "failed", "error": "UNSUPPORTED_PROTOCOL_VERSION",
                "message": "unsupported socket protocol version",
                "version": SOCKET_PROTOCOL_VERSION,
            }, to=sid)
            return
        audio = _as_text(data.get("audio"))
        if not audio or len(audio) > MAX_SVC_AUDIO_B64_LENGTH:
            await sio.emit(SVCEvents.DONE, {
                "status": "failed", "error": "INVALID_SVC_AUDIO",
                "message": "SVC audio payload is missing or too large",
                "version": SOCKET_PROTOCOL_VERSION,
            }, to=sid)
            return
        try:
            decoded_audio = base64.b64decode(audio, validate=True)
        except (ValueError, TypeError, binascii.Error):
            await sio.emit(SVCEvents.DONE, {
                "status": "failed", "error": "INVALID_SVC_AUDIO",
                "message": "SVC audio payload is not valid base64",
                "version": SOCKET_PROTOCOL_VERSION,
            }, to=sid)
            return
        if not decoded_audio or len(decoded_audio) > MAX_SVC_AUDIO_BYTES:
            await sio.emit(SVCEvents.DONE, {
                "status": "failed", "error": "INVALID_SVC_AUDIO",
                "message": "SVC audio payload is missing or too large",
                "version": SOCKET_PROTOCOL_VERSION,
            }, to=sid)
            return
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
                audio,
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
