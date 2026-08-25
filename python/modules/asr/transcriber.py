"""
ASR (Automatic Speech Recognition) module.
Handles per-session VAD segmentation and configured SenseVoice-style transcription.
"""

import asyncio
import logging
from typing import Any

import numpy as np

from ..core.state import ASRPipeline, Generation, GenerationManager
from ..system.voice_diagnostics import VoiceDiagnostics

logger = logging.getLogger("yuizaki.asr")


async def _safe_send(ws: Any, gen: Generation, msg: dict) -> None:
    """Send message to WebSocket, respecting cancellation."""
    if gen.invalidated or gen.cancel.is_set():
        return
    try:
        await ws.send_json(msg)
    except (ConnectionError, OSError, RuntimeError) as e:
        logger.warning("Failed to send WS message: %s", e)


class ASRManager:
    """Manages ASR pipeline per session with transcription handling."""

    def __init__(
        self,
        sensevoice_client: Any,
        vad_threshold: float = 0.5,
        vad_min_silence_ms: int = 300,
        asr_partial_every: int = 15,
        language: str = "zh",
        diagnostics: VoiceDiagnostics | None = None,
    ):
        self.sensevoice_client = sensevoice_client
        self.vad_threshold = vad_threshold
        self.vad_min_silence_ms = vad_min_silence_ms
        self.asr_partial_every = asr_partial_every
        self.language = language
        self.diagnostics = diagnostics or VoiceDiagnostics()
        self._pipelines: dict[str, ASRPipeline] = {}
        self._partial_tasks: dict[str, asyncio.Task[None]] = {}
        self._streaming_partials: dict[str, str] = {}

    @property
    def is_available(self) -> bool:
        return bool(getattr(self.sensevoice_client, "is_available", True))

    def _transcription_engine(self) -> Any:
        if bool(getattr(self.sensevoice_client, "supports_streaming", False)):
            return self.sensevoice_client
        model = getattr(self.sensevoice_client, "_model", None)
        if model is not None and hasattr(model, "generate"):
            return model
        if hasattr(self.sensevoice_client, "generate"):
            return self.sensevoice_client
        raise RuntimeError("ASR client must expose a generate-capable transcription engine")

    def get_or_create(self, session_id: str) -> ASRPipeline:
        if session_id not in self._pipelines:
            self._pipelines[session_id] = ASRPipeline(
                self._transcription_engine(),
                vad_threshold=self.vad_threshold,
                vad_min_silence_ms=self.vad_min_silence_ms,
                asr_partial_every=self.asr_partial_every,
            )
        return self._pipelines[session_id]

    def cleanup(self, session_id: str) -> None:
        """Clean up ASR pipeline for session."""
        task = self._partial_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
        cancel_stream = getattr(self.sensevoice_client, "cancel_stream", None)
        if callable(cancel_stream):
            cancel_stream(session_id)
        self._streaming_partials.pop(session_id, None)
        if session_id in self._pipelines:
            self._pipelines[session_id].reset()
            del self._pipelines[session_id]

    async def handle_audio_chunk(
        self,
        ws: Any,
        session_id: str,
        mgr: GenerationManager,
        pcm16_bytes: bytes,
        is_final: bool = False,
    ) -> None:
        """
        Process audio chunk through VAD and optionally trigger transcription.
        """
        asr = self.get_or_create(session_id)
        event = asr.feed_chunk(pcm16_bytes)
        if bool(getattr(self.sensevoice_client, "supports_streaming", False)):
            await self._handle_streaming_chunk(ws, session_id, mgr, asr, pcm16_bytes, event, is_final)
            return

        if event == "vad_start":
            logger.debug("[%s] VAD: speech started", session_id)
            await _safe_send(ws, Generation(
                generation_id="vad",
                session_id=session_id,
            ), {
                "type": "asr_vad_start",
                "session_id": session_id,
                "confirmed_ms": asr.start_confirmation_ms,
            })

        elif event == "speech_start":
            await _safe_send(ws, Generation(
                generation_id="speech",
                session_id=session_id,
            ), {
                "type": "asr_speech_start",
                "session_id": session_id,
                "confirmed_ms": asr.real_start_confirmation_ms,
            })

        elif event == "vad_end":
            logger.debug("[%s] VAD: speech ended", session_id)
            self._cancel_partial(session_id)
            audio = asr.snapshot_audio()
            if audio is not None:
                await self._transcribe(ws, session_id, mgr, asr, audio, is_final=True)

        elif event == "partial":
            audio = asr.snapshot_audio()
            existing = self._partial_tasks.get(session_id)
            if audio is not None and (existing is None or existing.done()):
                task = asyncio.create_task(
                    self._transcribe(ws, session_id, mgr, asr, audio, is_final=False),
                    name=f"asr-partial-{session_id}",
                )
                self._partial_tasks[session_id] = task
                asr.transcribe_task = task
                task.add_done_callback(lambda completed, key=session_id: self._partial_done(key, completed))

        if is_final:
            self._cancel_partial(session_id)
            audio = asr.snapshot_audio()
            if audio is not None:
                await self._transcribe(ws, session_id, mgr, asr, audio, is_final=True)

    def _cancel_partial(self, session_id: str) -> None:
        task = self._partial_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _partial_done(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._partial_tasks.get(session_id) is task:
            self._partial_tasks.pop(session_id, None)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            logger.error("[%s] background partial transcription failed: %s", session_id, error)

    async def _handle_streaming_chunk(
        self,
        ws: Any,
        session_id: str,
        mgr: GenerationManager,
        asr: ASRPipeline,
        pcm16_bytes: bytes,
        event: str | None,
        is_final: bool,
    ) -> None:
        client = self.sensevoice_client
        text = ""
        final_started_at = asyncio.get_running_loop().time() if event == "vad_end" or is_final else None
        if event == "vad_start":
            await _safe_send(ws, Generation(generation_id="vad", session_id=session_id), {
                "type": "asr_vad_start",
                "session_id": session_id,
                "confirmed_ms": asr.start_confirmation_ms,
            })
            initial_audio = asr.snapshot_audio()
            if initial_audio is not None:
                text = await client.start_stream(session_id, initial_audio)
        elif asr.is_speaking or event == "vad_end":
            chunk = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            text = await client.feed_stream(session_id, chunk)

        if event == "speech_start":
            await _safe_send(ws, Generation(generation_id="speech", session_id=session_id), {
                "type": "asr_speech_start",
                "session_id": session_id,
                "confirmed_ms": asr.real_start_confirmation_ms,
            })

        if event == "vad_end" or is_final:
            final_text = (await client.finish_stream(session_id)).strip() or text.strip() or self._streaming_partials.get(session_id, "")
            if final_started_at is not None:
                self.diagnostics.record_elapsed(
                    "asr_final",
                    final_started_at,
                    ok=bool(final_text),
                    error_kind=None if final_text else "empty_result",
                )
            if final_text:
                asr.mark("asr_final")
                mgr.append_history(session_id, "user", final_text)
                await _safe_send(ws, Generation(generation_id="asr", session_id=session_id), {
                    "type": "asr_final",
                    "session_id": session_id,
                    "text": final_text,
                })
                await _safe_send(ws, Generation(generation_id="asr-latency", session_id=session_id), {
                    "type": "latency",
                    "session_id": session_id,
                    **asr.latency_snapshot(),
                })
            self._streaming_partials.pop(session_id, None)
            asr.reset()
            return

        clean_text = text.strip()
        if clean_text and clean_text != self._streaming_partials.get(session_id):
            self._streaming_partials[session_id] = clean_text
            await _safe_send(ws, Generation(generation_id="asr", session_id=session_id), {
                "type": "asr_partial",
                "session_id": session_id,
                "text": clean_text,
            })

    async def _transcribe(
        self,
        ws: Any,
        session_id: str,
        mgr: GenerationManager,
        asr: ASRPipeline,
        audio: np.ndarray,
        is_final: bool = False,
    ) -> None:
        """Run the configured ASR transcription backend in a thread pool."""
        beam = 5 if is_final else 1
        started_at = asyncio.get_running_loop().time()
        asr.mark("asr_started" if is_final else "asr_partial_started")
        try:
            text = await asyncio.to_thread(
                asr.transcribe_sync,
                audio,
                beam,
                self.language,
            )
        except asyncio.CancelledError:
            self.diagnostics.record_elapsed("asr_final" if is_final else "asr", started_at, ok=False, error_kind="cancelled")
            return

        if not text:
            self.diagnostics.record_elapsed("asr_final" if is_final else "asr", started_at, ok=False, error_kind="empty_result")
            if is_final:
                asr.reset()
            return

        if is_final:
            asr.mark("asr_final")
        self.diagnostics.record_elapsed("asr_final" if is_final else "asr", started_at)

        msg_type = "asr_final" if is_final else "asr_partial"
        logger.debug("[%s] ASR %s: %s", session_id, msg_type, text)

        # Append to history if final
        if is_final:
            mgr.append_history(session_id, "user", text)

        await _safe_send(ws, Generation(
            generation_id="asr",
            session_id=session_id,
        ), {
            "type": msg_type,
            "session_id": session_id,
            "text": text,
        })
        if is_final:
            await _safe_send(ws, Generation(
                generation_id="asr-latency",
                session_id=session_id,
            ), {
                "type": "latency",
                "session_id": session_id,
                **asr.latency_snapshot(),
            })
            asr.reset()
