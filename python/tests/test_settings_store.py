from __future__ import annotations

import json

import pytest

from modules.system import settings_store as settings_store_module
from modules.system.settings_store import SettingsStore


@pytest.fixture(autouse=True)
def _no_credential_environment(monkeypatch):
    monkeypatch.delenv("YUIZAKI_PROVIDER_CREDENTIALS_JSON", raising=False)


def test_save_replaces_file_without_leaving_temp_files(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "light"}), encoding="utf-8")
    store = SettingsStore(path)

    store.set("theme", "dark")
    store.save()

    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "dark"
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_save_keeps_previous_content_when_replace_fails(tmp_path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    original = json.dumps({"theme": "light"}, indent=2)
    path.write_text(original, encoding="utf-8")
    store = SettingsStore(path)
    store.set("theme", "dark")

    def _deny_replace(*_args, **_kwargs):
        raise PermissionError("denied by test")

    monkeypatch.setattr(settings_store_module.os, "replace", _deny_replace)

    with pytest.raises(PermissionError):
        store.save()

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(f".{path.name}.*.tmp"))


def test_save_scrubs_secrets_before_persisting(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    store.set("llm.api_key", "sk-must-not-persist")
    store.set("llm.model", "deepseek-flash")
    store.save()

    raw = path.read_text(encoding="utf-8")
    assert "sk-must-not-persist" not in raw
    assert json.loads(raw)["llm"] == {"api_key": "", "model": "deepseek-flash"}


def test_load_quarantines_unparsable_settings(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "dark"', encoding="utf-8")

    store = SettingsStore(path)

    assert store.settings == {}
    assert not path.exists()
    quarantined = list(tmp_path.glob(f"{path.name}.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == '{"theme": "dark"'


def test_load_quarantines_non_object_payload(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    store = SettingsStore(path)

    assert store.settings == {}
    assert list(tmp_path.glob(f"{path.name}.corrupt-*"))


def test_load_quarantines_deeply_nested_payload(tmp_path) -> None:
    """A pathological payload must not abort startup with a RecursionError."""
    path = tmp_path / "settings.json"
    path.write_text("[" * 5000 + "]" * 5000, encoding="utf-8")

    store = SettingsStore(path)

    assert store.settings == {}
    assert list(tmp_path.glob(f"{path.name}.corrupt-*"))


def test_save_after_quarantine_writes_fresh_file(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not json at all", encoding="utf-8")
    store = SettingsStore(path)

    store.set("theme", "dark")
    store.save()

    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "dark"}
    assert list(tmp_path.glob(f"{path.name}.corrupt-*"))
