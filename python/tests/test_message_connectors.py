from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.agent.context import AgentPipelineResult
from modules.agent.turn_service import TurnPorts, TurnService
from modules.agent.turn_store import TurnCommitStore
from modules.system.message_connectors import (
    ConnectorMessage,
    MessageConnectorError,
    MessageConnectorRegistry,
    verify_discord_signature,
)
from routes.connector_api import MAX_CONNECTOR_BODY_BYTES, create_message_connector_router

TELEGRAM_WEBHOOK_SECRET = "test-webhook-secret"
TELEGRAM_WEBHOOK_HEADERS = {
    "X-Telegram-Bot-Api-Secret-Token": TELEGRAM_WEBHOOK_SECRET,
}
TELEGRAM_WEBHOOK_ENV = {
    "YUIZAKI_TELEGRAM_BOT_TOKEN": "token",
    "YUIZAKI_TELEGRAM_ENABLED": "1",
    "YUIZAKI_TELEGRAM_WEBHOOK_SECRET": TELEGRAM_WEBHOOK_SECRET,
}


@pytest.mark.asyncio
async def test_chunked_connector_webhook_rejects_oversized_body_before_parsing() -> None:
    registry = MessageConnectorRegistry(env=TELEGRAM_WEBHOOK_ENV)
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: object(),
        active_workspace_id_provider=lambda: "default",
    ))

    async def oversized_body():
        yield b"{" + (b"a" * (MAX_CONNECTOR_BODY_BYTES // 2))
        yield b"a" * (MAX_CONNECTOR_BODY_BYTES // 2 + 1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/system/connectors/telegram/webhook",
            headers=TELEGRAM_WEBHOOK_HEADERS,
            content=oversized_body(),
        )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_connector_delivery_observability_and_manual_retry(tmp_path) -> None:
    sent: list[str] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_TELEGRAM_BOT_TOKEN": "token", "YUIZAKI_TELEGRAM_ENABLED": "1"},
        http_post=lambda _url, _headers, payload: sent.append(str(payload["text"])) or {"ok": True},
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    message = ConnectorMessage(
        connector_id="telegram", event_id="event-1", session_id="connector:telegram:chat:1",
        external_user_id="user-1", conversation_id="1", text="hello", reply_target={"chat_id": "1"},
    )
    owner = "seed"
    claim = store.claim_connector_delivery(
        "connector:telegram:event-1", "connector:telegram:event-1", "telegram", "event-1", owner,
        message=message.__dict__, reply_text="saved reply",
    )
    assert claim["attempt_count"] == 1
    assert store.mark_connector_delivery_failed("connector:telegram:event-1", owner, "provider timeout")
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    client = TestClient(app, headers=TELEGRAM_WEBHOOK_HEADERS)
    listed = client.get("/api/system/connectors/telegram/deliveries?status=failed")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["attempt_count"] == 1
    assert listed.json()["items"][0]["last_error"] == "provider timeout"
    assert "message_json" not in listed.json()["items"][0]
    retried = client.post("/api/system/connectors/telegram/deliveries/connector:telegram:event-1/retry")
    assert retried.status_code == 200
    assert retried.json()["retried"] is True
    assert retried.json()["delivery"]["status"] == "delivered"
    assert retried.json()["delivery"]["attempt_count"] == 2
    assert sent == ["saved reply"]


def test_persisted_discord_retry_reports_expired_interaction_window(tmp_path) -> None:
    patches: list[dict] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda _url, _headers, payload: patches.append(dict(payload)) or {"ok": True},
        clock=lambda: 1001.0,
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    message = ConnectorMessage(
        connector_id="discord",
        event_id="interaction-expired",
        session_id="connector:discord:channel:channel-1",
        external_user_id="user-1",
        conversation_id="channel-1",
        text="/ask hello",
        reply_target={
            "interaction_id": "interaction-expired",
            "interaction_token": "interaction-token",
            "application_id": "app-1",
            "channel_id": "channel-1",
            "interaction_expires_at": "1000",
        },
    )
    owner = "seed"
    store.claim_connector_delivery(
        "connector:discord:interaction-expired",
        "connector:discord:interaction-expired",
        "discord",
        "interaction-expired",
        owner,
        message=message.__dict__,
        reply_text="saved reply",
    )
    assert store.mark_connector_delivery_failed(
        "connector:discord:interaction-expired",
        owner,
        "provider timeout",
    )
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    response = TestClient(app).post(
        "/api/system/connectors/discord/deliveries/connector:discord:interaction-expired/retry",
    )
    assert response.status_code == 502
    assert response.json()["error"] == "delivery_failed"
    assert response.json()["delivery"]["last_error"] == "interaction_token_expired"
    assert patches == []


def test_adapters_are_uninstalled_without_credentials() -> None:
    registry = MessageConnectorRegistry(env={})
    rows = {row["id"]: row for row in registry.snapshot()}
    assert rows["telegram"]["state"] == "uninstalled"
    assert rows["discord"]["state"] == "uninstalled"
    assert rows["telegram"]["experimental"] is True
    assert rows["discord"]["experimental"] is True
    assert rows["telegram"]["canDisable"] is False
    assert rows["discord"]["message"] == "适配器未配置 Public Key"
    assert rows["qq"]["state"] == "uninstalled"
    assert rows["wechat"]["state"] == "uninstalled"


def test_personal_bridge_qq_login_onebot_message_and_logout(tmp_path) -> None:
    calls = []
    def post(url, headers, payload):
        calls.append((url, dict(headers), dict(payload)))
        if url.endswith('/login'):
            return {'state': 'awaiting_scan', 'qr_url': 'http://127.0.0.1:3000/qr/1'}
        return {'ok': True}
    registry = MessageConnectorRegistry(state_path=tmp_path / 'connectors.json', env={}, http_post=post)
    registry.update_config('qq', {'enabled': True, 'accountMode': 'personal_bridge', 'bridgeUrl': 'http://127.0.0.1:3000', 'bridgeProtocol': 'onebot11', 'bridgeToken': 'secret'})
    account = registry.login_account('qq')
    assert account['loginState'] == 'awaiting_scan'
    message = registry.parse('qq', {'post_type': 'message', 'message_type': 'group', 'message_id': 9, 'group_id': 42, 'user_id': 7, 'message': [{'type': 'text', 'data': {'text': '你好'}}]})
    assert message is not None and message.conversation_id == '42'
    assert registry.send_reply(message, '回复')['ok'] is True
    assert calls[-1][0].endswith('/send_group_msg')
    assert registry.logout_account('qq')['loginState'] == 'signed_out'


def test_personal_bridge_can_be_unbound_through_account_endpoint(tmp_path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json", env={})
    registry.update_config("qq", {
        "enabled": True,
        "bridgeUrl": "http://127.0.0.1:3000",
        "bridgeProtocol": "onebot11",
        "bridgeToken": "bridge-secret",
    })
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))

    response = TestClient(app).delete("/api/system/connectors/qq/account")

    assert response.status_code == 200
    assert response.json()["account"]["loginState"] == "signed_out"
    config = response.json()["config"]
    assert config["id"] == "qq"
    assert config["enabled"] is False
    assert config["bridgeUrl"] == ""
    assert config["bridgeProtocol"] == "generic"
    assert config["bridgeUrlConfigured"] is False
    assert config["bridgeTokenConfigured"] is False
    persisted = (tmp_path / "connectors.json").read_text(encoding="utf-8")
    assert "bridge-secret" not in persisted
    assert "127.0.0.1:3000" not in persisted


def test_personal_bridge_wechat_accepts_json_message(tmp_path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / 'connectors.json', env={}, http_post=lambda *_args: {'ok': True})
    registry.update_config('wechat', {'enabled': True, 'bridgeUrl': 'http://127.0.0.1:3100', 'bridgeToken': 'secret'})
    message = registry.parse('wechat', {'event_id': 'wx-1', 'openid': 'user-1', 'text': 'hello'})
    assert message is not None and message.session_id == 'connector:wechat:user:user-1'


def test_qq_wechat_have_no_official_connector_surface(tmp_path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json", env={})
    qq = registry.update_config("qq", {"enabled": True, "bridgeUrl": "http://127.0.0.1:3000", "bridgeToken": "qq-secret"})
    wechat = registry.update_config("wechat", {"enabled": True, "bridgeUrl": "http://127.0.0.1:3100", "bridgeToken": "wechat-secret"})
    assert qq["accountMode"] == "personal_bridge"
    assert wechat["accountMode"] == "personal_bridge"
    assert "botTokenConfigured" not in qq
    assert "botTokenConfigured" not in wechat
    for field in ("botToken", "webhookSecret", "publicKey", "appId", "appSecret", "apiBaseUrl"):
        with pytest.raises(MessageConnectorError, match="官方连接器已移除"):
            registry.update_config("qq", {field: "legacy-value"})
    # Official QQ event envelopes are not accepted by the bridge-only parser.
    assert registry.parse("qq", {"id": "official-1", "d": {"content": "hello", "channel_id": "1"}}) is None


def test_qq_wechat_ignore_legacy_official_credentials_from_state_and_env(tmp_path) -> None:
    state_path = tmp_path / "connectors.json"
    state_path.write_text(
        '{"connectors": {"qq": {"enabled": true, "botToken": "old-bot", '
        '"webhookSecret": "old-secret", "appId": "old-app", '
        '"bridgeUrl": "http://127.0.0.1:3000"}}}',
        encoding="utf-8",
    )
    registry = MessageConnectorRegistry(
        state_path=state_path,
        env={"YUIZAKI_QQ_BOT_TOKEN": "old-env-token", "YUIZAKI_QQ_ENABLED": "1"},
    )
    snapshot = registry.config_snapshot("qq")
    assert snapshot is not None
    assert snapshot["accountMode"] == "personal_bridge"
    assert "botTokenConfigured" not in snapshot
    assert registry._token("qq") == ""  # removed official token is never a fallback

    registry.update_config("qq", {"enabled": True, "bridgeToken": "new-bridge-secret"})
    persisted = state_path.read_text(encoding="utf-8")
    assert "old-bot" not in persisted
    assert "old-secret" not in persisted
    assert "old-app" not in persisted


def test_personal_bridge_webhook_uses_shared_turn_service_and_group_reply(tmp_path) -> None:
    calls: list[tuple[str, dict]] = []

    def post(url, _headers, payload):
        calls.append((url, dict(payload)))
        return {"ok": True}

    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json", env={}, http_post=post)
    registry.update_config("qq", {
        "enabled": True,
        "bridgeUrl": "http://127.0.0.1:3000",
        "bridgeProtocol": "onebot11",
        "bridgeToken": "bridge-secret",
    })

    class FakeTurnService:
        async def execute(self, _trigger, request):
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="桥接回复"),
                replayed=False,
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: FakeTurnService(),
        active_workspace_id_provider=lambda: "workspace-a",
    ))
    response = TestClient(app, headers={"Authorization": "Bearer bridge-secret"}).post("/api/system/connectors/qq/webhook", json={
        "post_type": "message",
        "message_type": "group",
        "message_id": 12,
        "group_id": 42,
        "user_id": 7,
        "message": [{"type": "text", "data": {"text": "你好"}}],
    })
    assert response.status_code == 200
    assert response.json()["reply_sent"] is True
    assert calls == [("http://127.0.0.1:3000/send_group_msg", {"group_id": "42", "message": "桥接回复"})]


def test_enabled_telegram_sends_and_persists_disable_state(tmp_path) -> None:
    calls: list[tuple[str, dict, dict]] = []

    def post(url, headers, payload):
        calls.append((url, dict(headers), dict(payload)))
        return {"ok": True}

    registry = MessageConnectorRegistry(
        state_path=tmp_path / "connectors.json",
        env={"YUIZAKI_TELEGRAM_BOT_TOKEN": "bot-token", "YUIZAKI_TELEGRAM_ENABLED": "true"},
        http_post=post,
    )
    message = registry.parse("telegram", {"update_id": 7, "message": {"message_id": 9, "chat": {"id": 42}, "from": {"id": 5}, "text": "hello"}})
    assert message is not None
    assert message.session_id == "connector:telegram:chat:42"
    registry.send_reply(message, "reply")
    assert calls[0][0].endswith("/sendMessage")
    assert calls[0][2] == {"chat_id": "42", "text": "reply"}

    disabled = registry.disable("telegram")
    assert disabled is not None and disabled["state"] == "disabled"
    reloaded = MessageConnectorRegistry(
        state_path=tmp_path / "connectors.json",
        env={"YUIZAKI_TELEGRAM_BOT_TOKEN": "bot-token", "YUIZAKI_TELEGRAM_ENABLED": "true"},
    )
    assert reloaded.snapshot()[0]["state"] == "disabled"


def test_connector_config_is_persisted_without_returning_secrets(tmp_path) -> None:
    state_path = tmp_path / "connectors.json"
    registry = MessageConnectorRegistry(state_path=state_path, env={})
    snapshot = registry.update_config("telegram", {
        "enabled": True,
        "botToken": "secret-token",
        "webhookSecret": "secret-header",
    })
    assert snapshot == {
        "id": "telegram",
        "enabled": True,
        "botTokenConfigured": True,
        "webhookSecretConfigured": True,
        "publicKeyConfigured": False,
        "webhookPath": "/api/system/connectors/telegram/webhook",
    }
    assert "secret-token" not in str(snapshot)
    reloaded = MessageConnectorRegistry(state_path=state_path, env={})
    assert reloaded.config_snapshot("telegram") == snapshot


def test_telegram_requires_update_id() -> None:
    registry = MessageConnectorRegistry(env={"YUIZAKI_TELEGRAM_BOT_TOKEN": "token", "YUIZAKI_TELEGRAM_ENABLED": "1"})
    with pytest.raises(MessageConnectorError, match="update_id"):
        registry.parse("telegram", {"message": {"chat": {"id": 1}, "text": "hello"}})


def test_discord_rfc8032_signature_vector() -> None:
    signature = (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    public_key = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert verify_discord_signature(body=b"", timestamp="", signature=signature, public_key=public_key)
    assert not verify_discord_signature(body=b"tampered", timestamp="", signature=signature, public_key=public_key)


def test_discord_webhook_secret_field_does_not_override_ed25519() -> None:
    signature = (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    public_key = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    registry = MessageConnectorRegistry(env={
        "YUIZAKI_DISCORD_PUBLIC_KEY": public_key,
        "YUIZAKI_DISCORD_WEBHOOK_SECRET": "unused-proxy-secret",
    })
    assert registry.verify_request("discord", {
        "X-Signature-Timestamp": "",
        "X-Signature-Ed25519": signature,
    }, b"")


def test_discord_signature_requires_public_key() -> None:
    registry = MessageConnectorRegistry(env={"YUIZAKI_DISCORD_ENABLED": "1"})
    assert registry.verify_request("discord", {}, b'{"type":1}') is False


def test_telegram_webhook_secret_is_required_and_enforced() -> None:
    missing = MessageConnectorRegistry(
        env={"YUIZAKI_TELEGRAM_BOT_TOKEN": "token", "YUIZAKI_TELEGRAM_ENABLED": "1"},
    )
    assert missing.is_enabled("telegram") is False
    assert missing.verify_request("telegram", {}, b"{}") is False

    protected = MessageConnectorRegistry(env={
        "YUIZAKI_TELEGRAM_BOT_TOKEN": "token",
        "YUIZAKI_TELEGRAM_ENABLED": "1",
        "YUIZAKI_TELEGRAM_WEBHOOK_SECRET": "recommended-secret",
    })
    assert protected.verify_request("telegram", {}, b"{}") is False
    assert protected.verify_request(
        "telegram",
        {"X-Telegram-Bot-Api-Secret-Token": "recommended-secret"},
        b"{}",
    ) is True


@pytest.mark.parametrize("connector_id", ["qq", "wechat"])
def test_personal_bridge_requires_token_before_enable(connector_id: str) -> None:
    registry = MessageConnectorRegistry(env={})

    with pytest.raises(MessageConnectorError) as exc:
        registry.update_config(connector_id, {
            "enabled": True,
            "bridgeUrl": "http://127.0.0.1:3000",
        })

    assert exc.value.code == "missing_bridge_token"
    assert registry.verify_request(connector_id, {}, b"{}") is False


def test_discord_original_response_patch_treats_204_as_success() -> None:
    patches: list[tuple[str, dict]] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda url, _headers, payload: patches.append((url, dict(payload))) or {"status_code": 204},
        clock=lambda: 100.0,
    )
    message = registry.parse("discord", {
        "id": "interaction-1",
        "application_id": "app-1",
        "type": 2,
        "token": "interaction-token",
        "channel_id": "channel-1",
        "member": {"user": {"id": "user-1"}},
        "data": {"name": "ask", "options": [{"name": "prompt", "value": "hello"}]},
    })
    assert message is not None
    delivery = registry.send_reply(message, "reply")
    assert delivery["status_code"] == 204
    assert delivery.get("ok") is None
    assert patches == [(
        "https://discord.com/api/v10/webhooks/app-1/interaction-token/messages/@original",
        {"content": "reply", "allowed_mentions": {"parse": []}},
    )]


def test_discord_adapter_rejects_ordinary_message_without_gateway_ingress() -> None:
    registry = MessageConnectorRegistry(env={})
    assert registry.parse("discord", {
        "id": "message-1",
        "channel_id": "channel-1",
        "author": {"id": "user-1"},
        "content": "hello",
    }) is None


def test_expired_discord_interaction_requires_bot_token_for_channel_fallback() -> None:
    now = [100.0]
    posts: list[tuple[str, dict, dict]] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_post=lambda url, headers, payload: posts.append((url, dict(headers), dict(payload))) or {"ok": True},
        clock=lambda: now[0],
    )
    message = registry.parse("discord", {
        "id": "interaction-expiring",
        "application_id": "app-1",
        "type": 2,
        "token": "interaction-token",
        "channel_id": "channel-1",
        "member": {"user": {"id": "user-1"}},
        "data": {"name": "ask"},
    })
    assert message is not None
    now[0] = 1001.0
    expired = registry.send_reply(message, "late reply")
    assert expired == {
        "ok": False,
        "sent": False,
        "status_code": 410,
        "reason": "interaction_token_expired",
    }
    assert posts == []

    fallback = MessageConnectorRegistry(
        env={
            "YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32,
            "YUIZAKI_DISCORD_BOT_TOKEN": "bot-token",
            "YUIZAKI_DISCORD_ENABLED": "1",
        },
        http_post=lambda url, headers, payload: posts.append((url, dict(headers), dict(payload))) or {"ok": True},
        clock=lambda: now[0],
    )
    delivered = fallback.send_reply(message, "late reply")
    assert delivered["ok"] is True
    assert posts == [(
        "https://discord.com/api/v10/channels/channel-1/messages",
        {"Authorization": "Bot bot-token"},
        {"content": "late reply", "allowed_mentions": {"parse": []}},
    )]


def test_discord_ping_requires_signature_and_accepts_verified_request() -> None:
    registry = MessageConnectorRegistry(env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"})
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))
    client = TestClient(app, headers=TELEGRAM_WEBHOOK_HEADERS)
    rejected = client.post("/api/system/connectors/discord/webhook", json={"type": 1})
    assert rejected.status_code == 401
    assert rejected.json()["error"] == "invalid_signature"

    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]
    accepted = client.post("/api/system/connectors/discord/webhook", json={"type": 1})
    assert accepted.status_code == 200
    assert accepted.json() == {"type": 1}


def test_discord_interaction_reports_turn_service_unavailable_in_protocol_response() -> None:
    registry = MessageConnectorRegistry(env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"})
    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))
    response = TestClient(app).post(
        "/api/system/connectors/discord/webhook",
        json={
            "id": "interaction-unavailable",
            "application_id": "app-1",
            "type": 2,
            "token": "interaction-token",
            "channel_id": "channel-1",
            "member": {"user": {"id": "user-1"}},
            "data": {"name": "ask"},
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "type": 4,
        "data": {
            "content": "Yuizaki 暂时不可用，请稍后重试。",
            "allowed_mentions": {"parse": []},
        },
    }


def test_connector_webhook_reuses_turn_service_and_scope() -> None:
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, _payload: {"ok": True},
    )
    requests = []

    class FakeTurnService:
        calls = 0
        async def execute(self, trigger, request):
            requests.append((trigger, request))
            self.calls += 1
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="agent reply"),
                replayed=self.calls > 1,
            )

    fake_turn_service = FakeTurnService()
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: fake_turn_service,
        active_workspace_id_provider=lambda: "workspace-a",
    ))
    client = TestClient(app, headers=TELEGRAM_WEBHOOK_HEADERS)
    payload = {"update_id": 100, "message": {"chat": {"id": 9}, "from": {"id": 3}, "text": "hello"}}
    response = client.post("/api/system/connectors/telegram/webhook", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert requests[0][0] == "http"
    assert requests[0][1].workspace_id == "workspace-a"
    assert requests[0][1].session_id == "connector:telegram:chat:9"
    duplicate = client.post("/api/system/connectors/telegram/webhook", json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_disabled_connector_rejects_before_turn_service() -> None:
    registry = MessageConnectorRegistry(env={})
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))
    response = TestClient(app).post(
        "/api/system/connectors/telegram/webhook",
        json={"update_id": 1, "message": {"chat": {"id": 1}, "text": "hello"}},
    )
    assert response.status_code == 409
    assert response.json()["error"] == "connector_disabled"


def test_connector_config_routes_validate_and_redact(tmp_path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json", env={})
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: None,
        active_workspace_id_provider=lambda: "default",
    ))
    client = TestClient(app)
    missing_telegram_token = client.put(
        "/api/system/connectors/telegram/config",
        json={"enabled": True},
    )
    assert missing_telegram_token.status_code == 422
    assert missing_telegram_token.json()["error"] == "missing_bot_token"

    missing_telegram_secret = client.put(
        "/api/system/connectors/telegram/config",
        json={"enabled": True, "botToken": "bot-secret"},
    )
    assert missing_telegram_secret.status_code == 422
    assert missing_telegram_secret.json()["error"] == "missing_webhook_secret"

    missing_discord_key = client.put(
        "/api/system/connectors/discord/config",
        json={"enabled": True},
    )
    assert missing_discord_key.status_code == 422
    assert missing_discord_key.json()["error"] == "missing_public_key"

    response = client.put("/api/system/connectors/discord/config", json={
        "enabled": True,
        "botToken": "bot-secret",
        "webhookSecret": "webhook-secret",
        "publicKey": "not-hex",
    })
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_public_key"

    response = client.put("/api/system/connectors/discord/config", json={
        "enabled": True,
        "botToken": "bot-secret",
        "webhookSecret": "webhook-secret",
        "publicKey": "11" * 32,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["botTokenConfigured"] is True
    assert body["config"]["webhookSecretConfigured"] is True
    assert body["config"]["publicKeyConfigured"] is True
    assert "bot-secret" not in response.text
    assert "webhook-secret" not in response.text
    loaded = client.get("/api/system/connectors/discord/config")
    assert loaded.status_code == 200
    assert "bot-secret" not in loaded.text
    assert "webhook-secret" not in loaded.text

    cleared = client.put("/api/system/connectors/discord/config", json={
        "enabled": False,
        "clearBotToken": True,
        "clearWebhookSecret": True,
        "clearPublicKey": True,
    })
    assert cleared.status_code == 200
    assert cleared.json()["config"]["botTokenConfigured"] is False
    assert cleared.json()["config"]["webhookSecretConfigured"] is False
    assert cleared.json()["config"]["publicKeyConfigured"] is False


def test_failed_config_update_does_not_reenable_disabled_connector(tmp_path) -> None:
    registry = MessageConnectorRegistry(state_path=tmp_path / "connectors.json", env={})
    registry.update_config("discord", {"enabled": True, "publicKey": "11" * 32})
    registry.disable("discord")

    with pytest.raises(Exception, match="64 位十六进制"):
        registry.update_config("discord", {"enabled": True, "publicKey": "invalid"})

    assert registry.config_snapshot("discord")["enabled"] is False


def _discord_interaction(event_id: str) -> dict:
    return {
        "id": event_id,
        "application_id": "app-1",
        "type": 2,
        "token": "interaction-token",
        "channel_id": "channel-1",
        "member": {"user": {"id": "user-1"}},
        "data": {"name": "ask", "options": [{"name": "prompt", "value": "hello"}]},
    }


@pytest.mark.asyncio
async def test_discord_webhook_defers_then_edits_original_response_in_background() -> None:
    patches: list[tuple[str, dict, dict]] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda url, headers, payload: patches.append((url, dict(headers), dict(payload))) or {"ok": True, "id": "reply-1"},
    )
    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowTurnService:
        async def execute(self, trigger, request):
            assert trigger == "http"
            assert request.session_id == "connector:discord:channel:channel-1"
            started.set()
            await release.wait()
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="agent response"),
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=SlowTurnService,
        active_workspace_id_provider=lambda: "workspace-a",
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await asyncio.wait_for(
            client.post("/api/system/connectors/discord/webhook", json=_discord_interaction("interaction-1")),
            timeout=1,
        )
        assert response.status_code == 200
        assert response.json() == {"type": 5, "data": {"allowed_mentions": {"parse": []}}}
        await asyncio.wait_for(started.wait(), timeout=1)
        assert patches == []

        release.set()
        for _ in range(100):
            if patches:
                break
            await asyncio.sleep(0.01)

    assert len(patches) == 1
    assert patches[0][0] == "https://discord.com/api/v10/webhooks/app-1/interaction-token/messages/@original"
    assert patches[0][1] == {}
    assert patches[0][2] == {
        "content": "agent response",
        "allowed_mentions": {"parse": []},
    }


@pytest.mark.asyncio
async def test_discord_background_failure_converges_original_response() -> None:
    patches: list[dict] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda _url, _headers, payload: patches.append(dict(payload)) or {"ok": True},
    )
    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]

    class FailingTurnService:
        async def execute(self, _trigger, _request):
            raise RuntimeError("provider unavailable")

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=FailingTurnService,
        active_workspace_id_provider=lambda: "default",
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/system/connectors/discord/webhook",
            json=_discord_interaction("interaction-failed"),
        )
        assert response.json()["type"] == 5
        for _ in range(100):
            if patches:
                break
            await asyncio.sleep(0.01)

    assert patches == [{
        "content": "处理失败，请在 Yuizaki 连接器面板中重试。",
        "allowed_mentions": {"parse": []},
    }]


@pytest.mark.asyncio
async def test_failed_discord_turn_is_durably_retryable_after_router_restart(tmp_path) -> None:
    patches: list[dict] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda _url, _headers, payload: patches.append(dict(payload)) or {"ok": True},
    )
    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    class FailingTurnService:
        async def execute(self, _trigger, _request):
            raise RuntimeError("provider unavailable")

    first_app = FastAPI()
    first_app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=FailingTurnService,
        active_workspace_id_provider=lambda: "workspace-before-restart",
        delivery_store_provider=lambda: store,
    ))
    first_transport = httpx.ASGITransport(app=first_app)
    async with httpx.AsyncClient(transport=first_transport, base_url="http://test") as client:
        deferred = await client.post(
            "/api/system/connectors/discord/webhook",
            json=_discord_interaction("interaction-durable-turn-failure"),
        )
        assert deferred.json()["type"] == 5
        for _ in range(100):
            row = store.connector_delivery("connector:discord:interaction-durable-turn-failure")
            if row is not None and row["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("failed connector turn was not persisted")

    captured_workspaces: list[str] = []

    class RecoveredTurnService:
        async def execute(self, _trigger, request):
            captured_workspaces.append(request.workspace_id)
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="recovered reply", outcome="completed"),
            )

    restarted_app = FastAPI()
    restarted_app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=RecoveredTurnService,
        active_workspace_id_provider=lambda: "wrong-current-workspace",
        delivery_store_provider=lambda: store,
    ))
    retry_transport = httpx.ASGITransport(app=restarted_app)
    async with httpx.AsyncClient(transport=retry_transport, base_url="http://test") as client:
        listed = await client.get("/api/system/connectors/discord/deliveries?status=failed")
        assert listed.json()["items"][0]["last_error"] == "connector_turn_failed"
        retried = await client.post(
            "/api/system/connectors/discord/deliveries/connector:discord:interaction-durable-turn-failure/retry",
        )

    assert retried.status_code == 200
    assert retried.json()["delivery"]["status"] == "delivered"
    assert captured_workspaces == ["workspace-before-restart"]
    assert patches[-1] == {"content": "recovered reply", "allowed_mentions": {"parse": []}}


def test_discord_interaction_expiry_uses_route_receipt_time() -> None:
    registry = MessageConnectorRegistry(env={}, clock=lambda: 100.0)
    message = registry.parse(
        "discord",
        _discord_interaction("receipt-boundary"),
        received_at=25.0,
    )
    assert message is not None
    assert message.reply_target["interaction_expires_at"] == "925.0"


@pytest.mark.asyncio
async def test_manual_turn_retry_releases_lease_for_unexpected_agent_exception(tmp_path) -> None:
    registry = MessageConnectorRegistry(env=TELEGRAM_WEBHOOK_ENV)
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    message = ConnectorMessage(
        connector_id="telegram",
        event_id="unexpected-agent-error",
        session_id="connector:telegram:chat:1",
        external_user_id="user-1",
        conversation_id="1",
        text="retry me",
        reply_target={"chat_id": "1"},
    )
    owner = "seed-owner"
    store.record_connector_turn_pending(
        "connector:telegram:unexpected-agent-error",
        "connector:telegram:unexpected-agent-error",
        "telegram",
        "unexpected-agent-error",
        owner,
        message={**message.__dict__, "workspace_id": "default"},
    )
    assert store.mark_connector_turn_failed(
        "connector:telegram:unexpected-agent-error",
        owner,
        "connector_turn_failed",
    )

    class UnexpectedFailureTurnService:
        async def execute(self, _trigger, _request):
            raise KeyError("custom provider exception")

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=UnexpectedFailureTurnService,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    url = "/api/system/connectors/telegram/deliveries/connector:telegram:unexpected-agent-error/retry"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(url)
        second = await client.post(url)

    assert first.status_code == 502
    assert second.status_code == 502
    row = store.connector_delivery("connector:telegram:unexpected-agent-error")
    assert row is not None
    assert row["status"] == "failed"
    assert row["claimed_by"] is None
    assert row["claim_expires_at"] is None
    assert row["attempt_count"] == 2


@pytest.mark.asyncio
async def test_stale_processing_turn_recovers_after_router_restart(tmp_path) -> None:
    now = [0.0]
    sent: list[str] = []
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, payload: sent.append(str(payload["text"])) or {"ok": True},
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: now[0])
    message = ConnectorMessage(
        connector_id="telegram",
        event_id="interrupted-turn",
        session_id="connector:telegram:chat:1",
        external_user_id="user-1",
        conversation_id="1",
        text="resume me",
        reply_target={"chat_id": "1"},
    )
    store.record_connector_turn_pending(
        "connector:telegram:interrupted-turn",
        "connector:telegram:interrupted-turn",
        "telegram",
        "interrupted-turn",
        "dead-router",
        lease_seconds=5,
        message={**message.__dict__, "workspace_id": "workspace-before-crash"},
    )
    now[0] = 10.0

    class RecoveredTurnService:
        async def execute(self, _trigger, request):
            assert request.workspace_id == "workspace-before-crash"
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="resumed reply", outcome="completed"),
            )

    restarted_app = FastAPI()
    restarted_app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=RecoveredTurnService,
        active_workspace_id_provider=lambda: "current-workspace",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=restarted_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/system/connectors/telegram/deliveries")
        assert listed.json()["items"][0]["status"] == "failed"
        assert listed.json()["items"][0]["last_error"] == "connector_turn_interrupted"
        retried = await client.post(
            "/api/system/connectors/telegram/deliveries/connector:telegram:interrupted-turn/retry",
        )

    assert retried.status_code == 200
    assert retried.json()["delivery"]["status"] == "delivered"
    assert sent == ["resumed reply"]


@pytest.mark.asyncio
async def test_turn_retry_refreshes_send_lease_and_prevents_concurrent_send(tmp_path) -> None:
    now = [0.0]
    entered_send = threading.Event()
    release_send = threading.Event()
    sent: list[str] = []

    def blocking_send(_url, _headers, payload):
        entered_send.set()
        assert release_send.wait(timeout=2)
        sent.append(str(payload["text"]))
        return {"ok": True}

    registry = MessageConnectorRegistry(env=TELEGRAM_WEBHOOK_ENV, http_post=blocking_send)
    store = TurnCommitStore(tmp_path / "turns.sqlite3", wall_clock=lambda: now[0])
    message = ConnectorMessage(
        connector_id="telegram",
        event_id="lease-refresh",
        session_id="connector:telegram:chat:1",
        external_user_id="user-1",
        conversation_id="1",
        text="retry near expiry",
        reply_target={"chat_id": "1"},
    )
    owner = "seed-owner"
    store.record_connector_turn_pending(
        "connector:telegram:lease-refresh",
        "connector:telegram:lease-refresh",
        "telegram",
        "lease-refresh",
        owner,
        message={**message.__dict__, "workspace_id": "default"},
    )
    assert store.mark_connector_turn_failed(
        "connector:telegram:lease-refresh",
        owner,
        "connector_turn_failed",
    )

    class NearExpiryTurnService:
        async def execute(self, _trigger, request):
            now[0] = 899.0
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="single refreshed send", outcome="completed"),
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=NearExpiryTurnService,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    url = "/api/system/connectors/telegram/deliveries/connector:telegram:lease-refresh/retry"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = asyncio.create_task(client.post(url))
        assert await asyncio.to_thread(entered_send.wait, 1)
        promoted = store.connector_delivery("connector:telegram:lease-refresh")
        assert promoted is not None
        assert promoted["status"] == "sending"
        assert promoted["claim_expires_at"] == 959.0
        now[0] = 901.0
        concurrent = await client.post(url)
        assert concurrent.status_code == 409
        assert concurrent.json()["error"] == "delivery_in_progress"
        release_send.set()
        completed = await asyncio.wait_for(first, timeout=1)

    assert completed.status_code == 200
    assert completed.json()["delivery"]["status"] == "delivered"
    assert sent == ["single refreshed send"]


@pytest.mark.asyncio
async def test_discord_background_event_can_be_cancelled_and_retried() -> None:
    patches: list[dict] = []
    registry = MessageConnectorRegistry(
        env={"YUIZAKI_DISCORD_PUBLIC_KEY": "11" * 32, "YUIZAKI_DISCORD_ENABLED": "1"},
        http_patch=lambda _url, _headers, payload: patches.append(dict(payload)) or {"ok": True, "id": "reply-2"},
    )
    registry.verify_request = lambda _connector_id, _headers, _body=b"": True  # type: ignore[method-assign]
    first_started = asyncio.Event()
    calls = 0

    class CancelThenCompleteTurnService:
        async def execute(self, _trigger, request):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_started.set()
                await asyncio.Event().wait()
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="retry reply"),
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=CancelThenCompleteTurnService,
        active_workspace_id_provider=lambda: "default",
    ))
    transport = httpx.ASGITransport(app=app)
    payload = _discord_interaction("interaction-cancel")
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/system/connectors/discord/webhook", json=payload)
        assert first.json()["type"] == 5
        await asyncio.wait_for(first_started.wait(), timeout=1)

        cancelled = await client.post("/api/system/connectors/discord/events/interaction-cancel/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["cancelled"] is True

        for _ in range(100):
            retry = await client.post("/api/system/connectors/discord/webhook", json=payload)
            if retry.json().get("type") == 5:
                break
            assert retry.json()["duplicate"] is True
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("cancelled Discord event did not release its idempotency claim")

        for _ in range(100):
            if len(patches) >= 2:
                break
            await asyncio.sleep(0.01)

    assert calls == 2
    assert patches == [
        {"content": "已停止处理。", "allowed_mentions": {"parse": []}},
        {"content": "retry reply", "allowed_mentions": {"parse": []}},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_result, expected_reason", [
    ({"ok": False, "description": "provider rejected"}, "provider_rejected"),
    ({"ok": True}, "empty_reply"),
])
async def test_failed_delivery_releases_event_for_retry(provider_result, expected_reason) -> None:
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, _payload: provider_result,
    )

    class ReplyTurnService:
        async def execute(self, _trigger, request):
            reply = "" if expected_reason == "empty_reply" else "reply"
            return SimpleNamespace(context=SimpleNamespace(turn_id=request.turn_id), result=SimpleNamespace(reply=reply))

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=ReplyTurnService,
        active_workspace_id_provider=lambda: "default",
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": f"delivery-{expected_reason}", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        first = await client.post("/api/system/connectors/telegram/webhook", json=payload)
        assert first.status_code == 502
        assert first.json()["delivery"] == {"ok": False, "reason": expected_reason}
        retry = await client.post("/api/system/connectors/telegram/webhook", json=payload)
    assert retry.status_code == 502
    assert retry.json()["delivery"]["reason"] == expected_reason


@pytest.mark.asyncio
async def test_persisted_turn_retries_failed_provider_delivery(tmp_path) -> None:
    deliveries = [{"ok": False}, {"ok": True}]
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, _payload: deliveries.pop(0),
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    runs = 0

    async def run(_ctx):
        nonlocal runs
        runs += 1
        return AgentPipelineResult(reply="retryable reply")

    turn_service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
    ))
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": "durable-delivery", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        first = await client.post("/api/system/connectors/telegram/webhook", json=payload)
        second = await client.post("/api/system/connectors/telegram/webhook", json=payload)
    assert first.status_code == 502
    assert second.status_code == 200
    assert second.json()["reply_sent"] is True
    assert runs == 1
    assert store.connector_delivery("connector:telegram:durable-delivery")["status"] == "delivered"


@pytest.mark.asyncio
async def test_running_connector_event_can_be_cancelled(tmp_path) -> None:
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, _payload: {"ok": True},
    )
    started = asyncio.Event()
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    class SlowTurnService:
        async def execute(self, _trigger, _request):
            started.set()
            await asyncio.Event().wait()

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=SlowTurnService,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        webhook = asyncio.create_task(client.post(
            "/api/system/connectors/telegram/webhook",
            json={"update_id": 33, "message": {"chat": {"id": 1}, "text": "wait"}},
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        listed = await client.get("/api/system/connectors/telegram/deliveries")
        assert listed.json()["items"][0]["status"] == "processing"
        cancelled = await client.post("/api/system/connectors/telegram/events/33/cancel")
        response = await asyncio.wait_for(webhook, timeout=1)

    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert response.status_code == 409
    assert response.json()["error"] == "connector_event_cancelled"


@pytest.mark.asyncio
async def test_provider_send_is_too_late_to_cancel_and_is_not_retried(tmp_path) -> None:
    entered_send = threading.Event()
    release_send = threading.Event()
    sent: list[str] = []

    def blocking_send(_url, _headers, payload):
        entered_send.set()
        assert release_send.wait(timeout=2)
        sent.append(str(payload["text"]))
        return {"ok": True}

    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=blocking_send,
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    class ReplyTurnService:
        async def execute(self, _trigger, request):
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="single reply"),
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=ReplyTurnService,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": "too-late", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        webhook = asyncio.create_task(client.post("/api/system/connectors/telegram/webhook", json=payload))
        assert await asyncio.to_thread(entered_send.wait, 1)

        cancelled = await client.post("/api/system/connectors/telegram/events/too-late/cancel")
        assert cancelled.status_code == 409
        assert cancelled.json()["error"] == "cancel_too_late"
        assert cancelled.json()["outcome"] == "too_late"
        assert cancelled.json()["status"] == "sending"

        listed = await client.get("/api/system/connectors/telegram/deliveries")
        assert listed.json()["items"][0]["status"] == "sending"

        release_send.set()
        response = await asyncio.wait_for(webhook, timeout=1)
        assert response.status_code == 200

        retried = await client.post("/api/system/connectors/telegram/events/too-late/retry")
        assert retried.status_code == 200
        assert retried.json()["already_sent"] is True

    assert sent == ["single reply"]
    assert store.connector_delivery("connector:telegram:too-late")["status"] == "delivered"


@pytest.mark.asyncio
async def test_replayed_webhook_does_not_auto_retry_unknown_sending_delivery(tmp_path) -> None:
    sends = 0

    def unexpected_send(_url, _headers, _payload):
        nonlocal sends
        sends += 1
        return {"ok": True}

    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=unexpected_send,
    )
    store = TurnCommitStore(tmp_path / "turns.sqlite3")
    message = ConnectorMessage(
        connector_id="telegram",
        event_id="unknown-send",
        session_id="connector:telegram:chat:1",
        external_user_id="user-1",
        conversation_id="1",
        text="hello",
        reply_target={"chat_id": "1"},
    )
    store.claim_connector_delivery(
        "connector:telegram:unknown-send",
        "connector:telegram:unknown-send",
        "telegram",
        "unknown-send",
        "lost-owner",
        lease_seconds=0.1,
        message=message.__dict__,
        reply_text="possibly sent",
    )

    class ReplayedTurnService:
        async def execute(self, _trigger, request):
            return SimpleNamespace(
                context=SimpleNamespace(turn_id=request.turn_id),
                result=SimpleNamespace(reply="possibly sent"),
                replayed=True,
            )

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=ReplayedTurnService,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": "unknown-send", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        await asyncio.sleep(0.11)
        response = await client.post("/api/system/connectors/telegram/webhook", json=payload)

    assert response.status_code == 409
    assert response.json()["error"] == "delivery_state_unknown"
    assert response.json()["outcome"] == "unknown"
    assert sends == 0
    row = store.connector_delivery("connector:telegram:unknown-send")
    assert row["status"] == "sending"
    assert row["attempt_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_webhooks_share_one_canonical_turn_and_delivery(tmp_path) -> None:
    run_started = asyncio.Event()
    release_run = asyncio.Event()
    runs = 0
    sent: list[str] = []
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    async def run(_ctx):
        nonlocal runs
        runs += 1
        run_started.set()
        await release_run.wait()
        return AgentPipelineResult(reply="canonical reply")

    turn_service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
    ))
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, payload: sent.append(str(payload["text"])) or {"ok": True},
    )
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": "concurrent", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        first = asyncio.create_task(client.post("/api/system/connectors/telegram/webhook", json=payload))
        await asyncio.wait_for(run_started.wait(), timeout=1)
        duplicate = asyncio.create_task(client.post("/api/system/connectors/telegram/webhook", json=payload))
        await asyncio.sleep(0.01)
        release_run.set()
        first_response, duplicate_response = await asyncio.gather(first, duplicate)

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 200
    assert first_response.json() == duplicate_response.json()
    assert runs == 1
    assert sent == ["canonical reply"]
    row = store.connector_delivery("connector:telegram:concurrent")
    assert row["status"] == "delivered"
    assert row["attempt_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_webhook_cancel_targets_canonical_turn(tmp_path) -> None:
    run_started = asyncio.Event()
    runs = 0
    sends = 0
    store = TurnCommitStore(tmp_path / "turns.sqlite3")

    async def run(_ctx):
        nonlocal runs
        runs += 1
        run_started.set()
        await asyncio.Event().wait()
        return AgentPipelineResult(reply="must not send")

    def unexpected_send(_url, _headers, _payload):
        nonlocal sends
        sends += 1
        return {"ok": True}

    turn_service = TurnService(TurnPorts(
        run=run,
        persist=store.persist,
        load=store.load,
        claim=store.claim,
        renew_claim=store.renew_claim,
        release_claim=store.release_claim,
    ))
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=unexpected_send,
    )
    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: turn_service,
        active_workspace_id_provider=lambda: "default",
        delivery_store_provider=lambda: store,
    ))
    transport = httpx.ASGITransport(app=app)
    payload = {"update_id": "concurrent-cancel", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        first = asyncio.create_task(client.post("/api/system/connectors/telegram/webhook", json=payload))
        await asyncio.wait_for(run_started.wait(), timeout=1)
        duplicate = asyncio.create_task(client.post("/api/system/connectors/telegram/webhook", json=payload))
        await asyncio.sleep(0.01)
        cancelled = await client.post("/api/system/connectors/telegram/events/concurrent-cancel/cancel")
        first_response, duplicate_response = await asyncio.gather(first, duplicate)

    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert first_response.status_code == 409
    assert duplicate_response.status_code == 409
    assert first_response.json()["error"] == "connector_event_cancelled"
    assert duplicate_response.json()["error"] == "connector_event_cancelled"
    assert runs == 1
    assert sends == 0
    assert store.connector_delivery("connector:telegram:concurrent-cancel") is None


@pytest.mark.asyncio
async def test_setup_failure_does_not_claim_event() -> None:
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
        http_post=lambda _url, _headers, _payload: {"ok": True},
    )
    calls = 0

    def workspace_id() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("workspace unavailable")
        return "default"

    class TurnService:
        async def execute(self, _trigger, request):
            return SimpleNamespace(context=SimpleNamespace(turn_id=request.turn_id), result=SimpleNamespace(reply="ok"))

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=TurnService,
        active_workspace_id_provider=workspace_id,
    ))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    payload = {"update_id": "setup-failure", "message": {"chat": {"id": 1}, "text": "hello"}}
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        first = await client.post("/api/system/connectors/telegram/webhook", json=payload)
        second = await client.post("/api/system/connectors/telegram/webhook", json=payload)
    assert first.status_code == 503
    assert first.json()["error"] == "connector_setup_failed"
    assert second.status_code == 200
    assert second.json()["accepted"] is True


@pytest.mark.asyncio
async def test_setup_failure_returns_retryable_connector_error() -> None:
    registry = MessageConnectorRegistry(
        env=TELEGRAM_WEBHOOK_ENV,
    )

    def workspace_id() -> str:
        raise RuntimeError("workspace unavailable")

    app = FastAPI()
    app.include_router(create_message_connector_router(
        registry_provider=lambda: registry,
        turn_service_provider=lambda: object(),
        active_workspace_id_provider=workspace_id,
    ))
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TELEGRAM_WEBHOOK_HEADERS) as client:
        response = await client.post(
            "/api/system/connectors/telegram/webhook",
            json={"update_id": "setup-error", "message": {"chat": {"id": 1}, "text": "hello"}},
        )
    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "connector_setup_failed",
        "message": "连接器暂时不可用，请稍后重试",
    }
