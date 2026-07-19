import asyncio
import sys
import time
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from modules.tts import TTSClient
from modules.tts.synthesizer import StreamingSentenceBuffer
from modules.core.state import Generation


class _FakeWebSocket:
    def __init__(self):
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def test_genie_tts_cold_status_does_not_claim_runtime_transport():
    client = TTSClient(genie_character="feibi")

    status = client.status_snapshot()

    assert status["available"] is False
    assert status["streaming_transport"] == "wav"
    assert status["capabilities"]["output_audio_streaming"] is False
    assert status["capabilities"]["output_transport"] == "unavailable"


@pytest.mark.asyncio
async def test_genie_tts_client_sets_reference_audio_and_split_option(monkeypatch, tmp_path):
    calls = []
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"RIFF....WAVE")

    def load_character(**kwargs):
        calls.append(("load_character", kwargs))

    def set_reference_audio(*args, **kwargs):
        calls.append(("set_reference_audio", args, kwargs))

    def tts(**kwargs):
        calls.append(("tts", kwargs))
        Path(kwargs["save_path"]).write_bytes(b"wav")

    fake_genie = SimpleNamespace(
        load_character=load_character,
        load_predefined_character=lambda character: calls.append(("load_predefined_character", character)),
        set_reference_audio=set_reference_audio,
        tts=tts,
    )
    monkeypatch.setitem(sys.modules, "genie_tts", fake_genie)

    client = TTSClient(
        genie_character="feibi",
        genie_model_dir="E:/Genie-TTS/Output/11111111111111111",
        language="ja",
        ref_audio=str(ref_audio),
        ref_text="もうこんなひどいことさせないからね",
        split="禁用",
        audio_cache_dir=tmp_path,
    )

    await client.connect()
    assert client.is_enabled is True

    result = await client.test_connection()

    assert result["ok"] is True
    assert calls[0] == (
        "load_character",
        {
            "character_name": "feibi",
            "onnx_model_dir": "E:/Genie-TTS/Output/11111111111111111",
            "language": "Japanese",
        },
    )
    assert calls[1] == (
        "set_reference_audio",
        ("feibi", str(ref_audio), "もうこんなひどいことさせないからね"),
        {"language": "Japanese"},
    )
    assert any(
        call[0] == "tts"
        and call[1]["split_sentence"] is False
        and call[1]["text"] == "テストです"
        and call[1]["language"] == "Japanese"
        for call in calls
    )


@pytest.mark.asyncio
async def test_genie_tts_client_background_warmup_can_be_awaited(monkeypatch, tmp_path):
    calls = []
    load_started = Event()

    def load_predefined_character(character: str):
        load_started.set()
        time.sleep(0.05)
        calls.append(("load_predefined_character", character))

    fake_genie = SimpleNamespace(
        load_predefined_character=load_predefined_character,
        tts=lambda **_kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "genie_tts", fake_genie)

    client = TTSClient(genie_character="feibi", audio_cache_dir=tmp_path)

    await client.connect(background=True)

    for _ in range(100):
        if load_started.is_set():
            break
        await asyncio.sleep(0.01)

    assert load_started.is_set()
    assert client.is_warming_up or client.is_enabled
    assert await client.ensure_ready() is True
    assert client.is_enabled is True
    assert calls == [("load_predefined_character", "feibi")]


@pytest.mark.asyncio
async def test_genie_tts_client_inference_warmup_records_status(monkeypatch, tmp_path):
    calls = []

    def load_predefined_character(character: str):
        calls.append(("load_predefined_character", character))

    def tts(**kwargs):
        calls.append(("tts", kwargs))
        Path(kwargs["save_path"]).write_bytes(b"wav")

    fake_genie = SimpleNamespace(
        load_predefined_character=load_predefined_character,
        tts=tts,
    )
    monkeypatch.setitem(sys.modules, "genie_tts", fake_genie)

    client = TTSClient(genie_character="feibi", language="en", audio_cache_dir=tmp_path)

    await client.connect()
    before = client.status_snapshot()

    assert before["available"] is True
    assert before["warmup_done"] is False

    assert await client.warmup() is True
    status = client.status_snapshot()

    assert status["available"] is True
    assert status["provider"] == "genie-tts"
    assert status["capabilities"] == {
        "provider": "genie-tts",
        "locality": "local",
        "input_text_streaming": False,
        "output_audio_streaming": False,
        "output_transport": "wav",
        "alignment": "none",
        "viseme_vocabulary": [],
        "warmup": True,
        "cancellation": "cooperative",
    }
    assert status["warmup_done"] is True
    assert status["last_load_ms"] is not None
    assert status["last_load_queue_ms"] is not None
    assert status["last_load_model_ms"] is not None
    assert status["last_load_ms"] >= status["last_load_model_ms"]
    assert status["load_latency_summary"]["total"]["samples"] >= 1
    assert status["load_latency_summary"]["total"]["p50_ms"] is not None
    assert status["load_latency_summary"]["total"]["p95_ms"] is not None
    assert status["last_warmup_ms"] is not None
    assert status["last_warmup_queue_ms"] is not None
    assert status["last_warmup_inference_ms"] is not None
    assert status["last_warmup_ms"] >= status["last_warmup_inference_ms"]
    assert status["warmup_latency_summary"]["total"]["samples"] >= 1
    assert status["warmup_latency_summary"]["queue"]["p50_ms"] is not None
    assert status["warmup_latency_summary"]["inference"]["p95_ms"] is not None
    assert status["last_error"] is None
    assert calls[-1][0] == "tts"
    assert calls[-1][1]["text"] == "test"


@pytest.mark.asyncio
async def test_genie_tts_warmups_are_serialized_across_clients(monkeypatch, tmp_path):
    state_lock = Lock()
    active_calls = 0
    max_active_calls = 0

    def begin_call() -> None:
        nonlocal active_calls, max_active_calls
        with state_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)

    def end_call() -> None:
        nonlocal active_calls
        with state_lock:
            active_calls -= 1

    def load_predefined_character(_character: str) -> None:
        begin_call()
        time.sleep(0.03)
        end_call()

    def tts(**kwargs):
        begin_call()
        time.sleep(0.03)
        Path(kwargs["save_path"]).write_bytes(b"wav")
        end_call()

    fake_genie = SimpleNamespace(
        load_predefined_character=load_predefined_character,
        clear_reference_audio_cache=lambda: None,
        tts=tts,
    )
    monkeypatch.setitem(sys.modules, "genie_tts", fake_genie)
    first = TTSClient(genie_character="feibi", audio_cache_dir=tmp_path)
    second = TTSClient(genie_character="feibi", audio_cache_dir=tmp_path)

    await asyncio.gather(first.connect(), second.connect())
    results = await asyncio.gather(first.warmup(), second.warmup())

    assert results == [True, True]
    assert max_active_calls == 1
    first_status = first.status_snapshot()
    second_status = second.status_snapshot()
    assert first_status["last_load_model_ms"] >= 20
    assert second_status["last_load_model_ms"] >= 20
    assert max(first_status["last_load_queue_ms"], second_status["last_load_queue_ms"]) >= 20
    load_summary = second_status["load_latency_summary"]
    assert load_summary["total"]["samples"] >= 2
    assert load_summary["queue"]["samples"] >= 2
    assert load_summary["model"]["samples"] >= 2
    assert load_summary["total"]["p50_ms"] is not None
    assert load_summary["total"]["p95_ms"] is not None
    assert first_status["last_warmup_inference_ms"] >= 20
    assert second_status["last_warmup_inference_ms"] >= 20
    assert max(first_status["last_warmup_queue_ms"], second_status["last_warmup_queue_ms"]) >= 20
    warmup_summary = second_status["warmup_latency_summary"]
    assert warmup_summary["total"]["samples"] >= 2
    assert warmup_summary["queue"]["samples"] >= 2
    assert warmup_summary["inference"]["samples"] >= 2


@pytest.mark.asyncio
async def test_genie_tts_warmup_rejects_swallowed_engine_failure(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=lambda **_kwargs: None,
    ))
    client = TTSClient(genie_character="feibi", audio_cache_dir=tmp_path)

    await client.connect()
    samples_before = client.status_snapshot()["warmup_latency_summary"]["total"]["samples"]

    assert await client.warmup() is False
    status = client.status_snapshot()
    assert status["warmup_done"] is False
    assert status["last_error"] == "Genie-TTS warmup failed: Genie-TTS produced no WAV audio"
    assert status["warmup_latency_summary"]["total"]["samples"] == samples_before


@pytest.mark.asyncio
async def test_genie_tts_emits_clean_sentence_segments_in_order(monkeypatch, tmp_path):
    calls = []

    def tts(**kwargs):
        calls.append(kwargs)
        Path(kwargs["save_path"]).write_bytes(b"wav")

    fake_genie = SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=tts,
    )
    monkeypatch.setitem(sys.modules, "genie_tts", fake_genie)

    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    generation = Generation(generation_id="gen-segments", session_id="session-1")
    first_sentence = "\u7b2c\u4e00\u53e5\u3002"
    second_sentence = "\u7b2c\u4e8c\u53e5\uff01"
    generation.tokens = [first_sentence + second_sentence]
    websocket = _FakeWebSocket()

    await client.synthesize(websocket, generation)

    assert [call["text"] for call in calls] == [first_sentence, second_sentence]
    assert all(call["split_sentence"] is False for call in calls)
    assert [message["sequence"] for message in websocket.messages] == [0, 1]
    assert [message["is_final"] for message in websocket.messages] == [False, True]
    assert websocket.messages[0]["audio_url"].endswith("gen-segments-000.wav")
    assert "tts_first_audio_ready" in websocket.messages[0]["latency"]["stages"]


def test_streaming_sentence_buffer_releases_only_complete_sentences():
    buffer = StreamingSentenceBuffer()

    assert buffer.feed("第一") == []
    assert buffer.feed("句。第二") == ["第一句。"]
    assert buffer.feed("句！尾巴") == ["第二句！"]
    assert buffer.flush() == ["尾巴"]


@pytest.mark.asyncio
async def test_genie_tts_stream_segment_emits_audio_then_completion(monkeypatch, tmp_path):
    calls = []

    def tts(**kwargs):
        calls.append(kwargs)
        Path(kwargs["save_path"]).write_bytes(b"wav")

    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=tts,
    ))
    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    generation = Generation(generation_id="gen-stream", session_id="session-1")
    websocket = _FakeWebSocket()
    ready_wait_samples_before = client.status_snapshot()["ready_wait_latency_summary"]["samples"]

    assert await client.synthesize_stream_segment(websocket, generation, "第一句。", 0) is True
    assert await client.synthesize_stream_segment(websocket, generation, "第二句。", 1) is True
    await client.complete_stream(websocket, generation, 2)

    assert calls[0]["text"] == "第一句。"
    assert calls[1]["text"] == "第二句。"
    assert websocket.messages[0]["type"] == "tts_audio"
    assert websocket.messages[0]["is_final"] is False
    assert websocket.messages[1]["type"] == "tts_audio"
    assert websocket.messages[2]["type"] == "tts_complete"
    assert websocket.messages[2]["is_final"] is True
    assert client.status_snapshot()["ready_wait_latency_summary"]["samples"] == ready_wait_samples_before + 1


@pytest.mark.asyncio
async def test_genie_tts_stream_segment_prefers_pcm_without_wav_io(monkeypatch, tmp_path):
    async def tts_async(**kwargs):
        assert kwargs["split_sentence"] is False
        assert kwargs["save_path"] is None
        yield b"\x00\x00" * 3200

    sync_tts = pytest.fail
    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=sync_tts,
        tts_async=tts_async,
    ))
    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    generation = Generation(generation_id="gen-pcm", session_id="session-1")
    websocket = _FakeWebSocket()

    assert await client.synthesize_stream_segment(websocket, generation, "第一句。", 0) is True

    assert list(tmp_path.iterdir()) == []
    assert len(websocket.messages) == 1
    message = websocket.messages[0]
    assert message["type"] == "tts_pcm"
    assert message["audio"] == b"\x00\x00" * 3200
    assert message["audio_format"] == "pcm_s16le"
    assert message["sample_rate"] == 32000
    assert message["channels"] == 1
    assert message["sample_width_bytes"] == 2
    assert message["duration_ms"] == 100.0
    assert message["sequence"] == 0
    assert message["chunk_index"] == 0
    assert message["text"] == "第一句。"
    assert "tts_ready_wait" in generation.timings_ms
    assert "tts_first_chunk" in generation.timings_ms
    assert client.status_snapshot()["streaming_transport"] == "pcm_s16le"
    assert client.status_snapshot()["capabilities"]["output_audio_streaming"] is True
    assert client.status_snapshot()["capabilities"]["output_transport"] == "pcm_s16le"
    assert client.status_snapshot()["ready_wait_latency_summary"]["samples"] >= 1
    assert client.status_snapshot()["ready_wait_latency_summary"]["p95_ms"] is not None
    assert client.status_snapshot()["generation_latency_summary"]["samples"] >= 1


@pytest.mark.asyncio
async def test_pcm_provider_chunk_can_include_normalized_viseme_timeline(monkeypatch, tmp_path):
    async def tts_async(**_kwargs):
        yield {
            "audio": b"\x00\x00" * 3200,
            "visemes": [
                {"viseme": "AA", "offset_ms": 0},
                {"viseme": "ih", "offset_ms": 45, "weight": 0.8},
            ],
        }

    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=pytest.fail,
        tts_async=tts_async,
    ))
    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    generation = Generation(generation_id="gen-viseme", session_id="session-1")
    websocket = _FakeWebSocket()

    assert await client.synthesize_stream_segment(websocket, generation, "hello", 0) is True
    assert websocket.messages[0]["visemes"] == [
        {"viseme": "aa", "offset_ms": 0.0},
        {"viseme": "ih", "offset_ms": 45.0, "weight": 0.8},
    ]
    capabilities = client.status_snapshot()["capabilities"]
    assert capabilities["alignment"] == "viseme"
    assert capabilities["viseme_vocabulary"] == ["aa", "ih"]


@pytest.mark.asyncio
async def test_genie_tts_empty_pcm_stream_is_reported_as_failure(monkeypatch, tmp_path):
    async def tts_async(**_kwargs):
        if False:
            yield b""

    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=pytest.fail,
        tts_async=tts_async,
    ))
    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    generation = Generation(generation_id="gen-empty-pcm", session_id="session-1")
    websocket = _FakeWebSocket()
    samples_before = client.status_snapshot()["generation_latency_summary"]["samples"]

    assert await client.synthesize_stream_segment(websocket, generation, "没有声音。", 0) is False

    status = client.status_snapshot()
    assert status["last_error"] == "TTS generation failed: Genie-TTS produced no PCM audio"
    assert status["generation_latency_summary"]["samples"] == samples_before
    assert websocket.messages[-1]["type"] == "error"


@pytest.mark.asyncio
async def test_genie_tts_cancel_stops_worker_before_next_inference(monkeypatch, tmp_path):
    first_started = Event()
    stop_started = Event()
    release_first = Event()
    second_started = Event()
    stop_calls: list[str] = []

    def tts(**kwargs):
        text = kwargs["text"]
        if text == "first":
            first_started.set()
            release_first.wait(timeout=2)
        else:
            second_started.set()
        Path(kwargs["save_path"]).write_bytes(b"wav")

    def stop():
        stop_calls.append("stop")
        stop_started.set()
        time.sleep(0.05)
        release_first.set()

    monkeypatch.setitem(sys.modules, "genie_tts", SimpleNamespace(
        load_predefined_character=lambda _character: None,
        tts=tts,
        stop=stop,
    ))
    client = TTSClient(genie_character="feibi", language="zh", audio_cache_dir=tmp_path)
    await client.connect()
    websocket = _FakeWebSocket()
    first_generation = Generation(generation_id="gen-cancelled", session_id="session-1")
    next_generation = Generation(generation_id="gen-next", session_id="session-1")

    first_task = asyncio.create_task(
        client.synthesize_stream_segment(websocket, first_generation, "first", 0)
    )
    assert await asyncio.to_thread(first_started.wait, 1)

    first_task.cancel()
    next_task = asyncio.create_task(
        client.synthesize_stream_segment(websocket, next_generation, "second", 0)
    )
    assert await asyncio.to_thread(stop_started.wait, 1)
    await asyncio.sleep(0.01)
    assert second_started.is_set() is False

    with pytest.raises(asyncio.CancelledError):
        await first_task
    assert await next_task is True

    status = client.status_snapshot()
    assert stop_calls == ["stop"]
    assert second_started.is_set() is True
    assert status["cancel_count"] == 1
    assert status["last_cancel_ms"] is not None
    assert status["cancel_latency_summary"]["samples"] >= 1
    assert status["cancel_latency_summary"]["p95_ms"] is not None
    assert "tts_cancel_requested" in first_generation.timings_ms
    assert "tts_cancelled" in first_generation.timings_ms
