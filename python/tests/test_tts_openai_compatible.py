from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import httpx
import pytest

from modules.tts.openai_compatible import (
    OpenAICompatibleTTSClient,
    normalize_speech_endpoint,
)


class FakeGeneration:
    session_id = "session"
    generation_id = "generation"
    full_text = "hello"
    invalidated = False
    cancel = asyncio.Event()

    def __init__(self) -> None:
        self.marks: list[str] = []

    def mark(self, value: str) -> None:
        self.marks.append(value)


class FakeSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)


def test_normalize_speech_endpoint_supports_root_v1_and_full_endpoint():
    assert normalize_speech_endpoint("http://localhost:8000") == "http://localhost:8000/v1/audio/speech"
    assert normalize_speech_endpoint("http://localhost:8000/v1") == "http://localhost:8000/v1/audio/speech"
    assert normalize_speech_endpoint("http://localhost:8000/v1/audio/speech") == "http://localhost:8000/v1/audio/speech"


def _wav_fixture() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 1_600)
    return output.getvalue()


@pytest.mark.asyncio
async def test_openai_compatible_stream_segment_writes_wav_and_preserves_generation_identity(tmp_path: Path):
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append({"url": str(request.url), **(request.read() and {})})
        return httpx.Response(200, content=_wav_fixture())

    client = OpenAICompatibleTTSClient(
        base_url="http://localhost:8000/v1",
        model="local-tts",
        voice="companion",
        audio_cache_dir=tmp_path,
        transport=httpx.MockTransport(handler),
    )
    await client.connect()
    generation = FakeGeneration()
    socket = FakeSocket()

    assert await client.synthesize_stream_segment(socket, generation, "hello", 0) is True
    assert requests and requests[0]["url"] == "http://localhost:8000/v1/audio/speech"
    assert (tmp_path / "generation-stream-000.wav").read_bytes() == _wav_fixture()
    assert socket.messages[0]["generation_id"] == "generation"
    assert socket.messages[0]["duration_ms"] == 100.0
    assert "tts_first_audio_ready" in generation.marks

    await client.disconnect()


@pytest.mark.asyncio
async def test_openai_compatible_cancellation_stops_inflight_request(tmp_path: Path):
    request_started = asyncio.Event()
    request_cancelled = asyncio.Event()

    async def slow_handler(_request: httpx.Request) -> httpx.Response:
        request_started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            request_cancelled.set()
            raise
        return httpx.Response(200, content=b"late")

    client = OpenAICompatibleTTSClient(
        base_url="http://localhost:8000/v1",
        audio_cache_dir=tmp_path,
        transport=httpx.MockTransport(slow_handler),
    )
    await client.connect()
    generation = FakeGeneration()
    socket = FakeSocket()
    task = asyncio.create_task(client.synthesize_stream_segment(socket, generation, "hello", 0))
    await request_started.wait()
    generation.invalidated = True
    await client.disconnect()
    assert await task is False
    assert request_cancelled.is_set()
    assert client.status_snapshot()["cancel_count"] >= 1
    assert client.diagnostics.snapshot()["stages"]["interruption"]["recovery_successes"] >= 1
    assert not socket.messages
