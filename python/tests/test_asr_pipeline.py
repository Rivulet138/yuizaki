import numpy as np
import pytest

from modules.asr.transcriber import ASRManager
from modules.core.state import ASRPipeline


class _FakeSenseVoiceModel:
    def generate(self, **_kwargs):
        return [{"text": "你好"}]


class _FakeSenseVoiceClient:
    _model = _FakeSenseVoiceModel()


class _FakeSenseVoiceServiceClient:
    def generate(self, **_kwargs):
        return [{"text": "service transcript"}]


class _FakeStreamingClient:
    supports_streaming = True
    is_available = True

    def __init__(self):
        self.feed_count = 0

    async def start_stream(self, _session_id, _audio):
        return "你"

    async def feed_stream(self, _session_id, _audio):
        self.feed_count += 1
        return "你好"

    async def finish_stream(self, _session_id):
        return "你好"

    def cancel_stream(self, _session_id):
        return None


class _FakeGenerationManager:
    def __init__(self):
        self.history: list[tuple[str, str, str]] = []

    def append_history(self, session_id: str, role: str, text: str) -> None:
        self.history.append((session_id, role, text))


class _FakeWebSocket:
    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.messages.append(msg)


def _confirm_speech(pipeline: ASRPipeline, speech: bytes) -> str | None:
    assert pipeline.feed_chunk(speech) is None
    assert pipeline.feed_chunk(speech) is None
    return pipeline.feed_chunk(speech)


def test_asr_pipeline_ignores_empty_final_chunks_without_nan_state():
    pipeline = ASRPipeline(_FakeSenseVoiceModel())

    assert pipeline.feed_chunk(b"") is None
    assert pipeline.snapshot_audio() is None
    assert pipeline.is_speaking is False


def test_asr_pipeline_uses_configured_vad_threshold_and_keeps_first_speech_chunk():
    quiet_speech = (np.ones(512, dtype=np.float32) * 0.004).astype(np.float32)
    pcm16 = (quiet_speech * 32767).astype(np.int16).tobytes()

    strict_pipeline = ASRPipeline(_FakeSenseVoiceModel(), vad_threshold=0.8)
    assert strict_pipeline.feed_chunk(pcm16) is None
    assert strict_pipeline.snapshot_audio() is None

    sensitive_pipeline = ASRPipeline(_FakeSenseVoiceModel(), vad_threshold=0.3)
    assert _confirm_speech(sensitive_pipeline, pcm16) == "vad_start"
    snapshot = sensitive_pipeline.snapshot_audio()

    assert snapshot is not None
    assert snapshot.shape[0] == 1536
    assert sensitive_pipeline.is_speaking is True
    assert sensitive_pipeline.start_confirmation_ms == 96
    assert sensitive_pipeline.real_start_confirmation_ms == 192
    assert "vad_start_confirmed" in sensitive_pipeline.latency_snapshot()["stages"]

    assert sensitive_pipeline.feed_chunk(pcm16) is None
    assert sensitive_pipeline.feed_chunk(pcm16) is None
    assert sensitive_pipeline.feed_chunk(pcm16) == "speech_start"
    assert "speech_start_confirmed" in sensitive_pipeline.latency_snapshot()["stages"]


def test_asr_pipeline_rejects_transient_noise_before_confirming_speech():
    pipeline = ASRPipeline(_FakeSenseVoiceModel())
    speech = (np.ones(512, dtype=np.float32) * 0.08 * 32767).astype(np.int16).tobytes()
    silence = np.zeros(512, dtype=np.int16).tobytes()

    assert pipeline.feed_chunk(speech) is None
    assert pipeline.feed_chunk(silence) is None
    assert pipeline.feed_chunk(speech) is None
    assert pipeline.feed_chunk(speech) is None
    assert pipeline.is_speaking is False
    assert pipeline.feed_chunk(speech) == "vad_start"

    snapshot = pipeline.snapshot_audio()
    assert snapshot is not None
    assert snapshot.shape[0] == 2560


def test_asr_manager_accepts_service_client_without_private_model():
    manager = ASRManager(_FakeSenseVoiceServiceClient())
    pipeline = manager.get_or_create("session-service")

    text = pipeline.transcribe_sync(np.ones(1600, dtype=np.float32) * 0.1)

    assert text == "service transcript"


def test_asr_pipeline_shortens_endpoint_after_a_stable_utterance():
    pipeline = ASRPipeline(_FakeSenseVoiceModel(), vad_min_silence_ms=500)
    speech = (np.ones(512, dtype=np.float32) * 0.08 * 32767).astype(np.int16).tobytes()
    silence = np.zeros(512, dtype=np.int16).tobytes()

    assert _confirm_speech(pipeline, speech) == "vad_start"
    for _ in range(29):
        pipeline.feed_chunk(speech)

    event = None
    silence_chunks = 0
    while event is None and silence_chunks < 16:
        event = pipeline.feed_chunk(silence)
        silence_chunks += 1

    assert event == "vad_end"
    assert silence_chunks == 9
    snapshot = pipeline.latency_snapshot()
    assert snapshot["endpoint_silence_ms"] == 288
    assert "endpoint_detected" in snapshot["stages"]
    assert snapshot["stages"]["speech_end"] < snapshot["stages"]["endpoint_detected"]


def test_asr_pipeline_learns_recovered_pauses_before_closing_the_turn():
    pipeline = ASRPipeline(_FakeSenseVoiceModel(), vad_min_silence_ms=600)
    speech = (np.ones(512, dtype=np.float32) * 0.08 * 32767).astype(np.int16).tobytes()
    silence = np.zeros(512, dtype=np.int16).tobytes()

    assert _confirm_speech(pipeline, speech) == "vad_start"
    for _ in range(10):
        assert pipeline.feed_chunk(silence) != "vad_end"
    pipeline.feed_chunk(speech)
    for _ in range(65):
        pipeline.feed_chunk(speech)

    snapshot = pipeline.latency_snapshot()
    assert snapshot["observed_pause_ms"] == 320.0
    assert snapshot["endpoint_silence_ms"] == 416

    event = None
    silence_chunks = 0
    while event is None and silence_chunks < 20:
        event = pipeline.feed_chunk(silence)
        silence_chunks += 1

    assert event == "vad_end"
    assert silence_chunks == 13


def test_asr_pipeline_reduces_full_buffer_partial_retries_for_long_utterances():
    pipeline = ASRPipeline(_FakeSenseVoiceModel(), asr_partial_every=5)
    speech = (np.ones(512, dtype=np.float32) * 0.08 * 32767).astype(np.int16).tobytes()

    assert _confirm_speech(pipeline, speech) == "vad_start"
    partials = [pipeline.feed_chunk(speech) for _ in range(100)].count("partial")

    assert 8 <= partials < 20


@pytest.mark.asyncio
async def test_asr_manager_resets_buffer_after_final_transcript():
    manager = ASRManager(_FakeSenseVoiceClient())
    pipeline = ASRPipeline(_FakeSenseVoiceModel())
    pipeline.is_speaking = True
    pipeline._buffer = [np.ones(1600, dtype=np.float32) * 0.1]
    generation_manager = _FakeGenerationManager()
    websocket = _FakeWebSocket()

    await manager._transcribe(
        websocket,
        "session-1",
        generation_manager,  # type: ignore[arg-type]
        pipeline,
        np.ones(1600, dtype=np.float32) * 0.1,
        is_final=True,
    )

    assert websocket.messages[0] == {
        "type": "asr_final",
        "session_id": "session-1",
        "text": "你好",
    }
    assert websocket.messages[1]["type"] == "latency"
    assert websocket.messages[1]["kind"] == "asr"
    assert websocket.messages[1]["session_id"] == "session-1"
    assert generation_manager.history == [("session-1", "user", "你好")]
    assert pipeline.snapshot_audio() is None
    assert pipeline.is_speaking is False


@pytest.mark.asyncio
async def test_asr_manager_uses_persistent_online_stream_without_full_buffer_retranscription():
    client = _FakeStreamingClient()
    manager = ASRManager(client, vad_min_silence_ms=160)
    generation_manager = _FakeGenerationManager()
    websocket = _FakeWebSocket()
    speech = (np.ones(512, dtype=np.float32) * 0.08 * 32767).astype(np.int16).tobytes()
    silence = np.zeros(512, dtype=np.int16).tobytes()

    for _ in range(6):
        await manager.handle_audio_chunk(websocket, "session-stream", generation_manager, speech)
    for _ in range(5):
        await manager.handle_audio_chunk(websocket, "session-stream", generation_manager, silence)

    message_types = [message["type"] for message in websocket.messages]
    vad_message = next(message for message in websocket.messages if message["type"] == "asr_vad_start")
    speech_message = next(message for message in websocket.messages if message["type"] == "asr_speech_start")
    assert vad_message["confirmed_ms"] == 96
    assert speech_message["confirmed_ms"] == 192
    assert message_types.count("asr_partial") >= 1
    assert message_types.count("asr_final") == 1
    assert client.feed_count >= 1
    assert generation_manager.history == [("session-stream", "user", "你好")]
