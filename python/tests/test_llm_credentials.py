from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from modules.llm.client import fetch_available_models
from modules.llm.providers import (
    LlmCredentialError,
    build_llm_auth_headers,
    validate_llm_api_key,
)
from modules.system.dynamic_config import DynamicConfigManager
from modules.system.settings_api import SettingsAPI, reload_provider_credentials
from modules.system.settings_store import PROVIDER_CREDENTIALS_ENV, SettingsStore


class _ReloadRequest:
    def __init__(self, payload, token: str | None = None) -> None:
        self._payload = payload
        self.headers = {"x-yuizaki-backend-token": token} if token is not None else {}

    async def json(self):
        return self._payload


class _ReloadAPI:
    def __init__(self, store: SettingsStore) -> None:
        self.settings_store = store

    async def reload_provider_credentials(self, credentials):
        return self.settings_store.reload_provider_credentials(credentials)


def test_settings_store_reloads_provider_credentials_without_persisting_plaintext(monkeypatch) -> None:
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        settings_path = Path(temp_dir) / "settings.json"
        settings_path.write_text(json.dumps({"llm": {"provider": "custom", "model": "test"}}), encoding="utf-8")
        monkeypatch.setenv(PROVIDER_CREDENTIALS_ENV, json.dumps({"llm.api_key": "sk-persisted"}))

        store = SettingsStore(settings_path)
        assert store.get("llm.api_key") == "sk-persisted"
        store.save()

        persisted = json.loads(settings_path.read_text(encoding="utf-8"))
        assert persisted["llm"]["api_key"] == ""
        assert SettingsStore(settings_path).get("llm.api_key") == "sk-persisted"


def test_provider_credential_environment_ignores_non_credential_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        PROVIDER_CREDENTIALS_ENV,
        json.dumps({"llm.api_key": "sk-valid", "llm.model": "attacker-model", "system.api_key": "ignored"}),
    )

    store = SettingsStore(tmp_path / "settings.json")

    assert store.get("llm.api_key") == "sk-valid"
    assert store.get("llm.model") is None
    assert store.get("system.api_key") is None


def test_authenticated_reload_replaces_secrets_in_memory_only(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    store = SettingsStore(settings_path)
    assert store.reload_provider_credentials({"llm.api_key": "sk-live", "tts.api_key": "tts-live"}) == 2
    assert store.get("llm.api_key") == "sk-live"
    assert store.get("tts.api_key") == "tts-live"
    assert not settings_path.exists()
    assert store.reload_provider_credentials({"llm.api_key": "sk-next"}) == 2
    assert store.get("llm.api_key") == "sk-next"
    assert store.get("tts.api_key") == ""


def test_authenticated_reload_rejects_unknown_or_non_string_fields(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(ValueError, match="unsupported"):
        store.reload_provider_credentials({"llm.model": "bad"})
    with pytest.raises(ValueError, match="strings"):
        store.reload_provider_credentials({"llm.api_key": 123})  # type: ignore[arg-type]


def test_validate_llm_api_key_accepts_ascii_keys() -> None:
    assert validate_llm_api_key("  sk-test-123  ") == "sk-test-123"


def test_validate_llm_api_key_allows_empty_credentials() -> None:
    assert validate_llm_api_key("") == ""
    assert validate_llm_api_key("   ") == ""


def test_validate_llm_api_key_rejects_non_ascii_credentials() -> None:
    with pytest.raises(LlmCredentialError) as excinfo:
        validate_llm_api_key("密钥-abc")

    assert isinstance(excinfo.value, ValueError)
    assert "non-ASCII" in str(excinfo.value)


def test_validate_llm_api_key_rejects_control_characters() -> None:
    with pytest.raises(LlmCredentialError):
        validate_llm_api_key("sk-abc\ndef")


def test_build_llm_auth_headers_reports_a_readable_credential_error() -> None:
    with pytest.raises(LlmCredentialError) as excinfo:
        build_llm_auth_headers("密钥", "deepseek")

    message = str(excinfo.value)
    assert "ascii' codec" not in message
    assert "API key" in message


def test_build_llm_auth_headers_formats_each_provider() -> None:
    assert build_llm_auth_headers("sk-1", "deepseek") == {"Authorization": "Bearer sk-1"}
    assert build_llm_auth_headers("", "deepseek") == {}
    assert build_llm_auth_headers("g-1", "gemini") == {"x-goog-api-key": "g-1"}
    assert build_llm_auth_headers("", "gemini") == {}
    assert build_llm_auth_headers("c-1", "claude") == {
        "anthropic-version": "2023-06-01",
        "x-api-key": "c-1",
    }


@pytest.mark.asyncio
async def test_fetch_available_models_rejects_a_non_ascii_key_before_any_request() -> None:
    with pytest.raises(LlmCredentialError):
        await fetch_available_models("https://api.deepseek.com/v1", "密钥", 5.0, "deepseek")


@pytest.mark.asyncio
async def test_reload_provider_credentials_requires_token_and_allowlists_fields(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("YUIZAKI_BACKEND_API_TOKEN", "backend-secret")
    store = SettingsStore(tmp_path / "settings.json")
    with pytest.raises(HTTPException) as missing:
        await reload_provider_credentials(_ReloadRequest({"credentials": {}}), _ReloadAPI(store))
    assert missing.value.status_code == 401

    response = await reload_provider_credentials(
        _ReloadRequest({"credentials": {"llm.api_key": "sk-runtime"}}, "backend-secret"),
        _ReloadAPI(store),
    )
    assert response == {"ok": True, "changed": 1}
    assert store.get("llm.api_key") == "sk-runtime"

    with pytest.raises(HTTPException) as rejected:
        await reload_provider_credentials(
            _ReloadRequest({"credentials": {"llm.model": "must-reject"}}, "backend-secret"),
            _ReloadAPI(store),
        )
    assert rejected.value.status_code == 400


@pytest.mark.asyncio
async def test_settings_api_refreshes_runtime_sections_after_vault_sync(tmp_path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    refreshed: list[set[str]] = []

    async def reload_runtime(sections: set[str]) -> None:
        refreshed.append(sections)

    api = SettingsAPI(
        store,
        DynamicConfigManager(),
        reload_runtime_services=reload_runtime,
    )
    assert await api.reload_provider_credentials({"llm.api_key": "sk-runtime"}) == 1
    assert refreshed == [{"llm"}]
