"""Experimental external message adapters.

The adapters intentionally depend on no Telegram/Discord SDK. They normalize
the small inbound envelope needed by Yuizaki, keep connector credentials out of
snapshots, and send replies through an injectable JSON transport. Durable event
idempotency is owned by the shared TurnService/TurnCommitStore route boundary;
the adapter itself only owns configuration and protocol validation. Runtime
dispatch is owned by the route layer so the adapter cannot bypass TurnService
or workspace/session binding.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

ConnectorHttpPost = Callable[[str, Mapping[str, str], Mapping[str, Any]], Mapping[str, Any]]
ConnectorHttpPatch = Callable[[str, Mapping[str, str], Mapping[str, Any]], Mapping[str, Any]]
ConnectorHttpGet = Callable[[str, Mapping[str, str]], Mapping[str, Any]]
ConnectorClock = Callable[[], float]

# These keys belonged to the removed QQ Bot / WeChat official connectors.
# Keep rejecting them at the API boundary so stale clients fail explicitly,
# while never loading or persisting their values for personal bridges.
_REMOVED_OFFICIAL_FIELDS = frozenset({
    "botToken",
    "clearBotToken",
    "webhookSecret",
    "clearWebhookSecret",
    "publicKey",
    "clearPublicKey",
    "appId",
    "clearAppId",
    "appSecret",
    "clearAppSecret",
    "apiBaseUrl",
    "clearApiBaseUrl",
})

_SECRET_CONFIG_FIELDS = frozenset({"botToken", "webhookSecret", "publicKey", "bridgeToken"})


def _env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bounded_text(value: Any, limit: int) -> str:
    return _text(value)[:limit]


def _validate_bridge_url(value: Any) -> str:
    """Validate a bridge origin before it can receive connector credentials."""
    normalized = _bounded_text(value, 512)
    if not normalized:
        return ""
    try:
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("bridge URL must use http:// or https:// with a hostname")
        if parsed.username or parsed.password:
            raise ValueError("bridge URL must not contain URL credentials")
        if parsed.fragment:
            raise ValueError("bridge URL must not contain a fragment")
        if any(ord(char) < 0x20 for char in normalized):
            raise ValueError("bridge URL contains control characters")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("bridge URL port is invalid")
    except ValueError:
        raise
    except (TypeError, UnicodeError) as exc:
        raise ValueError("bridge URL is invalid") from exc
    return normalized.rstrip("/")


def _default_http_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json", **dict(headers)}, method=method)
    with urlopen(request, timeout=15) as response:
        raw = response.read(512 * 1024)
        status_code = int(getattr(response, "status", response.getcode()))
    parsed: Mapping[str, Any] = {}
    if raw:
        decoded = json.loads(raw.decode("utf-8"))
        if isinstance(decoded, Mapping):
            parsed = decoded
    result = dict(parsed)
    result.setdefault("ok", 200 <= status_code < 300)
    result.setdefault("sent", 200 <= status_code < 300)
    result["status_code"] = status_code
    return result


def _default_http_post(url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return _default_http_json("POST", url, headers, payload)


def _default_http_patch(url: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return _default_http_json("PATCH", url, headers, payload)


def _default_http_get(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
    request = Request(url, headers=dict(headers), method="GET")
    with urlopen(request, timeout=15) as response:
        raw = response.read(512 * 1024)
        status_code = int(getattr(response, "status", response.getcode()))
    parsed: Mapping[str, Any] = {}
    if raw:
        decoded = json.loads(raw.decode("utf-8"))
        if isinstance(decoded, Mapping):
            parsed = decoded
    result = dict(parsed)
    result.setdefault("ok", 200 <= status_code < 300)
    result["status_code"] = status_code
    return result


@dataclass(frozen=True)
class ConnectorMessage:
    connector_id: str
    event_id: str
    session_id: str
    external_user_id: str
    conversation_id: str
    text: str
    reply_target: Mapping[str, str]


# Minimal RFC 8032 Ed25519 verifier.  The adapter is optional and should not
# force the core local runtime to install a crypto package just for Discord.
_ED25519_Q = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493
_ED25519_D = (-121665 * pow(121666, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q
_ED25519_I = pow(2, (_ED25519_Q - 1) // 4, _ED25519_Q)


def _ed25519_xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_ED25519_D * y * y + 1, _ED25519_Q - 2, _ED25519_Q) % _ED25519_Q
    x = pow(xx, (_ED25519_Q + 3) // 8, _ED25519_Q)
    if (x * x - xx) % _ED25519_Q != 0:
        x = x * _ED25519_I % _ED25519_Q
    return x


def _ed25519_decode_point(value: bytes) -> tuple[int, int] | None:
    if len(value) != 32:
        return None
    encoded = int.from_bytes(value, "little")
    sign = encoded >> 255
    y = encoded & ((1 << 255) - 1)
    if y >= _ED25519_Q:
        return None
    x = _ed25519_xrecover(y)
    if (x * x - (y * y - 1) * pow(_ED25519_D * y * y + 1, _ED25519_Q - 2, _ED25519_Q)) % _ED25519_Q != 0:
        return None
    if (x & 1) != sign:
        x = _ED25519_Q - x
    if x == 0 and sign:
        return None
    return x, y


def _ed25519_add(left: tuple[int, int], right: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = left
    x2, y2 = right
    product = _ED25519_D * x1 * x2 * y1 * y2 % _ED25519_Q
    denominator_x = pow(1 + product, _ED25519_Q - 2, _ED25519_Q)
    denominator_y = pow(1 - product, _ED25519_Q - 2, _ED25519_Q)
    return (
        (x1 * y2 + x2 * y1) * denominator_x % _ED25519_Q,
        (y1 * y2 + x1 * x2) * denominator_y % _ED25519_Q,
    )


def _ed25519_scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    result = (0, 1)
    current = point
    while scalar:
        if scalar & 1:
            result = _ed25519_add(result, current)
        current = _ed25519_add(current, current)
        scalar >>= 1
    return result


_ED25519_BASE = _ed25519_decode_point(bytes.fromhex("5866666666666666666666666666666666666666666666666666666666666666"))


def verify_discord_signature(*, body: bytes, timestamp: str, signature: str, public_key: str) -> bool:
    """Verify Discord's ``timestamp + raw_body`` Ed25519 signature."""

    try:
        signature_bytes = bytes.fromhex(signature)
        public_key_bytes = bytes.fromhex(public_key)
    except ValueError:
        return False
    if len(signature_bytes) != 64 or len(public_key_bytes) != 32 or _ED25519_BASE is None:
        return False
    r_point = _ed25519_decode_point(signature_bytes[:32])
    a_point = _ed25519_decode_point(public_key_bytes)
    scalar = int.from_bytes(signature_bytes[32:], "little")
    if r_point is None or a_point is None or scalar >= _ED25519_L:
        return False
    identity = (0, 1)
    if (
        _ed25519_scalarmult(r_point, 8) == identity
        or _ed25519_scalarmult(a_point, 8) == identity
        or _ed25519_scalarmult(r_point, _ED25519_L) != identity
        or _ed25519_scalarmult(a_point, _ED25519_L) != identity
    ):
        return False
    # The public key is part of the challenge; keep the construction explicit
    # so raw-body verification cannot accidentally hash a re-encoded payload.
    digest = hashlib.sha512(signature_bytes[:32] + public_key_bytes + timestamp.encode("utf-8") + body).digest()
    challenge = int.from_bytes(digest, "little") % _ED25519_L
    return _ed25519_scalarmult(_ED25519_BASE, scalar) == _ed25519_add(r_point, _ed25519_scalarmult(a_point, challenge))


class MessageConnectorError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MessageConnectorRegistry:
    """Own adapter configuration and transient webhook health state."""

    _CONNECTOR_ORDER = ("telegram", "discord", "qq", "wechat")
    def __init__(
        self,
        *,
        state_path: Path | None = None,
        env: Mapping[str, str] | None = None,
        http_post: ConnectorHttpPost | None = None,
        http_patch: ConnectorHttpPatch | None = None,
        http_get: ConnectorHttpGet | None = None,
        clock: ConnectorClock | None = None,
    ) -> None:
        self._env = dict(env or os.environ)
        self._state_path = state_path
        self._http_post = http_post or _default_http_post
        self._http_patch = http_patch or _default_http_patch
        self._http_get = http_get or _default_http_get
        self._clock = clock or time.time
        self._config, self._disabled = self._load_state()
        self._last_error: dict[str, str | None] = {connector_id: None for connector_id in self._CONNECTOR_ORDER}
        self._account_last_error: dict[str, str | None] = {"qq": None, "wechat": None}
        self._account_login_urls: dict[str, str | None] = {"qq": None, "wechat": None}

    def current_time(self) -> float:
        """Return the adapter clock used for provider response deadlines."""
        return float(self._clock())

    def _load_state(self) -> tuple[dict[str, dict[str, Any]], set[str]]:
        if self._state_path is None or not self._state_path.is_file():
            return {}, set()
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}, set()
        config: dict[str, dict[str, Any]] = {}
        raw_connectors = raw.get("connectors") if isinstance(raw, Mapping) else None
        if isinstance(raw_connectors, Mapping):
            for connector_id in self._CONNECTOR_ORDER:
                item = raw_connectors.get(connector_id)
                if isinstance(item, Mapping):
                    normalized: dict[str, Any] = {"enabled": bool(item.get("enabled", False))}
                    if connector_id in {"qq", "wechat"}:
                        # Do not carry forward removed official credentials from
                        # an older connectors.json into the personal bridge.
                        normalized.update({
                            "accountMode": "personal_bridge",
                            "bridgeUrl": _bounded_text(item.get("bridgeUrl"), 512),
                            "bridgeProtocol": _bounded_text(item.get("bridgeProtocol"), 32) or "generic",
                            "bridgeToken": _bounded_text(item.get("bridgeToken"), 512),
                            "accountId": _bounded_text(item.get("accountId"), 256),
                            "accountName": _bounded_text(item.get("accountName"), 256),
                            "loginState": _bounded_text(item.get("loginState"), 32) or "signed_out",
                        })
                    else:
                        normalized.update({
                            "botToken": _bounded_text(item.get("botToken"), 512),
                            "webhookSecret": _bounded_text(item.get("webhookSecret"), 256),
                            "publicKey": _bounded_text(item.get("publicKey"), 64).lower(),
                        })
                    config[connector_id] = normalized
        values = raw.get("disabled") if isinstance(raw, Mapping) else None
        disabled = {str(value) for value in values if str(value) in self._CONNECTOR_ORDER} if isinstance(values, list) else set()
        return config, disabled

    def _save_disabled(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        persisted_connectors = {
            connector_id: {
                key: value
                for key, value in connector_config.items()
                if key not in _SECRET_CONFIG_FIELDS
            }
            for connector_id, connector_config in self._config.items()
        }
        temp_path.write_text(json.dumps({
            "version": 1,
            "disabled": sorted(self._disabled),
            "connectors": persisted_connectors,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._state_path)

    def _token(self, connector_id: str) -> str:
        if connector_id in {"qq", "wechat"}:
            return ""
        configured = _text(self._config.get(connector_id, {}).get("botToken"))
        if configured:
            return configured
        return self._env.get(f"YUIZAKI_{connector_id.upper()}_BOT_TOKEN", "").strip()

    def _bridge_url(self, connector_id: str) -> str:
        configured = _text(self._config.get(connector_id, {}).get("bridgeUrl"))
        return configured or self._env.get(f"YUIZAKI_{connector_id.upper()}_BRIDGE_URL", "").strip()

    def _bridge_protocol(self, connector_id: str) -> str:
        configured = _text(self._config.get(connector_id, {}).get("bridgeProtocol"))
        return configured or self._env.get(f"YUIZAKI_{connector_id.upper()}_BRIDGE_PROTOCOL", "generic").strip().lower()

    def _bridge_token(self, connector_id: str) -> str:
        configured = _text(self._config.get(connector_id, {}).get("bridgeToken"))
        return configured or self._env.get(f"YUIZAKI_{connector_id.upper()}_BRIDGE_TOKEN", "").strip()

    def _enabled(self, connector_id: str) -> bool:
        if connector_id in self._config:
            return bool(self._config[connector_id].get("enabled", False))
        return _env_bool(self._env.get(f"YUIZAKI_{connector_id.upper()}_ENABLED"), False)

    def _secret(self, connector_id: str) -> str:
        configured = _text(self._config.get(connector_id, {}).get("webhookSecret"))
        if configured:
            return configured
        return self._env.get(f"YUIZAKI_{connector_id.upper()}_WEBHOOK_SECRET", "").strip()

    def _public_key(self, connector_id: str) -> str:
        configured = _text(self._config.get(connector_id, {}).get("publicKey"))
        if configured:
            return configured
        return self._env.get(f"YUIZAKI_{connector_id.upper()}_PUBLIC_KEY", "").strip()

    def _installed(self, connector_id: str) -> bool:
        if connector_id == "discord":
            return bool(self._public_key(connector_id))
        if connector_id == "qq":
            return bool(self._bridge_url(connector_id))
        if connector_id == "wechat":
            return bool(self._bridge_url(connector_id))
        return bool(self._token(connector_id))

    def _verification_configured(self, connector_id: str) -> bool:
        if connector_id == "discord":
            return bool(self._public_key(connector_id))
        if connector_id in {"qq", "wechat"}:
            return bool(self._bridge_token(connector_id))
        if connector_id == "telegram":
            return bool(self._secret(connector_id))
        return False

    def _state(self, connector_id: str) -> str:
        if not self._installed(connector_id):
            return "uninstalled"
        if connector_id in self._disabled or not self._enabled(connector_id):
            return "disabled"
        if not self._verification_configured(connector_id):
            return "failure"
        return "failure" if self._last_error[connector_id] else "running"

    def snapshot(self) -> list[dict[str, Any]]:
        specs = {
            "telegram": {
                "name": "Telegram",
                "kind": "external_message",
                "capabilities": ["message-in", "message-out", "webhook"],
                "dataFlow": ["Telegram Update -> Agent 会话", "Agent 回复 -> Telegram"],
            },
            "discord": {
                "name": "Discord",
                "kind": "external_message",
                "capabilities": ["interaction-in", "interaction-response"],
                "dataFlow": ["Discord Interaction -> Agent 会话", "Agent 终态 -> 原始 Interaction 响应"],
            },
            "qq": {
                "name": "QQ 个人账号兼容桥",
                "kind": "external_message",
                "capabilities": ["message-in", "message-out", "webhook"],
                "dataFlow": ["QQ 兼容桥事件 -> Agent 会话", "Agent 回复 -> QQ 兼容桥"],
            },
            "wechat": {
                "name": "微信个人账号兼容桥",
                "kind": "external_message",
                "capabilities": ["message-in", "message-out", "callback"],
                "dataFlow": ["微信兼容桥事件 -> Agent 会话", "Agent 回复 -> 微信兼容桥"],
            },
        }
        rows: list[dict[str, Any]] = []
        for connector_id in self._CONNECTOR_ORDER:
            installed = self._installed(connector_id)
            state = self._state(connector_id)
            if state == "uninstalled":
                message = {
                    "discord": "适配器未配置 Public Key",
                    "qq": "适配器未配置 QQ 个人账号兼容桥地址",
                    "wechat": "适配器未配置微信个人账号兼容桥地址",
                }.get(connector_id, "适配器未配置 Bot token")
            elif state == "disabled":
                message = "适配器已停用"
            elif state == "failure":
                if not self._verification_configured(connector_id):
                    message = {
                        "telegram": "启用前需配置 webhook secret",
                        "qq": "启用前需配置兼容桥 token",
                        "wechat": "启用前需配置兼容桥 token",
                    }.get(connector_id, "接收校验未配置")
                else:
                    message = self._last_error[connector_id] or "最近一次发送失败"
            else:
                message = "适配器已启用，等待 webhook"
            spec = specs[connector_id]
            readiness = self.readiness_snapshot(connector_id)
            rows.append({
                "id": connector_id,
                "name": spec["name"],
                "kind": spec["kind"],
                "state": state,
                "installed": installed,
                "enabled": state == "running",
                "canDisable": installed,
                "experimental": True,
                "capabilities": list(spec["capabilities"]),
                "dataFlow": list(spec["dataFlow"]),
                "permissionScope": f"connector:{connector_id}",
                "message": message,
                "lastError": self._last_error[connector_id],
                "source": "adapter",
                "account": self.account_status(connector_id) if connector_id in {"qq", "wechat"} else None,
                "readiness": readiness,
            })
        return rows

    def readiness_snapshot(self, connector_id: str) -> dict[str, Any] | None:
        """Project configuration readiness without probing a provider or bridge.

        A ready result only means the local configuration is complete enough to
        start staging.  It deliberately does not claim that a public webhook,
        provider account, or bridge is reachable.
        """
        connector_id = _text(connector_id).lower()
        if connector_id not in self._CONNECTOR_ORDER:
            return None

        enabled = self._enabled(connector_id) and connector_id not in self._disabled
        installed = self._installed(connector_id)
        reasons: list[dict[str, str]] = []
        if not installed:
            reasons.append({"code": "not_configured", "detail": "连接器必需配置尚未完成"})
        if not enabled:
            reasons.append({"code": "disabled", "detail": "连接器当前未启用"})
        if installed and not self._verification_configured(connector_id):
            reasons.append({"code": "verification_not_configured", "detail": "入站请求校验尚未配置"})

        status = "ready_for_staging" if installed and enabled and not reasons else "not_qualified"
        return {
            "schemaVersion": "yuizaki.connector-readiness.v1",
            "status": status,
            "networkChecked": False,
            "externalProviderVerified": False,
            "requiresPublicHttps": connector_id in {"telegram", "discord"},
            "reasons": reasons,
            "claim": "configuration_only_not_provider_qualification",
        }

    def disable(self, connector_id: str) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in self._CONNECTOR_ORDER or not self._installed(connector_id):
            return None
        self._disabled.add(connector_id)
        self._save_disabled()
        return next(row for row in self.snapshot() if row["id"] == connector_id)

    def config_snapshot(self, connector_id: str) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in self._CONNECTOR_ORDER:
            return None
        snapshot = {
            "id": connector_id,
            "enabled": self.is_enabled(connector_id),
            "webhookPath": f"/api/system/connectors/{connector_id}/webhook",
        }
        if connector_id in {"qq", "wechat"}:
            snapshot.update({
                "accountMode": "personal_bridge",
                "bridgeUrlConfigured": bool(self._bridge_url(connector_id)),
                "bridgeUrl": self._bridge_url(connector_id),
                "bridgeTokenConfigured": bool(self._bridge_token(connector_id)),
                "bridgeProtocol": self._bridge_protocol(connector_id),
            })
        else:
            snapshot.update({
                "botTokenConfigured": bool(self._token(connector_id)),
                "webhookSecretConfigured": bool(self._secret(connector_id)),
                "publicKeyConfigured": bool(self._public_key(connector_id)),
            })
        return snapshot

    def is_personal_bridge(self, connector_id: str) -> bool:
        connector_id = _text(connector_id).lower()
        return connector_id in {"qq", "wechat"}

    def account_status(self, connector_id: str) -> dict[str, Any] | None:
        """Return local binding state without contacting the provider."""

        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            return None
        configured = bool(self._bridge_url(connector_id))
        account = self._config.get(connector_id, {})
        connected = configured and _text(account.get("loginState")) == "connected"
        account_kind = f"{connector_id}_personal_bridge"
        capabilities = ["bridge_login", "message_send", "message_receive"]
        return {
            "id": connector_id,
            "connected": connected,
            "configured": configured,
            "accountKind": account_kind,
            "capabilities": capabilities,
            "loginState": _text(account.get("loginState")) or "signed_out",
            "loginUrl": self._account_login_urls.get(connector_id),
            "bridgeProtocol": self._bridge_protocol(connector_id),
            "experimental": True,
            "accountId": _text(account.get("accountId")) or None,
            "accountName": _text(account.get("accountName")) or None,
            "lastError": self._account_last_error[connector_id],
        }

    def test_account_connection(self, connector_id: str) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            return None
        return self.refresh_account_status(connector_id)

    def probe(self, connector_id: str) -> dict[str, Any]:
        """Run a bounded, read-only provider check without changing connector state.

        The response intentionally contains only normalized health metadata. No
        provider payload, token, message body, or account identifier is echoed.
        """
        connector_id = _text(connector_id).lower()
        if connector_id not in self._CONNECTOR_ORDER:
            raise MessageConnectorError("unknown_connector", "不支持的消息连接器", status_code=404)

        checked_at = float(self._clock())
        base: dict[str, Any] = {
            "schemaVersion": "yuizaki.connector-probe.v1",
            "connectorId": connector_id,
            "checkedAt": checked_at,
            "externalSideEffects": False,
            "networkChecked": False,
        }
        if connector_id == "discord" and not self._token(connector_id):
            if not self._public_key(connector_id):
                return {**base, "ok": False, "status": "unconfigured", "errorCode": "missing_public_key"}
            return {
                **base,
                "ok": True,
                "status": "signature_ready",
                "verificationConfigured": True,
            }

        if connector_id in {"qq", "wechat"}:
            try:
                result = self._bridge_call(connector_id, "status")
            except MessageConnectorError as exc:
                return {
                    **base,
                    "ok": False,
                    "status": "unreachable",
                    "errorCode": exc.code,
                    "verificationConfigured": bool(self._bridge_token(connector_id)),
                }
            status = _text(result.get("state") or result.get("status")) or "unknown"
            healthy = result.get("ok") is not False and status not in {"error", "offline", "disconnected"}
            return {
                **base,
                "ok": healthy,
                "status": "reachable" if healthy else "provider_error",
                "bridgeStatus": status[:32],
                "verificationConfigured": bool(self._bridge_token(connector_id)),
                "networkChecked": True,
            }

        token = self._token(connector_id)
        if not token:
            return {**base, "ok": False, "status": "unconfigured", "errorCode": "missing_bot_token"}
        if connector_id == "telegram":
            url = f"https://api.telegram.org/bot{quote(token, safe='')}/getMe"
            headers: Mapping[str, str] = {}
        else:
            url = "https://discord.com/api/v10/users/@me"
            headers = {"Authorization": f"Bot {token}"}
        try:
            result = self._http_get(url, headers)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {
                **base,
                "ok": False,
                "status": "unreachable",
                "errorCode": type(exc).__name__[:80],
                "networkChecked": True,
            }
        if not isinstance(result, Mapping):
            return {**base, "ok": False, "status": "invalid_response", "errorCode": "provider_response_invalid", "networkChecked": True}
        status_code = result.get("status_code")
        provider_ok = result.get("ok") is True or (isinstance(status_code, int) and 200 <= status_code < 300)
        return {
            **base,
            "ok": provider_ok,
            "status": "reachable" if provider_ok else "provider_rejected",
            "statusCode": status_code if isinstance(status_code, int) and 100 <= status_code <= 599 else None,
            "verificationConfigured": bool(self._secret(connector_id)) if connector_id == "telegram" else bool(self._public_key(connector_id)),
            "networkChecked": True,
        }

    def _bridge_request_headers(self, connector_id: str) -> dict[str, str]:
        token = self._bridge_token(connector_id)
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _bridge_call(self, connector_id: str, operation: str, payload: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        base = self._bridge_url(connector_id).rstrip("/")
        if not base:
            raise MessageConnectorError("missing_bridge_url", "个人账号模式必须配置本地兼容桥地址", status_code=422)
        try:
            result = self._http_get(f"{base}/status", self._bridge_request_headers(connector_id)) if operation == "status" else self._http_post(f"{base}/{operation}", self._bridge_request_headers(connector_id), payload or {})
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise MessageConnectorError("bridge_unavailable", "个人账号兼容桥不可用", status_code=502) from exc
        if not isinstance(result, Mapping):
            raise MessageConnectorError("bridge_invalid_response", "兼容桥返回格式无效", status_code=502)
        if result.get("ok") is False and operation != "status":
            raise MessageConnectorError("bridge_rejected", "个人账号兼容桥拒绝了请求", status_code=502)
        return result

    def login_account(self, connector_id: str) -> dict[str, Any]:
        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            raise MessageConnectorError("account_mode_not_supported", "仅 QQ/微信支持个人账号兼容桥", status_code=409)
        try:
            result = self._bridge_call(connector_id, "login", {"platform": connector_id, "protocol": self._bridge_protocol(connector_id)})
        except MessageConnectorError as exc:
            self._account_last_error[connector_id] = exc.code
            raise
        account = dict(self._config.get(connector_id, {}))
        state = _text(result.get("state") or result.get("status")) or "awaiting_scan"
        account["loginState"] = state if state in {"connected", "awaiting_scan", "signed_out", "error"} else "awaiting_scan"
        account["accountId"] = _bounded_text(result.get("account_id") or result.get("accountId"), 256)
        account["accountName"] = _bounded_text(result.get("account_name") or result.get("accountName") or result.get("nickname"), 256)
        self._account_login_urls[connector_id] = _bounded_text(result.get("login_url") or result.get("loginUrl") or result.get("qr_url") or result.get("qrUrl"), 2048) or None
        if account["loginState"] == "connected":
            self._account_login_urls[connector_id] = None
        self._config[connector_id] = account
        self._account_last_error[connector_id] = _text(result.get("error")) or None
        self._save_disabled()
        return self.account_status(connector_id) or {}

    def refresh_account_status(self, connector_id: str) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            return None
        try:
            result = self._bridge_call(connector_id, "status")
        except MessageConnectorError as exc:
            self._account_last_error[connector_id] = exc.code
            return self.account_status(connector_id)
        account = dict(self._config.get(connector_id, {}))
        state = _text(result.get("state") or result.get("status")) or "signed_out"
        account["loginState"] = state if state in {"connected", "awaiting_scan", "signed_out", "error"} else "error"
        for key, aliases in (("accountId", ("account_id", "accountId")), ("accountName", ("account_name", "accountName", "nickname"))):
            for alias in aliases:
                if result.get(alias):
                    account[key] = _bounded_text(result.get(alias), 256)
                    break
        self._config[connector_id] = account
        self._account_last_error[connector_id] = _text(result.get("error")) or None
        self._save_disabled()
        return self.account_status(connector_id)

    def logout_account(self, connector_id: str) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            return None
        self._bridge_call(connector_id, "logout")
        account = dict(self._config.get(connector_id, {}))
        account.update({"loginState": "signed_out", "accountId": "", "accountName": ""})
        self._config[connector_id] = account
        self._account_login_urls[connector_id] = None
        self._account_last_error[connector_id] = None
        self._save_disabled()
        return self.account_status(connector_id)

    def unbind_account(self, connector_id: str) -> dict[str, Any] | None:
        """Clear account credentials while preserving callback verification config."""

        connector_id = _text(connector_id).lower()
        if connector_id not in {"qq", "wechat"}:
            return None
        existing = dict(self._config.get(connector_id, {}))
        existing["enabled"] = False
        existing["bridgeUrl"] = ""
        existing["bridgeProtocol"] = "generic"
        existing["bridgeToken"] = ""
        existing["accountId"] = ""
        existing["accountName"] = ""
        existing["loginState"] = "signed_out"
        self._config[connector_id] = existing
        self._disabled.add(connector_id)
        self._account_last_error[connector_id] = None
        self._save_disabled()
        return self.account_status(connector_id)

    def update_config(self, connector_id: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        connector_id = _text(connector_id).lower()
        if connector_id not in self._CONNECTOR_ORDER:
            return None
        existing = dict(self._config.get(connector_id, {}))
        if connector_id in {"qq", "wechat"} and _REMOVED_OFFICIAL_FIELDS.intersection(payload):
            raise MessageConnectorError("official_connector_removed", "QQ/微信仅支持个人账号兼容桥，官方连接器已移除", status_code=422)
        for field, limit in (("botToken", 512), ("webhookSecret", 256), ("publicKey", 64), ("bridgeUrl", 512), ("bridgeProtocol", 32), ("bridgeToken", 512)):
            clear_field = f"clear{field[0].upper()}{field[1:]}"
            if payload.get(clear_field) is True:
                existing[field] = ""
                continue
            if field in payload:
                existing[field] = _bounded_text(payload.get(field), limit)
        if connector_id in {"qq", "wechat"} and "bridgeUrl" in payload:
            try:
                existing["bridgeUrl"] = _validate_bridge_url(payload.get("bridgeUrl"))
            except ValueError as exc:
                raise MessageConnectorError("invalid_bridge_url", str(exc), status_code=422) from exc
        if "enabled" in payload:
            existing["enabled"] = bool(payload.get("enabled"))
        if connector_id in {"qq", "wechat"}:
            requested_mode = _text(payload.get("accountMode"))
            if requested_mode and requested_mode != "personal_bridge":
                raise MessageConnectorError("personal_bridge_only", "QQ/微信仅支持个人账号兼容桥模式", status_code=422)
            existing["accountMode"] = "personal_bridge"
            existing["bridgeProtocol"] = (_text(existing.get("bridgeProtocol")) or "generic").lower()
        if connector_id == "discord" and existing.get("publicKey"):
            key = _text(existing["publicKey"]).lower()
            try:
                valid_key = len(bytes.fromhex(key)) == 32
            except ValueError:
                valid_key = False
            if not valid_key:
                raise MessageConnectorError("invalid_public_key", "Discord Public Key 必须是 64 位十六进制字符串")
            existing["publicKey"] = key
        if existing.get("enabled"):
            token = _text(existing.get("botToken")) or self._env.get(f"YUIZAKI_{connector_id.upper()}_BOT_TOKEN", "").strip()
            webhook_secret = _text(existing.get("webhookSecret")) or self._env.get("YUIZAKI_TELEGRAM_WEBHOOK_SECRET", "").strip()
            public_key = _text(existing.get("publicKey")) or self._env.get("YUIZAKI_DISCORD_PUBLIC_KEY", "").strip()
            bridge_token = _text(existing.get("bridgeToken")) or self._env.get(f"YUIZAKI_{connector_id.upper()}_BRIDGE_TOKEN", "").strip()
            if connector_id == "telegram" and not token:
                raise MessageConnectorError("missing_bot_token", "启用 Telegram 前必须配置 Bot Token")
            if connector_id == "telegram" and not webhook_secret:
                raise MessageConnectorError("missing_webhook_secret", "启用 Telegram 前必须配置 webhook secret")
            if connector_id == "discord" and not public_key:
                raise MessageConnectorError("missing_public_key", "启用 Discord 前必须配置 Public Key")
            if connector_id in {"qq", "wechat"} and not (_text(existing.get("bridgeUrl")) or self._env.get(f"YUIZAKI_{connector_id.upper()}_BRIDGE_URL", "").strip()):
                raise MessageConnectorError("missing_bridge_url", "启用个人账号兼容桥前必须配置桥地址")
            if connector_id in {"qq", "wechat"} and not bridge_token:
                raise MessageConnectorError("missing_bridge_token", "启用个人账号兼容桥前必须配置桥 token")
        if existing.get("enabled"):
            self._disabled.discard(connector_id)
        self._config[connector_id] = existing
        self._save_disabled()
        return self.config_snapshot(connector_id)

    def is_enabled(self, connector_id: str) -> bool:
        # A transient delivery/turn failure must not disable future webhooks.
        # ``snapshot`` still exposes the failure health state until success.
        connector_id = _text(connector_id).lower()
        return (
            connector_id in self._CONNECTOR_ORDER
            and self._installed(connector_id)
            and self._verification_configured(connector_id)
            and self._enabled(connector_id)
            and connector_id not in self._disabled
        )

    def verify_request(self, connector_id: str, headers: Mapping[str, str], body: bytes = b"") -> bool:
        # Telegram uses its optional secret header; QQ/WeChat bridges use the
        # configured bearer token. Discord uses Ed25519.
        expected = self._bridge_token(connector_id) if connector_id in {"qq", "wechat"} else (self._secret(connector_id) if connector_id == "telegram" else "")
        provided = _text(
            headers.get("X-Telegram-Bot-Api-Secret-Token")
            or headers.get("X-Yuizaki-Connector-Secret")
            or headers.get("X-Discord-Webhook-Secret")
        )
        if not provided:
            authorization = _text(headers.get("Authorization"))
            if authorization.lower().startswith("bearer "):
                provided = authorization[7:].strip()
        if connector_id == "discord":
            public_key = self._public_key(connector_id)
            # Discord signs every interaction, including the endpoint PING.
            # Never accept an unsigned request merely because the key is absent.
            if not public_key:
                return False
            return verify_discord_signature(
                body=body,
                timestamp=_text(headers.get("X-Signature-Timestamp")),
                signature=_text(headers.get("X-Signature-Ed25519")),
                public_key=public_key,
            )
        if not expected:
            return False
        return bool(provided and hmac.compare_digest(provided, expected))

    # Compatibility spelling for callers that only have a header map.
    def verify_secret(self, connector_id: str, headers: Mapping[str, str]) -> bool:
        return self.verify_request(connector_id, headers)

    def parse(
        self,
        connector_id: str,
        payload: Mapping[str, Any],
        *,
        received_at: float | None = None,
    ) -> ConnectorMessage | None:
        connector_id = _text(connector_id).lower()
        if connector_id == "telegram":
            return self._parse_telegram(payload)
        if connector_id == "discord":
            return self._parse_discord(payload, received_at=received_at)
        if connector_id == "qq":
            return self._parse_bridge_message("qq", payload)
        if connector_id == "wechat":
            return self._parse_bridge_message("wechat", payload)
        raise MessageConnectorError("unknown_connector", "不支持的消息连接器", status_code=404)

    def _parse_bridge_message(self, connector_id: str, payload: Mapping[str, Any]) -> ConnectorMessage | None:
        event_id = _text(payload.get("id") or payload.get("event_id") or payload.get("message_id") or payload.get("time"))
        raw_sender = payload.get("sender")
        sender: Mapping[str, Any] = raw_sender if isinstance(raw_sender, Mapping) else {}
        user_id = _text(payload.get("user_id") or payload.get("openid") or payload.get("from_user") or sender.get("user_id"))
        group_id = _text(payload.get("group_id") or payload.get("channel_id") or payload.get("conversation_id"))
        raw_message = payload.get("message") or payload.get("text") or payload.get("content")
        if isinstance(raw_message, list):
            raw_message = "".join(_text(item.get("data", {}).get("text")) if isinstance(item, Mapping) and isinstance(item.get("data"), Mapping) else _text(item) for item in raw_message)
        text = _bounded_text(raw_message, 4000)
        conversation_id = group_id or user_id
        if not event_id or not text or not conversation_id:
            return None
        return ConnectorMessage(connector_id=connector_id, event_id=event_id, session_id=f"connector:{connector_id}:{'group' if group_id else 'user'}:{conversation_id}", external_user_id=user_id or "unknown", conversation_id=conversation_id, text=text, reply_target={"user_id": user_id, "group_id": group_id, "conversation_id": conversation_id})

    def _parse_telegram(self, payload: Mapping[str, Any]) -> ConnectorMessage | None:
        message = payload.get("message") or payload.get("edited_message")
        if not isinstance(message, Mapping):
            return None
        text = _bounded_text(message.get("text") or message.get("caption"), 4000)
        raw_chat = message.get("chat")
        chat: Mapping[str, Any] = raw_chat if isinstance(raw_chat, Mapping) else {}
        raw_sender = message.get("from")
        sender: Mapping[str, Any] = raw_sender if isinstance(raw_sender, Mapping) else {}
        chat_id = _text(chat.get("id"))
        if not text or not chat_id:
            return None
        event_id = _text(payload.get("update_id"))
        if not event_id:
            raise MessageConnectorError("invalid_update", "Telegram Update 缺少 update_id")
        return ConnectorMessage(
            connector_id="telegram",
            event_id=event_id,
            session_id=f"connector:telegram:chat:{chat_id}",
            external_user_id=_text(sender.get("id")) or "unknown",
            conversation_id=chat_id,
            text=text,
            reply_target={
                "chat_id": chat_id,
                "message_thread_id": _text(message.get("message_thread_id")),
            },
        )

    def _parse_discord(
        self,
        payload: Mapping[str, Any],
        *,
        received_at: float | None = None,
    ) -> ConnectorMessage | None:
        if payload.get("type") == 1:  # Discord PING is handled by the route.
            return None
        interaction_data = payload.get("data") if isinstance(payload.get("data"), Mapping) else None
        interaction_type = payload.get("type")
        if interaction_type in {2, 3, 5} and interaction_data is not None:
            if interaction_type == 2:
                command = _text(interaction_data.get("name"))
                options = interaction_data.get("options") if isinstance(interaction_data.get("options"), list) else []
                suffix = " ".join(_text(item.get("value")) for item in options if isinstance(item, Mapping) and _text(item.get("value")))
                text = _bounded_text(f"/{command} {suffix}".strip(), 4000)
            elif interaction_type == 3:
                text = _bounded_text(f"component:{_text(interaction_data.get('custom_id'))}", 4000)
            else:
                components = interaction_data.get("components") if isinstance(interaction_data.get("components"), list) else []
                values: list[str] = []
                for row in components:
                    if not isinstance(row, Mapping) or not isinstance(row.get("components"), list):
                        continue
                    values.extend(
                        f"{_text(item.get('custom_id'))}={_text(item.get('value'))}"
                        for item in row["components"]
                        if isinstance(item, Mapping) and _text(item.get("custom_id")) and _text(item.get("value"))
                    )
                text = _bounded_text("modal:" + " ".join(values), 4000)
            channel_id = _text(payload.get("channel_id"))
            application_id = _text(payload.get("application_id"))
            interaction_token = _text(payload.get("token"))
            user = payload.get("member") if isinstance(payload.get("member"), Mapping) else payload.get("user")
            user = user if isinstance(user, Mapping) else {}
            user_id = _text(user.get("user", {}).get("id")) if isinstance(user.get("user"), Mapping) else _text(user.get("id"))
            event_id = _text(payload.get("id"))
            if not text or not channel_id or not event_id or not application_id or not interaction_token:
                raise MessageConnectorError("invalid_interaction", "Discord Interaction 缺少必要身份字段")
            return ConnectorMessage(
                connector_id="discord",
                event_id=event_id,
                session_id=f"connector:discord:channel:{channel_id}",
                external_user_id=user_id or "unknown",
                conversation_id=channel_id,
                text=text,
                reply_target={
                    "interaction_id": event_id,
                    "interaction_token": interaction_token,
                    "application_id": application_id,
                    "channel_id": channel_id,
                    "interaction_expires_at": str(
                        (self._clock() if received_at is None else float(received_at)) + 15 * 60
                    ),
                },
            )
        # Ordinary Discord messages require a Gateway client. This adapter is
        # intentionally interaction-only until that host runtime exists.
        return None

    def record_failure(self, connector_id: str, error: str) -> None:
        if connector_id in self._last_error:
            self._last_error[connector_id] = _bounded_text(error, 240) or "连接器执行失败"

    def record_success(self, connector_id: str) -> None:
        if connector_id in self._last_error:
            self._last_error[connector_id] = None

    def send_reply(self, message: ConnectorMessage, reply: str) -> Mapping[str, Any]:
        reply = _bounded_text(reply, 4000)
        if not reply:
            return {"sent": False, "reason": "empty_reply"}
        connector_id = message.connector_id
        if connector_id in {"qq", "wechat"}:
            base_url = self._bridge_url(connector_id).rstrip("/")
            headers = self._bridge_request_headers(connector_id)
            if connector_id == "qq" and self._bridge_protocol(connector_id) in {"onebot11", "onebot12"}:
                group_id = message.reply_target.get("group_id")
                endpoint = f"{base_url}/send_group_msg" if group_id else f"{base_url}/send_private_msg"
                payload = {"group_id": group_id, "message": reply} if group_id else {"user_id": message.reply_target.get("user_id") or message.external_user_id, "message": reply}
                return self._http_post(endpoint, headers, payload)
            return self._http_post(f"{base_url}/send", headers, {"platform": connector_id, "conversation_id": message.conversation_id, "user_id": message.external_user_id, "text": reply})
        token = self._token(connector_id)
        if connector_id == "telegram":
            payload: dict[str, Any] = {"chat_id": message.reply_target["chat_id"], "text": reply}
            thread_id = message.reply_target.get("message_thread_id")
            if thread_id:
                payload["message_thread_id"] = thread_id
            return self._http_post(
                f"https://api.telegram.org/bot{quote(token, safe='')}/sendMessage",
                {},
                payload,
            )
        interaction_id = message.reply_target.get("interaction_id", "")
        interaction_token = message.reply_target.get("interaction_token", "")
        if interaction_id and interaction_token:
            if not self._discord_interaction_expired(message):
                return self._http_patch(
                    self._discord_original_response_url(message),
                    {},
                    {"content": _bounded_text(reply, 2000), "allowed_mentions": {"parse": []}},
                )
            token = self._token("discord")
            channel_id = message.reply_target.get("channel_id", "")
            if not token or not channel_id:
                return {
                    "ok": False,
                    "sent": False,
                    "status_code": 410,
                    "reason": "interaction_token_expired",
                }
            return self._http_post(
                f"https://discord.com/api/v10/channels/{quote(channel_id, safe='')}/messages",
                {"Authorization": f"Bot {token}"},
                {
                    "content": _bounded_text(reply, 2000),
                    "allowed_mentions": {"parse": []},
                },
            )
        channel_id = message.reply_target.get("channel_id", "")
        return self._http_post(
            f"https://discord.com/api/v10/channels/{quote(channel_id, safe='')}/messages",
            {"Authorization": f"Bot {token}"},
            {"content": _bounded_text(reply, 2000), "allowed_mentions": {"parse": []}},
        )

    def update_deferred_status(self, message: ConnectorMessage, status: str) -> Mapping[str, Any]:
        """Best-effort convergence for Discord's visible deferred response."""

        if message.connector_id != "discord" or not message.reply_target.get("interaction_token"):
            return {"ok": False, "sent": False, "reason": "not_deferred_interaction"}
        if self._discord_interaction_expired(message):
            return {"ok": False, "sent": False, "status_code": 410, "reason": "interaction_token_expired"}
        content = {
            "cancelled": "已停止处理。",
            "failed": "处理失败，请在 Yuizaki 连接器面板中重试。",
            "unknown": "处理未完成，最终结果尚未确认。",
        }.get(status, "处理未完成。")
        return self._http_patch(
            self._discord_original_response_url(message),
            {},
            {"content": content, "allowed_mentions": {"parse": []}},
        )

    def _discord_original_response_url(self, message: ConnectorMessage) -> str:
        application_id = quote(message.reply_target.get("application_id", ""), safe="")
        interaction_token = quote(message.reply_target.get("interaction_token", ""), safe="")
        return f"https://discord.com/api/v10/webhooks/{application_id}/{interaction_token}/messages/@original"

    def _discord_interaction_expired(self, message: ConnectorMessage) -> bool:
        try:
            expires_at = float(message.reply_target.get("interaction_expires_at", "0"))
        except (TypeError, ValueError):
            return True
        return expires_at <= 0 or self._clock() >= expires_at


__all__ = ["ConnectorMessage", "MessageConnectorError", "MessageConnectorRegistry"]
