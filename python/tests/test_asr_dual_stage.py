from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from modules.asr.transcriber import ASRManager


class _StreamingClient:
    supports_streaming = True
    is_available = True

    def __init__(self, final_text: str = "streaming draft") -> None:
        self.final_text = final_text

    async def feed_stream(self, _session_id: str, _audio: np.ndarray) -> str:
        return self.final_text

    async def finish_stream(self, _session_id: str) -> str:
        return self.final_text


class _FinalModel:
    def generate(self, **_kwargs: object) -> list[dict[str, str]]:
        return [{"text": "sensevoice final"}]


class _FinalClient:
    is_available = True

    def __init__(self) -> None:
        self._model = _FinalModel()


class _Pipeline:
    is_speaking = False

    def __init__(self, refined_text: str) -> None:
        self.refined_text = refined_text
        self.reset_called = False

    def snapshot_audio(self) -> np.ndarray:
        return np.ones(3200, dtype=np.float32)

    def transcribe_sync(self, *_args: object) -> str:
        return self.refined_text

    def mark(self, _stage: str) -> None:
        return None

    def latency_snapshot(self) -> dict[str, Any]:
        return {"kind": "asr", "stages": {}, "total_ms": 0.0}

    def reset(self) -> None:
        self.reset_called = True


class _WebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


class _GenerationManager:
    def __init__(self) -> None:
        self.history: list[tuple[str, str, str]] = []

    def append_history(self, session_id: str, role: str, content: str) -> None:
        self.history.append((session_id, role, content))


def test_streaming_manager_uses_dedicated_final_engine() -> None:
    final_client = _FinalClient()
    manager = ASRManager(_StreamingClient(), final_client=final_client)

    pipeline = manager.get_or_create("session")

    assert pipeline._sv is final_client._model


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("refined_text", "expected_text"),
    [
        ("sensevoice final", "sensevoice final"),
        ("", "streaming draft"),
    ],
)
async def test_streaming_final_prefers_sensevoice_and_falls_back(
    refined_text: str,
    expected_text: str,
) -> None:
    manager = ASRManager(_StreamingClient(), final_client=_FinalClient())
    pipeline = _Pipeline(refined_text)
    websocket = _WebSocket()
    generations = _GenerationManager()

    await manager._handle_streaming_chunk(
        websocket,
        "session",
        generations,
        pipeline,
        b"",
        "vad_end",
        False,
    )

    assert generations.history == [("session", "user", expected_text)]
    assert any(
        message.get("type") == "asr_final" and message.get("text") == expected_text
        for message in websocket.messages
    )
    assert pipeline.reset_called is True
