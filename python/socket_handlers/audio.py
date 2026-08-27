"""Socket.IO audio ingestion handler.

Only the ASR adapter and a few pipeline callbacks are injected. This keeps
audio framing, prefetch side effects and ASR event projection testable without
coupling the handler to the full SocketServer object.
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from socket_events import AudioEvents

JsonDict = dict[str, object]
EmitLatency = Callable[[str, Mapping[str, object]], Awaitable[None]]


def _as_text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_int(value: object, default: int = 0) -> int:
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_audio_chunk_handler(
    *,
    sio: Any,
    asr_manager_provider: Callable[[], Any],
    generation_manager_provider: Callable[[], Any],
    agent_pipeline_provider: Callable[[], Any],
    tool_registry_provider: Callable[[], Any],
    active_workspace_id: Callable[[], str],
    latest_visual_frame_for_sid: Callable[[str], JsonDict | None],
    voice_prepared_sessions: set[str],
    schedule_voice_turn_preparation: Callable[[], None],
    emit_latency: EmitLatency,
    logger: logging.Logger | None = None,
) -> Callable[[str, JsonDict], Awaitable[None]]:
    log = logger or logging.getLogger("socket-server.audio")

    async def on_audio_chunk(sid: str, data: JsonDict) -> None:
        chunk_b64 = _as_text(data.get("chunk"))
        is_final = bool(data.get("is_final", False))
        log.debug("[SIO] audio:chunk from %s, len=%d, final=%s", sid, len(chunk_b64), is_final)

        asr_manager = asr_manager_provider()
        generation_mgr = generation_manager_provider()
        if asr_manager is None or generation_mgr is None:
            log.debug("[SIO] ASR or generation manager not initialized, dropping audio chunk")
            return

        if is_final:
            voice_prepared_sessions.discard(sid)

        try:
            pcm16_bytes = base64.b64decode(chunk_b64, validate=True) if chunk_b64 else b""
        except (ValueError, TypeError, binascii.Error) as exc:
            log.warning("[SIO] failed to decode audio chunk: %s", exc)
            return

        if not is_final and pcm16_bytes and sid not in voice_prepared_sessions:
            voice_prepared_sessions.add(sid)
            schedule_voice_turn_preparation()

        session_id = _as_text(data.get("session_id"), sid)
        asr_identity = {
            "session_id": session_id,
            "generation_id": _as_text(data.get("generation_id")),
            "turn_id": _as_text(data.get("turn_id")),
            "request_id": _as_text(data.get("request_id")),
            "interruption_epoch": _as_int(data.get("interruption_epoch"), 0),
            "version": _as_int(data.get("version"), 1),
        }

        pipeline = agent_pipeline_provider()

        class _SocketIOWSAdapter:
            def __init__(self, client_sid: str) -> None:
                self._sid = client_sid

            async def send_json(self, msg: JsonDict) -> None:
                msg_type = msg.get("type")
                if msg_type == "asr_partial":
                    partial_text = _as_text(msg.get("text"))
                    await sio.emit(AudioEvents.ASR_PARTIAL, {
                        "text": partial_text,
                        "confidence": 0.0,
                        "lang": "zh",
                        **asr_identity,
                    }, to=self._sid)
                    pipeline.schedule_retrieval_prefetch(
                        cache_key=self._sid,
                        query=partial_text,
                        session_id=self._sid,
                        workspace_id=active_workspace_id(),
                    )
                    schedule_speculative = getattr(pipeline, "schedule_speculative_context_prefetch", None)
                    if callable(schedule_speculative):
                        latest_frame = latest_visual_frame_for_sid(self._sid)
                        schedule_speculative(
                            cache_key=self._sid,
                            query=partial_text,
                            workspace_id=active_workspace_id(),
                            tool_registry=tool_registry_provider(),
                            visual_frame_id=_as_text(latest_frame.get("frame_id")) if latest_frame else None,
                        )
                elif msg_type == "asr_final":
                    final_text = _as_text(msg.get("text"))
                    confirm_speculative = getattr(pipeline, "confirm_speculative_context_prefetch", None)
                    if callable(confirm_speculative):
                        confirm_speculative(
                            cache_key=self._sid,
                            final_query=final_text,
                            workspace_id=active_workspace_id(),
                            tool_registry=tool_registry_provider(),
                        )
                    await sio.emit(AudioEvents.ASR_FINAL, {
                        "text": final_text,
                        "confidence": 0.0,
                        "lang": "zh",
                        **asr_identity,
                    }, to=self._sid)
                elif msg_type == "asr_vad_start":
                    await sio.emit(AudioEvents.ASR_VAD_START, {
                        "session_id": _as_text(msg.get("session_id"), self._sid),
                        "confirmed_ms": _as_int(msg.get("confirmed_ms"), 0),
                    }, to=self._sid)
                elif msg_type == "asr_speech_start":
                    await sio.emit(AudioEvents.ASR_SPEECH_START, {
                        "session_id": _as_text(msg.get("session_id"), self._sid),
                        "confirmed_ms": _as_int(msg.get("confirmed_ms"), 0),
                    }, to=self._sid)
                elif msg_type == "latency":
                    await emit_latency(self._sid, {
                        key: value for key, value in msg.items() if key != "type"
                    })
                else:
                    log.debug("[SIO] unhandled ASR message: %s", msg_type)

        await asr_manager.handle_audio_chunk(
            _SocketIOWSAdapter(sid),
            sid,
            generation_mgr,
            pcm16_bytes,
            is_final=is_final,
        )

    return on_audio_chunk


__all__ = ["build_audio_chunk_handler"]
