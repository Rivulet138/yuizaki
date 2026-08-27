from __future__ import annotations

import asyncio
import base64
from typing import Any

from socket_events import AudioEvents, SystemEvents
from socket_handlers.audio import build_audio_chunk_handler


class _Sio:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object], str]] = []

    async def emit(self, event: str, payload: dict[str, object], *, to: str) -> None:
        self.events.append((event, payload, to))


class _Pipeline:
    def __init__(self) -> None:
        self.partial_prefetch: list[dict[str, object]] = []
        self.confirmed_prefetch: list[dict[str, object]] = []

    def schedule_retrieval_prefetch(self, **payload: object) -> None:
        self.partial_prefetch.append(payload)

    def schedule_speculative_context_prefetch(self, **payload: object) -> None:
        self.partial_prefetch.append({"speculative": True, **payload})

    def confirm_speculative_context_prefetch(self, **payload: object) -> None:
        self.confirmed_prefetch.append(payload)


class _Asr:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, bool]] = []

    async def handle_audio_chunk(self, websocket: Any, sid: str, _generation_mgr: Any, audio: bytes, *, is_final: bool) -> None:
        self.calls.append((sid, audio, is_final))
        await websocket.send_json({"type": "asr_partial", "text": "你好"})
        await websocket.send_json({"type": "asr_vad_start", "confirmed_ms": 96})
        await websocket.send_json({"type": "asr_speech_start", "confirmed_ms": 128})
        await websocket.send_json({"type": "asr_final", "text": "你好"})
        await websocket.send_json({"type": "latency", "asr_ms": 33})


def _handler(sio: _Sio, asr: _Asr, pipeline: _Pipeline, prepared: set[str], scheduled: list[bool]):
    return build_audio_chunk_handler(
        sio=sio,
        asr_manager_provider=lambda: asr,
        generation_manager_provider=lambda: object(),
        agent_pipeline_provider=lambda: pipeline,
        tool_registry_provider=lambda: "tools",
        active_workspace_id=lambda: "workspace",
        latest_visual_frame_for_sid=lambda _sid: {"frame_id": "frame-1"},
        voice_prepared_sessions=prepared,
        schedule_voice_turn_preparation=lambda: scheduled.append(True),
        emit_latency=lambda sid, payload: sio.emit(SystemEvents.LATENCY, dict(payload), to=sid),
    )


def test_audio_handler_preserves_asr_events_and_prefetch_identity() -> None:
    sio = _Sio()
    asr = _Asr()
    pipeline = _Pipeline()
    prepared: set[str] = set()
    scheduled: list[bool] = []
    handler = _handler(sio, asr, pipeline, prepared, scheduled)
    payload = base64.b64encode(b"pcm16").decode()

    asyncio.run(handler("sid-1", {
        "chunk": payload,
        "session_id": "session-1",
        "generation_id": "generation-1",
        "turn_id": "turn-1",
        "request_id": "request-1",
        "interruption_epoch": 2,
        "version": 1,
    }))

    assert asr.calls == [("sid-1", b"pcm16", False)]
    assert scheduled == [True]
    assert pipeline.partial_prefetch[0]["workspace_id"] == "workspace"
    assert pipeline.partial_prefetch[1]["visual_frame_id"] == "frame-1"
    assert pipeline.confirmed_prefetch[0]["final_query"] == "你好"
    assert [event[0] for event in sio.events] == [
        AudioEvents.ASR_PARTIAL,
        AudioEvents.ASR_VAD_START,
        AudioEvents.ASR_SPEECH_START,
        AudioEvents.ASR_FINAL,
        SystemEvents.LATENCY,
    ]
    assert sio.events[0][1]["request_id"] == "request-1"


def test_audio_handler_resets_prepared_session_on_final_and_drops_invalid_base64() -> None:
    sio = _Sio()
    asr = _Asr()
    pipeline = _Pipeline()
    prepared = {"sid-1"}
    scheduled: list[bool] = []
    handler = _handler(sio, asr, pipeline, prepared, scheduled)

    asyncio.run(handler("sid-1", {"chunk": "%%%", "is_final": True}))
    assert asr.calls == []
    assert "sid-1" not in prepared

    asyncio.run(handler("sid-1", {"chunk": base64.b64encode(b"x").decode(), "is_final": True}))
    assert asr.calls == [("sid-1", b"x", True)]
    assert "sid-1" not in prepared
