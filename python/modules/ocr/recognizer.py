from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import time
from collections import OrderedDict
from importlib import import_module
from typing import Protocol, Sequence, TypeAlias, cast

from .payload import decode_base64_image_payload

logger = logging.getLogger("yuizaki.ocr")

OCRCoordinate: TypeAlias = int | float
OCRPoint: TypeAlias = Sequence[OCRCoordinate]
OCRBox: TypeAlias = Sequence[OCRPoint]
OCRLine: TypeAlias = tuple[OCRBox, str, OCRCoordinate]
OCRResult: TypeAlias = Sequence[OCRLine] | None


class OCREngine(Protocol):
    def __call__(self, image: bytes) -> tuple[OCRResult, object]: ...


class OCRClient:
    """RapidOCR text recognition client."""

    def __init__(self) -> None:
        self._ocr: OCREngine | None = None
        self._available = False
        self._initialization_attempted = False
        self._initialization_error: str | None = None
        self._connect_lock = asyncio.Lock()
        self._recognize_lock = asyncio.Lock()
        self._last_error: tuple[str, float] | None = None
        self._result_cache: OrderedDict[bytes, dict[str, object]] = OrderedDict()

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
        async with self._recognize_lock:
            async with self._connect_lock:
                self._ocr = None
                self._available = False
                self._initialization_attempted = False
                self._initialization_error = None
                self._result_cache.clear()
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
        try:
            async with self._recognize_lock:
                await self.connect()
                engine = self._ocr
                if not self._available or engine is None:
                    return {
                        "status": "error",
                        "error": self._initialization_error or "OCR not available",
                        "text": "",
                        "blocks": [],
                    }
                return await asyncio.to_thread(self._recognize_sync, image_base64, engine)
        except Exception as exc:
            error_text = str(exc)
            now = time.monotonic()
            previous = self._last_error
            if previous is None or previous[0] != error_text or now - previous[1] >= 30.0:
                logger.warning("OCR error: %s", exc)
                self._last_error = (error_text, now)
            else:
                logger.debug("OCR error repeated: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
                "text": "",
                "blocks": [],
            }

    def _recognize_sync(self, image_base64: str, engine: OCREngine) -> dict[str, object]:
        # RapidOCR accepts encoded bytes/ndarrays, but not PIL images. Decode once
        # at this boundary so callers cannot accidentally pass an image object.
        image_bytes = bytes(decode_base64_image_payload(image_base64))
        cache_key = hashlib.blake2s(image_bytes, digest_size=16).digest()
        cached = self._result_cache.get(cache_key)
        if cached is not None:
            self._result_cache.move_to_end(cache_key)
            return copy.deepcopy(cached)
        result, _ = engine(image_bytes)

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
        payload = {"status": "ok", "text": full_text, "blocks": blocks}
        self._result_cache[cache_key] = copy.deepcopy(payload)
        self._result_cache.move_to_end(cache_key)
        while len(self._result_cache) > 4:
            self._result_cache.popitem(last=False)
        return payload


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
