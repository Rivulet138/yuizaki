"""
SenseVoice ASR module.
Uses Alibaba DAMO SenseVoiceSmall for speech recognition with
built-in VAD, automatic language detection, and emotion recognition.

Replaces the legacy faster-whisper + Silero VAD pipeline.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import socket
import threading
import time
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import numpy as np

logger = logging.getLogger("yuizaki.asr.sensevoice")

_SENSEVOICE_MODEL = "iic/SenseVoiceSmall"
_SENSEVOICE_SERVICE_DEFAULT_BASE_URLS = (
    "http://127.0.0.1:8899/v1",
    "http://localhost:8899/v1",
)
_SENSEVOICE_SERVICE_TCP_PROBE_TIMEOUT = 0.2
_SENSEVOICE_SERVICE_PROBE_TIMEOUT = 0.75
_SAMPLE_RATE = 16_000
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SHERPA_MODEL_PATH = _BACKEND_ROOT / ".cache" / "sherpa-onnx" / "sensevoice" / "model.int8.onnx"
_DEFAULT_SHERPA_TOKENS_PATH = _BACKEND_ROOT / ".cache" / "sherpa-onnx" / "sensevoice" / "tokens.txt"
_DEFAULT_SHERPA_ONLINE_MODEL_PATH = _BACKEND_ROOT / ".cache" / "sherpa-onnx" / "streaming-zipformer-small-ctc-zh" / "model.int8.onnx"
_DEFAULT_SHERPA_ONLINE_TOKENS_PATH = _BACKEND_ROOT / ".cache" / "sherpa-onnx" / "streaming-zipformer-small-ctc-zh" / "tokens.txt"


def _local_asr_startup_mode() -> str:
    """Return the local Sherpa startup policy without changing service providers."""
    mode = os.getenv("ASR_STARTUP_MODE", "lazy").strip().lower()
    if mode in {"blocking", "eager", "foreground", "sync"}:
        return "blocking"
    if mode in {"background", "warmup", "preload"}:
        return "background"
    return "lazy"


def _resolve_modelscope_cache() -> str:
    return os.environ.get(
        "MODELSCOPE_CACHE",
        str(Path(__file__).resolve().parents[2] / ".cache" / "modelscope"),
    )


class SenseVoiceClient:
    """SenseVoiceSmall ASR client.

    Provides:
      - connect() / disconnect() lifecycle
      - is_available property
      - transcribe(audio: np.ndarray) → text + language + emotion
      - Built-in VAD (fsmn-vad) for speech segmentation
    """

    def __init__(self, model: str = _SENSEVOICE_MODEL, device: str = "cpu") -> None:
        self._model_name = model
        self._device = device
        self._model: Any = None
        self._available = False
        self._cache_dir = _resolve_modelscope_cache()

    async def connect(self) -> None:
        """Load SenseVoiceSmall and its built-in VAD model.

        Models download to ``MODELSCOPE_CACHE`` (defaults to
        ``python/.cache/modelscope``) — stored locally inside the
        project; subsequent runs reuse the cached model.
        """
        try:
            from funasr import AutoModel  # type: ignore[import-untyped]

            cache = self._cache_dir
            os.makedirs(cache, exist_ok=True)
            os.environ.setdefault("MODELSCOPE_CACHE", cache)

            logger.info(
                "Loading SenseVoiceSmall model=%s device=%s cache=%s ...",
                self._model_name,
                self._device,
                cache,
            )
            self._model = await asyncio.to_thread(
                AutoModel,
                model=self._model_name,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self._device,
            )
            self._available = True
            logger.info("SenseVoiceSmall loaded successfully")

        except ImportError:
            self._available = False
            logger.warning("FunASR/SenseVoice dependencies not installed; ASR voice input disabled")
        except Exception as exc:
            self._available = False
            logger.error("SenseVoiceSmall init failed: %s", exc)

    async def disconnect(self) -> None:
        self._model = None
        self._available = False
        logger.info("SenseVoiceSmall disconnected")

    @property
    def is_available(self) -> bool:
        return self._available and self._model is not None

    async def transcribe(self, audio: np.ndarray) -> dict[str, object]:
        """Recognise speech from a 16 kHz mono float32 numpy array.

        Returns a dict with:

        .. code-block:: json

            {
              "status":    "ok" | "error",
              "text":      "<recognised text>",
              "language":  "zh" | "en" | "ja" | ...,
              "emotion":   "HAPPY" | "SAD" | "ANGRY" | "NEUTRAL" | "",
              "segments":  [ { "text", "language", "emotion", "timestamp" } ]
            }
        """
        if not self.is_available:
            return {"status": "error", "error": "SenseVoice not available"}

        if audio.size == 0:
            return {"status": "ok", "text": "", "language": "zh", "emotion": "", "segments": []}  # type: ignore[typeddict-item]

        try:
            t_start = time.perf_counter()
            result = await asyncio.to_thread(
                self._model.generate,  # type: ignore[union-attr]
                input=audio,
                language="auto",
                use_itn=True,
                batch_size_s=60,
            )
            elapsed_ms = int((time.perf_counter() - t_start) * 1000)

            if not result:
                return {"status": "ok", "text": "", "language": "zh", "emotion": "", "segments": []}  # type: ignore[typeddict-item]

            texts: list[str] = []
            segments: list[dict[str, object]] = []

            for item in result:
                raw_text: str = str(item.get("text", ""))
                lang: str = str(item.get("lang", "zh"))
                emotion: str = str(item.get("emo", ""))

                texts.append(raw_text)
                segments.append(
                    {
                        "text": raw_text,
                        "language": lang,
                        "emotion": emotion,
                        "timestamp": item.get("timestamp", []),
                    }
                )

            full_text = " ".join(t for t in texts if t)
            primary_lang: str = str(segments[0].get("language", "zh"))
            primary_emotion: str = str(segments[0].get("emotion", ""))

            logger.debug(
                "SenseVoice transcribe: %d ms, %d chars, lang=%s emo=%s",
                elapsed_ms,
                len(full_text),
                primary_lang,
                primary_emotion,
            )

            return {
                "status": "ok",
                "text": full_text,
                "language": primary_lang,
                "emotion": primary_emotion,
                "segments": segments,
            }

        except Exception as exc:
            logger.error("SenseVoice transcription error: %s", exc)
            return {"status": "error", "error": str(exc)}


def _audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(pcm16.tobytes())
    return buffer.getvalue()


def _resolve_backend_path(path: str, default: Path) -> Path:
    if not path:
        return default
    candidate = Path(path)
    return candidate if candidate.is_absolute() else _BACKEND_ROOT / candidate


def _is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip().lower()
    return host == "localhost" or host == "::1" or host.startswith("127.")


def _normalize_service_base_url(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return ""
    if "://" not in cleaned:
        cleaned = f"http://{cleaned}"
    return cleaned if cleaned.endswith("/v1") else f"{cleaned}/v1"


def _env_service_base_urls() -> list[str]:
    raw_values: list[str] = []
    for env_key in ("YUIZAKI_ASR_BASE_URL", "ASR_BASE_URL", "YUIZAKI_SENSEVOICE_BASE_URL"):
        raw_values.extend(value.strip() for value in os.getenv(env_key, "").split(",") if value.strip())
    return _unique_service_base_urls(raw_values)


def _unique_service_base_urls(raw_values: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        candidate = _normalize_service_base_url(raw_value)
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
    return candidates


def _candidate_service_base_urls() -> list[str]:
    raw_values: list[str] = []
    raw_values.extend(_env_service_base_urls())
    raw_values.extend([
        *_SENSEVOICE_SERVICE_DEFAULT_BASE_URLS,
    ])
    return _unique_service_base_urls(raw_values)


def _loopback_port_available(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not _is_loopback_host(host):
        return True
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=_SENSEVOICE_SERVICE_TCP_PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def resolve_sensevoice_service_base_url(configured_base_url: str = "") -> str:
    configured = _normalize_service_base_url(configured_base_url)
    if configured:
        return configured
    env_candidates = _env_service_base_urls()
    if env_candidates:
        return env_candidates[0]
    candidates = _candidate_service_base_urls()
    for candidate in candidates:
        if _loopback_port_available(candidate):
            logger.info("Auto-detected local SenseVoice service at %s", candidate)
            return candidate
    return ""


class SenseVoiceServiceClient:
    """OpenAI-compatible SenseVoice/FunASR HTTP client.

    The heavy FunASR, ModelScope, PyTorch, and CUDA stack lives in a separate
    service. This client keeps Yuizaki's default backend environment light.
    """

    def __init__(
        self,
        model: str = "sensevoice",
        base_url: str = "",
        api_key: str = "",
        timeout: float = 60.0,
    ) -> None:
        self._model_name = model or "sensevoice"
        self._base_url = resolve_sensevoice_service_base_url(base_url)
        self._api_key = api_key
        self._timeout = timeout
        self._model: Any = None
        self._available = False

    async def connect(self) -> None:
        self._model = self
        if not self._base_url:
            self._available = False
            logger.warning("SenseVoice service URL is empty; ASR disabled")
            return

        try:
            await asyncio.to_thread(self._probe_service)
        except ConnectionError as exc:
            self._model = None
            self._available = False
            logger.info("SenseVoice service unavailable at %s: %s", self._base_url, exc)
            return
        except Exception as exc:
            self._model = None
            self._available = False
            logger.warning("SenseVoice service unavailable at %s: %s", self._base_url, exc)
            return

        self._available = True
        logger.info("SenseVoice service configured endpoint=%s model=%s", self._transcription_url(), self._model_name)

    async def disconnect(self) -> None:
        self._model = None
        self._available = False
        logger.info("SenseVoice service disconnected")

    @property
    def is_available(self) -> bool:
        return self._available and self._model is self

    def generate(
        self,
        *,
        input: np.ndarray,
        language: str = "auto",
        use_itn: bool = True,
        batch_size_s: int = 60,
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        if not self.is_available:
            raise RuntimeError("SenseVoice service not configured")
        if input.size == 0:
            return []

        wav_bytes = _audio_to_wav_bytes(input)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        data: dict[str, object] = {
            "model": self._model_name,
            "response_format": "verbose_json",
            "language": language,
            "use_itn": str(bool(use_itn)).lower(),
            "batch_size_s": str(batch_size_s),
        }
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}

        with httpx.Client(timeout=self._timeout, trust_env=False) as client:
            response = client.post(self._transcription_url(), data=data, files=files, headers=headers)
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        segments = payload.get("segments")
        if isinstance(segments, list) and segments:
            normalized: list[dict[str, object]] = []
            for item in segments:
                if isinstance(item, dict):
                    normalized.append(
                        {
                            "text": str(item.get("text", "")),
                            "lang": str(item.get("language") or item.get("lang") or language or "auto"),
                            "emo": str(item.get("emotion") or item.get("emo") or ""),
                            "timestamp": [item.get("start"), item.get("end")] if "start" in item or "end" in item else item.get("timestamp", []),
                        }
                    )
            if normalized:
                return normalized

        text = str(payload.get("text", "")).strip()
        return [{
            "text": text,
            "lang": str(payload.get("language") or payload.get("lang") or language or "auto"),
            "emo": str(payload.get("emotion") or payload.get("emo") or ""),
            "timestamp": payload.get("timestamp", []),
        }] if text else []

    async def transcribe(self, audio: np.ndarray) -> dict[str, object]:
        try:
            result = await asyncio.to_thread(self.generate, input=audio, language="auto")
        except Exception as exc:
            logger.error("SenseVoice service transcription error: %s", exc)
            return {"status": "error", "error": str(exc)}
        if not result:
            return {"status": "ok", "text": "", "language": "auto", "emotion": "", "segments": []}
        text = " ".join(str(item.get("text", "")) for item in result if item.get("text")).strip()
        return {
            "status": "ok",
            "text": text,
            "language": str(result[0].get("lang", "auto")),
            "emotion": str(result[0].get("emo", "")),
            "segments": [
                {
                    "text": str(item.get("text", "")),
                    "language": str(item.get("lang", "auto")),
                    "emotion": str(item.get("emo", "")),
                    "timestamp": item.get("timestamp", []),
                }
                for item in result
            ],
        }

    def _transcription_url(self) -> str:
        base = self._base_url.rstrip("/")
        if base.endswith("/v1/audio/transcriptions") or base.endswith("/audio/transcriptions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/audio/transcriptions"
        return f"{base}/v1/audio/transcriptions"

    def _models_url(self) -> str:
        base = self._base_url.rstrip("/")
        for suffix in ("/v1/audio/transcriptions", "/audio/transcriptions"):
            if base.endswith(suffix):
                return f"{base[: -len(suffix)]}/v1/models"
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"

    def _probe_service(self) -> None:
        self._probe_loopback_port()
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        probe_timeout = min(max(self._timeout, 0.25), _SENSEVOICE_SERVICE_PROBE_TIMEOUT)
        with httpx.Client(timeout=probe_timeout, trust_env=False) as client:
            response = client.get(self._models_url(), headers=headers)
        if response.status_code in {401, 403} or response.status_code >= 500:
            response.raise_for_status()

    def _probe_loopback_port(self) -> None:
        parsed = urlparse(self._base_url)
        host = parsed.hostname
        if not _is_loopback_host(host):
            return
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=_SENSEVOICE_SERVICE_TCP_PROBE_TIMEOUT):
                return
        except OSError as exc:
            raise ConnectionError(f"local SenseVoice service is not listening on {host}:{port}") from exc


class SherpaOnnxOnlineClient:
    """Incremental sherpa-onnx Zipformer2 CTC recognizer with per-session streams."""

    supports_streaming = True

    def __init__(
        self,
        model_path: str = "",
        tokens_path: str = "",
        num_threads: int = 2,
        provider: str = "cpu",
        language: str = "auto",
    ) -> None:
        self._model_path = _resolve_backend_path(model_path, _DEFAULT_SHERPA_ONLINE_MODEL_PATH)
        self._tokens_path = _resolve_backend_path(tokens_path, _DEFAULT_SHERPA_ONLINE_TOKENS_PATH)
        self._num_threads = max(1, int(num_threads))
        self._provider = provider or "cpu"
        self._language = language or "auto"
        self._recognizer: Any = None
        self._streams: dict[str, Any] = {}
        self._available = False
        self._startup_mode = _local_asr_startup_mode()
        self._load_lock = threading.Lock()
        self._warmup_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        if not self._model_path.exists() or not self._tokens_path.exists():
            logger.warning(
                "sherpa-onnx online model files missing; ASR disabled (model=%s tokens=%s)",
                self._model_path,
                self._tokens_path,
            )
            return
        try:
            import sherpa_onnx  # type: ignore[import-untyped]
            del sherpa_onnx
            self._available = True
            if self._startup_mode == "blocking":
                await asyncio.to_thread(self._ensure_ready_sync)
            elif self._startup_mode == "background":
                self._warmup_task = asyncio.create_task(self._warmup(), name="sherpa-asr-warmup")
            logger.info(
                "sherpa-onnx online ASR registered model=%s tokens=%s provider=%s startup=%s",
                self._model_path,
                self._tokens_path,
                self._provider,
                self._startup_mode,
            )
        except ImportError:
            logger.warning("sherpa-onnx is not installed; online ASR disabled")
        except Exception as exc:
            self._recognizer = None
            logger.error(
                "sherpa-onnx online ASR init failed; use a Zipformer2 CTC streaming model, not SenseVoice: %s",
                exc,
            )

    async def disconnect(self) -> None:
        if self._warmup_task is not None and not self._warmup_task.done():
            self._warmup_task.cancel()
        self._warmup_task = None
        self._streams.clear()
        self._recognizer = None
        self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    async def _warmup(self) -> None:
        await asyncio.to_thread(self._ensure_ready_sync)

    async def _ensure_ready(self) -> None:
        if self._recognizer is not None:
            return
        task = self._warmup_task
        if task is not None and not task.done():
            await task
            return
        await asyncio.to_thread(self._ensure_ready_sync)

    def _ensure_ready_sync(self) -> bool:
        if self._recognizer is not None:
            return True
        with self._load_lock:
            if self._recognizer is not None:
                return True
            try:
                import sherpa_onnx  # type: ignore[import-untyped]

                self._recognizer = sherpa_onnx.OnlineRecognizer.from_zipformer2_ctc(
                    tokens=str(self._tokens_path),
                    model=str(self._model_path),
                    num_threads=self._num_threads,
                    provider=self._provider,
                    enable_endpoint_detection=False,
                )
                logger.info("sherpa-onnx online ASR model loaded on demand")
                return True
            except Exception as exc:
                self._available = False
                logger.error("sherpa-onnx online ASR init failed: %s", exc)
                return False

    async def start_stream(self, session_id: str, audio: np.ndarray) -> str:
        await self._ensure_ready()
        if self._recognizer is None:
            raise RuntimeError("sherpa-onnx online ASR not available")
        stream = self._recognizer.create_stream()
        self._streams[session_id] = stream
        return await asyncio.to_thread(self._feed_sync, stream, audio, False)

    async def feed_stream(self, session_id: str, audio: np.ndarray) -> str:
        stream = self._streams.get(session_id)
        if stream is None:
            return ""
        return await asyncio.to_thread(self._feed_sync, stream, audio, False)

    async def finish_stream(self, session_id: str) -> str:
        stream = self._streams.pop(session_id, None)
        if stream is None:
            return ""
        return await asyncio.to_thread(self._feed_sync, stream, np.empty(0, dtype=np.float32), True)

    def cancel_stream(self, session_id: str) -> None:
        self._streams.pop(session_id, None)

    def _feed_sync(self, stream: Any, audio: np.ndarray, finished: bool) -> str:
        recognizer = self._recognizer
        if recognizer is None:
            return ""
        if audio.size:
            stream.accept_waveform(_SAMPLE_RATE, audio.astype(np.float32, copy=False))
        if finished:
            stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        result = recognizer.get_result(stream)
        return str(getattr(result, "text", "") or "").strip()


class SherpaOnnxSenseVoiceClient:
    """Local SenseVoice ONNX client powered by sherpa-onnx.

    ``sherpa-onnx`` is light enough for the default environment, but the model
    files are still user-managed so the repository does not carry large weights.
    """

    def __init__(
        self,
        model_path: str = "",
        tokens_path: str = "",
        num_threads: int = 2,
        provider: str = "cpu",
        language: str = "auto",
        use_itn: bool = True,
    ) -> None:
        self._model_path = _resolve_backend_path(model_path, _DEFAULT_SHERPA_MODEL_PATH)
        self._tokens_path = _resolve_backend_path(tokens_path, _DEFAULT_SHERPA_TOKENS_PATH)
        self._num_threads = max(1, int(num_threads))
        self._provider = provider or "cpu"
        self._language = language or "auto"
        self._use_itn = use_itn
        self._recognizer: Any = None
        self._model: Any = None
        self._available = False
        self._startup_mode = _local_asr_startup_mode()
        self._load_lock = threading.Lock()
        self._warmup_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        if not self._model_path.exists() or not self._tokens_path.exists():
            self._available = False
            logger.warning(
                "sherpa-onnx SenseVoice model files missing; ASR disabled (model=%s tokens=%s)",
                self._model_path,
                self._tokens_path,
            )
            return

        try:
            import sherpa_onnx  # type: ignore[import-untyped]
            del sherpa_onnx
            self._model = self
            self._available = True
            if self._startup_mode == "blocking":
                await asyncio.to_thread(self._ensure_ready_sync)
            elif self._startup_mode == "background":
                self._warmup_task = asyncio.create_task(self._warmup(), name="sherpa-asr-warmup")
            logger.info(
                "sherpa-onnx SenseVoice registered model=%s tokens=%s provider=%s startup=%s",
                self._model_path,
                self._tokens_path,
                self._provider,
                self._startup_mode,
            )
        except ImportError:
            self._available = False
            logger.warning("sherpa-onnx is not installed; ASR disabled")
        except Exception as exc:
            self._available = False
            logger.error("sherpa-onnx SenseVoice init failed: %s", exc)

    async def disconnect(self) -> None:
        if self._warmup_task is not None and not self._warmup_task.done():
            self._warmup_task.cancel()
        self._warmup_task = None
        self._recognizer = None
        self._model = None
        self._available = False
        logger.info("sherpa-onnx SenseVoice disconnected")

    @property
    def is_available(self) -> bool:
        return self._available

    async def _warmup(self) -> None:
        await asyncio.to_thread(self._ensure_ready_sync)

    async def _ensure_ready(self) -> None:
        if self._recognizer is not None:
            return
        task = self._warmup_task
        if task is not None and not task.done():
            await task
            return
        await asyncio.to_thread(self._ensure_ready_sync)

    def _ensure_ready_sync(self) -> bool:
        if self._recognizer is not None:
            return True
        with self._load_lock:
            if self._recognizer is not None:
                return True
            try:
                import sherpa_onnx  # type: ignore[import-untyped]

                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(self._model_path),
                    tokens=str(self._tokens_path),
                    num_threads=self._num_threads,
                    provider=self._provider,
                    language=self._language,
                    use_itn=self._use_itn,
                )
                logger.info("sherpa-onnx SenseVoice model loaded on demand")
                return True
            except Exception as exc:
                self._available = False
                logger.error("sherpa-onnx SenseVoice init failed: %s", exc)
                return False

    def generate(
        self,
        *,
        input: np.ndarray,
        language: str = "auto",
        **_kwargs: object,
    ) -> list[dict[str, object]]:
        if self._recognizer is None:
            self._ensure_ready_sync()
        if not self.is_available:
            raise RuntimeError("sherpa-onnx SenseVoice not available")
        if input.size == 0:
            return []

        recognizer = self._recognizer
        if recognizer is None:
            self._available = False
            raise RuntimeError("sherpa-onnx SenseVoice recognizer is not initialized")

        stream = recognizer.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, input.astype(np.float32, copy=False))
        recognizer.decode_stream(stream)
        result = getattr(stream, "result", None)
        text = str(getattr(result, "text", "") or "").strip()
        if not text:
            return []
        return [{
            "text": text,
            "lang": language or self._language,
            "emo": "",
            "timestamp": getattr(result, "timestamps", []),
            "tokens": getattr(result, "tokens", []),
        }]

    async def transcribe(self, audio: np.ndarray) -> dict[str, object]:
        try:
            result = await asyncio.to_thread(self.generate, input=audio, language=self._language)
        except Exception as exc:
            logger.error("sherpa-onnx SenseVoice transcription error: %s", exc)
            return {"status": "error", "error": str(exc)}
        if not result:
            return {"status": "ok", "text": "", "language": self._language, "emotion": "", "segments": []}
        return {
            "status": "ok",
            "text": str(result[0].get("text", "")),
            "language": str(result[0].get("lang", self._language)),
            "emotion": "",
            "segments": [
                {
                    "text": str(item.get("text", "")),
                    "language": str(item.get("lang", self._language)),
                    "emotion": "",
                    "timestamp": item.get("timestamp", []),
                }
                for item in result
            ],
        }
