from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from threading import Event

import pytest

from modules.system.stream_runtime import StreamRuntime
from modules.system.twitch_connection import (
    TwitchConnectionSupervisor,
    TwitchIrcTransport,
)
from routes.system_api import create_system_router


def test_connection_retries_with_exponential_backoff_and_recovers() -> None:
    attempts: list[int] = []
    clock = [100.0]

    def connect() -> bool:
        attempts.append(1)
        return len(attempts) >= 3

    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=connect,
        clock=lambda: clock[0],
        base_backoff_seconds=2,
        max_backoff_seconds=10,
    )

    first = supervisor.start(now=100.0)
    assert first["status"] == "backoff"
    assert first["attempt"] == 1
    assert first["backoffSeconds"] == 2.0
    assert first["nextRetryInSeconds"] == 2.0

    clock[0] = 101.9
    assert supervisor.tick()["attempt"] == 1
    clock[0] = 102.0
    second = supervisor.tick()
    assert second["status"] == "backoff"
    assert second["attempt"] == 2
    assert second["backoffSeconds"] == 4.0

    clock[0] = 106.0
    third = supervisor.tick()
    assert third["status"] == "connected"
    assert third["attempt"] == 0
    assert third["nextRetryInSeconds"] is None
    assert len(attempts) == 3


def test_stop_cancels_retry_and_revocation_blocks_restart() -> None:
    closed: list[bool] = []
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: False,
        close=lambda: closed.append(True),
        clock=lambda: 0.0,
    )

    assert supervisor.start(now=0.0)["status"] == "backoff"
    stopped = supervisor.stop()
    assert stopped["status"] == "stopped"
    assert stopped["desired"] is False
    assert closed

    revoked = supervisor.mark_revoked()
    assert revoked["status"] == "revoked"
    assert revoked["desired"] is False
    assert supervisor.start(now=1.0)["status"] == "revoked"
    # A reconfigure clears the revocation marker before another attempt.
    supervisor.mark_revoked(False)
    assert supervisor.start(now=1.0)["status"] == "backoff"


def test_unconfigured_start_is_fail_closed() -> None:
    supervisor = TwitchConnectionSupervisor(configured=False)
    snapshot = supervisor.start(now=0.0)
    assert snapshot["status"] == "unconfigured"
    assert snapshot["desired"] is False


def test_auto_retry_worker_recovers_after_explicit_start() -> None:
    attempts: list[int] = []
    connected = Event()

    def connect() -> bool:
        attempts.append(1)
        if len(attempts) >= 2:
            connected.set()
            return True
        return False

    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=connect,
        close=lambda: None,
        base_backoff_seconds=0.1,
        max_backoff_seconds=0.1,
        auto_retry=True,
    )
    assert supervisor.start()["status"] == "backoff"
    assert connected.wait(1.0)
    for _ in range(20):
        if supervisor.snapshot()["status"] == "connected":
            break
        time.sleep(0.005)
    assert supervisor.snapshot()["status"] == "connected"
    supervisor.stop()


def test_stream_snapshot_exposes_irc_connection_state_without_opening_network() -> None:
    runtime = StreamRuntime()
    twitch = runtime.snapshot()["platforms"]["twitch"]
    assert twitch["ircConnection"]["status"] == "unconfigured"
    assert twitch["ircConnection"]["desired"] is False


def test_reconfigure_twitch_updates_runtime_without_returning_credentials() -> None:
    transport = TwitchIrcTransport(
        access_token="",
        channel="",
        username="",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    runtime = StreamRuntime(twitch_transport=transport)

    result = runtime.reconfigure_twitch({
        "clientId": "client-id",
        "eventsubSecret": "event-secret-123",
        "eventsubToken": "event-token",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "Yuizaki",
        "username": "yuizaki_bot",
    })

    assert result["ok"] is True
    assert "event-secret-123" not in str(result)
    assert "chat-token" not in str(result)
    assert result["configured"] == {
        "eventsub": True,
        "chat": True,
        "irc": True,
        "subscriptions": False,
    }
    snapshot = runtime.snapshot()["platforms"]["twitch"]
    assert snapshot["eventsubConfigured"] is True
    assert snapshot["chatConfigured"] is True
    assert snapshot["ircConnection"]["configured"] is True


def test_reconfigure_twitch_rejects_incomplete_helix_before_mutation() -> None:
    runtime = StreamRuntime()
    before = runtime.snapshot()["platforms"]["twitch"]

    try:
        runtime.reconfigure_twitch({"subscriptionProvider": "helix"})
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete Helix configuration should be rejected")

    after = runtime.snapshot()["platforms"]["twitch"]
    assert after["eventsubConfigured"] == before["eventsubConfigured"]
    assert after["chatConfigured"] == before["chatConfigured"]


def test_clearing_twitch_chat_credentials_stops_connection_intent() -> None:
    transport = TwitchIrcTransport(
        access_token="chat-token",
        channel="yuizaki",
        username="yuizaki-bot",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: True,
        close=lambda: None,
        auto_retry=False,
    )
    runtime = StreamRuntime(twitch_transport=transport, twitch_connection=supervisor)
    runtime.reconfigure_twitch({
        "clientId": "client-id",
        "eventsubSecret": "event-secret",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "yuizaki",
        "username": "yuizaki-bot",
    })
    assert runtime.connect_twitch()["ircConnection"]["desired"] is True

    result = runtime.reconfigure_twitch({"clearChatToken": True})

    assert result["ok"] is True
    twitch = runtime.snapshot()["platforms"]["twitch"]
    assert twitch["chatConfigured"] is False
    assert twitch["outboundActions"] is False
    assert twitch["ircConnection"]["configured"] is False
    assert twitch["ircConnection"]["desired"] is False
    assert twitch["ircConnection"]["status"] == "unconfigured"


def test_eventsub_revocation_immediately_stops_irc_reconnect_intent() -> None:
    transport = TwitchIrcTransport(
        access_token="chat-token",
        channel="yuizaki",
        username="yuizaki-bot",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: True,
        close=lambda: None,
        auto_retry=False,
    )
    runtime = StreamRuntime(twitch_transport=transport, twitch_connection=supervisor)
    runtime.reconfigure_twitch({
        "clientId": "client-id",
        "eventsubSecret": "event-secret",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "yuizaki",
        "username": "yuizaki-bot",
    })
    assert runtime.connect_twitch()["ircConnection"]["status"] == "connected"

    body = json.dumps({"subscription": {"status": "authorization_revoked"}}).encode()
    message_id = "revocation-message-1"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = hmac.new(
        b"event-secret",
        message_id.encode() + timestamp.encode() + body,
        hashlib.sha256,
    ).hexdigest()
    result = runtime.ingest_twitch_eventsub(body, {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": f"sha256={digest}",
        "Twitch-Eventsub-Message-Type": "revocation",
    })

    assert result["revoked"] is True
    snapshot = supervisor.snapshot()
    assert snapshot["status"] == "revoked"
    assert snapshot["desired"] is False


def test_runtime_connect_twitch_does_not_reconnect_after_revocation() -> None:
    attempts: list[int] = []
    transport = TwitchIrcTransport(
        access_token="chat-token",
        channel="yuizaki",
        username="yuizaki-bot",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: attempts.append(1) or True,
        close=lambda: None,
        auto_retry=False,
    )
    runtime = StreamRuntime(twitch_transport=transport, twitch_connection=supervisor)
    runtime.reconfigure_twitch({
        "clientId": "client-id",
        "eventsubSecret": "event-secret",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "yuizaki",
        "username": "yuizaki-bot",
    })
    assert runtime.connect_twitch()["ircConnection"]["status"] == "connected"
    assert len(attempts) == 1

    body = json.dumps({"subscription": {"status": "authorization_revoked"}}).encode()
    message_id = "revocation-no-reconnect"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = hmac.new(
        b"event-secret",
        message_id.encode() + timestamp.encode() + body,
        hashlib.sha256,
    ).hexdigest()
    runtime.ingest_twitch_eventsub(body, {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": f"sha256={digest}",
        "Twitch-Eventsub-Message-Type": "revocation",
    })

    reconnect = runtime.connect_twitch()
    assert reconnect["ok"] is False
    assert reconnect["ircConnection"]["status"] == "revoked"
    assert reconnect["ircConnection"]["desired"] is False
    assert len(attempts) == 1


def test_revocation_blocks_chat_preview_and_execute_before_provider_call() -> None:
    transport = TwitchIrcTransport(
        access_token="chat-token",
        channel="yuizaki",
        username="yuizaki-bot",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: True,
        close=lambda: None,
        auto_retry=False,
    )
    runtime = StreamRuntime(twitch_transport=transport, twitch_connection=supervisor)
    runtime.reconfigure_twitch({
        "clientId": "client-id",
        "eventsubSecret": "event-secret",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "yuizaki",
        "username": "yuizaki-bot",
    })
    calls: list[str] = []
    runtime._twitch_chat_adapter.send_message = lambda text: calls.append(text) or {"sent": True}

    body = json.dumps({"subscription": {"status": "authorization_revoked"}}).encode()
    message_id = "revocation-no-chat"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = hmac.new(
        b"event-secret",
        message_id.encode() + timestamp.encode() + body,
        hashlib.sha256,
    ).hexdigest()
    runtime.ingest_twitch_eventsub(body, {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": f"sha256={digest}",
        "Twitch-Eventsub-Message-Type": "revocation",
    })

    preview = runtime.preview({"action": "stream.chat_send", "params": {"text": "hello"}})
    assert preview["executed"] is False
    assert calls == []
    with pytest.raises(RuntimeError, match="EventSub is revoked"):
        runtime.execute({
            "requestId": preview["preview"]["requestId"],
            "action": "stream.chat_send",
            "params": {"text": "hello"},
            "confirmed": True,
        })
    assert calls == []


def test_revocation_is_rechecked_after_initial_capability_read() -> None:
    runtime = StreamRuntime(
        twitch_client_id="client-id",
        twitch_chat_token="chat-token",
        twitch_broadcaster_id="broadcaster",
        twitch_sender_id="sender",
    )
    calls: list[str] = []
    runtime._twitch_chat_adapter.send_message = lambda text: calls.append(text) or {"sent": True}
    preview = runtime.preview({"action": "stream.chat_send", "params": {"text": "hello"}})

    original_snapshot = runtime._twitch_ingress.snapshot
    reads = 0

    def revocation_changes_between_reads() -> dict[str, object]:
        nonlocal reads
        reads += 1
        snapshot = original_snapshot()
        return {**snapshot, "revoked": reads >= 2}

    runtime._twitch_ingress.snapshot = revocation_changes_between_reads  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="EventSub is revoked"):
        runtime.execute({
            "requestId": preview["preview"]["requestId"],
            "action": "stream.chat_send",
            "params": {"text": "hello"},
            "confirmed": True,
        })

    assert reads == 2
    assert calls == []


def test_full_twitch_reconfigure_clears_revocation_and_allows_reconnect() -> None:
    attempts: list[int] = []
    transport = TwitchIrcTransport(
        access_token="chat-token",
        channel="yuizaki",
        username="yuizaki-bot",
        on_line=lambda _line: None,
        websocket_factory=lambda *_args, **_kwargs: None,
    )
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: attempts.append(1) or True,
        close=lambda: None,
        auto_retry=False,
    )
    runtime = StreamRuntime(twitch_transport=transport, twitch_connection=supervisor)
    initial = {
        "clientId": "client-id",
        "eventsubSecret": "event-secret",
        "chatToken": "chat-token",
        "broadcasterId": "broadcaster",
        "senderId": "sender",
        "channel": "yuizaki",
        "username": "yuizaki-bot",
    }
    runtime.reconfigure_twitch(initial)
    assert runtime.connect_twitch()["ircConnection"]["status"] == "connected"

    body = json.dumps({"subscription": {"status": "authorization_revoked"}}).encode()
    message_id = "revocation-reconfigure"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    digest = hmac.new(
        b"event-secret",
        message_id.encode() + timestamp.encode() + body,
        hashlib.sha256,
    ).hexdigest()
    runtime.ingest_twitch_eventsub(body, {
        "Twitch-Eventsub-Message-Id": message_id,
        "Twitch-Eventsub-Message-Timestamp": timestamp,
        "Twitch-Eventsub-Message-Signature": f"sha256={digest}",
        "Twitch-Eventsub-Message-Type": "revocation",
    })
    assert runtime.snapshot()["platforms"]["twitch"]["revoked"] is True

    result = runtime.reconfigure_twitch({
        **initial,
        "eventsubSecret": "event-secret-rotated",
        "chatToken": "chat-token-rotated",
    })
    assert result["ok"] is True
    assert result["revocation"]["revoked"] is False
    assert result["twitch"]["revoked"] is False
    assert "event-secret-rotated" not in str(result)
    assert "chat-token-rotated" not in str(result)

    connected = runtime.connect_twitch()
    assert connected["ircConnection"]["status"] == "connected"
    assert connected["ircConnection"]["desired"] is True
    assert len(attempts) == 2


def test_twitch_connection_routes_are_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_twitch_connect_handler=dict,
        stream_twitch_disconnect_handler=dict,
        stream_twitch_tick_handler=dict,
        stream_twitch_reconfigure_handler=dict,
    )
    paths = {route.path for route in router.routes}
    assert "/api/system/stream/twitch/connect" in paths
    assert "/api/system/stream/twitch/disconnect" in paths
    assert "/api/system/stream/twitch/tick" in paths
    assert "/api/system/stream/twitch/config" in paths


def test_irc_transport_authenticates_handles_ping_and_reports_disconnect() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.frames = ["PING :tmi.twitch.tv", ":viewer!user PRIVMSG #channel :hello", ""]
            self.closed = False

        def settimeout(self, _seconds: float) -> None:
            return

        def send(self, value: str) -> None:
            self.sent.append(value)

        def recv(self) -> str:
            return self.frames.pop(0)

        def close(self) -> None:
            self.closed = True

    fake = FakeSocket()
    lines: list[str] = []
    disconnects: list[str] = []
    transport = TwitchIrcTransport(
        access_token="oauth-token",
        channel="#Channel",
        username="yuizaki",
        on_line=lines.append,
        on_disconnect=disconnects.append,
        websocket_factory=lambda *_args, **_kwargs: fake,
    )

    assert transport.configured is True
    assert transport.connect() is True
    for _ in range(20):
        if disconnects:
            break
        time.sleep(0.005)
    transport.close()

    assert fake.sent[:4] == [
        "PASS oauth:oauth-token\r\n",
        "NICK yuizaki\r\n",
        "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n",
        "JOIN #channel\r\n",
    ]
    assert "PONG :tmi.twitch.tv\r\n" in fake.sent
    assert lines == [":viewer!user PRIVMSG #channel :hello"]
    assert disconnects


def test_irc_transport_server_reconnect_enters_retryable_disconnect_state() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed = False

        def settimeout(self, _seconds: float) -> None:
            return

        def send(self, value: str) -> None:
            self.sent.append(value)

        def recv(self) -> str:
            return "RECONNECT"

        def close(self) -> None:
            self.closed = True

    fake = FakeSocket()
    disconnects: list[str] = []
    transport = TwitchIrcTransport(
        access_token="token",
        channel="channel",
        username="user",
        on_line=lambda _line: None,
        on_disconnect=disconnects.append,
        websocket_factory=lambda *_args, **_kwargs: fake,
    )
    assert transport.connect() is True
    for _ in range(20):
        if disconnects:
            break
        time.sleep(0.005)
    transport.close()
    assert disconnects == ["server_reconnect"]


def test_authentication_failure_disables_automatic_retry() -> None:
    supervisor = TwitchConnectionSupervisor(
        configured=True,
        connect=lambda: False,
        clock=lambda: 0.0,
    )
    supervisor.start(now=0.0)
    result = supervisor.mark_disconnected("auth_failed", now=1.0)
    assert result["status"] == "stopped"
    assert result["desired"] is False
    assert result["nextRetryInSeconds"] is None
