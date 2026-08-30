from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from modules.agent.turn_store import TurnCommitStore
from modules.system.message_connectors import MessageConnectorRegistry
from routes.connector_api import create_message_connector_router


class _UnusedTurnService:
    async def execute(self, _trigger: str, _request: object) -> object:
        raise AssertionError("manual resolution must not create a new turn")


def _build_app(registry: MessageConnectorRegistry, store: TurnCommitStore) -> FastAPI:
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: _UnusedTurnService(),
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
        wall_clock=store._wall_clock,
    ))
    return app


def _seed_sending(store: TurnCommitStore, *, lease_seconds: float) -> None:
    assert store.claim_connector_delivery(
        "connector:telegram:orphan-1",
        "connector:telegram:orphan-1",
        "telegram",
        "orphan-1",
        "crashed-worker",
        lease_seconds=lease_seconds,
        message={"connector_id": "telegram", "event_id": "orphan-1", "text": "hello"},
        reply_text="reply",
    )["status"] == "claimed"


@pytest.mark.asyncio
async def test_manual_resolution_requires_expired_lease_and_is_idempotent(tmp_path: Path) -> None:
    clock = [time.time()]
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    registry = MessageConnectorRegistry()
    registry.update_config("telegram", {
        "botToken": "staging-bot-token",
        "webhookSecret": "staging-webhook-secret",
        "enabled": True,
    })
    _seed_sending(store, lease_seconds=60)
    app = _build_app(registry, store)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        active = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "delivered"},
        )
        assert active.status_code == 409
        assert active.json()["error"] == "delivery_lease_active"

        clock[0] += 61
        resolved = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "delivered"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["resolved"] is True
        assert resolved.json()["delivery"]["status"] == "delivered"

        repeated = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "delivered"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["already_resolved"] is True

        invalid = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "unknown_effect"},
        )
        assert invalid.status_code == 422

    assert store.connector_delivery("connector:telegram:orphan-1")["status"] == "delivered"


@pytest.mark.asyncio
async def test_resolution_projection_uses_injected_clock(tmp_path: Path) -> None:
    # Keep the store clock deliberately ahead of the process clock.  The
    # endpoint must use one consistent clock for both the lease decision and
    # the public ``resolvable`` projection.
    clock = [time.time() + 10_000]
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    registry = MessageConnectorRegistry()
    registry.update_config("telegram", {
        "botToken": "staging-bot-token",
        "webhookSecret": "staging-webhook-secret",
        "enabled": True,
    })
    _seed_sending(store, lease_seconds=60)
    app = _build_app(registry, store)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "delivered"},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "delivery_lease_active"
    assert response.json()["delivery"]["resolvable"] is False


@pytest.mark.asyncio
async def test_manual_resolution_rejects_corrupt_lease_metadata(tmp_path: Path) -> None:
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    registry = MessageConnectorRegistry()
    registry.update_config("telegram", {
        "botToken": "staging-bot-token",
        "webhookSecret": "staging-webhook-secret",
        "enabled": True,
    })
    _seed_sending(store, lease_seconds=0.1)
    with store._connect() as conn:
        conn.execute(
            "UPDATE connector_deliveries SET claim_expires_at = ? WHERE delivery_key = ?",
            ("corrupt", "connector:telegram:orphan-1"),
        )
    app = _build_app(registry, store)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/system/connectors/telegram/events/orphan-1/resolve",
            json={"outcome": "delivered"},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "delivery_lease_invalid"
    assert response.json()["delivery"]["resolvable"] is False
