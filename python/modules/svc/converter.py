"""SVC module: external voice-conversion service client."""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

from modules.core.paths import DEFAULT_AUDIO_CACHE_DIR

logger = logging.getLogger("yuizaki.svc")

DEFAULT_PROVIDER = "soulx-service"
SERVICE_PROVIDERS = {DEFAULT_PROVIDER}
DISABLED_PROVIDERS = {"disabled", "none", "off"}


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if not normalized:
        return DEFAULT_PROVIDER
    return normalized


class SVCClient:
    """Brokered SVC client for the external SoulX-Singer-SVC service."""

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        base_url: str = "",
        speaker_id: int = 0,
        pitch: int = 0,
        timeout: float = 120.0,
        audio_cache_dir: Path = DEFAULT_AUDIO_CACHE_DIR,
    ) -> None:
        self._provider = normalize_provider(provider)
        self._base_url = base_url.rstrip("/")
        self.speaker_id = speaker_id
        self.pitch = pitch
        self._timeout = timeout
        self.audio_cache_dir = audio_cache_dir
        self._available = False
        self._tasks: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        if self._provider in DISABLED_PROVIDERS:
            self._available = False
            logger.info("SVC disabled by provider=%s", self._provider)
            return

        if self._provider not in SERVICE_PROVIDERS:
            logger.warning("Unsupported SVC provider=%s; expected SoulX service provider", self._provider)
            self._available = False
            return

        self._available = bool(self._base_url)
        if self._available:
            logger.info("SVC service configured endpoint=%s provider=%s", self._service_convert_url(), self._provider)
        else:
            logger.warning("SVC service URL is empty; voice conversion disabled")

    async def disconnect(self) -> None:
        self._available = False
        self._tasks.clear()
        logger.info("SVC client disconnected")

    @property
    def is_available(self) -> bool:
        if self._provider in SERVICE_PROVIDERS:
            self._available = bool(self._base_url)
            return self._available and bool(self._base_url)
        return False

    async def convert(
        self,
        generation_id: str,
        audio_base64: str,
        speaker_id: int | None = None,
        pitch: int | None = None,
    ) -> dict[str, Any]:
        if not self.is_available:
            return {"status": "error", "error": f"SVC not available (provider={self._provider})"}

        try:
            audio_bytes = base64.b64decode(audio_base64)
        except Exception as exc:
            return {"status": "error", "error": f"Failed to decode audio: {exc}"}

        input_path = Path(tempfile.gettempdir()) / f"yuizaki_svc_in_{generation_id}.wav"
        input_path.write_bytes(audio_bytes)

        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.audio_cache_dir / f"{generation_id}_svc.wav"

        f0_pitch = pitch if pitch is not None else self.pitch
        target_speaker = speaker_id if speaker_id is not None else self.speaker_id
        logger.info("[%s] SVC convert start  pitch=%d", generation_id, f0_pitch)

        try:
            result = await asyncio.to_thread(
                self._convert_with_service,
                input_path,
                output_path,
                generation_id,
                target_speaker,
                f0_pitch,
            )
        finally:
            input_path.unlink(missing_ok=True)
        self._tasks[generation_id] = result
        return result

    def get_status(self, generation_id: str) -> dict[str, Any]:
        return self._tasks.get(generation_id, {"status": "unknown"})

    def _service_convert_url(self) -> str:
        base = self._base_url.rstrip("/")
        if base.endswith("/convert") or base.endswith("/svc/convert"):
            return base
        return f"{base}/convert"

    def _convert_with_service(
        self,
        input_path: Path,
        output_path: Path,
        generation_id: str,
        speaker_id: int,
        pitch: int,
    ) -> dict[str, Any]:
        data = {
            "generation_id": generation_id,
            "speaker_id": str(speaker_id),
            "pitch": str(pitch),
            "f0_shift": str(pitch),
        }
        with input_path.open("rb") as audio_file:
            files = {"file": (input_path.name, audio_file, "audio/wav")}
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(self._service_convert_url(), data=data, files=files)
                response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
            if not isinstance(payload, dict):
                return {"status": "error", "error": "SVC service returned invalid JSON"}
            if str(payload.get("status", "")).lower() in {"error", "failed"}:
                return {"status": "error", "error": str(payload.get("error") or payload.get("message") or "SVC service failed")}
            audio_base64 = payload.get("audio_base64")
            if isinstance(audio_base64, str) and audio_base64:
                output_path.write_bytes(base64.b64decode(audio_base64))
                return {"status": "done", "audio_url": f"/audio/{output_path.name}", "provider": self._provider}
            audio_url = payload.get("audio_url") or payload.get("url")
            if isinstance(audio_url, str) and audio_url:
                return {"status": "done", "audio_url": audio_url, "provider": self._provider}
            output_file = payload.get("output_path") or payload.get("file_path") or payload.get("path")
            if isinstance(output_file, str) and output_file:
                return {"status": "error", "error": "SVC service returned unsupported local file path"}
            return {"status": "error", "error": "SVC service did not return audio"}

        output_path.write_bytes(response.content)
        if not output_path.exists() or output_path.stat().st_size == 0:
            return {"status": "error", "error": "SVC service returned empty audio"}
        return {"status": "done", "audio_url": f"/audio/{output_path.name}", "provider": self._provider}
