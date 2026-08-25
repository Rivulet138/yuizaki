from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.core.config import AppConfig
from modules.system import runtime_services


def test_tts_defaults_to_lazy_without_warmup(monkeypatch):
    monkeypatch.delenv("TTS_STARTUP_MODE", raising=False)
    monkeypatch.delenv("TTS_WARMUP_ENABLED", raising=False)

    assert runtime_services._tts_startup_mode() == "lazy"
    assert runtime_services._tts_warmup_enabled() is False


def test_tts_startup_override_supports_explicit_background_warmup(monkeypatch):
    monkeypatch.setenv("TTS_STARTUP_MODE", "background")
    monkeypatch.setenv("TTS_WARMUP_ENABLED", "1")

    assert runtime_services._tts_startup_mode() == "background"
    assert runtime_services._tts_warmup_enabled() is True


@pytest.mark.asyncio
async def test_initialize_tts_has_no_default_connect_or_warmup_side_effect(monkeypatch):
    monkeypatch.delenv("TTS_STARTUP_MODE", raising=False)
    monkeypatch.delenv("TTS_WARMUP_ENABLED", raising=False)
    client = SimpleNamespace(
        connect=AsyncMock(),
        warmup=AsyncMock(),
        is_enabled=False,
        is_warming_up=False,
    )
    monkeypatch.setattr(runtime_services, "create_tts_client", lambda **_kwargs: client)

    result = await runtime_services.initialize_tts(AppConfig(), MagicMock())

    assert result is client
    client.connect.assert_not_awaited()
    client.warmup.assert_not_awaited()


@pytest.mark.asyncio
async def test_initialize_tts_injects_runtime_voice_diagnostics(monkeypatch):
    captured: dict[str, object] = {}
    client = SimpleNamespace(
        connect=AsyncMock(),
        warmup=AsyncMock(),
        is_enabled=False,
        is_warming_up=False,
    )

    def create_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr(runtime_services, "create_tts_client", create_client)

    result = await runtime_services.initialize_tts(AppConfig(), MagicMock())

    assert result is client
    assert captured["diagnostics"] is runtime_services.voice_diagnostics()


@pytest.mark.asyncio
async def test_initialize_llm_injects_runtime_voice_diagnostics(monkeypatch):
    captured: dict[str, object] = {}

    class FakeLLM:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def connect(self):
            return None

    monkeypatch.setattr(runtime_services, "LLMClient", FakeLLM)

    result = await runtime_services.initialize_llm(AppConfig(), MagicMock())

    assert isinstance(result, FakeLLM)
    assert captured["diagnostics"] is runtime_services.voice_diagnostics()
