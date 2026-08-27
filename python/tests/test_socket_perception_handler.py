from __future__ import annotations

import asyncio
import base64
from typing import Any

from socket_events import ScreenshotEvents
from socket_handlers.perception import build_ocr_request_handler


class _Sio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


class _Ocr:
    def __init__(self) -> None:
        self.images: list[str] = []

    async def recognize(self, image: str) -> dict[str, object]:
        self.images.append(image)
        return {"text": "桌面" if image else ""}


def _handler(sio: _Sio, client: Any = None):
    return build_ocr_request_handler(
        sio=sio,
        ocr_client_provider=lambda: client,
        max_image_bytes=16,
    )


def test_ocr_handler_returns_false_for_visual_modes() -> None:
    sio = _Sio()
    handled = asyncio.run(_handler(sio, _Ocr())("sid", {"mode": "observe", "image": "abc"}))
    assert handled is False
    assert sio.events == []


def test_ocr_handler_projects_success_and_validation_errors() -> None:
    sio = _Sio()
    client = _Ocr()
    handler = _handler(sio, client)
    image = base64.b64encode(b"pixels").decode()

    assert asyncio.run(handler("sid", {"mode": "ocr", "frame_id": "frame-1", "image": image})) is True
    assert sio.events[-1] == (ScreenshotEvents.RESULT, {"text": "桌面"}, "sid")
    assert client.images == [image]

    electron_image = f"data:image/png;base64,{image}"
    assert asyncio.run(handler("sid", {
        "mode": "ocr",
        "frame_id": "frame-electron",
        "image": electron_image,
    })) is True
    assert sio.events[-1] == (ScreenshotEvents.RESULT, {"text": "桌面"}, "sid")
    assert client.images[-1] == electron_image

    asyncio.run(handler("sid", {"mode": "ocr", "frame_id": "frame-2", "image": "%%%"}))
    assert sio.events[-1][1] == {
        "frame_id": "frame-2",
        "error": "INVALID_IMAGE",
        "message": "image must be valid base64",
    }

    asyncio.run(handler("sid", {"mode": "ocr", "image": ""}))
    assert sio.events[-1][1]["error"] == "NO_IMAGE"


def test_ocr_handler_reports_provider_unavailable_and_size_limit() -> None:
    sio = _Sio()
    handler = _handler(sio)
    image = base64.b64encode(b"this payload is too large").decode()

    asyncio.run(handler("sid", {"mode": "ocr", "image": image}))
    assert sio.events[-1][1]["error"] == "IMAGE_TOO_LARGE"

    asyncio.run(handler("sid", {"mode": "ocr", "image": base64.b64encode(b"ok").decode()}))
    assert sio.events[-1][1]["error"] == "OCR_NOT_AVAILABLE"


def test_ocr_handler_applies_size_limit_to_decoded_data_url_payload() -> None:
    sio = _Sio()
    handler = _handler(sio, _Ocr())
    image = "data:image/jpeg;base64," + base64.b64encode(b"this payload is too large").decode()

    asyncio.run(handler("sid", {"mode": "ocr", "image": image}))

    assert sio.events[-1][1]["error"] == "IMAGE_TOO_LARGE"
