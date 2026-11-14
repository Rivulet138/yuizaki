from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from urllib.error import HTTPError

import httpx
import pytest
from fastapi import FastAPI
from modules.agent.turn_store import TurnCommitStore
from modules.system.message_connectors import MessageConnectorRegistry
from routes.connector_api import create_message_connector_router


class TurnService:
    def __init__(self) -> None:
        self.task = None
        self.started = asyncio.Event()
        self.release = None
        self.calls = 0

    async def execute(self, _trigger, request):
        self.task = asyncio.current_task()
        self.calls += 1
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        return SimpleNamespace(
            replayed=False,
            context=SimpleNamespace(turn_id=request.turn_id),
            result=SimpleNamespace(outcome="completed", reply="reply"),
        )


def build_app(registry, store, service, *, fast_ack=False):
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
        wall_clock=store._wall_clock,
        fast_ack_connectors={"telegram"} if fast_ack else None,
    ))
    return app


async def post_webhook(client, kind):
    if kind == "telegram":
        return await client.post(
            "/api/system/connectors/telegram/webhook",
            json={"update_id": 1, "message": {"chat": {"id": 123}, "from": {"id": 42}, "text": "hello"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
        )
    # RFC 8032 test-vector signature for timestamp + the exact request body.
    body = (
        b'{"type":2,"id":"interaction-42","application_id":"app-1",'
        b'"token":"interaction-token","channel_id":"channel-1",'
        b'"data":{"name":"hello","options":[{"name":"text","value":"\xe4\xbd\xa0\xe5\xa5\xbd"}]},'
        b'"member":{"user":{"id":"user-1"}}}'
    )
    return await client.post(
        "/api/system/connectors/discord/webhook", content=body,
        headers={
            "Content-Type": "application/json", "X-Signature-Timestamp": "1710000000",
            "X-Signature-Ed25519": (
                "84fff18844caa92084c4ae7ecc83c4103ce7bca67d9ff88a802fdee9a9a34c315"
                "382f0e188992093ef87d4fa4cc073bbfe56d502f4dc61f48c1f415bdd4f820d"
            ),
        },
    )


def registry_for(kind, clock, sender):
    registry = MessageConnectorRegistry(
        env={}, clock=lambda: clock[0], http_post=sender, http_patch=sender,
    )
    connector_id = kind.split("_")[0]
    if connector_id in {"qq", "wechat"}:
        config = {
            "bridgeUrl": "http://127.0.0.1:3000", "bridgeToken": "bridge-secret",
            "bridgeProtocol": "onebot11" if connector_id == "qq" else "generic",
        }
    else:
        config = {"botToken": "bot-token", "webhookSecret": "webhook-secret"}
    if connector_id == "discord":
        config["publicKey"] = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    registry.update_config(connector_id, {**config, "enabled": True})
    return registry


def seed_failed(store, kind, *, retry_turn=False):
    connector_id = kind.split("_")[0]
    key = f"connector:{connector_id}:1"
    target = {"chat_id": "123", "channel_id": "123", "user_id": "42"}
    if kind in {"discord_patch", "discord_expired"}:
        target.update({
            "interaction_id": "1", "interaction_token": "interaction-token",
            "application_id": "app-1",
            "interaction_expires_at": "900" if kind == "discord_expired" else "10000",
        })
    message = {
        "connector_id": connector_id, "event_id": "1", "session_id": "session-1",
        "external_user_id": "42", "conversation_id": "123", "text": "hello",
        "reply_target": target, "metadata": {}, "workspace_id": "default",
    }
    if retry_turn:
        assert store.record_connector_turn_pending(key, key, connector_id, "1", "seed", message=message)
        assert store.mark_connector_turn_failed(key, "seed", "connector_turn_failed")
    else:
        assert store.claim_connector_delivery(
            key, key, connector_id, "1", "seed", message=message, reply_text="reply",
        )["status"] == "claimed"
        assert store.mark_connector_delivery_failed(key, "seed", "provider_rejected")
    return connector_id, key


@pytest.mark.parametrize("kind", ["telegram", "wechat", "qq", "discord_patch", "discord_post", "discord_expired"])
@pytest.mark.parametrize("retry_turn", [False, True])
@pytest.mark.asyncio
async def test_cancelled_retry_keeps_provider_send_fenced_until_resolution(tmp_path: Path, kind, retry_turn):
    started, release, finished = Event(), Event(), Event()
    calls = []

    def sender(url, _headers, _payload):
        calls.append(url)
        if len(calls) == 1:
            started.set()
            try:
                assert release.wait(5), "test did not release the sender"
            finally:
                finished.set()
        return {"ok": True, "sent": True, "status": "ok", "retcode": 0}

    clock = [1000.0]
    store_path = tmp_path / "turns.sqlite3"
    store = TurnCommitStore(store_path, wall_clock=lambda: clock[0])
    registry = registry_for(kind, clock, sender)
    connector_id, key = seed_failed(store, kind, retry_turn=retry_turn)
    service = TurnService()
    app = build_app(registry, store, service)
    retry_url = f"/api/system/connectors/{connector_id}/events/1/retry"
    resolve_url = f"/api/system/connectors/{connector_id}/events/1/resolve"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        running = asyncio.create_task(client.post(retry_url))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            before = store.connector_delivery(key)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            row = store.connector_delivery(key)
            assert row["status"] == "sending"
            assert row["claimed_by"] == before["claimed_by"]
            assert row["claim_expires_at"] == before["claim_expires_at"]
            assert store.claim_connector_delivery(key, key, connector_id, "1", "second")["status"] == "busy"
            assert (await client.post(resolve_url, json={"outcome": "delivered"})).status_code == 409

            clock[0] += 2000
            restarted = TurnCommitStore(store_path, wall_clock=lambda: clock[0])
            assert restarted.reset_connector_delivery_for_retry(key) is False
            for owner in ("second", before["claimed_by"]):
                assert restarted.claim_connector_delivery(key, key, connector_id, "1", owner)["status"] == "unknown"
            assert restarted.claim_connector_turn_retry(key, "second")["status"] == "not_retryable"
            response = await client.post(retry_url)
            assert response.status_code == 409
            assert response.json()["outcome"] == "unknown"
            assert store.connector_delivery(key)["attempt_count"] == before["attempt_count"]
            assert len(calls) == 1
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

        # The abandoned thread cannot settle SQLite. Confirm the external
        # result explicitly, then allow a retry only for confirmed failure.
        outcome = "failed" if retry_turn else "delivered"
        resolved = await client.post(resolve_url, json={"outcome": outcome})
        assert resolved.status_code == 200
        assert resolved.json()["delivery"]["status"] == outcome
        retried = await client.post(retry_url)
        assert retried.status_code == 200
        assert len(calls) == (2 if retry_turn else 1)
        assert service.calls == (1 if retry_turn else 0)
        assert store.connector_delivery(key)["status"] == "delivered"
    if kind == "discord_patch":
        assert all(url.endswith("/messages/@original") for url in calls)
    elif kind.startswith("discord"):
        assert all(url.endswith("/channels/123/messages") for url in calls)


@pytest.mark.asyncio
async def test_cancel_before_retry_send_remains_retryable(tmp_path: Path):
    clock = [1000.0]
    calls = []
    registry = registry_for("telegram", clock, lambda *args: calls.append(args) or {"ok": True})
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    _connector_id, key = seed_failed(store, "telegram", retry_turn=True)
    service = TurnService()
    service.release = asyncio.Event()
    app = build_app(registry, store, service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        running = asyncio.create_task(client.post("/api/system/connectors/telegram/events/1/retry"))
        try:
            await asyncio.wait_for(service.started.wait(), 2)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            row = store.connector_delivery(key)
            assert row["status"] == "failed"
            assert row["claimed_by"] is None
            assert row["claim_expires_at"] is None
            assert not calls
            service.release.set()
            response = await client.post("/api/system/connectors/telegram/events/1/retry")
            assert response.status_code == 200
            assert len(calls) == 1
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


@pytest.mark.parametrize("kind", ["telegram", "discord_patch"])
@pytest.mark.asyncio
async def test_cancelled_webhook_send_keeps_lease_and_does_not_resend(tmp_path: Path, kind):
    started, release, finished = Event(), Event(), Event()
    calls = []

    def sender(*args):
        calls.append(args)
        started.set()
        try:
            assert release.wait(5)
            return {"ok": True}
        finally:
            finished.set()

    clock = [1710000000.0]
    registry = registry_for(kind, clock, sender)
    connector_id = kind.split("_")[0]
    event_id = "interaction-42" if connector_id == "discord" else "1"
    event_url = f"/api/system/connectors/{connector_id}/events/{event_id}"
    key = f"connector:{connector_id}:{event_id}"
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    service = TurnService()
    app = build_app(registry, store, service, fast_ack=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        try:
            response = await post_webhook(client, kind)
            assert response.status_code == 200
            assert await asyncio.to_thread(started.wait, 2)
            cancel = await client.post(f"{event_url}/cancel")
            assert cancel.status_code == 409
            assert cancel.json()["error"] == "cancel_too_late"
            service.task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await service.task
            assert store.connector_delivery(key)["status"] == "sending"
            clock[0] += 2000
            assert not store.reset_connector_delivery_for_retry(key)
            retry = await client.post(f"{event_url}/retry")
            assert retry.status_code == 409
            assert retry.json()["outcome"] == "unknown"
            duplicate = await post_webhook(client, kind)
            assert duplicate.status_code == 409
            assert len(calls) == 1
            assert service.calls == 1
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            if service.task is not None and not service.task.done():
                service.task.cancel()
                await asyncio.gather(service.task, return_exceptions=True)
        resolved = await client.post(f"{event_url}/resolve", json={"outcome": "delivered"})
        assert resolved.status_code == 200
        assert store.connector_delivery(key)["status"] == "delivered"
    if connector_id == "discord":
        # Cancellation must not race the original response with a status PATCH.
        assert calls[0][0].endswith("/messages/@original")
        assert len(calls) == 1


@pytest.mark.parametrize("kind", ["telegram", "wechat", "qq", "discord_patch", "discord_post"])
@pytest.mark.parametrize("failure", ["transport", "commit_exception", "commit_lost"])
@pytest.mark.asyncio
async def test_retry_preserves_unknown_after_any_possible_send(tmp_path: Path, monkeypatch, kind, failure):
    calls = []

    def sender(*args):
        calls.append(args)
        if failure == "transport":
            raise OSError("response lost after send")
        return {"ok": True, "sent": True, "status": "ok", "retcode": 0}

    clock = [1000.0]
    registry = registry_for(kind, clock, sender)
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    connector_id, key = seed_failed(store, kind)
    if failure != "transport":
        def lose_commit(*_args):
            if failure == "commit_exception":
                raise OSError("local commit failed")
            return False
        monkeypatch.setattr(store, "mark_connector_delivery_sent", lose_commit)
    app = build_app(registry, store, TurnService())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/system/connectors/{connector_id}/events/1/retry"
        response = await client.post(url)
        assert response.status_code == 409
        assert response.json()["error"] == "delivery_state_unknown"
        row = store.connector_delivery(key)
        assert row["status"] == "sending"
        assert row["claimed_by"] is not None
        assert row["claim_expires_at"] is not None
        clock[0] += 2000
        assert not store.reset_connector_delivery_for_retry(key)
        assert (await client.post(url)).status_code == 409
        assert store.connector_delivery(key)["attempt_count"] == row["attempt_count"]
        assert len(calls) == 1


@pytest.mark.parametrize("via_retry", [False, True])
@pytest.mark.parametrize("result, retryable", [
    ({"sent": False, "reason": "empty_reply"}, True),
    ({"ok": False, "reason": "provider_rejected"}, True),
    ({"status_code": 403}, True),
    (HTTPError("http://provider.invalid", 403, "Forbidden", {}, None), True),
    ({"status_code": 503}, False),
    (HTTPError("http://provider.invalid", 503, "Unavailable", {}, None), False),
    ({"sent": False, "outcome": "unknown"}, False),
    ({"ok": False, "sent": True}, False),
    ({}, False),
    (None, False),
])
@pytest.mark.asyncio
async def test_only_definite_delivery_failure_allows_retry(tmp_path: Path, via_retry, result, retryable):
    calls = []

    def sender(*args):
        calls.append(args)
        if len(calls) == 1:
            if isinstance(result, Exception):
                raise result
            return result
        return {"ok": True}

    clock = [1000.0]
    registry = registry_for("telegram", clock, sender)
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    service = TurnService()
    app = build_app(registry, store, service)
    key = "connector:telegram:1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        retry_url = "/api/system/connectors/telegram/events/1/retry"
        if via_retry:
            seed_failed(store, "telegram")
            response = await client.post(retry_url)
        else:
            response = await post_webhook(client, "telegram")
        assert response.status_code == (502 if retryable else 409)
        row = store.connector_delivery(key)
        assert row["status"] == ("failed" if retryable else "sending")
        if retryable:
            assert row["claimed_by"] is None
            assert row["claim_expires_at"] is None
        else:
            assert response.json()["outcome"] == "unknown"
            assert row["claimed_by"] is not None
        clock[0] += 2000
        retry = await client.post(retry_url)
        assert retry.status_code == (200 if retryable else 409)
        assert len(calls) == (2 if retryable else 1)


@pytest.mark.parametrize("kind", ["telegram", "discord_patch"])
@pytest.mark.parametrize("failure", ["commit_exception", "commit_lost"])
@pytest.mark.asyncio
async def test_webhook_success_with_lost_local_confirmation_stays_unknown(tmp_path: Path, monkeypatch, kind, failure):
    clock = [1710000000.0]
    calls = []
    registry = registry_for(kind, clock, lambda *args: calls.append(args) or {"ok": True})
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: clock[0])
    service = TurnService()

    def lose_commit(*_args):
        if failure == "commit_exception":
            raise OSError("local commit failed")
        return False

    monkeypatch.setattr(store, "mark_connector_delivery_sent", lose_commit)
    app = build_app(registry, store, service)
    connector_id = kind.split("_")[0]
    event_id = "interaction-42" if connector_id == "discord" else "1"
    key = f"connector:{connector_id}:{event_id}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await post_webhook(client, kind)
        if connector_id == "discord":
            assert response.json()["type"] == 5
            # Discord acknowledges before the worker starts. Wait for the
            # actual route task, rather than observing its intermediate row.
            await asyncio.wait_for(service.started.wait(), 2)
            response = await asyncio.wait_for(asyncio.shield(service.task), 2)
            assert response.status_code == 409
        else:
            assert response.status_code == 409
        row = store.connector_delivery(key)
        assert row["status"] == "sending"
        assert row["claimed_by"] is not None
        assert row["claim_expires_at"] is not None
        clock[0] += 2000
        assert not store.reset_connector_delivery_for_retry(key)
        retry = await client.post(f"/api/system/connectors/{connector_id}/events/{event_id}/retry")
        assert retry.status_code == 409
        assert len(calls) == 1
