from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from modules.agent.turn_store import TurnCommitStore
from modules.system.backend_api_auth import backend_api_auth_required
from modules.system.message_connectors import MessageConnectorRegistry
from routes.connector_api import create_message_connector_router


class FakeTurnService:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _trigger: str, request: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            replayed=False,
            context=SimpleNamespace(turn_id=getattr(request, "turn_id", "turn:fake")),
            result=SimpleNamespace(outcome="completed", reply="已收到，我在这里。"),
        )


async def _wait_for_status(store: TurnCommitStore, key: str, status: str) -> dict[str, object]:
    for _ in range(50):
        row = store.connector_delivery(key)
        if row is not None and row.get("status") == status:
            return row
        await asyncio.sleep(0.01)
    pytest.fail(f"delivery {key} did not reach {status}")


@pytest.mark.asyncio
async def test_telegram_webhook_durable_delivery_and_replay_are_idempotent(tmp_path: Path) -> None:
    provider_calls: list[dict[str, object]] = []

    def http_post(url: str, headers: object, payload: object) -> dict[str, object]:
        provider_calls.append({"url": url, "headers": headers, "payload": payload})
        return {"ok": True, "sent": True, "status_code": 200}

    registry = MessageConnectorRegistry(http_post=http_post)
    registry.update_config("telegram", {
        "botToken": "bot-token",
        "webhookSecret": "webhook-secret",
        "enabled": True,
    })
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    turn_service = FakeTurnService()
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
        fast_ack_connectors={"telegram"},
    ))

    payload = {
        "update_id": 42,
        "message": {
            "chat": {"id": 123},
            "from": {"id": 456},
            "text": "你好",
        },
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/system/connectors/telegram/webhook", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["queued"] is True

        row = await _wait_for_status(store, "connector:telegram:42", "delivered")
        assert row["reply_text"] == "已收到，我在这里。"
        assert turn_service.calls == 1
        assert len(provider_calls) == 1
        assert provider_calls[0]["payload"] == {"chat_id": "123", "text": "已收到，我在这里。"}

        duplicate = await client.post("/api/system/connectors/telegram/webhook", json=payload, headers=headers)
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["already_sent"] is True

        unauthorized = await client.post(
            "/api/system/connectors/telegram/webhook",
            json={**payload, "update_id": 43},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert unauthorized.status_code == 401

    assert turn_service.calls == 1
    assert len(provider_calls) == 1


@pytest.mark.asyncio
async def test_discord_interaction_webhook_verifies_signature_and_converges_deferred_reply(tmp_path: Path) -> None:
    # RFC 8032 test-vector key, reused only for deterministic local signing.
    public_key = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    body = (
        b'{"type":2,"id":"interaction-42","application_id":"app-1",'
        b'"token":"interaction-token","channel_id":"channel-1",'
        b'"data":{"name":"hello","options":[{"name":"text","value":"\xe4\xbd\xa0\xe5\xa5\xbd"}]},'
        b'"member":{"user":{"id":"user-1"}}}'
    )
    timestamp = "1710000000"
    # Signature generated from the RFC 8032 seed over timestamp + raw body.
    signature = (
        "84fff18844caa92084c4ae7ecc83c4103ce7bca67d9ff88a802fdee9a9a34c315"
        "382f0e188992093ef87d4fa4cc073bbfe56d502f4dc61f48c1f415bdd4f820d"
    )
    provider_calls: list[dict[str, object]] = []

    def http_patch(url: str, headers: object, payload: object) -> dict[str, object]:
        provider_calls.append({"url": url, "headers": headers, "payload": payload})
        return {"ok": True, "sent": True, "status_code": 200}

    registry = MessageConnectorRegistry(http_patch=http_patch, clock=lambda: 1710000000)
    registry.update_config("discord", {"publicKey": public_key, "enabled": True})
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    turn_service = FakeTurnService()
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    headers = {
        "Content-Type": "application/json",
        "X-Signature-Timestamp": timestamp,
        "X-Signature-Ed25519": signature,
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/system/connectors/discord/webhook",
            content=body,
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["type"] == 5

        row = await _wait_for_status(store, "connector:discord:interaction-42", "delivered")
        assert row["reply_text"] == "已收到，我在这里。"
        assert turn_service.calls == 1
        assert len(provider_calls) == 1
        assert provider_calls[0]["url"] == (
            "https://discord.com/api/v10/webhooks/app-1/interaction-token/messages/@original"
        )
        assert provider_calls[0]["payload"] == {
            "content": "已收到，我在这里。",
            "allowed_mentions": {"parse": []},
        }

        duplicate = await client.post(
            "/api/system/connectors/discord/webhook",
            content=body,
            headers=headers,
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["already_sent"] is True

        invalid = await client.post(
            "/api/system/connectors/discord/webhook",
            content=body,
            headers={**headers, "X-Signature-Ed25519": "00" * 64},
        )
        assert invalid.status_code == 401

    assert turn_service.calls == 1
    assert len(provider_calls) == 1


def test_external_webhooks_bypass_only_backend_token_boundary() -> None:
    public_host = "203.0.113.10"
    assert backend_api_auth_required(
        "/api/system/connectors/telegram/webhook",
        "POST",
        client_host=public_host,
    ) is False
    assert backend_api_auth_required(
        "/api/system/connectors/discord/webhook",
        "POST",
        client_host=public_host,
    ) is False
    assert backend_api_auth_required(
        "/api/system/stream/twitch/eventsub",
        "POST",
        client_host=public_host,
    ) is False
    # The exemption is exact and method-scoped: management endpoints stay
    # behind the backend token, and a GET cannot impersonate a webhook.
    assert backend_api_auth_required(
        "/api/system/connectors/telegram/config",
        "GET",
        client_host=public_host,
    ) is True
    assert backend_api_auth_required(
        "/api/system/connectors/telegram/webhook",
        "GET",
        client_host=public_host,
    ) is True
