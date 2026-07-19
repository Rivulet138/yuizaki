from __future__ import annotations

import asyncio
import io
import logging
from importlib import import_module
from typing import Protocol, Sequence, TypeAlias, cast

from PIL import Image

from .payload import decode_base64_image_payload

logger = logging.getLogger("yuizaki.ocr")

OCRCoordinate: TypeAlias = int | float
OCRPoint: TypeAlias = Sequence[OCRCoordinate]
OCRBox: TypeAlias = Sequence[OCRPoint]
OCRLine: TypeAlias = tuple[OCRBox, str, OCRCoordinate]
OCRResult: TypeAlias = Sequence[OCRLine] | None


class OCREngine(Protocol):
    def __call__(self, image: Image.Image) -> tuple[OCRResult, object]: ...


class OCRClient:
    """RapidOCR text recognition client."""

    def __init__(self) -> None:
        self._ocr: OCREngine | None = None
        self._available = False
        self._initialization_attempted = False
        self._initialization_error: str | None = None
        self._connect_lock = asyncio.Lock()
        self._recognize_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.is_available:
            return
        async with self._connect_lock:
            if self.is_available or self._initialization_attempted:
                return
            self._initialization_attempted = True
            try:
                self._ocr = await asyncio.to_thread(self._create_engine)
                self._available = True
                self._initialization_error = None
                logger.info("OCR engine initialized on demand")
            except ImportError:
                self._available = False
                self._initialization_error = "RapidOCR not installed"
                logger.warning("RapidOCR not installed, OCR disabled")
            except Exception as exc:
                self._available = False
                self._initialization_error = str(exc)
                logger.exception("OCR initialization failed")

    @staticmethod
    def _create_engine() -> OCREngine:
        module = import_module("rapidocr_onnxruntime")
        rapidocr_type = cast("type[OCREngine]", getattr(module, "RapidOCR"))
        return rapidocr_type()

    async def disconnect(self) -> None:
        async with self._connect_lock:
            self._ocr = None
            self._available = False
            self._initialization_attempted = False
            self._initialization_error = None
        logger.info("OCR engine disconnected")

    @property
    def is_available(self) -> bool:
        return self._available and self._ocr is not None

    @property
    def initialization_state(self) -> str:
        if self.is_available:
            return "ready"
        return "unavailable" if self._initialization_attempted else "idle"

    async def recognize(self, image_base64: str) -> dict[str, object]:
        await self.connect()
        if not self.is_available:
            return {
                "status": "error",
                "error": self._initialization_error or "OCR not available",
                "text": "",
                "blocks": [],
            }

        try:
            async with self._recognize_lock:
                return await asyncio.to_thread(self._recognize_sync, image_base64)
        except Exception as exc:
            logger.error("OCR error: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
                "text": "",
                "blocks": [],
            }

    def _recognize_sync(self, image_base64: str) -> dict[str, object]:
        if self._ocr is None:
            raise RuntimeError("OCR not available")
        image_bytes = decode_base64_image_payload(image_base64)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result, _ = self._ocr(image)

        texts: list[str] = []
        blocks: list[dict[str, object]] = []
        for line in result or []:
            box, text, confidence = line
            normalized_box = _normalize_box(box)
            text_value = str(text or "")
            texts.append(text_value)
            blocks.append({
                "text": text_value,
                "bbox": normalized_box,
                "confidence": float(confidence),
            })

        full_text = "\n".join(item for item in texts if item)
        logger.info("OCR recognized %d lines, %d chars", len(texts), len(full_text))
        return {"status": "ok", "text": full_text, "blocks": blocks}


def _normalize_box(box: OCRBox) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for point in box:
        if len(point) < 2:
            continue
        xs.append(float(point[0]))
        ys.append(float(point[1]))
    if not xs or not ys:
        return [0.0, 0.0, 0.0, 0.0]
    x_min = min(xs)
    y_min = min(ys)
    return [x_min, y_min, max(xs) - x_min, max(ys) - y_min]
