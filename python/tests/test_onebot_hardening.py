from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from modules.agent.turn_store import TurnCommitStore
from modules.system.message_connectors import MessageConnectorError, MessageConnectorRegistry
from routes.connector_api import (
    _message_from_snapshot,
    _message_snapshot,
    create_message_connector_router,
)


DEFAULTS = {
    "mentionRequired": True,
    "prefixes": [],
    "allowedUsers": [],
    "allowedGroups": [],
    "ratePerMinute": 10,
    "maxConcurrent": 2,
}
HEADERS = {"Authorization": "Bearer bridge-secret"}
WEBHOOK = "/api/system/connectors/qq/webhook"


def _registry(**config: object) -> MessageConnectorRegistry:
    registry = MessageConnectorRegistry(
        env={}, http_post=lambda *_args: {"ok": True, "sent": True},
    )
    registry.update_config("qq", {
        "bridgeUrl": "http://127.0.0.1:3000", "bridgeToken": "bridge-secret",
        "bridgeProtocol": "onebot11", "enabled": True, **config,
    })
    return registry


def _event(event_id: int = 1, *, user_id: int = 42, group_id: int | None = None) -> dict:
    event = {
        "post_type": "message", "message_id": event_id, "self_id": 99,
        "user_id": user_id, "sender": {"user_id": user_id},
        "message": [{"type": "text", "data": {"text": "你好"}}],
    }
    if group_id is not None:
        event["group_id"] = group_id
        event["message"].insert(0, {"type": "at", "data": {"qq": "99"}})
    return event


class TurnService:
    def __init__(self) -> None:
        self.requests: list = []
        self.release: asyncio.Event | None = None
        self.error = False
        self.outcome = "completed"
        self.seen: set[str] = set()

    async def execute(self, _trigger: str, request: object) -> SimpleNamespace:
        self.requests.append(request)
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise RuntimeError("test turn failed")
        request_id = request.request_id
        replayed = request_id in self.seen
        self.seen.add(request_id)
        return SimpleNamespace(
            replayed=replayed, context=SimpleNamespace(turn_id=request.turn_id),
            result=SimpleNamespace(outcome=self.outcome, reply="收到"),
        )


def _client(registry, service, store=None, *, fast_ack=False) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry, turn_service_provider=lambda: service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=(lambda: store) if store is not None else None,
        fast_ack_connectors={"qq"} if fast_ack else None,
    ))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers=HEADERS)


async def _delivered(store, event_id: int) -> dict:
    for _ in range(100):
        row = store.connector_delivery(f"connector:qq:{event_id}")
        if row and row["status"] == "delivered":
            return row
        await asyncio.sleep(0.01)
    pytest.fail(f"event {event_id} was not delivered")


@pytest.mark.parametrize("post_type", ["message", "message_sent"])
@pytest.mark.parametrize("identity", ["user", "sender"])
def test_self_messages_are_ignored(post_type, identity) -> None:
    event = _event()
    event["post_type"] = post_type
    if identity == "user":
        event["user_id"] = "99"
    else:
        event["sender"]["user_id"] = "99"
    assert _registry().parse("qq", event) is None


@pytest.mark.parametrize("post_type", ["notice", "meta_event", "request", "", None, 1])
def test_nonmessage_posts_with_text_are_ignored(post_type) -> None:
    assert _registry().parse("qq", {**_event(), "post_type": post_type}) is None


def test_message_sent_from_other_user_and_generic_private_are_supported() -> None:
    registry = _registry()
    assert registry.parse("qq", {**_event(), "post_type": "message_sent"}) is not None
    generic = {"id": "generic-1", "user_id": "42", "text": "你好"}
    assert registry.parse("qq", generic).text == "你好"


@pytest.mark.parametrize("target,accepted", [("99", True), (99, True), ("all", False), ("42", False)])
def test_group_requires_at_self_but_private_does_not(target, accepted) -> None:
    registry = _registry()
    event = _event(group_id=7)
    event["message"][0]["data"]["qq"] = target
    message = registry.parse("qq", event)
    assert (message is not None) is accepted
    if message:
        assert message.text == "你好"
    event["message"].pop(0)
    assert registry.parse("qq", event) is None
    assert registry.parse("qq", _event()) is not None
    registry.update_config("qq", {"mentionRequired": False})
    assert registry.parse("qq", event) is not None


def test_prefixes_are_additional_required_triggers_and_strip_longest_match() -> None:
    registry = _registry(prefixes=["小", "小崎"])
    assert registry.parse("qq", _event()) is None
    event = _event(group_id=7)
    event["message"][-1]["data"]["text"] = "  小崎 你好 "
    assert registry.parse("qq", event).text == "你好"
    event["message"].pop(0)
    assert registry.parse("qq", event) is None  # A prefix cannot bypass mandatory @.
    registry.update_config("qq", {"mentionRequired": False})
    assert registry.parse("qq", event).text == "你好"
    event.pop("group_id")
    assert registry.parse("qq", event).text == "你好"
    event["message"][-1]["data"]["text"] = "你好小崎"
    assert registry.parse("qq", event) is None
    event["message"][-1]["data"]["text"] = "小崎"
    assert registry.parse("qq", event) is None


@pytest.mark.parametrize("segment,text", [("image", "[图片]"), ("record", "[语音]"), ("voice", "[语音]"), ("file", "[文件]")])
def test_pure_media_and_reply_metadata_survive_durable_envelope(segment, text) -> None:
    event = _event()
    event["message"] = [
        {"type": "reply", "data": {"id": 123, "text": "do not quote"}},
        {"type": segment, "data": {"file": "private-file", "text": "do not leak"}},
    ]
    message = _registry().parse("qq", event)
    assert message.text == text
    assert message.metadata["reply_id"] == "123"
    restored = _message_from_snapshot(_message_snapshot(message))
    assert restored == message


def test_reply_only_and_unknown_segments_do_not_become_prompt_text() -> None:
    event = _event()
    event["message"] = [{"type": "reply", "data": {"id": 12, "text": "hidden"}}]
    assert _registry().parse("qq", event) is None
    event["message"] = [{"type": "unknown", "data": {"text": "hidden"}}]
    assert _registry().parse("qq", event) is None


def test_config_defaults_normalize_persist_and_snapshots_are_detached(tmp_path: Path) -> None:
    path = tmp_path / "connectors.json"
    registry = MessageConnectorRegistry(state_path=path, env={})
    assert DEFAULTS.items() <= registry.config_snapshot("qq").items()
    values = {"mentionRequired": False, "prefixes": [" 小崎 ", "小崎"],
              "allowedUsers": [" 42 "], "allowedGroups": ["7", "7"],
              "ratePerMinute": 3, "maxConcurrent": 1}
    registry.update_config("qq", values)
    expected = {**values, "prefixes": ["小崎"], "allowedUsers": ["42"], "allowedGroups": ["7"]}
    snapshot = registry.config_snapshot("qq")
    assert expected.items() <= snapshot.items()
    snapshot["prefixes"].append("other")
    assert registry.config_snapshot("qq")["prefixes"] == ["小崎"]
    stored = json.loads(path.read_text(encoding="utf-8"))["connectors"]["qq"]
    assert expected.items() <= stored.items()
    assert expected.items() <= MessageConnectorRegistry(state_path=path, env={}).config_snapshot("qq").items()


@pytest.mark.parametrize("field,value", [
    ("mentionRequired", "false"), ("mentionRequired", 1), ("mentionRequired", None),
    ("prefixes", "hi"), ("prefixes", [1]), ("prefixes", [""]),
    ("allowedUsers", "42"), ("allowedUsers", [42]), ("allowedUsers", [" "]),
    ("allowedGroups", {}), ("allowedGroups", [True]),
    ("ratePerMinute", True), ("ratePerMinute", 0), ("ratePerMinute", -1),
    ("ratePerMinute", "10"), ("ratePerMinute", 1.5),
    ("maxConcurrent", False), ("maxConcurrent", 0), ("maxConcurrent", None),
])
@pytest.mark.asyncio
async def test_config_types_are_rejected_atomically_by_registry_and_api(field, value) -> None:
    registry = _registry()
    before = registry.config_snapshot("qq")
    with pytest.raises(MessageConnectorError):
        registry.update_config("qq", {field: value})
    async with _client(registry, TurnService()) as client:
        response = await client.put("/api/system/connectors/qq/config", json={field: value})
    assert response.status_code == 422
    assert registry.config_snapshot("qq") == before


@pytest.mark.asyncio
async def test_config_put_whitelists_new_fields_and_get_includes_them() -> None:
    async with _client(_registry(), TurnService()) as client:
        values = {**DEFAULTS, "prefixes": ["小崎"], "ratePerMinute": 4}
        response = await client.put("/api/system/connectors/qq/config", json=values)
        assert response.status_code == 200
        assert values.items() <= response.json()["config"].items()
        snapshot = await client.get("/api/system/connectors/qq/config")
        assert values.items() <= snapshot.json().items()
        invalid = await client.put("/api/system/connectors/qq/config", json={"madeUp": True})
        assert invalid.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("config,event,accepted", [
    ({"allowedUsers": ["42"]}, _event(), True),
    ({"allowedUsers": ["43"]}, _event(), False),
    ({"allowedGroups": ["7"]}, _event(group_id=7), True),
    ({"allowedGroups": ["8"]}, _event(group_id=7), False),
    ({"allowedUsers": ["43"], "allowedGroups": ["7"]}, _event(group_id=7), False),
    ({"allowedGroups": ["7"]}, _event(), True),  # Group restrictions do not ban private chat.
])
async def test_allowlists_reject_before_turn_or_delivery(tmp_path, config, event, accepted) -> None:
    service = TurnService()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(_registry(**config), service, store) as client:
        response = await client.post(WEBHOOK, json=event)
    assert response.status_code == 200
    assert response.json()["accepted"] is accepted
    assert len(service.requests) == int(accepted)
    if not accepted:
        assert response.json()["reason"] == "not_allowlisted"
        assert store.connector_delivery("connector:qq:1") is None


@pytest.mark.asyncio
async def test_default_rate_limit_replay_window_expiry_and_session_isolation(tmp_path) -> None:
    now = [100.0]
    registry = _registry()
    registry._clock = lambda: now[0]
    service = TurnService()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(registry, service, store) as client:
        for event_id in range(1, 11):
            assert (await client.post(WEBHOOK, json=_event(event_id))).json()["accepted"]
        duplicate = await client.post(WEBHOOK, json=_event())
        assert duplicate.json()["duplicate"] is True
        for timestamp in (100.0, 159.999):
            now[0] = timestamp
            limited = await client.post(WEBHOOK, json=_event(11))
            assert limited.status_code == 200
            assert limited.json() == {"ok": True, "accepted": False, "reason": "rate_limited"}
            assert store.connector_delivery("connector:qq:11") is None
        isolated = await client.post(WEBHOOK, json=_event(12, user_id=43))
        assert isolated.json()["accepted"] is True
        now[0] = 160.0
        assert (await client.post(WEBHOOK, json=_event(11))).json()["accepted"] is True
    assert len(service.requests) == 12


@pytest.mark.asyncio
async def test_replay_without_delivery_store_does_not_consume_rate_quota() -> None:
    service = TurnService()
    async with _client(_registry(ratePerMinute=2), service) as client:
        assert (await client.post(WEBHOOK, json=_event())).json()["reply_sent"]
        duplicate = await client.post(WEBHOOK, json=_event())
        assert duplicate.json()["replayed"] is True
        assert (await client.post(WEBHOOK, json=_event(2))).json()["reply_sent"]
        assert (await client.post(WEBHOOK, json=_event(3))).json()["reason"] == "rate_limited"


@pytest.mark.asyncio
async def test_non_fast_ack_inflight_replay_shares_turn_and_quota(tmp_path) -> None:
    service = TurnService()
    service.release = asyncio.Event()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(_registry(ratePerMinute=2, maxConcurrent=1), service, store) as client:
        first = asyncio.create_task(client.post(WEBHOOK, json=_event()))
        while not service.requests:
            await asyncio.sleep(0)
        duplicate = asyncio.create_task(client.post(WEBHOOK, json=_event()))
        try:
            limited = await client.post(WEBHOOK, json=_event(2, user_id=43))
            assert limited.status_code == 200
            assert limited.json()["reason"] == "rate_limited"
            assert store.connector_delivery("connector:qq:2") is None
        finally:
            service.release.set()
        responses = await asyncio.gather(first, duplicate)
        assert all(response.status_code == 200 for response in responses)
        assert len(service.requests) == 1
        assert (await client.post(WEBHOOK, json=_event(3))).json()["reply_sent"] is True
        assert (await client.post(WEBHOOK, json=_event(4))).json()["reason"] == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.parametrize("max_concurrent", [1, 2])
async def test_global_concurrency_fast_ack_duplicate_and_slot_release(tmp_path, max_concurrent) -> None:
    registry = _registry(maxConcurrent=max_concurrent, ratePerMinute=1)
    service = TurnService()
    service.release = asyncio.Event()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(registry, service, store, fast_ack=True) as client:
        try:
            for event_id in range(1, max_concurrent + 1):
                response = await client.post(WEBHOOK, json=_event(event_id, user_id=event_id))
                assert response.json()["queued"] is True
                assert store.connector_delivery(f"connector:qq:{event_id}") is not None
            duplicate = await client.post(WEBHOOK, json=_event(1, user_id=1))
            assert duplicate.json()["queued"] is True
            assert duplicate.json()["duplicate"] is True
            limited = await client.post(WEBHOOK, json=_event(20, user_id=20))
            assert limited.status_code == 200
            assert limited.json()["reason"] == "rate_limited"
            assert store.connector_delivery("connector:qq:20") is None
        finally:
            service.release.set()
        for event_id in range(1, max_concurrent + 1):
            await _delivered(store, event_id)
        response = await client.post(WEBHOOK, json=_event(20, user_id=20))
        assert response.json()["queued"] is True
        await _delivered(store, 20)
    assert len(service.requests) == max_concurrent + 1


@pytest.mark.asyncio
async def test_enqueue_failure_releases_slot_and_does_not_consume_rate(tmp_path, monkeypatch) -> None:
    service = TurnService()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    original = store.record_connector_turn_pending

    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("test enqueue failed")

    async with _client(_registry(maxConcurrent=1, ratePerMinute=1), service, store, fast_ack=True) as client:
        monkeypatch.setattr(store, "record_connector_turn_pending", fail_enqueue)
        failed = await client.post(WEBHOOK, json=_event())
        assert failed.status_code == 503
        assert failed.json()["error"] == "connector_enqueue_failed"
        assert store.connector_delivery("connector:qq:1") is None
        monkeypatch.setattr(store, "record_connector_turn_pending", original)
        accepted = await client.post(WEBHOOK, json=_event(2))
        assert accepted.json()["queued"] is True
        await _delivered(store, 2)


@pytest.mark.asyncio
async def test_fast_ack_task_cancellation_releases_slot(tmp_path) -> None:
    service = TurnService()
    service.release = asyncio.Event()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(_registry(maxConcurrent=1), service, store, fast_ack=True) as client:
        try:
            assert (await client.post(WEBHOOK, json=_event())).json()["queued"] is True
            while not service.requests:
                await asyncio.sleep(0)
            cancelled = await client.post("/api/system/connectors/qq/events/1/cancel")
            assert cancelled.status_code == 200
            assert store.connector_delivery("connector:qq:1") is None
            assert (await client.post(WEBHOOK, json=_event(2))).json()["queued"] is True
        finally:
            service.release.set()
        await _delivered(store, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "unknown_effect", "cancelled"])
async def test_worker_failure_always_releases_inflight_slot(tmp_path, failure) -> None:
    service = TurnService()
    service.error = failure == "exception"
    service.outcome = failure if failure != "exception" else "completed"
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    async with _client(_registry(maxConcurrent=1), service, store) as client:
        failed = await client.post(WEBHOOK, json=_event())
        assert failed.status_code == (502 if failure == "exception" else 409)
        if failure != "exception":
            assert store.connector_delivery("connector:qq:1") is None
        service.error = False
        service.outcome = "completed"
        assert (await client.post(WEBHOOK, json=_event(2))).json()["reply_sent"] is True


@pytest.mark.asyncio
async def test_auth_and_reply_metadata_are_preserved(tmp_path) -> None:
    service = TurnService()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    event = _event()
    event["message"].insert(0, {"type": "reply", "data": {"id": "earlier"}})
    async with _client(_registry(), service, store) as client:
        denied = await client.post(WEBHOOK, json=event, headers={"Authorization": "Bearer wrong"})
        assert denied.status_code == 401
        assert store.connector_delivery("connector:qq:1") is None
        assert (await client.post(WEBHOOK, json=event)).json()["reply_sent"] is True
    assert service.requests[0].extra["connector_metadata"]["reply_id"] == "earlier"


def test_wechat_remains_generic_without_qq_event_filters() -> None:
    calls = []
    registry = MessageConnectorRegistry(env={}, http_post=lambda *args: calls.append(args) or {"ok": True})
    registry.update_config("wechat", {
        "bridgeUrl": "http://localhost:3000", "bridgeToken": "token", "bridgeProtocol": "onebot11",
    })
    event = {"id": "wx-1", "user_id": "42", "conversation_id": "group", "text": "hello"}
    message = registry.parse("wechat", event)
    assert message.text == "hello"
    registry.send_reply(message, "reply")
    assert calls[0][0] == "http://localhost:3000/send"
    assert registry.config_snapshot("wechat")["bridgeProtocol"] == "generic"
