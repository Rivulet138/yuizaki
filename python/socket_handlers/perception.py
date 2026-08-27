"""Small perception handler ports shared by screenshot and OCR flows."""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from modules.ocr.payload import normalize_base64_image_payload
from socket_events import ScreenshotEvents

JsonDict = dict[str, object]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def build_ocr_request_handler(
    *,
    sio: Any,
    ocr_client_provider: Callable[[], Any],
    max_image_bytes: int,
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[bool]]:
    """Handle only ``mode=ocr``; return False for other screenshot modes."""

    log = logger or logging.getLogger("socket-server.perception")

    async def on_ocr_request(sid: str, data: JsonDict) -> bool:
        mode = _as_text(data.get("mode"), "observe").strip().lower() or "observe"
        if mode != "ocr":
            return False

        image_b64 = _as_text(data.get("image"))
        request_frame_id = _as_text(data.get("frame_id")).strip()
        correlation = {"frame_id": request_frame_id} if request_frame_id else {}
        if not image_b64:
            await sio.emit(ScreenshotEvents.RESULT, {
                **correlation,
                "error": "NO_IMAGE",
                "message": "image field is required",
            }, to=sid)
            return True

        normalized_image_b64 = normalize_base64_image_payload(image_b64)
        try:
            estimated_bytes = len(base64.b64decode(normalized_image_b64, validate=True))
        except (ValueError, TypeError, binascii.Error):
            await sio.emit(ScreenshotEvents.RESULT, {
                **correlation,
                "error": "INVALID_IMAGE",
                "message": "image must be valid base64",
            }, to=sid)
            return True

        if estimated_bytes > max_image_bytes:
            await sio.emit(ScreenshotEvents.RESULT, {
                **correlation,
                "error": "IMAGE_TOO_LARGE",
                "message": "image payload exceeds OCR limit",
                "max_bytes": max_image_bytes,
                "estimated_bytes": estimated_bytes,
            }, to=sid)
            return True

        ocr_client = ocr_client_provider()
        if not ocr_client:
            await sio.emit(ScreenshotEvents.RESULT, {
                **correlation,
                "error": "OCR_NOT_AVAILABLE",
                "message": "OCR client not initialized",
            }, to=sid)
            return True

        try:
            result = await ocr_client.recognize(image_b64)
            await sio.emit(ScreenshotEvents.RESULT, result, to=sid)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            log.error("[SIO] OCR error: %s", exc)
            await sio.emit(ScreenshotEvents.RESULT, {
                **correlation,
                "error": "OCR_ERROR",
                "message": "OCR processing failed",
            }, to=sid)
        return True

    return on_ocr_request


__all__ = ["build_ocr_request_handler"]
