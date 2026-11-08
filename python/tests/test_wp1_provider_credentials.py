from __future__ import annotations

from types import SimpleNamespace

import pytest
from modules.core.config import AppConfig
from modules.llm.client import redact_error_text
from modules.system import settings_schema
from modules.system.dynamic_config import DynamicConfigManager
from modules.system.runtime_config import apply_runtime_config
from modules.system.settings_api import SettingsAPI
from modules.system.settings_history_store import SettingsHistoryStore
from modules.system.settings_store import PROVIDER_CREDENTIALS_ENV, SettingsStore


def _llm_config() -> SimpleNamespace:
    return SimpleNamespace(
        provider="custom",
        base_url="https://old.example/v1",
        api_key="short-old-key",
        model="model",
        timeout=30.0,
        context_max_tokens=100,
        default_max_output_tokens=100,
        temperature=0.7,
        top_p=1.0,
        top_k=0,
        min_p=0.0,
        frequency_penalty=0.0,
        presence_penalty=0.0,
        repetition_penalty=1.0,
        vision_enabled=False,
        vision_provider="custom",
        vision_base_url="https://vision-old.example/v1",
        vision_api_key="vision-old-key",
        vision_model="vision",
        vision_timeout=30.0,
        vision_detail="auto",
    )


def _settings_api(tmp_path) -> tuple[SettingsAPI, SettingsStore]:
    store = SettingsStore(tmp_path / "settings.json")
    store.replace(
        {
            "llm": {
                "provider": "custom",
                "base_url": "https://old.example/v1",
                "api_key": "old-main-key",
                "vision_provider": "custom",
                "vision_base_url": "https://vision-old.example/v1",
                "vision_api_key": "old-vision-key",
            }
        }
    )
    api = SettingsAPI(
        store,
        DynamicConfigManager(),
        settings_history_store=SettingsHistoryStore(tmp_path / "settings-history.json"),
    )
    return api, store


def test_runtime_connection_change_clears_old_llm_key_but_same_connection_placeholders_keep_it() -> None:
    config = SimpleNamespace(llm=_llm_config())

    apply_runtime_config(config, {"llm": {"base_url": "https://new.example/v1"}})
    assert config.llm.base_url == "https://new.example/v1"
    assert config.llm.api_key == ""

    config.llm.api_key = "short-old-key"
    apply_runtime_config(config, {"llm": {"base_url": "https://new.example/v1", "api_key": "********"}})
    assert config.llm.api_key == "short-old-key"
    apply_runtime_config(config, {"llm": {"api_key": ""}})
    assert config.llm.api_key == "short-old-key"


def test_runtime_explicit_custom_is_preserved_when_switching_endpoint() -> None:
    config = SimpleNamespace(llm=_llm_config())
    apply_runtime_config(config, {"llm": {"provider": "custom", "base_url": "https://gateway.example/v1"}})
    assert config.llm.provider == "custom"
    assert config.llm.api_key == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connection_patch", "credential_key"),
    [
        ({"provider": "chatgpt"}, "api_key"),
        ({"base_url": "https://new.example/v1"}, "api_key"),
        ({"vision_provider": "chatgpt"}, "vision_api_key"),
        ({"vision_base_url": "https://vision-new.example/v1"}, "vision_api_key"),
    ],
)
async def test_settings_api_connection_switch_clears_old_credential(
    tmp_path, connection_patch: dict[str, str], credential_key: str
) -> None:
    api, store = _settings_api(tmp_path)
    payload = {"llm": connection_patch}

    await api.update_settings(payload)

    assert store.get(f"llm.{credential_key}") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_key", ["api_key", "vision_api_key"])
@pytest.mark.parametrize("placeholder", ["", "********"])
async def test_settings_api_same_connection_placeholders_preserve_credential(
    tmp_path, credential_key: str, placeholder: str
) -> None:
    api, store = _settings_api(tmp_path)
    if credential_key == "api_key":
        connection = {"provider": "custom", "base_url": "https://old.example/v1"}
        expected = "old-main-key"
    else:
        connection = {"vision_provider": "custom", "vision_base_url": "https://vision-old.example/v1"}
        expected = "old-vision-key"

    await api.update_settings({"llm": {**connection, credential_key: placeholder}})

    assert store.get(f"llm.{credential_key}") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("placeholder", ["", "********"])
async def test_runtime_vision_same_connection_placeholders_preserve_key(placeholder: str) -> None:
    config = SimpleNamespace(llm=_llm_config())

    apply_runtime_config(
        config,
        {
            "llm": {
                "vision_provider": "custom",
                "vision_base_url": "https://vision-old.example/v1",
                "vision_api_key": placeholder,
            }
        },
    )

    assert config.llm.vision_api_key == "vision-old-key"


def test_runtime_vision_connection_change_clears_old_key() -> None:
    config = SimpleNamespace(llm=_llm_config())

    apply_runtime_config(config, {"llm": {"vision_base_url": "https://vision-new.example/v1"}})

    assert config.llm.vision_api_key == ""


@pytest.mark.parametrize("raw_value", [None, "   "])
def test_settings_store_empty_credential_environment_loads_empty_settings(monkeypatch, tmp_path, raw_value) -> None:
    if raw_value is None:
        monkeypatch.delenv(PROVIDER_CREDENTIALS_ENV, raising=False)
    else:
        monkeypatch.setenv(PROVIDER_CREDENTIALS_ENV, raw_value)

    assert SettingsStore(tmp_path / "settings.json").settings == {}


def test_redaction_removes_short_custom_key_before_truncation() -> None:
    secret = "cust-k7"
    text = f"upstream detail: {secret} and " + ("x" * 80)
    redacted = redact_error_text(text, limit=24, secrets=[secret])
    assert secret not in redacted
    assert "cust-" not in redacted


@pytest.mark.parametrize("placeholder", ["", "********"])
def test_redaction_does_not_change_unrelated_text(placeholder: str) -> None:
    assert redact_error_text(f"message {placeholder}", secrets=["real-key"]) == f"message {placeholder}"


def _live_settings_api(tmp_path):
    api, store = _settings_api(tmp_path)
    config = AppConfig()
    for key, value in vars(_llm_config()).items():
        setattr(config.llm, key, value)
    config.llm.api_key = "old-main-key"
    config.llm.vision_api_key = "old-vision-key"
    api.config = config
    return api, store, config


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["set", "delete"])
@pytest.mark.parametrize("connection_field, credential", [
    ("provider", "api_key"), ("base_url", "api_key"),
    ("vision_provider", "vision_api_key"), ("vision_base_url", "vision_api_key"),
])
async def test_single_setting_connection_changes_isolate_credentials(
    tmp_path, monkeypatch, method, connection_field, credential
):
    api, store, config = _live_settings_api(tmp_path)
    new_value = "chatgpt" if connection_field.endswith("provider") else "https://new.example/v1"
    if method == "set":
        await api.set_setting(f"llm.{connection_field}", new_value)
    else:
        # Empty endpoint resets must also reach the running client.
        default = "chatgpt" if connection_field.endswith("provider") else ""
        monkeypatch.setattr(settings_schema.env_config.llm, connection_field, default)
        await api.delete_setting(f"llm.{connection_field}")
        new_value = default
    assert store.get(f"llm.{credential}") == ""
    assert getattr(config.llm, credential) == ""
    assert getattr(config.llm, connection_field) == store.get(f"llm.{connection_field}")
    assert getattr(config.llm, connection_field) == new_value
    other = "vision_api_key" if credential == "api_key" else "api_key"
    assert getattr(config.llm, other) == store.get(f"llm.{other}")
    assert getattr(config.llm, other)


@pytest.mark.asyncio
async def test_single_setting_switch_does_not_send_old_key_to_model_discovery(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    fetch = AsyncMock(return_value=[])
    monkeypatch.setattr("modules.system.settings_api.fetch_available_models", fetch)
    api, _, _ = _live_settings_api(tmp_path)
    await api.set_setting("llm.base_url", "https://new.example/v1")
    await api.list_llm_models({"provider": "custom", "base_url": "https://new.example/v1"})
    assert fetch.await_args.args[1] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", ["api_key", "vision_api_key"])
@pytest.mark.parametrize("environment_key", ["", "environment-key"])
async def test_delete_credential_clears_store_and_runtime(tmp_path, monkeypatch, credential, environment_key):
    api, store, config = _live_settings_api(tmp_path)
    monkeypatch.setattr(settings_schema.env_config.llm, credential, environment_key)
    await api.delete_setting(f"llm.{credential}")
    assert store.get(f"llm.{credential}") == ""
    assert getattr(config.llm, credential) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", ["api_key", "vision_api_key"])
async def test_delete_credential_already_empty_in_store_clears_runtime(tmp_path, monkeypatch, credential):
    api, store, config = _live_settings_api(tmp_path)
    monkeypatch.setattr(settings_schema.env_config.llm, credential, "")
    store.set(f"llm.{credential}", "")
    await api.delete_setting(f"llm.{credential}")
    assert getattr(config.llm, credential) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("prefix", ["", "vision_"])
@pytest.mark.parametrize("connection_changed", [False, True])
async def test_rollback_preserves_credentials_only_for_same_connection(tmp_path, legacy, prefix, connection_changed):
    api, store, config = _live_settings_api(tmp_path)
    field = f"{prefix}base_url" if connection_changed else "model"
    patch = {field: "https://new.example/v1" if connection_changed else "new-model",
             f"{prefix}api_key": "new-current-key"}
    await api.update_settings({"llm": patch})
    if legacy:
        # Exercise the dynamic-config history fallback used by older sessions.
        snapshot = api._settings_history.peek(1)
        api._settings_history.clear()
        api.dynamic_config.config = snapshot
        await api.dynamic_config.update_batch({"llm": store.get("llm")})
    await api.rollback_changes(1)
    credential = f"{prefix}api_key"
    expected = "" if connection_changed else "new-current-key"
    assert store.get(f"llm.{credential}") == expected
    assert getattr(config.llm, credential) == expected
    if connection_changed:
        expected_base = "https://vision-old.example/v1" if prefix else "https://old.example/v1"
        assert store.get(f"llm.{field}") == expected_base
        assert getattr(config.llm, field) == expected_base
    other = "api_key" if prefix else "vision_api_key"
    assert getattr(config.llm, other) == store.get(f"llm.{other}")
    assert getattr(config.llm, other)


@pytest.mark.asyncio
@pytest.mark.parametrize("placeholder", ["", "********"])
async def test_single_section_setting_placeholders_keep_live_credentials(tmp_path, placeholder):
    api, store, config = _live_settings_api(tmp_path)
    await api.set_setting("llm", {"api_key": placeholder, "vision_api_key": placeholder, "model": "new-model"})
    assert store.get("llm.api_key") == config.llm.api_key == "old-main-key"
    assert store.get("llm.vision_api_key") == config.llm.vision_api_key == "old-vision-key"


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["", "vision_"])
async def test_single_section_connection_switch_keeps_explicit_credential(tmp_path, prefix):
    api, store, config = _live_settings_api(tmp_path)
    credential = f"{prefix}api_key"
    supplied_key = store.get(f"llm.{credential}")
    await api.set_setting("llm", {f"{prefix}base_url": "https://new.example/v1", credential: supplied_key})
    assert store.get(f"llm.{credential}") == supplied_key
    assert getattr(config.llm, credential) == supplied_key
