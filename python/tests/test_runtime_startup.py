from __future__ import annotations

from modules.system import runtime_services


def test_tts_defaults_to_background_warmup(monkeypatch):
    monkeypatch.delenv("TTS_STARTUP_MODE", raising=False)
    monkeypatch.delenv("TTS_WARMUP_ENABLED", raising=False)

    assert runtime_services._tts_startup_mode() == "background"
    assert runtime_services._tts_warmup_enabled() is True


def test_tts_startup_override_supports_explicit_lazy_mode(monkeypatch):
    monkeypatch.setenv("TTS_STARTUP_MODE", "lazy")
    monkeypatch.setenv("TTS_WARMUP_ENABLED", "0")

    assert runtime_services._tts_startup_mode() == "lazy"
    assert runtime_services._tts_warmup_enabled() is False
