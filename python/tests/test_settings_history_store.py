from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from modules.system.dynamic_config import DynamicConfigManager
from modules.system.settings_api import SettingsAPI
from modules.system.settings_history_store import (
    MAX_SETTINGS_SNAPSHOTS,
    SettingsHistoryStore,
)
from modules.system.settings_store import SettingsStore


def test_history_store_scrubs_secrets_and_round_trips(tmp_path) -> None:
    path = tmp_path / "settings_history.json"
    store = SettingsHistoryStore(path)

    store.append({"llm": {"api_key": "sk-should-not-persist", "model": "m1"}})

    raw = path.read_text(encoding="utf-8")
    assert "sk-should-not-persist" not in raw
    reloaded = SettingsHistoryStore(path)
    snapshot = reloaded.peek(1)
    assert snapshot is not None
    assert snapshot["llm"]["api_key"] == ""
    assert snapshot["llm"]["model"] == "m1"


def test_history_store_is_bounded_and_pops_applied_steps(tmp_path) -> None:
    store = SettingsHistoryStore(tmp_path / "settings_history.json")
    for index in range(MAX_SETTINGS_SNAPSHOTS + 5):
        store.append({"llm": {"model": f"model-{index}"}})

    assert len(store) == MAX_SETTINGS_SNAPSHOTS
    assert store.peek(1)["llm"]["model"] == f"model-{MAX_SETTINGS_SNAPSHOTS + 4}"

    popped = store.pop(2)
    assert popped is not None
    assert popped["llm"]["model"] == f"model-{MAX_SETTINGS_SNAPSHOTS + 3}"
    assert len(store) == MAX_SETTINGS_SNAPSHOTS - 2


def test_history_store_quarantines_corrupt_file(tmp_path) -> None:
    path = tmp_path / "settings_history.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(Exception, match="settings_history_store_corrupt"):
        SettingsHistoryStore(path)

    assert list(tmp_path.glob("settings_history.json.corrupt-*"))


@pytest.mark.asyncio
async def test_settings_rollback_uses_persisted_snapshots_after_restart(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    history_path = tmp_path / "settings_history.json"
    store = SettingsStore(settings_path)
    api = SettingsAPI(
        store,
        DynamicConfigManager(),
        settings_history_store=SettingsHistoryStore(history_path),
    )
    await api.set_setting("llm.model", "first-model")

    restarted = SettingsAPI(
        SettingsStore(settings_path),
        DynamicConfigManager(),
        settings_history_store=SettingsHistoryStore(history_path),
    )

    response = await restarted.rollback_changes(1)
    assert response.status == "rolled_back"
    assert SettingsStore(settings_path).get("llm.model") != "first-model"


@pytest.mark.asyncio
async def test_clear_history_also_clears_persisted_rollback_entries(tmp_path) -> None:
    settings_path = tmp_path / "settings.json"
    history_path = tmp_path / "settings_history.json"
    api = SettingsAPI(
        SettingsStore(settings_path),
        DynamicConfigManager(),
        settings_history_store=SettingsHistoryStore(history_path),
    )
    await api.set_setting("llm.model", "first-model")
    await api.clear_history()

    payload = json.loads(history_path.read_text(encoding="utf-8"))
    assert payload["snapshots"] == []

    restarted = SettingsAPI(
        SettingsStore(settings_path),
        DynamicConfigManager(),
        settings_history_store=SettingsHistoryStore(history_path),
    )
    with pytest.raises(HTTPException) as error:
        await restarted.rollback_changes(1)
    assert error.value.status_code == 400
