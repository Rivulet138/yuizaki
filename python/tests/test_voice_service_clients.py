import base64
import sys
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

import modules.asr.sensevoice as sensevoice_module
import modules.svc.converter as svc_module
from modules.asr.sensevoice import SenseVoiceServiceClient, SherpaOnnxOnlineClient, SherpaOnnxSenseVoiceClient
from modules.svc.converter import SVCClient


def test_sensevoice_service_url_uses_env_without_local_probe(monkeypatch):
    monkeypatch.setenv("ASR_BASE_URL", "http://asr.env")
    monkeypatch.setattr(sensevoice_module, "_loopback_port_available", lambda _base_url: False)

    assert sensevoice_module.resolve_sensevoice_service_base_url("") == "http://asr.env/v1"


def test_sensevoice_service_url_stays_empty_when_auto_detection_fails(monkeypatch):
    for env_key in ("YUIZAKI_ASR_BASE_URL", "ASR_BASE_URL", "YUIZAKI_SENSEVOICE_BASE_URL"):
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setattr(sensevoice_module, "_loopback_port_available", lambda _base_url: False)

    assert sensevoice_module.resolve_sensevoice_service_base_url("") == ""


@pytest.mark.asyncio
async def test_sensevoice_service_client_uses_openai_transcription_endpoint(monkeypatch):
    captured: dict[str, str] = {}
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        if str(request.url).endswith("/v1/models"):
            return httpx.Response(200, json={"data": [{"id": "iic/SenseVoiceSmall"}]})
        return httpx.Response(
            200,
            json={
                "text": "你好",
                "language": "zh",
                "segments": [{"text": "你好", "language": "zh", "start": 0.0, "end": 0.4}],
            },
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        sensevoice_module.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )

    client = SenseVoiceServiceClient(
        model="iic/SenseVoiceSmall",
        base_url="http://asr.local/v1",
        api_key="secret",
    )
    await client.connect()

    result = client.generate(input=np.ones(1600, dtype=np.float32) * 0.1, language="zh")

    assert captured["url"] == "http://asr.local/v1/audio/transcriptions"
    assert captured["authorization"] == "Bearer secret"
    assert result == [{"text": "你好", "lang": "zh", "emo": "", "timestamp": [0.0, 0.4]}]


@pytest.mark.asyncio
async def test_sensevoice_service_client_marks_unavailable_when_endpoint_cannot_be_reached(monkeypatch):
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        sensevoice_module.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )

    client = SenseVoiceServiceClient(base_url="http://asr.local/v1")
    await client.connect()

    assert client.is_available is False


@pytest.mark.asyncio
async def test_sensevoice_service_client_skips_http_probe_when_loopback_port_is_closed(monkeypatch):
    def fail_http_client(**_kwargs):
        pytest.fail("HTTP probe should be skipped when the local TCP port is closed")

    def fail_connect(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(sensevoice_module.httpx, "Client", fail_http_client)
    monkeypatch.setattr(sensevoice_module.socket, "create_connection", fail_connect)

    client = SenseVoiceServiceClient(base_url="http://127.0.0.1:8899/v1")
    await client.connect()

    assert client.is_available is False


@pytest.mark.asyncio
async def test_sherpa_onnx_sensevoice_client_transcribes_with_local_recognizer(monkeypatch, tmp_path):
    model_path = tmp_path / "model.int8.onnx"
    tokens_path = tmp_path / "tokens.txt"
    model_path.write_bytes(b"onnx")
    tokens_path.write_text("tokens", encoding="utf-8")
    captured: dict[str, object] = {}

    class _FakeStream:
        result = SimpleNamespace(text="本地识别", timestamps=[0.0, 0.5], tokens=["本地", "识别"])

        def accept_waveform(self, sample_rate: int, audio: np.ndarray) -> None:
            captured["sample_rate"] = sample_rate
            captured["audio_size"] = int(audio.size)

    class _FakeRecognizer:
        @classmethod
        def from_sense_voice(cls, **kwargs):
            captured.update(kwargs)
            return cls()

        def create_stream(self):
            return _FakeStream()

        def decode_stream(self, stream: _FakeStream) -> None:
            captured["decoded"] = stream is not None

    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(OfflineRecognizer=_FakeRecognizer))

    client = SherpaOnnxSenseVoiceClient(
        model_path=str(model_path),
        tokens_path=str(tokens_path),
        num_threads=3,
        provider="cpu",
        language="zh",
    )
    await client.connect()

    result = client.generate(input=np.ones(1600, dtype=np.float32), language="zh")

    assert captured["model"] == str(model_path)
    assert captured["tokens"] == str(tokens_path)
    assert captured["num_threads"] == 3
    assert captured["sample_rate"] == 16000
    assert captured["audio_size"] == 1600
    assert captured["decoded"] is True
    assert result == [{
        "text": "本地识别",
        "lang": "zh",
        "emo": "",
        "timestamp": [0.0, 0.5],
        "tokens": ["本地", "识别"],
    }]


@pytest.mark.asyncio
async def test_sherpa_onnx_online_client_uses_zipformer2_stream(monkeypatch, tmp_path):
    model_path = tmp_path / "model.int8.onnx"
    tokens_path = tmp_path / "tokens.txt"
    model_path.write_bytes(b"online-onnx")
    tokens_path.write_text("tokens", encoding="utf-8")
    captured: dict[str, object] = {}

    class _FakeStream:
        def accept_waveform(self, sample_rate: int, audio: np.ndarray) -> None:
            captured["sample_rate"] = sample_rate
            captured["audio_size"] = int(audio.size)

        def input_finished(self) -> None:
            captured["finished"] = True

    class _FakeOnlineRecognizer:
        @classmethod
        def from_zipformer2_ctc(cls, **kwargs):
            captured.update(kwargs)
            return cls()

        def create_stream(self):
            return _FakeStream()

        def is_ready(self, _stream: _FakeStream) -> bool:
            return not bool(captured.get("decoded"))

        def decode_stream(self, _stream: _FakeStream) -> None:
            captured["decoded"] = True

        def get_result(self, _stream: _FakeStream):
            return SimpleNamespace(text="实时识别")

    monkeypatch.setitem(sys.modules, "sherpa_onnx", SimpleNamespace(OnlineRecognizer=_FakeOnlineRecognizer))
    client = SherpaOnnxOnlineClient(
        model_path=str(model_path),
        tokens_path=str(tokens_path),
        num_threads=3,
        provider="cpu",
    )

    await client.connect()
    partial = await client.start_stream("voice-1", np.ones(1600, dtype=np.float32))
    final = await client.finish_stream("voice-1")

    assert captured["model"] == str(model_path)
    assert captured["tokens"] == str(tokens_path)
    assert captured["num_threads"] == 3
    assert captured["sample_rate"] == 16000
    assert captured["audio_size"] == 1600
    assert captured["finished"] is True
    assert partial == "实时识别"
    assert final == "实时识别"


def test_sherpa_online_default_does_not_reuse_sensevoice_assets():
    client = SherpaOnnxOnlineClient()

    assert "streaming-zipformer-small-ctc-zh" in str(client._model_path)
    assert "sensevoice" not in str(client._model_path).lower()


@pytest.mark.asyncio
async def test_external_svc_service_client_writes_base64_audio_result(monkeypatch, tmp_path):
    real_client = httpx.Client
    output_audio = b"converted wav bytes"
    captured: dict[str, str | bytes] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(
            200,
            json={"status": "done", "audio_base64": base64.b64encode(output_audio).decode("ascii")},
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        svc_module.httpx,
        "Client",
        lambda **kwargs: real_client(transport=transport, timeout=kwargs.get("timeout")),
    )
    client = SVCClient(
        provider="soulx-service",
        base_url="http://svc.local",
        audio_cache_dir=tmp_path,
    )
    await client.connect()

    result = await client.convert("svc_test", base64.b64encode(b"input wav bytes").decode("ascii"), speaker_id=7, pitch=2)

    assert captured["url"] == "http://svc.local/convert"
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"name=\"generation_id\"" in body
    assert b"svc_test" in body
    assert b"name=\"speaker_id\"" in body
    assert b"7" in body
    assert b"name=\"pitch\"" in body
    assert b"name=\"f0_shift\"" in body
    assert b"2" in body
    assert b"name=\"file\"" in body
    assert result == {"status": "done", "audio_url": "/audio/svc_test_svc.wav", "provider": "soulx-service"}
    assert (tmp_path / "svc_test_svc.wav").read_bytes() == output_audio
