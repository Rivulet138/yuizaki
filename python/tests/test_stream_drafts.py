from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.system.stream_drafts import StreamDraftService
from modules.system.stream_platforms import (
    InMemoryTwitchSubscriptionProvider,
    TwitchHelixSubscriptionProvider,
)
from modules.system.stream_runtime import StreamRuntime
from routes.system_api import create_system_router


class FakeTurnService:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[object] = []

    def build_context(self, _trigger: str, request: object) -> SimpleNamespace:
        self.request = request
        return SimpleNamespace(
            extra=dict(getattr(request, "extra", {})),
            workspace_id=getattr(request, "workspace_id", None),
            session_id=getattr(request, "session_id", ""),
            turn_id=getattr(request, "turn_id", None),
        )

    async def execute_context(self, _trigger: str, context: object) -> SimpleNamespace:
        self.calls += 1
        self.contexts.append(context)
        return SimpleNamespace(
            context=SimpleNamespace(turn_id="turn:stream-draft"),
            result=SimpleNamespace(reply="欢迎来到直播间！", outcome="completed", failure=None),
        )


class FlakyTurnService(FakeTurnService):
    async def execute_context(self, _trigger: str, context: object) -> SimpleNamespace:
        self.calls += 1
        self.contexts.append(context)
        if self.calls == 1:
            return SimpleNamespace(
                context=SimpleNamespace(turn_id="turn:stream-draft-failed"),
                result=SimpleNamespace(reply="", outcome="failed", failure="provider_failed"),
            )
        return SimpleNamespace(
            context=SimpleNamespace(turn_id="turn:stream-draft-retry"),
            result=SimpleNamespace(reply="重试后的直播回复", outcome="completed", failure=None),
        )


def test_obs_configuration_is_memory_only_and_redacts_password() -> None:
    stream = StreamRuntime()

    configured = stream.configure_obs({
        "endpoint": "ws://127.0.0.1:4455",
        "password": "super-secret",
    })

    assert configured["ok"] is True
    assert configured["passwordConfigured"] is True
    assert configured["endpoint"] == "ws://127.0.0.1:4455"
    snapshot = stream.snapshot()
    assert snapshot["adapter"]["configured"] is True
    assert snapshot["adapter"]["endpoint"] == "ws://127.0.0.1:4455"
    assert snapshot["adapter"]["passwordConfigured"] is True
    assert "super-secret" not in repr(configured)
    assert "super-secret" not in repr(snapshot)


def test_obs_configuration_requires_explicit_remote_opt_in() -> None:
    stream = StreamRuntime()
    with pytest.raises(ValueError, match="allowRemote"):
        stream.configure_obs({"endpoint": "ws://192.168.1.20:4455"})

    configured = stream.configure_obs({
        "endpoint": "wss://192.168.1.20:4455",
        "allowRemote": True,
    })
    assert configured["remoteAllowed"] is True
    assert stream.snapshot()["adapter"]["remoteAllowed"] is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:4455",
        "ws://user:password@127.0.0.1:4455",
        "ws://127.0.0.1:4455/?token=secret",
    ],
)
def test_obs_configuration_rejects_unsafe_endpoint(endpoint: str) -> None:
    stream = StreamRuntime()
    with pytest.raises(ValueError):
        stream.configure_obs({"endpoint": endpoint})
    assert stream.snapshot()["adapter"] is None


def test_obs_configuration_can_clear_runtime_adapter() -> None:
    stream = StreamRuntime()
    stream.configure_obs({"endpoint": "ws://localhost:4455", "password": "secret"})
    cleared = stream.configure_obs({"endpoint": "", "clearPassword": True})
    assert cleared["configured"] is False
    assert stream.snapshot()["adapter"] is None


def test_obs_configuration_route_is_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_obs_configure_handler=lambda _payload: {"ok": True},
    )
    assert "/api/system/stream/obs" in {route.path for route in router.routes}


class BlockingTurnService(FakeTurnService):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.active = 0
        self.max_active = 0

    async def execute_context(self, _trigger: str, context: object) -> SimpleNamespace:
        self.calls += 1
        self.contexts.append(context)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started.set()
        try:
            await self.release.wait()
        finally:
            self.active -= 1
        return SimpleNamespace(
            context=SimpleNamespace(turn_id="turn:stream-draft"),
            result=SimpleNamespace(reply="欢迎来到直播间！", outcome="completed", failure=None),
        )


def _service(tmp_path: Path) -> tuple[StreamRuntime, FakeTurnService, StreamDraftService]:
    stream = StreamRuntime(events_path=tmp_path / "stream_events.json")
    turn_service = FakeTurnService()
    host = SimpleNamespace(
        llm_client=object(),
        generation_mgr=object(),
        runtime=SimpleNamespace(
            tool_registry=object(),
            tool_executor=object(),
            step_executor=object(),
            scheduler=object(),
            trace_store=object(),
            plugin_manager=object(),
        ),
    )
    service = StreamDraftService(
        stream_runtime=stream,
        turn_service_provider=lambda: turn_service,
        runtime_provider=lambda: host,
        active_workspace_id_provider=lambda: "default",
        db_repo_provider=lambda: None,
        relationship_history_provider=list,
        relationship_summary_provider=dict,
        drafts_path=tmp_path / "stream_drafts.json",
    )
    return stream, turn_service, service


def _blocking_service(tmp_path: Path) -> tuple[StreamRuntime, BlockingTurnService, StreamDraftService]:
    stream = StreamRuntime(events_path=tmp_path / "stream_events.json")
    turn_service = BlockingTurnService()
    host = SimpleNamespace(
        llm_client=object(),
        generation_mgr=object(),
        runtime=SimpleNamespace(
            tool_registry=object(),
            tool_executor=object(),
            step_executor=object(),
            scheduler=object(),
            trace_store=object(),
            plugin_manager=object(),
        ),
    )
    service = StreamDraftService(
        stream_runtime=stream,
        turn_service_provider=lambda: turn_service,
        runtime_provider=lambda: host,
        active_workspace_id_provider=lambda: "default",
        db_repo_provider=lambda: None,
        relationship_history_provider=list,
        relationship_summary_provider=dict,
        drafts_path=tmp_path / "stream_drafts.json",
    )
    return stream, turn_service, service


def _flaky_service(tmp_path: Path) -> tuple[StreamRuntime, FlakyTurnService, StreamDraftService]:
    stream = StreamRuntime(events_path=tmp_path / "stream_events.json")
    turn_service = FlakyTurnService()
    host = SimpleNamespace(
        llm_client=object(),
        generation_mgr=object(),
        runtime=SimpleNamespace(
            tool_registry=object(),
            tool_executor=object(),
            step_executor=object(),
            scheduler=object(),
            trace_store=object(),
            plugin_manager=object(),
        ),
    )
    service = StreamDraftService(
        stream_runtime=stream,
        turn_service_provider=lambda: turn_service,
        runtime_provider=lambda: host,
        active_workspace_id_provider=lambda: "default",
        db_repo_provider=lambda: None,
        relationship_history_provider=list,
        relationship_summary_provider=dict,
        drafts_path=tmp_path / "stream_drafts.json",
    )
    return stream, turn_service, service


@pytest.mark.asyncio
async def test_generate_stream_draft_is_local_and_idempotent(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "你好", "author": "viewer"})
    event_id = queued["event"]["eventId"]

    first = await service.generate({"eventId": event_id})
    second = await service.generate({"eventId": event_id})

    assert first["ok"] is True
    assert first["created"] is True
    assert first["draft"]["reply"] == "欢迎来到直播间！"
    assert first["draft"]["externalSideEffects"] is False
    assert first["draft"]["sent"] is False
    assert second["created"] is False
    assert second["draft"]["draftId"] == first["draft"]["draftId"]
    assert turn_service.calls == 1
    context = turn_service.contexts[0]
    assert context.extra["allowed_tool_names"] == []
    assert context.extra["tool_budget"] == 0
    assert context.extra["stream_draft"] is True


@pytest.mark.asyncio
async def test_failed_stream_draft_requires_explicit_retry_and_can_recover(tmp_path: Path) -> None:
    stream, turn_service, service = _flaky_service(tmp_path)
    event_id = stream.enqueue_event({"kind": "chat", "text": "请再说一次", "author": "viewer"})["event"]["eventId"]

    failed = await service.generate({"eventId": event_id})
    duplicate = await service.generate({"eventId": event_id})
    recovered = await service.generate({"eventId": event_id, "retry": True})

    assert failed["created"] is True
    assert failed["draft"]["status"] == "failed"
    assert duplicate["created"] is False
    assert duplicate["draft"]["draftId"] == failed["draft"]["draftId"]
    assert recovered["created"] is True
    assert recovered["draft"]["status"] == "generated"
    assert recovered["draft"]["reply"] == "重试后的直播回复"
    assert recovered["draft"]["requestId"] == failed["draft"]["requestId"]
    assert turn_service.calls == 2
    assert stream.actions()["actions"] == []


@pytest.mark.asyncio
async def test_consume_pending_drafts_is_bounded_and_idempotent(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    events = [
        stream.enqueue_event({"kind": "chat", "text": f"hello-{index}", "author": "viewer"})["event"]
        for index in range(3)
    ]

    first = await service.consume_pending({"limit": 2})
    second = await service.consume_pending({"limit": 2})

    assert first["ok"] is True
    assert first["attempted"] == 2
    assert first["created"] == 2
    assert len(first["drafts"]) == 2
    assert second["attempted"] == 1
    assert second["created"] == 1
    assert second["errors"] == []
    assert turn_service.calls == 3
    assert {draft["eventId"] for draft in first["drafts"]} == {event["eventId"] for event in events[:2]}


@pytest.mark.asyncio
async def test_twitch_ingress_to_local_draft_has_no_external_side_effects(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    received = stream.ingest_twitch_irc(":viewer!user PRIVMSG #channel :请介绍一下今天的内容")
    event_id = received["event"]["eventId"]
    consumer = service.configure_consumer(
        state_path=tmp_path / "stream_draft_consumer.json",
        max_per_run=1,
    )
    consumer.set_enabled(True)
    stream.set_takeover(False)

    result = await consumer.consume_once()

    assert result["consumed"] == 1
    assert result["failures"] == 0
    assert turn_service.calls == 1
    event = stream.get_event(event_id)
    assert event is not None
    assert event["source"] == "twitch"
    assert event["draftState"] == "generated"
    drafts = service.snapshot()["drafts"]
    assert len(drafts) == 1
    assert drafts[0]["eventId"] == event_id
    assert drafts[0]["externalSideEffects"] is False
    assert drafts[0]["sent"] is False
    assert stream.actions()["actions"] == []


@pytest.mark.asyncio
async def test_consume_pending_rejects_workspace_mismatch_without_agent_call(tmp_path: Path) -> None:
    _stream, turn_service, service = _service(tmp_path)

    with pytest.raises(ValueError, match="active workspace") as error:
        await service.consume_pending({"workspaceId": "other", "limit": 1})

    assert getattr(error.value, "code", None) == "workspace_mismatch"
    assert turn_service.calls == 0


@pytest.mark.asyncio
async def test_opt_in_consumer_persists_state_and_respects_human_takeover(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "hello", "author": "viewer"})
    consumer = service.configure_consumer(
        state_path=tmp_path / "stream_draft_consumer.json",
        interval_seconds=0.1,
        max_per_run=1,
    )
    consumer.set_enabled(True)

    stream.set_takeover(True)
    paused = await consumer.consume_once()
    assert paused["skipped"] == "human_takeover"
    assert turn_service.calls == 0

    stream.set_takeover(False)
    consumed = await consumer.consume_once()
    assert consumed["consumed"] == 1
    assert consumed["failures"] == 0
    assert turn_service.calls == 1
    assert stream.get_event(queued["event"]["eventId"])["draftState"] == "generated"
    assert consumer.snapshot()["enabled"] is True

    restarted_stream, _restarted_turn, restarted_service = _service(tmp_path)
    restarted_consumer = restarted_service.configure_consumer(state_path=tmp_path / "stream_draft_consumer.json")
    assert restarted_consumer.snapshot()["enabled"] is True
    assert restarted_stream.get_event(queued["event"]["eventId"])["draftState"] == "generated"


@pytest.mark.asyncio
async def test_missing_event_is_rejected_without_agent_call(tmp_path: Path) -> None:
    _stream, turn_service, service = _service(tmp_path)

    with pytest.raises(ValueError, match="stream event was not found") as error:
        await service.generate({"eventId": "missing-event"})

    assert getattr(error.value, "code", None) == "event_not_found"
    assert turn_service.calls == 0


@pytest.mark.asyncio
async def test_draft_delivery_status_is_idempotent_and_unknown_effect_is_not_sent(tmp_path: Path) -> None:
    stream, _turn_service, service = _service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "hello", "author": "viewer"})
    generated = await service.generate({"eventId": queued["event"]["eventId"]})
    draft_id = generated["draft"]["draftId"]

    unknown = service.mark_delivery(draft_id, "unknown_effect")
    assert unknown["sendStatus"] == "unknown_effect"
    assert unknown["sent"] is False
    repeated = service.mark_delivery(draft_id, "known_success")
    assert repeated["sendStatus"] == "known_success"
    assert repeated["sent"] is True
    # Once the provider has been confirmed, later error observations cannot
    # regress the durable draft state or invite an automatic retry.
    stable = service.mark_delivery(draft_id, "failed")
    assert stable["sendStatus"] == "known_success"
    assert stable["sent"] is True


def test_drafts_survive_restart_and_corrupt_records_are_ignored(tmp_path: Path) -> None:
    stream, _turn_service, service = _service(tmp_path)
    queued = stream.enqueue_event({"kind": "caption", "text": "caption", "author": "host"})
    draft_path = tmp_path / "stream_drafts.json"
    draft_path.write_text(
        '{"schemaVersion":"yuizaki.stream-drafts.v1","drafts":[{"draftId":"bad"}]}',
        encoding="utf-8",
    )
    assert service.snapshot()["drafts"] == []
    assert stream.get_event(queued["event"]["eventId"])["text"] == "caption"


def test_twitch_ingress_is_tagged_and_routes_expose_drafts_only() -> None:
    stream = StreamRuntime()
    result = stream.ingest_twitch_irc(":viewer!user PRIVMSG #channel :hello")
    assert result["queued"] is True
    event = stream.get_event(result["event"]["eventId"])
    assert event is not None
    assert event["source"] == "twitch"

    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_drafts_handler=lambda _limit: {"drafts": []},
        stream_draft_generate_handler=lambda _payload: {"ok": True},
        stream_draft_consume_handler=lambda _payload: {"ok": True},
    )
    paths = {route.path for route in router.routes}
    assert "/api/system/stream/drafts" in paths
    assert "/api/system/stream/drafts/consume" in paths
    assert "/api/system/stream/drafts/{draft_id}/send" not in paths


def test_twitch_revocation_state_survives_restart_until_explicit_reset(tmp_path: Path) -> None:
    events_path = tmp_path / "stream_events.json"
    secret = "test-secret"
    stream = StreamRuntime(events_path=events_path, twitch_eventsub_secret=secret)
    body = json.dumps({"subscription": {"type": "channel.chat.message"}, "event": {"message": {"text": "hello"}}}).encode()
    message_id = "revocation-1"
    timestamp = datetime.now(timezone.utc).isoformat()
    signature = "sha256=" + hmac.new(secret.encode(), message_id.encode() + timestamp.encode() + body, hashlib.sha256).hexdigest()
    headers = {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": signature,
        "Twitch-Eventsub-Message-Type": "revocation",
    }
    stream.ingest_twitch_eventsub(body, headers)
    assert stream.snapshot()["platforms"]["twitch"]["revoked"] is True

    restarted = StreamRuntime(events_path=events_path, twitch_eventsub_secret=secret)
    twitch = restarted.snapshot()["platforms"]["twitch"]
    assert twitch["revoked"] is True
    assert twitch["connectionStatus"] == "revoked"
    reset = restarted.reconfigure_twitch()
    assert reset["externalSideEffects"] is False
    assert restarted.snapshot()["platforms"]["twitch"]["revoked"] is False


def test_twitch_eventsub_subscription_plan_is_local_and_persistent(tmp_path: Path) -> None:
    events_path = tmp_path / "stream_events.json"
    stream = StreamRuntime(events_path=events_path, twitch_eventsub_secret="test-secret")

    result = stream.configure_twitch_subscriptions({
        "subscriptions": ["channel.chat.message", "channel.follow", "channel.chat.message"],
    })
    plan = result["subscriptionPlan"]
    assert result["ok"] is True
    assert result["externalSideEffects"] is False
    assert plan["status"] == "planned"
    assert plan["management"] == "local_only"
    assert plan["remoteSyncAvailable"] is False
    assert plan["desired"] == ["channel.chat.message", "channel.follow"]
    assert plan["active"] == []

    restarted = StreamRuntime(events_path=events_path, twitch_eventsub_secret="test-secret")
    restarted_plan = restarted.snapshot()["platforms"]["twitch"]["subscriptionPlan"]
    assert restarted_plan["desired"] == ["channel.chat.message", "channel.follow"]
    assert restarted_plan["active"] == []
    assert restarted_plan["management"] == "local_only"


def test_twitch_eventsub_subscription_plan_rejects_unknown_types_without_mutation(tmp_path: Path) -> None:
    stream = StreamRuntime(events_path=tmp_path / "stream_events.json", twitch_eventsub_secret="test-secret")
    with pytest.raises(ValueError, match="unsupported EventSub subscription type"):
        stream.configure_twitch_subscriptions({"subscriptions": ["channel.unknown"]})
    assert stream.snapshot()["platforms"]["twitch"]["subscriptionPlan"]["desired"] == []


def test_twitch_staging_provider_is_idempotent_and_reconciles_with_preview(tmp_path: Path) -> None:
    provider = InMemoryTwitchSubscriptionProvider(["channel.follow"])
    stream = StreamRuntime(
        events_path=tmp_path / "stream_events.json",
        twitch_eventsub_secret="test-secret",
        twitch_subscription_provider=provider,
    )
    assert provider.create_subscription("channel.follow")["id"] == "staging-sub-1"
    stream.configure_twitch_subscriptions({"subscriptions": ["channel.chat.message", "channel.follow"]})
    stream.set_takeover(False)
    preview = stream.preview({"action": "stream.twitch_subscriptions_sync"})
    sync = preview["preview"]["subscriptionSync"]
    assert sync["provider"] == "in-memory-staging"
    assert sync["active"][0]["type"] == "channel.follow"
    assert sync["toCreate"] == ["channel.chat.message"]
    request_id = preview["preview"]["requestId"]
    result = stream.execute({"requestId": request_id, "action": "stream.twitch_subscriptions_sync", "params": {}, "confirmed": True})
    assert result["outcome"] == "known_success"
    assert result["result"]["subscriptionPlan"]["status"] == "synced"
    assert stream.snapshot()["platforms"]["twitch"]["subscriptionPlan"]["active"] == ["channel.follow", "channel.chat.message"]
    with pytest.raises(ValueError, match="unknown or already used"):
        stream.execute({"requestId": request_id, "action": "stream.twitch_subscriptions_sync", "params": {}, "confirmed": True})


def test_twitch_helix_provider_uses_explicit_http_boundary_without_leaking_secret() -> None:
    calls: list[dict[str, object]] = []

    class Response:
        def __init__(self, status_code: int, payload: object) -> None:
            self.status_code = status_code
            self._payload = payload
            self.content = b"{}"

        def json(self) -> object:
            return self._payload

    responses = [
        Response(200, {"data": [{"id": "sub-1", "type": "channel.follow", "status": "enabled"}]}),
        Response(202, {"data": [{"id": "sub-2", "type": "channel.chat.message", "status": "enabled"}]}),
        Response(204, {}),
    ]

    def request(method: str, url: str, **kwargs: object) -> Response:
        calls.append({"method": method, "url": url, **kwargs})
        return responses.pop(0)

    provider = TwitchHelixSubscriptionProvider(
        client_id="client-id",
        access_token="Bearer secret-token",
        broadcaster_id="broadcaster-1",
        callback_url="https://example.test/twitch/eventsub",
        secret="eventsub-secret-value",
        request=request,
    )
    assert provider.configured is True
    assert provider.list_subscriptions()[0]["type"] == "channel.follow"
    created = provider.create_subscription("channel.chat.message")
    assert created["id"] == "sub-2"
    deleted = provider.delete_subscription("sub-2")
    assert deleted == {"id": "sub-2", "type": "channel.chat.message", "status": "removed"}
    assert [call["method"] for call in calls] == ["GET", "POST", "DELETE"]
    post_body = calls[1]["json"]
    assert isinstance(post_body, dict)
    assert post_body["transport"]["callback"] == "https://example.test/twitch/eventsub"
    assert "secret-token" not in repr(created)
    assert "eventsub-secret-value" not in repr(deleted)


def test_twitch_helix_provider_is_fail_closed_when_callback_or_secret_is_weak() -> None:
    provider = TwitchHelixSubscriptionProvider(
        client_id="client-id",
        access_token="token",
        broadcaster_id="broadcaster-1",
        callback_url="http://localhost/eventsub",
        secret="short",
        request=lambda *_args, **_kwargs: None,
    )
    assert provider.configured is False
    with pytest.raises(ValueError, match="provider is not configured"):
        provider.list_subscriptions()


def test_twitch_subscription_sync_without_provider_is_not_executable(tmp_path: Path) -> None:
    stream = StreamRuntime(events_path=tmp_path / "stream_events.json", twitch_eventsub_secret="test-secret")
    stream.configure_twitch_subscriptions({"subscriptions": ["channel.follow"]})
    stream.set_takeover(False)
    capability = next(item for item in stream.snapshot()["capabilities"] if item["id"] == "stream.twitch_subscriptions_sync")
    assert capability["available"] is False
    with pytest.raises(RuntimeError, match="provider is not configured"):
        stream.preview({"action": "stream.twitch_subscriptions_sync"})


def test_twitch_subscription_provider_failure_records_unknown_effect(tmp_path: Path) -> None:
    class FailingProvider(InMemoryTwitchSubscriptionProvider):
        def create_subscription(self, subscription_type: str):
            raise RuntimeError("staging failure")

    provider = FailingProvider()
    stream = StreamRuntime(
        events_path=tmp_path / "stream_events.json",
        twitch_eventsub_secret="test-secret",
        twitch_subscription_provider=provider,
    )
    stream.configure_twitch_subscriptions({"subscriptions": ["channel.follow"]})
    stream.set_takeover(False)
    preview = stream.preview({"action": "stream.twitch_subscriptions_sync"})
    with pytest.raises(RuntimeError, match="unknown_effect"):
        stream.execute({"requestId": preview["preview"]["requestId"], "action": "stream.twitch_subscriptions_sync", "params": {}, "confirmed": True})
    assert stream.actions()["actions"][0]["status"] == "unknown_effect"


def test_chat_send_requires_preview_confirmation_and_uses_twitch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        status_code = 200
        content = b'{"data":[{"is_sent":true,"message_id":"msg-1"}]}'

        @staticmethod
        def json() -> dict[str, object]:
            return {"data": [{"is_sent": True, "message_id": "msg-1"}]}

    class Httpx:
        @staticmethod
        def post(url: str, **kwargs: object) -> Response:
            calls.append({"url": url, **kwargs})
            return Response()

    monkeypatch.setitem(sys.modules, "httpx", Httpx)
    stream = StreamRuntime(
        twitch_client_id="client",
        twitch_chat_token="token",
        twitch_broadcaster_id="broadcaster",
        twitch_sender_id="sender",
    )
    preview = stream.preview({"action": "stream.chat_send", "params": {"text": "hello"}})
    request_id = preview["preview"]["requestId"]
    assert preview["executed"] is False
    assert calls == []
    with pytest.raises(RuntimeError, match="human takeover"):
        stream.execute({"requestId": request_id, "action": "stream.chat_send", "params": {"text": "hello"}, "confirmed": True})
    assert calls == []

    stream.set_takeover(False)
    preview = stream.preview({"action": "stream.chat_send", "params": {"text": "hello"}})
    result = stream.execute({"requestId": preview["preview"]["requestId"], "action": "stream.chat_send", "params": {"text": "hello"}, "confirmed": True})
    assert result["ok"] is True
    assert result["externalSideEffects"] is True
    assert result["verificationStatus"] == "provider_acknowledged"
    assert calls[0]["url"] == "https://api.twitch.tv/helix/chat/messages"


def test_stream_action_history_persists_sending_and_known_success_before_restart(tmp_path: Path) -> None:
    actions_path = tmp_path / "stream_actions.json"

    class FakeObs:
        configured = True

        def start_stream(self) -> dict[str, object]:
            payload = json.loads(actions_path.read_text(encoding="utf-8"))
            assert payload["actions"][-1]["status"] == "sending"
            return {}

        def get_stream_status(self) -> dict[str, object]:
            return {"outputActive": True}

    stream = StreamRuntime(obs_adapter=FakeObs(), actions_path=actions_path)
    preview = stream.preview({"action": "stream.broadcast_start", "params": {}})
    stream.set_takeover(False)
    result = stream.execute({
        "requestId": preview["preview"]["requestId"],
        "action": "stream.broadcast_start",
        "params": {},
        "confirmed": True,
    })

    assert result["outcome"] == "known_success"
    history = stream.actions(10)["actions"]
    assert [item["status"] for item in history] == ["known_success", "sending"]
    assert all("params" not in item and "result" not in item for item in history)

    restarted = StreamRuntime(actions_path=actions_path)
    assert restarted.snapshot()["lastAction"]["status"] == "known_success"
    assert restarted.actions(10)["actions"] == history


def test_stream_action_provider_error_persists_unknown_effect_without_retry(tmp_path: Path) -> None:
    actions_path = tmp_path / "stream_actions.json"

    class FailingObs:
        configured = True

        def start_stream(self) -> dict[str, object]:
            raise TimeoutError("provider timed out")

    stream = StreamRuntime(obs_adapter=FailingObs(), actions_path=actions_path)
    preview = stream.preview({"action": "stream.broadcast_start", "params": {}})
    stream.set_takeover(False)
    with pytest.raises(RuntimeError, match="unknown_effect"):
        stream.execute({
            "requestId": preview["preview"]["requestId"],
            "action": "stream.broadcast_start",
            "params": {},
            "confirmed": True,
        })

    statuses = [item["status"] for item in stream.actions(10)["actions"]]
    assert statuses == ["unknown_effect", "sending"]
    restarted = StreamRuntime(actions_path=actions_path)
    assert [item["status"] for item in restarted.actions(10)["actions"]] == statuses
    assert "TimeoutError" == restarted.actions(1)["actions"][0]["errorCode"]


def test_stream_actions_route_is_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_actions_handler=lambda _limit: {"actions": []},
    )
    assert "/api/system/stream/actions" in {route.path for route in router.routes}


def test_twitch_eventsub_subscription_route_is_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_twitch_subscriptions_handler=lambda _payload: {"ok": True},
    )
    assert "/api/system/stream/twitch/subscriptions" in {route.path for route in router.routes}


@pytest.mark.asyncio
async def test_draft_consumer_is_opt_in_budgeted_and_idempotent(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    first = stream.enqueue_event({"kind": "chat", "text": "one", "author": "a"})
    second = stream.enqueue_event({"kind": "chat", "text": "two", "author": "b"})
    consumer = service.configure_consumer(state_path=tmp_path / "consumer.json", max_per_run=1)

    disabled = await consumer.consume_once()
    assert disabled["skipped"] == "disabled"
    assert turn_service.calls == 0
    consumer.set_enabled(True)
    stream.set_takeover(False)
    result = await consumer.consume_once()
    assert result["consumed"] == 1
    assert turn_service.calls == 1
    assert stream.get_event(first["event"]["eventId"])["draftState"] == "generated"
    assert stream.get_event(second["event"]["eventId"])["draftState"] == "pending"
    await consumer.consume_once()
    assert turn_service.calls == 2
    await consumer.consume_once()
    assert turn_service.calls == 2


@pytest.mark.asyncio
async def test_draft_consumer_lifecycle_is_opt_in_and_cancellable(tmp_path: Path) -> None:
    _stream, _turn_service, service = _service(tmp_path)
    consumer = service.configure_consumer(
        state_path=tmp_path / "consumer.json",
        interval_seconds=0.1,
    )

    disabled = await consumer.start()
    assert disabled["enabled"] is False
    assert disabled["running"] is False

    consumer.set_enabled(True)
    started = await consumer.start()
    assert started["enabled"] is True
    assert started["running"] is True

    stopped = await consumer.stop()
    assert stopped["running"] is False
    assert (await consumer.stop())["running"] is False


@pytest.mark.asyncio
async def test_draft_consumer_respects_human_takeover_and_restart_recovery(tmp_path: Path) -> None:
    stream, turn_service, service = _service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "hello", "author": "viewer"})
    state_path = tmp_path / "consumer.json"
    consumer = service.configure_consumer(state_path=state_path)
    consumer.set_enabled(True)
    blocked = await consumer.consume_once()
    assert blocked["skipped"] == "human_takeover"
    assert turn_service.calls == 0
    stream.set_takeover(False)
    claimed = stream.claim_next_draft_event()
    assert claimed is not None and claimed["draftState"] == "processing"
    # A fresh runtime turns an interrupted processing claim back into pending.
    restarted = StreamRuntime(events_path=tmp_path / "stream_events.json")
    assert restarted.get_event(queued["event"]["eventId"])["draftState"] == "pending"
    await consumer.stop()


@pytest.mark.asyncio
async def test_draft_consumer_serializes_concurrent_passes(tmp_path: Path) -> None:
    stream, turn_service, service = _blocking_service(tmp_path)
    stream.enqueue_event({"kind": "chat", "text": "one", "author": "a"})
    stream.enqueue_event({"kind": "chat", "text": "two", "author": "b"})
    consumer = service.configure_consumer(max_per_run=1)
    consumer.set_enabled(True)
    stream.set_takeover(False)

    first = asyncio.create_task(consumer.consume_once())
    await asyncio.wait_for(turn_service.started.wait(), timeout=1)
    second = asyncio.create_task(consumer.consume_once())
    await asyncio.sleep(0)
    assert not second.done()
    assert turn_service.max_active == 1

    turn_service.release.set()
    await asyncio.gather(first, second)
    assert turn_service.calls == 2
    assert turn_service.max_active == 1


@pytest.mark.asyncio
async def test_manual_draft_generation_is_single_flight_per_service(tmp_path: Path) -> None:
    stream, turn_service, service = _blocking_service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "hello", "author": "viewer"})
    event_id = queued["event"]["eventId"]

    first = asyncio.create_task(service.generate({"eventId": event_id}))
    await asyncio.wait_for(turn_service.started.wait(), timeout=1)
    second = asyncio.create_task(service.generate({"eventId": event_id}))
    await asyncio.sleep(0)
    assert not second.done()
    assert turn_service.calls == 1

    turn_service.release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result["created"] is True
    assert second_result["created"] is False
    assert turn_service.calls == 1


@pytest.mark.asyncio
async def test_draft_consumer_cancellation_releases_processing_claim(tmp_path: Path) -> None:
    stream, turn_service, service = _blocking_service(tmp_path)
    queued = stream.enqueue_event({"kind": "chat", "text": "hello", "author": "viewer"})
    consumer = service.configure_consumer()
    consumer.set_enabled(True)
    stream.set_takeover(False)

    task = asyncio.create_task(consumer.consume_once())
    await asyncio.wait_for(turn_service.started.wait(), timeout=1)
    assert stream.get_event(queued["event"]["eventId"])["draftState"] == "processing"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.get_event(queued["event"]["eventId"])["draftState"] == "pending"

    # A later pass can claim the event again after the interrupted turn.
    replacement = FakeTurnService()
    service._turn_service_provider = lambda: replacement
    result = await consumer.consume_once()
    assert result["consumed"] == 1
    assert replacement.calls == 1
