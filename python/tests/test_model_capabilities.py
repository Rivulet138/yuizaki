from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.llm import capabilities
from modules.llm.capabilities import (
    get_model_capabilities,
    get_model_limits,
    infer_model_capability_support,
    infer_model_vision_support,
    load_model_capability_registry,
)
from modules.llm.providers import LLM_PROVIDER_VALUES

REGISTRY_PATH = Path(capabilities._MODULE_DIR) / "model-capabilities.registry.json"


def test_registry_ships_with_the_python_package() -> None:
    assert REGISTRY_PATH.exists()


def test_registry_entries_are_well_formed() -> None:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    entries = {key: value for key, value in payload.items() if isinstance(value, dict)}
    assert entries, "registry must declare at least one model"

    for key, entry in entries.items():
        provider, _, model = key.partition(":")
        assert provider in LLM_PROVIDER_VALUES, f"unknown provider in {key}"
        assert model, f"missing model in {key}"
        assert key == key.lower(), f"registry keys must be lowercase: {key}"
        for flag in ("vision", "tools"):
            if flag in entry:
                assert isinstance(entry[flag], bool), f"{key}.{flag} must be boolean"
        metadata = entry.get("metadata")
        assert isinstance(metadata, dict), f"{key}.metadata must be an object"
        for limit in ("contextWindowTokens", "maxOutputTokens"):
            if limit in metadata:
                assert isinstance(metadata[limit], int) and metadata[limit] > 0, f"{key}.{limit} must be a positive integer"


def test_unknown_models_keep_existing_behavior() -> None:
    assert get_model_capabilities("custom", "unlisted-model") is None
    assert get_model_limits("custom", "unlisted-model") == {}
    assert infer_model_vision_support("custom", "unlisted-model") == "unknown"
    assert infer_model_capability_support("custom", "unlisted-model", "tools") == "unknown"


def test_registered_model_reports_limits_and_vision() -> None:
    assert get_model_limits("deepseek", "deepseek-chat") == {
        "context_window_tokens": 131072,
        "max_output_tokens": 8192,
    }
    # The current DeepSeek models advertise a 1M window and must not clamp the
    # default 131072 context / 8192 output settings.
    assert get_model_limits("deepseek", "deepseek-flash") == {
        "context_window_tokens": 1048576,
        "max_output_tokens": 393216,
    }
    assert infer_model_vision_support("deepseek", "deepseek-reasoner") == "unsupported"
    assert infer_model_vision_support("chatgpt", "gpt-4o") == "supported"
    # OpenAI-style "models/" prefixes are normalized before lookup.
    assert get_model_limits("chatgpt", "models/gpt-4o")["context_window_tokens"] == 128000


def test_legacy_electron_path_is_used_when_the_package_copy_is_absent(monkeypatch, tmp_path) -> None:
    legacy = tmp_path / "model-capabilities.registry.json"
    legacy.write_text(json.dumps({"custom:legacy-model": {"vision": True, "metadata": {"contextWindowTokens": 4096}}}), encoding="utf-8")

    monkeypatch.delenv("YUIZAKI_MODEL_CAPABILITIES_REGISTRY", raising=False)
    monkeypatch.setattr(capabilities, "_REGISTRY_CANDIDATES", (tmp_path / "missing.json", legacy))
    load_model_capability_registry.cache_clear()
    try:
        assert capabilities._registry_path() == legacy
        assert get_model_limits("custom", "legacy-model") == {"context_window_tokens": 4096}
    finally:
        load_model_capability_registry.cache_clear()


def test_registry_env_override_wins(monkeypatch, tmp_path) -> None:
    override = tmp_path / "override.json"
    override.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setenv("YUIZAKI_MODEL_CAPABILITIES_REGISTRY", str(override))
    load_model_capability_registry.cache_clear()
    try:
        assert capabilities._registry_path() == override
    finally:
        load_model_capability_registry.cache_clear()


@pytest.mark.parametrize("raw", ["not json", "[]"])
def test_registry_failures_fall_back_to_unknown(monkeypatch, tmp_path, raw: str) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(raw, encoding="utf-8")
    monkeypatch.setenv("YUIZAKI_MODEL_CAPABILITIES_REGISTRY", str(broken))
    load_model_capability_registry.cache_clear()
    try:
        assert load_model_capability_registry() == {}
        assert get_model_limits("deepseek", "deepseek-chat") == {}
    finally:
        load_model_capability_registry.cache_clear()
