from __future__ import annotations

import json
import logging

import httpx
import pytest

from modules.core.state import Generation, GenerationManager
from modules.llm.client import LLMClient
from modules.system.dynamic_config import DynamicConfigManager
from modules.system.settings_api import SettingsAPI
from modules.system.settings_store import SettingsStore


SECRET = "cust-k7"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "request", "value"])
async def test_model_discovery_redacts_errors_before_truncation(monkeypatch, tmp_path, failure):
    api = SettingsAPI(SettingsStore(tmp_path / "settings.json"), DynamicConfigManager())

    async def fail(*args):
        detail = "upstream echoed " + SECRET + " " + "x" * 300
        if failure == "request":
            raise httpx.ConnectError(detail)
        if failure == "value":
            raise ValueError(detail)
        request = httpx.Request("GET", "https://example.test/v1/models", headers={"Authorization": f"Bearer {SECRET}"})
        httpx.Response(401, text=detail, request=request).raise_for_status()

    monkeypatch.setattr("modules.system.settings_api.fetch_available_models", fail)
    result = await api.list_llm_models({
        "provider": "custom", "base_url": "https://example.test/v1", "api_key": SECRET,
    })
    assert result["ok"] is False
    assert SECRET not in result["message"]
    assert "<redacted>" in result["message"]
    assert "upstream echoed" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["custom", "claude", "gemini"])
@pytest.mark.parametrize("failure", ["http", "request"])
async def test_stream_errors_do_not_expose_provider_secret(provider, failure, caplog):
    client = LLMClient("https://example.test/v1", SECRET, "test-model", provider=provider)
    sent = []

    class Socket:
        async def send_json(self, message):
            sent.append(message)

    def fail(request):
        detail = f"upstream echoed {SECRET}"
        if failure == "request":
            raise httpx.ConnectError(detail, request=request)
        return httpx.Response(401, text=detail)

    with caplog.at_level(logging.DEBUG, logger="yuizaki.llm"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
            client._http = http
            await client.stream_chat(
                Socket(), Generation("generation", "session"), GenerationManager(),
                [{"role": "user", "content": "hello"}],
            )
    assert len(sent) == 1
    assert sent[0]["type"] == "error"
    assert SECRET not in json.dumps(sent)
    assert SECRET not in caplog.text
    assert "<redacted>" in sent[0]["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "request"])
async def test_connection_redacts_errors_in_result_and_logs(failure, caplog):
    client = LLMClient("https://example.test/v1", SECRET, "test-model")

    def fail(request):
        detail = f"upstream echoed {SECRET}"
        if failure == "request":
            raise httpx.ConnectError(detail, request=request)
        return httpx.Response(401, text=detail)

    with caplog.at_level(logging.DEBUG, logger="yuizaki.llm"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
            client._http = http
            result = await client.test_connection()
    assert result["ok"] is False
    assert SECRET not in result["message"]
    assert SECRET not in caplog.text
    assert "<redacted>" in result["message"]


@pytest.mark.asyncio
async def test_preconnect_diagnostics_redact_provider_secret(caplog):
    client = LLMClient("https://example.test/v1", SECRET, "test-model")

    def fail(request):
        raise httpx.ConnectError(f"upstream echoed {SECRET}", request=request)

    with caplog.at_level(logging.DEBUG, logger="yuizaki.llm"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
            client._http = http
            assert await client.preconnect() is False
    snapshot = client.status_snapshot()
    assert SECRET not in json.dumps(snapshot)
    assert SECRET not in caplog.text
    assert "<redacted>" in snapshot["last_preconnect_error"]
