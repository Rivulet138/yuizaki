from __future__ import annotations

import asyncio
import base64
import logging

from modules.ocr.recognizer import OCRClient
from socket_server import DesktopPetSocketServer


class _Engine:
    def __init__(self) -> None:
        self.inputs: list[object] = []

    def __call__(self, image: bytes) -> tuple[list[object], object]:
        self.inputs.append(image)
        return [], None


def test_ocr_decodes_payload_to_bytes() -> None:
    client = OCRClient()
    engine = _Engine()
    result = client._recognize_sync(
        "data:image/png;base64," + base64.b64encode(b"image").decode(),
        engine,
    )

    assert result["status"] == "ok"
    assert engine.inputs == [b"image"]

    second = client._recognize_sync(
        base64.b64encode(b"image").decode(),
        engine,
    )
    assert second == result
    assert engine.inputs == [b"image"]


def test_ocr_repeated_errors_are_rate_limited(caplog) -> None:
    client = OCRClient()

    def fail(_image: bytes) -> tuple[object, object]:
        raise TypeError("unsupported image type")

    client._ocr = fail
    client._available = True
    caplog.set_level(logging.WARNING, logger="yuizaki.ocr")

    async def run() -> None:
        await client.recognize(base64.b64encode(b"image").decode())
        await client.recognize(base64.b64encode(b"image").decode())

    asyncio.run(run())
    assert len([record for record in caplog.records if record.levelno >= logging.WARNING]) == 1


def test_visual_ocr_deduplicates_same_frame() -> None:
    server = DesktopPetSocketServer.__new__(DesktopPetSocketServer)
    calls = 0

    class _OCR:
        async def recognize(self, _image: str) -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"text": "", "blocks": []}

    server.ocr_client = _OCR()
    server._visual_ocr_frame_ids = {}
    server._visual_ocr_attempts = {}
    frame = {"frame_id": "frame-1", "image": base64.b64encode(b"image").decode()}

    asyncio.run(server._run_visual_ocr("sid", frame))
    asyncio.run(server._run_visual_ocr("sid", frame))

    assert calls == 1
    assert server._visual_ocr_attempts["sid"] == 1
