from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.system.stream_moderation import StreamModerationPolicy
from modules.system.stream_runtime import StreamRuntime
from routes.system_api import create_system_router


def test_policy_blocks_casefolded_terms_and_keeps_decision_bounded() -> None:
    policy = StreamModerationPolicy(blocked_terms=["spoiler", "剧透"])

    decision = policy.evaluate("这条 SPOILER 不应该发出", now=100.0)

    assert decision.allowed is False
    assert decision.reason_code == "blocked_term"
    assert decision.matched_term_count == 1
    assert decision.retry_after_seconds is None
    assert "这条" not in json.dumps(decision.snapshot(), ensure_ascii=False)


def test_policy_enforces_slow_mode_and_rate_limit() -> None:
    slow = StreamModerationPolicy(slow_mode_seconds=5, max_messages_per_minute=3)
    assert slow.evaluate("one", [100.0], now=102.0).reason_code == "slow_mode"
    assert slow.evaluate("one", [100.0], now=105.0).allowed is True

    limited = StreamModerationPolicy(max_messages_per_minute=2)
    decision = limited.evaluate("three", [40.0, 50.0], now=100.0)
    assert decision.allowed is False
    assert decision.reason_code == "rate_limit"
    assert decision.retry_after_seconds == 0.01


def test_runtime_moderation_configuration_persists_and_is_exposed(tmp_path: Path) -> None:
    events_path = tmp_path / "events.json"
    moderation_path = tmp_path / "moderation.json"
    stream = StreamRuntime(events_path=events_path, moderation_path=moderation_path)

    updated = stream.configure_moderation({
        "enabled": True,
        "blockedTerms": ["spoiler"],
        "slowModeSeconds": 2,
        "maxMessagesPerMinute": 12,
    })

    assert updated["ok"] is True
    assert updated["moderation"]["blockedTerms"] == ["spoiler"]
    assert stream.snapshot()["policy"]["moderation"]["slowModeSeconds"] == 2.0
    assert moderation_path.is_file()

    restarted = StreamRuntime(events_path=events_path, moderation_path=moderation_path)
    assert restarted.moderation()["moderation"]["maxMessagesPerMinute"] == 12
    assert restarted.moderation()["moderation"]["blockedTerms"] == ["spoiler"]


def test_chat_preview_rejects_blocked_text_and_exposes_allowed_decision(tmp_path: Path) -> None:
    stream = StreamRuntime(
        events_path=tmp_path / "events.json",
        twitch_client_id="client",
        twitch_chat_token="token",
        twitch_broadcaster_id="broadcaster",
        twitch_sender_id="sender",
    )
    stream.configure_moderation({"blockedTerms": ["secret"]})

    with pytest.raises(ValueError, match="blocked_term"):
        stream.preview({"action": "stream.chat_send", "params": {"text": "secret message"}})

    preview = stream.preview({"action": "stream.chat_send", "params": {"text": "hello"}})
    assert preview["preview"]["moderation"]["allowed"] is True
    assert preview["preview"]["moderation"]["reasonCode"] == "allowed"


def test_execute_claim_is_single_use_and_rechecks_moderation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200
        content = b'{"data":[{"is_sent":true,"message_id":"msg-1"}]}'

        @staticmethod
        def json() -> dict[str, object]:
            return {"data": [{"is_sent": True, "message_id": "msg-1"}]}

    class Httpx:
        calls = 0

        @staticmethod
        def post(_url: str, **_kwargs: object) -> Response:
            Httpx.calls += 1
            return Response()

    import sys

    monkeypatch.setitem(sys.modules, "httpx", Httpx)
    stream = StreamRuntime(
        events_path=tmp_path / "events.json",
        twitch_client_id="client",
        twitch_chat_token="token",
        twitch_broadcaster_id="broadcaster",
        twitch_sender_id="sender",
    )
    stream.set_takeover(False)
    preview = stream.preview({"action": "stream.chat_send", "params": {"text": "hello"}})
    payload = {
        "requestId": preview["preview"]["requestId"],
        "action": "stream.chat_send",
        "params": {"text": "hello"},
        "confirmed": True,
    }

    result = stream.execute(payload)
    assert result["ok"] is True
    with pytest.raises(ValueError, match="unknown or already used"):
        stream.execute(payload)
    assert Httpx.calls == 1


def test_stream_moderation_routes_are_exposed() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        stream_moderation_handler=dict,
        stream_moderation_update_handler=lambda _payload: {},
    )
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/api/system/stream/moderation", ("GET",)) in paths
    assert ("/api/system/stream/moderation", ("PATCH",)) in paths
