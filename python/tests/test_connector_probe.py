from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from modules.system.message_connectors import MessageConnectorRegistry
from routes.connector_api import create_message_connector_router


def test_telegram_probe_is_read_only_and_redacts_credentials() -> None:
    calls: list[tuple[str, object]] = []

    def http_get(url: str, headers: object) -> dict[str, object]:
        calls.append((url, headers))
        return {"ok": True, "status_code": 200, "result": {"id": 123, "username": "secret-bot"}}

    registry = MessageConnectorRegistry(http_get=http_get, env={})
    registry.update_config("telegram", {"botToken": "token-that-must-not-escape", "webhookSecret": "secret", "enabled": False})
    before = registry.snapshot()

    result = registry.probe("telegram")

    assert result["schemaVersion"] == "yuizaki.connector-probe.v1"
    assert result["ok"] is True
    assert result["status"] == "reachable"
    assert result["externalSideEffects"] is False
    assert result["networkChecked"] is True
    assert "token-that-must-not-escape" not in str(result)
    assert "secret-bot" not in str(result)
    assert registry.snapshot() == before
    assert len(calls) == 1
    assert "token-that-must-not-escape" in calls[0][0]


def test_discord_public_key_only_probe_reports_signature_readiness() -> None:
    registry = MessageConnectorRegistry(env={})
    registry.update_config("discord", {
        "publicKey": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "enabled": False,
    })

    result = registry.probe("discord")

    assert result["ok"] is True
    assert result["status"] == "signature_ready"
    assert result["networkChecked"] is False
    assert result["verificationConfigured"] is True
    assert result["externalSideEffects"] is False


def test_bridge_probe_normalizes_status_without_mutating_account_state() -> None:
    def http_get(url: str, headers: object) -> dict[str, object]:
        assert url == "http://127.0.0.1:39001/status"
        assert headers == {"Authorization": "Bearer bridge-secret"}
        return {"ok": True, "state": "connected", "account_id": "private-user"}

    registry = MessageConnectorRegistry(http_get=http_get, env={})
    registry.update_config("qq", {
        "bridgeUrl": "http://127.0.0.1:39001",
        "bridgeToken": "bridge-secret",
        "enabled": False,
    })
    before = registry.account_status("qq")

    result = registry.probe("qq")

    assert result["ok"] is True
    assert result["status"] == "reachable"
    assert result["bridgeStatus"] == "connected"
    assert result["networkChecked"] is True
    assert result["externalSideEffects"] is False
    assert "private-user" not in str(result)
    assert "bridge-secret" not in str(result)
    assert registry.account_status("qq") == before


@pytest.mark.asyncio
async def test_probe_route_is_registered_and_returns_normalized_snapshot(tmp_path: Path) -> None:
    registry = MessageConnectorRegistry(
        state_path=tmp_path / "connectors.json",
        env={},
        http_get=lambda _url, _headers: {"ok": True, "status_code": 200},
    )
    registry.update_config("telegram", {"botToken": "token", "webhookSecret": "secret", "enabled": False})
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/system/connectors/telegram/probe")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reachable"
    assert payload["externalSideEffects"] is False
    assert "token" not in str(payload)

