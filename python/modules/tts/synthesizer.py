"""
TTS (Text-to-Speech) synthesis module.
Uses Genie-TTS for voice generation.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import threading
import time
import weakref
from collections import deque
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from modules.core.paths import DEFAULT_AUDIO_CACHE_DIR
from modules.system.experience_metrics import percentile
from modules.tts.capabilities import (
    TTSAlignmentMode,
    TTSOutputTransport,
    resolve_tts_provider_capabilities,
)
from modules.tts.visemes import normalize_viseme_cues

logger = logging.getLogger("yuizaki.tts")

GENIE_PCM_SAMPLE_RATE = 32_000
GENIE_PCM_CHANNELS = 1
GENIE_PCM_SAMPLE_WIDTH_BYTES = 2
_GENIE_RUNTIME_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)
_LATENCY_LOCK = threading.Lock()
_LOAD_LATENCY_SAMPLES: dict[str, deque[float]] = {
    "total": deque(maxlen=64),
    "queue": deque(maxlen=64),
    "model": deque(maxlen=64),
}
_WARMUP_LATENCY_SAMPLES: dict[str, deque[float]] = {
    "total": deque(maxlen=64),
    "queue": deque(maxlen=64),
    "inference": deque(maxlen=64),
}
_READY_WAIT_LATENCY_SAMPLES: dict[str, deque[float]] = {
    "total": deque(maxlen=64),
}
_GENERATION_LATENCY_SAMPLES: dict[str, deque[float]] = {
    "total": deque(maxlen=64),
}
_CANCEL_LATENCY_SAMPLES: dict[str, deque[float]] = {
    "total": deque(maxlen=64),
}


def _record_latency(
    target: dict[str, deque[float]],
    **values: float | None,
) -> None:
    with _LATENCY_LOCK:
        for key, value in values.items():
            if value is not None:
                target[key].append(value)


def _latency_summary(
    target: dict[str, deque[float]],
) -> dict[str, dict[str, float | int | None]]:
    with _LATENCY_LOCK:
        samples = {key: list(values) for key, values in target.items()}
    return {
        key: {
            "samples": len(values),
            "latest_ms": _round_ms(values[-1]) if values else None,
            "p50_ms": percentile(values, 0.5),
            "p95_ms": percentile(values, 0.95),
        }
        for key, values in samples.items()
    }


def _genie_runtime_lock() -> asyncio.Lock:
    """Serialize access to Genie-TTS' process-global model, cache, and player state."""
    loop = asyncio.get_running_loop()
    lock = _GENIE_RUNTIME_LOCKS.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _GENIE_RUNTIME_LOCKS[loop] = lock
    return lock


class TTSClient:
    """Genie-TTS voice synthesis client.

    Loads a predefined or custom character via the ``genie_tts`` library
    and generates WAV audio files stored in ``audio_cache_dir``.
    """

    def __init__(
        self,
        genie_character: str = "",
        genie_model_dir: str | None = None,
        language: str = "zh",
        ref_audio: str = "",
        ref_text: str = "",
        device: str = "cpu",
        quality: str = "质量优先",
        split: str = "智能切分",
        mode: str = "串行推理",
        save_mode: str = "禁用自动保存",
        audio_cache_dir: Path = DEFAULT_AUDIO_CACHE_DIR,
    ) -> None:
        self._character = genie_character.strip()
        self._model_dir = genie_model_dir
        self._configured_language = (language or "").strip().lower() or "ja"
        self._language = _normalize_genie_language(language)
        self._ref_audio = ref_audio.strip()
        self._ref_text = ref_text.strip()
        self._device = device.strip().lower() or "cpu"
        self._quality = quality.strip() or "质量优先"
        self._split = split.strip() or "智能切分"
        self._mode = mode.strip() or "串行推理"
        self._save_mode = save_mode.strip() or "禁用自动保存"
        self._split_sentence = _split_sentence_enabled(self._split)
        self.audio_cache_dir = audio_cache_dir
        self._genie: Any = None
        self._available = False
        self._load_lock = asyncio.Lock()
        self._warmup_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()
        self._cancel_lock = asyncio.Lock()
        self._load_task: asyncio.Task[None] | None = None
        self._warmup_task: asyncio.Task[bool] | None = None
        self._active_inference_task: asyncio.Task[Any] | None = None
        self._warmup_done = False
        self._last_load_ms: float | None = None
        self._last_load_queue_ms: float | None = None
        self._last_load_model_ms: float | None = None
        self._last_warmup_ms: float | None = None
        self._last_warmup_queue_ms: float | None = None
        self._last_warmup_inference_ms: float | None = None
        self._last_ready_wait_ms: float | None = None
        self._last_generation_ms: float | None = None
        self._last_cancel_ms: float | None = None
        self._cancel_count = 0
        self._last_error: str | None = None
        self._observed_alignment: TTSAlignmentMode = "none"
        self._observed_visemes: set[str] = set()

    async def connect(self, *, background: bool = False) -> None:
        if background:
            if self._load_task is None or self._load_task.done():
                self._load_task = asyncio.create_task(self._connect_foreground())
                logger.info("TTS client load started in background (Genie-TTS, character=%s)", self._character)
            return
        await self.ensure_ready()

    async def ensure_ready(self) -> bool:
        if self._available:
            return True

        if self._load_task is not None:
            await self._load_task
            if self._load_task.done():
                self._load_task = None
            return self._available

        async with self._load_lock:
            if self._available:
                return True
            await self._connect_foreground()
            return self._available

    @property
    def is_warming_up(self) -> bool:
        return _task_running(self._load_task) or _task_running(self._warmup_task)

    async def warmup(self, *, background: bool = False, force: bool = False) -> bool:
        if self._warmup_done and not force:
            return True

        if self._warmup_task is not None and self._warmup_task.done():
            self._warmup_task = None

        if self._warmup_task is not None:
            if background:
                return True
            return await self._warmup_task

        if background:
            self._warmup_task = asyncio.create_task(self._warmup_foreground(force=force))
            logger.info("TTS inference warmup queued (Genie-TTS, character=%s)", self._character)
            return True

        return await self._warmup_foreground(force=force)

    def status_snapshot(self) -> dict[str, Any]:
        loading = _task_running(self._load_task)
        inference_warming = _task_running(self._warmup_task)
        supports_pcm_streaming = self._supports_pcm_streaming()
        streaming_transport: TTSOutputTransport = "pcm_s16le" if supports_pcm_streaming else "wav"
        capability_transport: TTSOutputTransport = (
            streaming_transport if self._genie is not None else "unavailable"
        )
        if self._last_error:
            message = self._last_error
        elif loading:
            message = "TTS model loading"
        elif inference_warming:
            message = "TTS inference warming"
        elif self._warmup_done:
            message = "TTS ready and warmed"
        elif self._available:
            message = "TTS model loaded"
        else:
            message = "TTS cold"

        return {
            "provider": "genie-tts",
            "available": self._available,
            "loading": loading,
            "warming_up": loading or inference_warming,
            "warmup_running": inference_warming,
            "warmup_done": self._warmup_done,
            "inference_running": _task_running(self._active_inference_task),
            "character": self._character,
            "language": self._language,
            "configured_language": self._configured_language,
            "device": self._device,
            "quality": self._quality,
            "split": self._split,
            "mode": self._mode,
            "save_mode": self._save_mode,
            "split_sentence": self._split_sentence,
            "streaming_transport": streaming_transport,
            "streaming_sample_rate": GENIE_PCM_SAMPLE_RATE if supports_pcm_streaming else None,
            "capabilities": resolve_tts_provider_capabilities(
                "genie-tts",
                output_transport=capability_transport,
                alignment=self._observed_alignment,
                observed_visemes=self._observed_visemes,
            ),
            "last_load_ms": _round_ms(self._last_load_ms),
            "last_load_queue_ms": _round_ms(self._last_load_queue_ms),
            "last_load_model_ms": _round_ms(self._last_load_model_ms),
            "load_latency_summary": _latency_summary(_LOAD_LATENCY_SAMPLES),
            "last_warmup_ms": _round_ms(self._last_warmup_ms),
            "last_warmup_queue_ms": _round_ms(self._last_warmup_queue_ms),
            "last_warmup_inference_ms": _round_ms(self._last_warmup_inference_ms),
            "warmup_latency_summary": _latency_summary(_WARMUP_LATENCY_SAMPLES),
            "last_ready_wait_ms": _round_ms(self._last_ready_wait_ms),
            "ready_wait_latency_summary": _latency_summary(_READY_WAIT_LATENCY_SAMPLES)["total"],
            "last_generation_ms": _round_ms(self._last_generation_ms),
            "generation_latency_summary": _latency_summary(_GENERATION_LATENCY_SAMPLES)["total"],
            "last_cancel_ms": _round_ms(self._last_cancel_ms),
            "cancel_latency_summary": _latency_summary(_CANCEL_LATENCY_SAMPLES)["total"],
            "cancel_count": self._cancel_count,
            "last_error": self._last_error,
            "message": message,
        }

    async def _connect_foreground(self) -> None:
        started = time.perf_counter()
        operation_timing: dict[str, float] = {}
        connected = False
        self._last_error = None
        self._last_load_queue_ms = None
        self._last_load_model_ms = None
        try:
            genie_tts = await self._run_serialized_blocking_call(
                self._load_genie,
                operation_timing=operation_timing,
                task_name=f"genie-tts-load-{id(self)}",
            )
            self._genie = genie_tts
            self._available = True
            connected = True
        except ImportError:
            self._available = False
            self._last_error = "genie-tts not installed"
            logger.warning(
                "genie-tts not installed; TTS disabled. "
                "Install with: pip install genie-tts"
            )
        except Exception as exc:
            self._available = False
            self._last_error = str(exc)
            logger.error("Genie-TTS init failed: %s", exc)
        finally:
            self._last_load_ms = (time.perf_counter() - started) * 1000
            self._last_load_queue_ms = operation_timing.get("queue_ms")
            self._last_load_model_ms = operation_timing.get("operation_ms")

        if connected:
            _record_latency(
                _LOAD_LATENCY_SAMPLES,
                total=self._last_load_ms,
                queue=self._last_load_queue_ms,
                model=self._last_load_model_ms,
            )
            logger.info(
                "TTS client connected (Genie-TTS, character=%s lang=%s device=%s quality=%s split=%s mode=%s save_mode=%s load=%.1fms queue=%.1fms model=%.1fms)",
                self._character,
                self._language,
                self._device,
                self._quality,
                self._split,
                self._mode,
                self._save_mode,
                self._last_load_ms,
                self._last_load_queue_ms or 0.0,
                self._last_load_model_ms or 0.0,
            )

    async def _warmup_foreground(self, *, force: bool = False) -> bool:
        async with self._warmup_lock:
            if self._warmup_done and not force:
                return True

            started = time.perf_counter()
            self._last_warmup_queue_ms = None
            self._last_warmup_inference_ms = None
            if not await self.ensure_ready():
                self._last_warmup_ms = (time.perf_counter() - started) * 1000
                self._last_error = self._last_error or "TTS client not initialized (genie-tts not available)"
                return False

            warmup_path = Path(tempfile.gettempdir()) / f"yuizaki_tts_warmup_{id(self)}.wav"
            operation_timing: dict[str, float] = {}
            try:
                async with self._inference_lock:
                    await self._run_serialized_blocking_call(
                        _generate_wav,
                        self._genie,
                        self._character,
                        _test_text_for_language(self._language),
                        str(warmup_path),
                        self._split_sentence,
                        self._language,
                        cancellable=True,
                        operation_timing=operation_timing,
                        task_name=f"genie-tts-warmup-{id(self)}",
                    )
                self._last_warmup_queue_ms = operation_timing.get("queue_ms")
                self._last_warmup_inference_ms = operation_timing.get("operation_ms")
                self._last_warmup_ms = (time.perf_counter() - started) * 1000
                self._warmup_done = True
                self._last_error = None
                _record_latency(
                    _WARMUP_LATENCY_SAMPLES,
                    total=self._last_warmup_ms,
                    queue=self._last_warmup_queue_ms,
                    inference=self._last_warmup_inference_ms,
                )
                logger.info(
                    "TTS inference warmup completed (Genie-TTS, character=%s total=%.1fms queue=%.1fms inference=%.1fms)",
                    self._character,
                    self._last_warmup_ms,
                    self._last_warmup_queue_ms or 0,
                    self._last_warmup_inference_ms or 0,
                )
                return True
            except Exception as exc:
                self._last_warmup_ms = (time.perf_counter() - started) * 1000
                self._warmup_done = False
                self._last_error = f"Genie-TTS warmup failed: {exc}"
                logger.warning("TTS inference warmup failed: %s", exc)
                return False
            finally:
                self._last_warmup_queue_ms = operation_timing.get("queue_ms")
                self._last_warmup_inference_ms = operation_timing.get("operation_ms")
                warmup_path.unlink(missing_ok=True)

    def _load_genie(self) -> Any:
        import os

        default_genie_dir = str(Path(__file__).resolve().parents[2] / ".cache" / "GenieData" / "GenieData")
        os.environ.setdefault("GENIE_DATA_DIR", default_genie_dir)

        import genie_tts  # type: ignore[import-untyped]

        clear_reference_audio_cache = getattr(genie_tts, "clear_reference_audio_cache", None)
        if callable(clear_reference_audio_cache):
            clear_reference_audio_cache()

        character = _resolve_genie_character(
            requested_character=self._character,
            model_dir=self._model_dir,
            language=self._language,
        )
        self._character = character

        if self._model_dir:
            genie_tts.load_character(
                character_name=character,
                onnx_model_dir=self._model_dir,
                language=self._language,
            )
        else:
            genie_tts.load_predefined_character(character)

        if self._ref_audio or self._ref_text:
            if not self._ref_audio or not self._ref_text:
                raise ValueError("Both TTS ref_audio and ref_text are required for Genie-TTS reference audio")
            if not Path(self._ref_audio).exists():
                raise FileNotFoundError(f"TTS reference audio not found: {self._ref_audio}")
            genie_tts.set_reference_audio(
                self._character,
                self._ref_audio,
                self._ref_text,
                language=self._language,
            )

        return genie_tts

    async def disconnect(self) -> None:
        await self._stop_active_inference()
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
            try:
                await self._load_task
            except asyncio.CancelledError:
                pass
        if self._warmup_task is not None and not self._warmup_task.done():
            self._warmup_task.cancel()
            try:
                await self._warmup_task
            except asyncio.CancelledError:
                pass
        self._load_task = None
        self._warmup_task = None
        self._active_inference_task = None
        self._genie = None
        self._available = False
        self._warmup_done = False
        self._observed_alignment = "none"
        self._observed_visemes.clear()
        logger.info("TTS client disconnected")

    @property
    def is_enabled(self) -> bool:
        return self._available

    async def synthesize(self, ws: Any, gen: Any) -> None:
        ready_started = time.perf_counter()
        if hasattr(gen, "mark"):
            gen.mark("tts_requested")
        if not await self.ensure_ready():
            return
        if gen.invalidated or gen.cancel.is_set():
            return
        if not gen.full_text:
            return
        self._record_ready_wait(gen, ready_started)

        sid = gen.session_id
        gid = gen.generation_id
        text = gen.full_text.strip()
        segments = _split_tts_segments(text) if self._split_sentence else [text]
        logger.info("[%s/%s] TTS start chars=%d segments=%d", sid, gid, len(text), len(segments))
        if hasattr(gen, "mark"):
            gen.mark("tts_started")

        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        generation_started = time.perf_counter()

        try:
            for sequence, segment in enumerate(segments):
                if gen.invalidated or gen.cancel.is_set():
                    return
                wav_name = f"{gid}.wav" if len(segments) == 1 else f"{gid}-{sequence:03d}.wav"
                wav_path = self.audio_cache_dir / wav_name
                utterance_language = _resolve_utterance_language(
                    segment,
                    self._configured_language,
                    self._language,
                )
                await self._run_cancellable_inference(
                    gen,
                    segment,
                    wav_path,
                    utterance_language,
                )

                if gen.invalidated or gen.cancel.is_set():
                    return

                is_final = sequence == len(segments) - 1
                if sequence == 0 and hasattr(gen, "mark"):
                    gen.mark("tts_first_chunk")
                    gen.mark("tts_first_audio_ready")
                if is_final and hasattr(gen, "mark"):
                    gen.mark("tts_completed")

                wav_size = wav_path.stat().st_size if wav_path.exists() else 0
                logger.info(
                    "[%s/%s] TTS segment ready sequence=%d final=%s wav=%s size=%d bytes",
                    sid, gid, sequence, is_final, wav_path.name, wav_size,
                )
                payload = {
                    "type": "tts_audio",
                    "session_id": sid,
                    "generation_id": gid,
                    "audio_url": f"/audio/{wav_path.name}",
                    "sequence": sequence,
                    "is_final": is_final,
                    "text": segment,
                }
                if hasattr(gen, "latency_snapshot"):
                    payload["latency"] = gen.latency_snapshot()
                await _safe_send(ws, gen, payload)
            self._last_generation_ms = (time.perf_counter() - generation_started) * 1000
            self._last_error = None
            _record_latency(
                _GENERATION_LATENCY_SAMPLES,
                total=self._last_generation_ms,
            )
        except Exception as exc:
            self._last_generation_ms = (time.perf_counter() - generation_started) * 1000
            self._last_error = f"TTS generation failed: {exc}"
            logger.error("[%s/%s] TTS generation failed: %s", sid, gid, exc)
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": sid,
                "generation_id": gid,
                "error": f"TTS generation failed: {exc}",
            })
            return

        logger.info(
            "[%s/%s] TTS done segments=%d wait=%.1fms gen=%.1fms",
            sid, gid, len(segments),
            self._last_ready_wait_ms or 0,
            self._last_generation_ms or 0,
        )

    async def synthesize_stream_segment(self, ws: Any, gen: Any, text: str, sequence: int) -> bool:
        segment = text.strip()
        if not segment or gen.invalidated or gen.cancel.is_set():
            return False
        ready_started = time.perf_counter()
        if sequence == 0 and hasattr(gen, "mark"):
            gen.mark("tts_requested")
        if not await self.ensure_ready():
            return False
        if gen.invalidated or gen.cancel.is_set():
            return False
        if sequence == 0:
            self._record_ready_wait(gen, ready_started)

        if sequence == 0 and hasattr(gen, "mark"):
            gen.mark("tts_started")
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        wav_path = self.audio_cache_dir / f"{gen.generation_id}-stream-{sequence:03d}.wav"
        utterance_language = _resolve_utterance_language(
            segment,
            self._configured_language,
            self._language,
        )
        started = time.perf_counter()
        try:
            if self._supports_pcm_streaming():
                generated = await self._run_cancellable_pcm_inference(
                    ws,
                    gen,
                    segment,
                    sequence,
                )
                self._last_generation_ms = (time.perf_counter() - started) * 1000
                self._last_error = None
                if generated:
                    _record_latency(
                        _GENERATION_LATENCY_SAMPLES,
                        total=self._last_generation_ms,
                    )
                return generated

            await self._run_cancellable_inference(
                gen,
                segment,
                wav_path,
                utterance_language,
            )
            if gen.invalidated or gen.cancel.is_set():
                return False
            self._last_generation_ms = (time.perf_counter() - started) * 1000
            self._last_error = None
            if sequence == 0 and hasattr(gen, "mark"):
                gen.mark("tts_first_chunk")
                gen.mark("tts_first_audio_ready")
            payload = {
                "type": "tts_audio",
                "session_id": gen.session_id,
                "generation_id": gen.generation_id,
                "audio_url": f"/audio/{wav_path.name}",
                "sequence": sequence,
                "is_final": False,
                "text": segment,
            }
            if hasattr(gen, "latency_snapshot"):
                payload["latency"] = gen.latency_snapshot()
            await _safe_send(ws, gen, payload)
            _record_latency(
                _GENERATION_LATENCY_SAMPLES,
                total=self._last_generation_ms,
            )
            return True
        except Exception as exc:
            self._last_generation_ms = (time.perf_counter() - started) * 1000
            self._last_error = f"TTS generation failed: {exc}"
            logger.error(
                "[%s/%s] streaming TTS segment %d failed: %s",
                gen.session_id,
                gen.generation_id,
                sequence,
                exc,
            )
            await _safe_send(ws, gen, {
                "type": "error",
                "session_id": gen.session_id,
                "generation_id": gen.generation_id,
                "error": f"TTS generation failed: {exc}",
            })
            return False

    def _record_ready_wait(self, gen: Any, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._last_ready_wait_ms = elapsed_ms
        _record_latency(_READY_WAIT_LATENCY_SAMPLES, total=elapsed_ms)
        if hasattr(gen, "record_duration"):
            gen.record_duration("tts_ready_wait", elapsed_ms)

    def _supports_pcm_streaming(self) -> bool:
        return callable(getattr(self._genie, "tts_async", None))

    async def _run_cancellable_pcm_inference(
        self,
        ws: Any,
        gen: Any,
        text: str,
        sequence: int,
    ) -> bool:
        """Forward Genie async PCM chunks without writing a temporary WAV file."""
        async with self._inference_lock, _genie_runtime_lock():
            async def _consume() -> bool:
                stream = self._genie.tts_async(
                    character_name=self._character,
                    text=text,
                    play=False,
                    split_sentence=False,
                    save_path=None,
                )
                chunk_index = 0
                async for raw_chunk in stream:
                    if gen.invalidated or gen.cancel.is_set():
                        return False
                    raw_audio: object = raw_chunk
                    visemes: list[dict[str, Any]] = []
                    if isinstance(raw_chunk, Mapping):
                        raw_audio = raw_chunk.get("audio")
                        visemes = normalize_viseme_cues(raw_chunk.get("visemes"))
                        if visemes:
                            self._observed_alignment = "viseme"
                            self._observed_visemes.update(cue["viseme"] for cue in visemes)
                    if not isinstance(raw_audio, (bytes, bytearray, memoryview)):
                        continue
                    pcm = bytes(raw_audio)
                    if not pcm:
                        continue
                    if sequence == 0 and chunk_index == 0 and hasattr(gen, "mark"):
                        gen.mark("tts_first_chunk")
                        gen.mark("tts_first_audio_ready")
                    duration_ms = round(
                        len(pcm)
                        / (GENIE_PCM_SAMPLE_RATE * GENIE_PCM_CHANNELS * GENIE_PCM_SAMPLE_WIDTH_BYTES)
                        * 1000,
                        1,
                    )
                    payload = {
                        "type": "tts_pcm",
                        "session_id": gen.session_id,
                        "generation_id": gen.generation_id,
                        "audio": pcm,
                        "audio_format": "pcm_s16le",
                        "sample_rate": GENIE_PCM_SAMPLE_RATE,
                        "channels": GENIE_PCM_CHANNELS,
                        "sample_width_bytes": GENIE_PCM_SAMPLE_WIDTH_BYTES,
                        "duration_ms": duration_ms,
                        "sequence": sequence,
                        "chunk_index": chunk_index,
                        "is_final": False,
                        "text": text if chunk_index == 0 else "",
                    }
                    if visemes:
                        payload["visemes"] = visemes
                    if hasattr(gen, "latency_snapshot"):
                        payload["latency"] = gen.latency_snapshot()
                    await _safe_send(ws, gen, payload)
                    chunk_index += 1
                if chunk_index == 0:
                    raise RuntimeError("Genie-TTS produced no PCM audio")
                return True

            worker = asyncio.create_task(
                _consume(),
                name=f"genie-tts-pcm-{getattr(gen, 'generation_id', 'unknown')}",
            )
            self._active_inference_task = worker
            try:
                return bool(await asyncio.shield(worker))
            except asyncio.CancelledError:
                if hasattr(gen, "mark"):
                    gen.mark("tts_cancel_requested")
                if not worker.done():
                    await self._stop_active_inference()
                await asyncio.gather(worker, return_exceptions=True)
                if hasattr(gen, "mark"):
                    gen.mark("tts_cancelled")
                raise
            finally:
                if self._active_inference_task is worker:
                    self._active_inference_task = None

    async def complete_stream(self, ws: Any, gen: Any, sequence: int) -> None:
        if gen.invalidated or gen.cancel.is_set():
            return
        if hasattr(gen, "mark"):
            gen.mark("tts_completed")
        payload = {
            "type": "tts_complete",
            "session_id": gen.session_id,
            "generation_id": gen.generation_id,
            "sequence": sequence,
            "is_final": True,
        }
        if hasattr(gen, "latency_snapshot"):
            payload["latency"] = gen.latency_snapshot()
        await _safe_send(ws, gen, payload)

    async def _run_cancellable_inference(
        self,
        gen: Any,
        text: str,
        wav_path: Path,
        language: str,
    ) -> None:
        """Keep the engine serialized until a cancelled worker has really stopped."""
        async with self._inference_lock:
            await self._run_serialized_blocking_call(
                _generate_wav,
                self._genie,
                self._character,
                text,
                str(wav_path),
                False,
                language,
                cancellable=True,
                generation=gen,
                task_name=f"genie-tts-inference-{getattr(gen, 'generation_id', 'unknown')}",
            )

    async def _run_serialized_blocking_call(
        self,
        callback: Any,
        *args: Any,
        cancellable: bool = False,
        generation: Any = None,
        operation_timing: dict[str, float] | None = None,
        task_name: str,
    ) -> Any:
        """Run one blocking Genie call without releasing shared state during cancellation."""
        queued_at = time.perf_counter()
        async with _genie_runtime_lock():
            operation_started = time.perf_counter()
            if operation_timing is not None:
                operation_timing["queue_ms"] = (operation_started - queued_at) * 1000
            worker = asyncio.create_task(asyncio.to_thread(callback, *args), name=task_name)
            if cancellable:
                self._active_inference_task = worker
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                if generation is not None and hasattr(generation, "mark"):
                    generation.mark("tts_cancel_requested")
                if cancellable and not worker.done():
                    await self._stop_active_inference()
                await asyncio.gather(worker, return_exceptions=True)
                if generation is not None and hasattr(generation, "mark"):
                    generation.mark("tts_cancelled")
                raise
            finally:
                if operation_timing is not None:
                    operation_timing["operation_ms"] = (time.perf_counter() - operation_started) * 1000
                if cancellable and self._active_inference_task is worker:
                    self._active_inference_task = None

    async def _stop_active_inference(self) -> bool:
        genie_stop = getattr(self._genie, "stop", None)
        if not callable(genie_stop):
            return False
        async with self._cancel_lock:
            active = self._active_inference_task
            if active is None or active.done():
                return False
            started = time.perf_counter()
            try:
                await asyncio.to_thread(genie_stop)
                self._last_cancel_ms = (time.perf_counter() - started) * 1000
                self._cancel_count += 1
                _record_latency(
                    _CANCEL_LATENCY_SAMPLES,
                    total=self._last_cancel_ms,
                )
                return True
            except Exception as exc:
                self._last_cancel_ms = (time.perf_counter() - started) * 1000
                logger.warning("Failed to stop active Genie-TTS inference: %s", exc)
                return False

    async def test_connection(self) -> dict[str, Any]:
        ok = await self.warmup(force=True)
        if ok:
            return {
                "ok": True,
                "message": "Genie-TTS connection OK",
                "runtime": self.status_snapshot(),
            }
        return {
            "ok": False,
            "message": self._last_error or "Genie-TTS test failed",
            "runtime": self.status_snapshot(),
        }


def _normalize_genie_language(language: str) -> str:
    normalized = (language or "").strip()
    language_map = {
        "zh": "Chinese",
        "cn": "Chinese",
        "chinese": "Chinese",
        "ja": "Japanese",
        "jp": "Japanese",
        "japanese": "Japanese",
        "en": "English",
        "english": "English",
        "ko": "Korean",
        "kr": "Korean",
        "korean": "Korean",
        "auto": "Japanese",
    }
    return language_map.get(normalized.lower(), normalized or "Japanese")


def _normalize_language_name(language: str) -> str:
    return _normalize_genie_language(language).strip().lower()


def _resolve_genie_character(
    *,
    requested_character: str,
    model_dir: str | None,
    language: str,
) -> str:
    configured = requested_character.strip()
    if configured:
        return configured

    if model_dir:
        model_name = Path(model_dir).expanduser().resolve().name.strip()
        return model_name or "custom"

    try:
        from genie_tts.PredefinedCharacter import CHARA_LANG  # type: ignore[import-untyped]
    except Exception as exc:
        raise ValueError("TTS Genie character is empty and predefined character metadata is unavailable") from exc

    if not isinstance(CHARA_LANG, dict) or not CHARA_LANG:
        raise ValueError("TTS Genie character is empty and no predefined characters were found")

    target_language = _normalize_language_name(language)
    for character_name, character_language in CHARA_LANG.items():
        if _normalize_language_name(str(character_language)) == target_language:
            return str(character_name)

    return str(next(iter(CHARA_LANG)))


def _detect_text_language(text: str) -> str:
    """Best-effort language hint for Genie-TTS when settings are set to auto."""
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "Japanese"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "Chinese"
    if any(("A" <= char <= "Z") or ("a" <= char <= "z") for char in text):
        return "English"
    return "Japanese"


def _resolve_utterance_language(text: str, configured_language: str, fallback_language: str) -> str:
    if configured_language == "auto":
        return _detect_text_language(text)
    return fallback_language or "Japanese"


def _split_sentence_enabled(split: str) -> bool:
    normalized = (split or "").strip().lower()
    return normalized not in {"none", "off", "false", "disabled", "禁用", "不切分", "无切分"}


def _split_tts_segments(text: str, *, max_chars: int = 96) -> list[str]:
    """Create short, natural playback units without dropping punctuation."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    clauses = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*|\n+", normalized) if part.strip()]
    segments: list[str] = []
    for clause in clauses or [normalized]:
        clause_segments: list[str] = []
        remaining = clause
        while len(remaining) > max_chars:
            split_at = max(remaining.rfind(mark, 0, max_chars + 1) for mark in ("，", ",", "、", " "))
            split_at = max_chars if split_at < max_chars // 2 else split_at + 1
            clause_segments.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            if clause_segments and len(remaining) < 8 and len(clause_segments[-1]) + len(remaining) <= max_chars:
                clause_segments[-1] = f"{clause_segments[-1]}{remaining}"
            else:
                clause_segments.append(remaining)
        segments.extend(clause_segments)
    return segments


class StreamingSentenceBuffer:
    """Collect token deltas and release only complete, speakable sentence units."""

    _BOUNDARY = re.compile(r"[。！？!?；;\n]")

    def __init__(self, *, max_chars: int = 96) -> None:
        self._buffer = ""
        self._max_chars = max_chars

    def feed(self, text: str) -> list[str]:
        if text:
            self._buffer += text
        segments: list[str] = []
        matches = list(self._BOUNDARY.finditer(self._buffer))
        if matches:
            cut = matches[-1].end()
            completed = self._buffer[:cut]
            self._buffer = self._buffer[cut:]
            segments.extend(_split_tts_segments(completed, max_chars=self._max_chars))

        while len(self._buffer) > self._max_chars:
            split_at = max(
                self._buffer.rfind(mark, 0, self._max_chars + 1)
                for mark in ("，", ",", "、", " ")
            )
            if split_at < self._max_chars // 2:
                break
            split_at += 1
            segment = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            if segment:
                segments.append(segment)
        return segments

    def flush(self) -> list[str]:
        remainder = self._buffer.strip()
        self._buffer = ""
        return _split_tts_segments(remainder, max_chars=self._max_chars) if remainder else []


def _task_running(task: asyncio.Task[Any] | None) -> bool:
    return task is not None and not task.done()


def _round_ms(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _test_text_for_language(language: str) -> str:
    normalized = (language or "").strip().lower()
    if normalized == "japanese":
        return "テストです"
    if normalized == "english":
        return "test"
    if normalized == "korean":
        return "테스트입니다"
    return "测试"


def _generate_wav(
    genie_module: Any,
    character: str,
    text: str,
    wav_path: str,
    split_sentence: bool = True,
    language: str = "Japanese",
) -> None:
    output_path = Path(wav_path)
    output_path.unlink(missing_ok=True)
    kwargs = {
        "character_name": character,
        "text": text,
        "play": False,
        "split_sentence": split_sentence,
        "save_path": wav_path,
    }
    try:
        genie_module.tts(**kwargs, language=language)
    except TypeError as exc:
        if "language" not in str(exc):
            raise
        genie_module.tts(**kwargs)
    if hasattr(genie_module, "wait_for_playback_done"):
        genie_module.wait_for_playback_done()
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Genie-TTS produced no WAV audio")


async def _safe_send(ws: Any, gen: Any, msg: dict[str, Any]) -> None:
    if gen.invalidated or gen.cancel.is_set():
        return
    try:
        await ws.send_json(msg)
    except Exception as exc:
        logger.warning("Failed to send TTS WS message: %s", exc)
