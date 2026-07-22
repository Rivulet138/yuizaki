from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from modules.asr.sensevoice import SherpaOnnxOnlineClient, SherpaOnnxSenseVoiceClient


class _FakeStream:
    def __init__(self, text: str = "测试") -> None:
        self.result = types.SimpleNamespace(text=text, timestamps=[], tokens=[])

    def accept_waveform(self, _sample_rate: int, _audio: np.ndarray) -> None:
        return None

    def input_finished(self) -> None:
        return None


class _FakeOnlineRecognizer:
    calls = 0

    @classmethod
    def from_zipformer2_ctc(cls, **_kwargs: object) -> "_FakeOnlineRecognizer":
        cls.calls += 1
        return cls()

    def create_stream(self) -> _FakeStream:
        return _FakeStream()

    def is_ready(self, _stream: _FakeStream) -> bool:
        return False

    def decode_stream(self, _stream: _FakeStream) -> None:
        return None

    def get_result(self, stream: _FakeStream) -> object:
        return stream.result


class _FakeOfflineRecognizer:
    calls = 0

    @classmethod
    def from_sense_voice(cls, **_kwargs: object) -> "_FakeOfflineRecognizer":
        cls.calls += 1
        return cls()

    def create_stream(self) -> _FakeStream:
        return _FakeStream("离线测试")

    def decode_stream(self, _stream: _FakeStream) -> None:
        return None


@pytest.fixture
def fake_sherpa(monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    _FakeOnlineRecognizer.calls = 0
    _FakeOfflineRecognizer.calls = 0
    module = types.SimpleNamespace(
        OnlineRecognizer=_FakeOnlineRecognizer,
        OfflineRecognizer=_FakeOfflineRecognizer,
    )
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    monkeypatch.delenv("ASR_STARTUP_MODE", raising=False)
    return module


@pytest.mark.asyncio
async def test_online_sherpa_defers_model_build_until_first_stream(tmp_path, fake_sherpa):
    model = tmp_path / "model.onnx"
    tokens = tmp_path / "tokens.txt"
    model.write_bytes(b"model")
    tokens.write_text("tokens", encoding="utf-8")

    client = SherpaOnnxOnlineClient(str(model), str(tokens))
    await client.connect()

    assert client.is_available is True
    assert _FakeOnlineRecognizer.calls == 0

    await client.start_stream("session", np.zeros(160, dtype=np.float32))
    assert _FakeOnlineRecognizer.calls == 1


def test_offline_sherpa_defers_model_build_until_first_transcription(tmp_path, fake_sherpa):
    model = tmp_path / "model.onnx"
    tokens = tmp_path / "tokens.txt"
    model.write_bytes(b"model")
    tokens.write_text("tokens", encoding="utf-8")

    client = SherpaOnnxSenseVoiceClient(str(model), str(tokens))
    import asyncio

    asyncio.run(client.connect())
    assert client.is_available is True
    assert _FakeOfflineRecognizer.calls == 0

    result = client.generate(input=np.ones(160, dtype=np.float32))
    assert result[0]["text"] == "离线测试"
    assert _FakeOfflineRecognizer.calls == 1
