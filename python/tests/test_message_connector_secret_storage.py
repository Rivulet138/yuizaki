from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.system.message_connectors import MessageConnectorRegistry


def test_connector_updates_do_not_persist_secrets(tmp_path: Path) -> None:
    state_path = tmp_path / "message_connectors.json"
    registry = MessageConnectorRegistry(state_path=state_path, env={})

    snapshot = registry.update_config(
        "telegram",
        {
            "botToken": "bot-secret",
            "webhookSecret": "webhook-secret",
            "enabled": False,
        },
    )

    assert snapshot is not None
    assert snapshot["botTokenConfigured"] is True
    assert snapshot["webhookSecretConfigured"] is True
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "bot-secret" not in state_path.read_text(encoding="utf-8")
    assert "webhook-secret" not in state_path.read_text(encoding="utf-8")
    assert "botToken" not in persisted["connectors"]["telegram"]
    assert "webhookSecret" not in persisted["connectors"]["telegram"]


def test_connector_environment_credentials_are_used_without_state_secrets(tmp_path: Path) -> None:
    state_path = tmp_path / "message_connectors.json"
    state_path.write_text(
        json.dumps({"version": 1, "disabled": [], "connectors": {"telegram": {"enabled": False}}}),
        encoding="utf-8",
    )

    registry = MessageConnectorRegistry(
        state_path=state_path,
        env={
            "YUIZAKI_TELEGRAM_BOT_TOKEN": "env-bot-secret",
            "YUIZAKI_TELEGRAM_WEBHOOK_SECRET": "env-webhook-secret",
        },
    )

    snapshot = registry.config_snapshot("telegram")
    assert snapshot is not None
    assert snapshot["botTokenConfigured"] is True
    assert snapshot["webhookSecretConfigured"] is True
    assert "env-bot-secret" not in state_path.read_text(encoding="utf-8")


def test_clear_connector_secret_removes_runtime_and_persisted_value(tmp_path: Path) -> None:
    state_path = tmp_path / "message_connectors.json"
    registry = MessageConnectorRegistry(state_path=state_path, env={})
    registry.update_config("telegram", {"botToken": "bot-secret", "webhookSecret": "webhook-secret"})

    registry.update_config("telegram", {"clearBotToken": True, "clearWebhookSecret": True})

    snapshot = registry.config_snapshot("telegram")
    assert snapshot is not None
    assert snapshot["botTokenConfigured"] is False
    assert snapshot["webhookSecretConfigured"] is False
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "botToken" not in persisted["connectors"]["telegram"]
    assert "webhookSecret" not in persisted["connectors"]["telegram"]


@pytest.mark.parametrize(
    "bridge_url",
    [
        "file:///tmp/bridge",
        "http://user:password@example.test/bridge",
        "http://example.test/bridge#secret",
    ],
)
def test_personal_bridge_rejects_unsafe_url_at_configuration_time(tmp_path: Path, bridge_url: str) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "message_connectors.json", env={})

    with pytest.raises(Exception) as error:
        registry.update_config("qq", {"bridgeUrl": bridge_url})

    assert getattr(error.value, "code", None) == "invalid_bridge_url"
    assert registry.config_snapshot("qq")["bridgeUrlConfigured"] is False


def test_personal_bridge_url_is_normalized_without_trailing_slash(tmp_path: Path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "message_connectors.json", env={})

    registry.update_config("wechat", {"bridgeUrl": "https://bridge.example.test/api/"})

    assert registry.config_snapshot("wechat")["bridgeUrl"] == "https://bridge.example.test/api"
