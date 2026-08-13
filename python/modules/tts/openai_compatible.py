from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from pathlib import Path
from typing import Any

import httpx

from modules.core.paths import DEFAULT_AUDIO_CACHE_DIR
from modules.tts.capabilities import resolve_tts_provider_capabilities
from modules.tts.synthesizer import _split_tts_segments

logger = logging.getLogger("yuizaki.tts.openai_compatible")


def normalize_speech_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return ""
    if normalized.endswith("/audio/speech"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/audio/speech"
    return f"{normalized}/v1/audio/speech"


class OpenAICompatibleTTSClient:
    """Sentence-streaming adapter for OpenAI-compatible speech endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        model: str = "tts-1",
        voice: str = "alloy",
        timeout: float = 60.0,
        audio_cache_dir: Path = DEFAULT_AUDIO_CACHE_DIR,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = normalize_speech_endpoint(base_url)
        self._api_key = api_key.strip()
        self._model = model.strip() or "tts-1"
        self._voice = voice.strip() or "alloy"
        self._timeout = max(1.0, float(timeout))
        self.audio_cache_dir = audio_cache_dir
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._available = False
        self._active_request: asyncio.Task[bytes] | None = None
        self._last_generation_ms: float | None = None
        self._last_cancel_ms: float | None = None
        self._cancel_count = 0
        self._last_error: str | None = None

    @property
    def is_enabled(self) -> bool:
        return self._available

    @property
    def is_warming_up(self) -> bool:
        return False

    async def connect(self, *, background: bool = False) -> None:
        del background
        if self._client is None:
            headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=self._timeout,
                transport=self._transport,
            )
        self._available = bool(self._endpoint and self._model and self._voice)
        self._last_error = None if self._available else "OpenAI-compatible TTS configuration is incomplete"

    async def ensure_ready(self) -> bool:
        if self._client is None:
            await self.connect()
        return self._available

    async def disconnect(self) -> None:
        await self._cancel_active_request()
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._available = False

    async def warmup(self, *, background: bool = False, force: bool = False) -> bool:
        del background, force
        return await self.ensure_ready()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "provider": "openai-compatible",
            "available": self._available,
            "loading": False,
            "warming_up": False,
            "warmup_running": False,
            "warmup_done": self._available,
            "inference_running": self._active_request is not None and not self._active_request.done(),
            "model": self._model,
            "voice": self._voice,
            "endpoint_configured": bool(self._endpoint),
            "streaming_transport": "wav",
            "streaming_sample_rate": None,
            "last_generation_ms": _round_ms(self._last_generation_ms),
            "last_cancel_ms": _round_ms(self._last_cancel_ms),
            "cancel_count": self._cancel_count,
            "last_error": self._last_error,
            "capabilities": resolve_tts_provider_capabilities(
                "openai-compatible",
                output_transport="wav" if self._available else "unavailable",
            ),
        }

    async def synthesize(self, ws: Any, gen: Any) -> None:
        text = str(getattr(gen, "full_text", "")).strip()
        if not text:
            return
        sequence = -1
        for sequence, segment in enumerate(_split_tts_segments(text)):
            if not await self.synthesize_stream_segment(ws, gen, segment, sequence):
                return
        await self.complete_stream(ws, gen, sequence + 1)

    async def synthesize_stream_segment(
        self,
        ws: Any,
        gen: Any,
        text: str,
        sequence: int,
    ) -> bool:
        segment = text.strip()
        if not segment or _generation_cancelled(gen):
            return False
        if sequence == 0 and hasattr(gen, "mark"):
            gen.mark("tts_requested")
        if not await self.ensure_ready() or _generation_cancelled(gen):
            return False
        if sequence == 0 and hasattr(gen, "mark"):
            gen.mark("tts_started")

        started = time.perf_counter()
        try:
            request = asyncio.create_task(self._request_audio(segment))
            self._active_request = request
            audio = await request
            if _generation_cancelled(gen):
                return False

            duration_ms = _wav_duration_ms(audio)

            self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
            wav_path = self.audio_cache_dir / f"{gen.generation_id}-stream-{sequence:03d}.wav"
            await asyncio.to_thread(wav_path.write_bytes, audio)
            if _generation_cancelled(gen):
                return False

            self._last_generation_ms = (time.perf_counter() - started) * 1000
            self._last_error = None
            if sequence == 0 and hasattr(gen, "mark"):
                gen.mark("tts_first_chunk")
                gen.mark("tts_first_audio_ready")
            payload: dict[str, Any] = {
                "type": "tts_audio",
                "session_id": gen.session_id,
                "generation_id": gen.generation_id,
                "audio_url": f"/audio/{wav_path.name}",
                "sequence": sequence,
                "is_final": False,
                "text": segment,
                "duration_ms": duration_ms,
            }
            if hasattr(gen, "latency_snapshot"):
                payload["latency"] = gen.latency_snapshot()
            await _safe_send(ws, gen, payload)
            return True
        except asyncio.CancelledError:
            await self._cancel_active_request()
            if _generation_cancelled(gen):
                return False
            raise
        except Exception as exc:
            self._last_generation_ms = (time.perf_counter() - started) * 1000
            self._last_error = f"TTS generation failed: {exc}"
            logger.error(
                "[%s/%s] OpenAI-compatible TTS segment %d failed: %s",
                gen.session_id,
                gen.generation_id,
                sequence,
                exc,
            )
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": gen.session_id,
                "generation_id": gen.generation_id,
                "error": self._last_error,
            })
            return False
        finally:
            if self._active_request is request and request.done():
                self._active_request = None

    async def complete_stream(self, ws: Any, gen: Any, sequence: int) -> None:
        if _generation_cancelled(gen):
            return
        if hasattr(gen, "mark"):
            gen.mark("tts_completed")
        payload: dict[str, Any] = {
            "type": "tts_complete",
            "session_id": gen.session_id,
            "generation_id": gen.generation_id,
            "sequence": sequence,
            "is_final": True,
        }
        if hasattr(gen, "latency_snapshot"):
            payload["latency"] = gen.latency_snapshot()
        await _safe_send(ws, gen, payload)

    async def test_connection(self) -> dict[str, Any]:
        if not await self.ensure_ready():
            return {"ok": False, "message": self._last_error, "runtime": self.status_snapshot()}
        started = time.perf_counter()
        try:
            audio = await self._request_audio("test")
            ok = bool(audio)
            self._last_generation_ms = (time.perf_counter() - started) * 1000
            self._last_error = None if ok else "TTS provider returned empty audio"
        except Exception as exc:
            ok = False
            self._last_error = f"TTS connection failed: {exc}"
        return {
            "ok": ok,
            "message": "OpenAI-compatible TTS connection OK" if ok else self._last_error,
            "runtime": self.status_snapshot(),
        }

    async def _request_audio(self, text: str) -> bytes:
        if self._client is None:
            raise RuntimeError("TTS client is not connected")
        response = await self._client.post(
            self._endpoint,
            json={
                "model": self._model,
                "voice": self._voice,
                "input": text,
                "response_format": "wav",
            },
            headers={"Accept": "audio/wav"},
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("TTS provider returned empty audio")
        return response.content

    async def _cancel_active_request(self) -> None:
        request = self._active_request
        if request is None or request.done():
            return
        started = time.perf_counter()
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        self._last_cancel_ms = (time.perf_counter() - started) * 1000
        self._cancel_count += 1
        self._active_request = None


def _generation_cancelled(gen: Any) -> bool:
    return bool(gen.invalidated or gen.cancel.is_set())


async def _safe_send(ws: Any, gen: Any, payload: dict[str, Any]) -> None:
    if _generation_cancelled(gen):
        return
    await ws.send_json(payload)


def _round_ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _wav_duration_ms(audio: bytes) -> float | None:
    """Read duration without decoding; malformed provider output stays compatible."""
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
        if frame_rate <= 0:
            return None
        return round(frame_count / frame_rate * 1000, 1)
    except (EOFError, OSError, wave.Error):
        return None
