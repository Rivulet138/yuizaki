"""Inbound Twitch stream events.

This module intentionally implements ingress only.  It verifies Twitch
EventSub requests and parses already-received IRC lines, then hands normalized
events to the local stream queue.  It never opens a socket or sends a message.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

MAX_EVENTSUB_BODY_BYTES = 512 * 1024
MAX_MESSAGE_ID_LENGTH = 256
_TWITCH_STATE_SCHEMA = "yuizaki.twitch-state.v1"
TWITCH_CHAT_ENDPOINT = "https://api.twitch.tv/helix/chat/messages"
_EVENTSUB_SUBSCRIPTION_TYPES = (
    "channel.chat.message",
    "channel.follow",
    "channel.subscribe",
)
_EVENTSUB_SUBSCRIPTION_SET = frozenset(_EVENTSUB_SUBSCRIPTION_TYPES)


class TwitchSubscriptionProvider(Protocol):
    """Explicit provider boundary for EventSub subscription reconciliation."""

    @property
    def name(self) -> str: ...

    def list_subscriptions(self) -> list[Mapping[str, Any]]: ...

    def create_subscription(self, subscription_type: str) -> Mapping[str, Any]: ...

    def delete_subscription(self, subscription_id: str) -> Mapping[str, Any]: ...


class InMemoryTwitchSubscriptionProvider:
    """Deterministic staging provider; it never opens a network connection."""

    name = "in-memory-staging"

    def __init__(self, subscription_types: list[str] | None = None) -> None:
        self._subscriptions: dict[str, str] = {}
        for subscription_type in subscription_types or []:
            if subscription_type in _EVENTSUB_SUBSCRIPTION_SET:
                self.create_subscription(subscription_type)

    def list_subscriptions(self) -> list[Mapping[str, Any]]:
        return [
            {"id": subscription_id, "type": subscription_type}
            for subscription_id, subscription_type in self._subscriptions.items()
        ]

    def create_subscription(self, subscription_type: str) -> Mapping[str, Any]:
        if subscription_type not in _EVENTSUB_SUBSCRIPTION_SET:
            raise TwitchEventSubError("unsupported EventSub subscription type")
        for subscription_id, current_type in self._subscriptions.items():
            if current_type == subscription_type:
                return {"id": subscription_id, "type": current_type, "status": "enabled"}
        subscription_id = f"staging-sub-{len(self._subscriptions) + 1}"
        self._subscriptions[subscription_id] = subscription_type
        return {"id": subscription_id, "type": subscription_type, "status": "enabled"}

    def delete_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        subscription_type = self._subscriptions.pop(subscription_id, None)
        if subscription_type is None:
            raise TwitchEventSubError("subscription id is unknown")
        return {"id": subscription_id, "type": subscription_type, "status": "removed"}


class TwitchHelixSubscriptionProvider:
    """Explicit Twitch Helix EventSub subscription manager.

    The provider is inert until the application explicitly selects it and
    supplies all required configuration. It performs one short-lived HTTP
    request per operation and never retries or exposes the access token.
    """

    name = "twitch-helix"
    endpoint = "https://api.twitch.tv/helix/eventsub/subscriptions"

    def __init__(
        self,
        *,
        client_id: str | None,
        access_token: str | None,
        broadcaster_id: str | None,
        callback_url: str | None,
        secret: str | None,
        moderator_id: str | None = None,
        timeout: float = 5.0,
        request: Callable[..., Any] | None = None,
    ) -> None:
        self.client_id = str(client_id or "").strip()
        self.access_token = str(access_token or "").strip().removeprefix("Bearer ").removeprefix("oauth:").strip()
        self.broadcaster_id = str(broadcaster_id or "").strip()
        self.callback_url = str(callback_url or "").strip()
        self.secret = str(secret or "").strip()
        self.moderator_id = str(moderator_id or self.broadcaster_id).strip()
        self.timeout = max(0.5, min(float(timeout), 15.0))
        self._request = request
        self._known_types: dict[str, str] = {}

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.access_token
            and self.broadcaster_id
            and self.callback_url.startswith("https://")
            and len(self.secret) >= 10
            and self.moderator_id
        )

    def _call(self, method: str, **kwargs: Any) -> Any:
        if not self.configured:
            raise TwitchEventSubError("Twitch Helix subscription provider is not configured")
        headers = {
            "Client-Id": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            if self._request is not None:
                response = self._request(method, self.endpoint, headers=headers, timeout=self.timeout, **kwargs)
            else:
                import httpx

                response = httpx.request(method, self.endpoint, headers=headers, timeout=self.timeout, **kwargs)
        except TwitchEventSubError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Twitch Helix request failed: {type(exc).__name__}") from exc
        status_code = int(getattr(response, "status_code", 0) or 0)
        try:
            payload = response.json() if getattr(response, "content", b"") else {}
        except Exception as exc:
            raise RuntimeError("Twitch Helix returned invalid JSON") from exc
        if status_code < 200 or status_code >= 300:
            message = payload.get("message") if isinstance(payload, Mapping) else None
            raise RuntimeError(f"Twitch Helix request rejected ({status_code}): {str(message or 'provider_error')[:120]}")
        return payload

    @staticmethod
    def _records(payload: Any) -> list[dict[str, Any]]:
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, list):
            raise TypeError("Twitch Helix subscription response is missing data")
        records: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, Mapping):
                raise TypeError("Twitch Helix subscription metadata is invalid")
            subscription_id = item.get("id")
            subscription_type = item.get("type")
            status = item.get("status")
            if not isinstance(subscription_id, str) or not isinstance(subscription_type, str):
                raise TypeError("Twitch Helix subscription metadata is incomplete")
            records.append({"id": subscription_id, "type": subscription_type, "status": str(status or "")[:40]})
        return records

    def list_subscriptions(self) -> list[Mapping[str, Any]]:
        records = self._records(self._call("GET"))
        self._known_types = {str(item["id"]): str(item["type"]) for item in records}
        return records

    def create_subscription(self, subscription_type: str) -> Mapping[str, Any]:
        if subscription_type not in _EVENTSUB_SUBSCRIPTION_SET:
            raise TwitchEventSubError("unsupported EventSub subscription type")
        conditions: dict[str, str] = {"broadcaster_user_id": self.broadcaster_id}
        if subscription_type == "channel.follow":
            conditions["moderator_user_id"] = self.moderator_id
        elif subscription_type == "channel.chat.message":
            conditions["user_id"] = self.moderator_id
        payload = self._call(
            "POST",
            json={
                "type": subscription_type,
                "version": "1",
                "condition": conditions,
                "transport": {"method": "webhook", "callback": self.callback_url, "secret": self.secret},
            },
        )
        records = self._records(payload)
        if len(records) != 1 or records[0]["type"] != subscription_type:
            raise RuntimeError("Twitch Helix create response is invalid")
        self._known_types[records[0]["id"]] = records[0]["type"]
        return records[0]

    def delete_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        value = str(subscription_id or "").strip()
        if not value or len(value) > 160:
            raise TwitchEventSubError("subscription id is invalid")
        subscription_type = self._known_types.get(value)
        if subscription_type is None:
            raise TwitchEventSubError("subscription id is not known; refresh subscriptions first")
        self._call("DELETE", params={"id": value})
        self._known_types.pop(value, None)
        return {"id": value, "type": subscription_type, "status": "removed"}


class TwitchEventSubError(ValueError):
    """A malformed or unauthenticated Twitch webhook request."""


class TwitchChatAdapter:
    """Explicit Twitch Helix chat sender.

    The adapter is intentionally short-lived and never retries a request. The
    caller's preview ticket provides the replay boundary; a timeout is treated
    as an unknown provider effect by the stream runtime.
    """

    def __init__(
        self,
        client_id: str | None,
        access_token: str | None,
        broadcaster_id: str | None,
        sender_id: str | None,
        *,
        timeout: float = 5.0,
    ) -> None:
        self.client_id = (client_id or "").strip()
        self.access_token = (access_token or "").strip().removeprefix("Bearer ").strip()
        self.broadcaster_id = (broadcaster_id or "").strip()
        self.sender_id = (sender_id or "").strip()
        self.timeout = max(0.5, min(float(timeout), 15.0))

    def configure(
        self,
        client_id: str | None,
        access_token: str | None,
        broadcaster_id: str | None,
        sender_id: str | None,
    ) -> None:
        """Replace credentials in memory; callers must stop active sends first."""
        self.client_id = str(client_id or "").strip()
        self.access_token = str(access_token or "").strip().removeprefix("Bearer ").strip()
        self.broadcaster_id = str(broadcaster_id or "").strip()
        self.sender_id = str(sender_id or "").strip()

    @property
    def configured(self) -> bool:
        return all((self.client_id, self.access_token, self.broadcaster_id, self.sender_id))

    def send_message(self, text: str) -> dict[str, Any]:
        message = str(text or "").strip()
        if not message:
            raise TwitchEventSubError("Twitch chat message is empty")
        if len(message) > 500:
            raise TwitchEventSubError("Twitch chat message is longer than 500 characters")
        if not self.configured:
            raise TwitchEventSubError("Twitch chat sender is not configured")
        try:
            import httpx

            response = httpx.post(
                TWITCH_CHAT_ENDPOINT,
                headers={
                    "Client-Id": self.client_id,
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "broadcaster_id": self.broadcaster_id,
                    "sender_id": self.sender_id,
                    "message": message,
                },
                timeout=self.timeout,
            )
            status_code = int(response.status_code)
            payload = response.json() if response.content else {}
        except TwitchEventSubError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Twitch chat request failed: {type(exc).__name__}") from exc
        data = payload.get("data") if isinstance(payload, Mapping) else None
        item = data[0] if isinstance(data, list) and data and isinstance(data[0], Mapping) else {}
        sent = item.get("is_sent") is True
        if status_code < 200 or status_code >= 300 or not sent:
            reason = str(item.get("drop_reason") or payload.get("message") if isinstance(payload, Mapping) else "provider_rejected")
            raise RuntimeError(f"Twitch chat provider rejected message: {reason[:160]}")
        return {
            "provider": "twitch-helix",
            "statusCode": status_code,
            "sent": True,
            "messageId": str(item.get("message_id") or "")[:160] or None,
        }


class TwitchEventIngress:
    """Verify and normalize Twitch EventSub notifications and IRC messages."""

    def __init__(
        self,
        secret: str | None,
        enqueue_event: Callable[[dict[str, Any]], Any],
        *,
        max_age_seconds: int = 600,
        max_events_per_minute: int = 120,
        state_path: str | Path | None = None,
        subscription_provider: TwitchSubscriptionProvider | None = None,
    ) -> None:
        self.secret = (secret or "").strip()
        self.enqueue_event = enqueue_event
        self.max_age_seconds = max(30, min(int(max_age_seconds), 900))
        self.max_events_per_minute = max(10, min(int(max_events_per_minute), 1000))
        self._seen_message_ids: dict[str, float] = {}
        self._seen_lock = RLock()
        self._event_times: deque[float] = deque()
        self._throttled_events = 0
        self._revoked = False
        self._revocation_count = 0
        self._last_event_at: str | None = None
        self._last_message_id: str | None = None
        self._desired_subscriptions: list[str] = []
        self._active_subscriptions: list[dict[str, str]] = []
        self._last_sync_at: str | None = None
        self._last_sync_error: str | None = None
        self._subscription_provider = subscription_provider
        self._state_path = Path(state_path) if state_path is not None else None
        self._load_state()

    def _load_state(self) -> None:
        path = self._state_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError):
            return
        if not isinstance(payload, Mapping) or payload.get("schemaVersion") != _TWITCH_STATE_SCHEMA:
            return
        with self._seen_lock:
            self._revoked = payload.get("revoked") is True
            try:
                self._revocation_count = max(0, int(payload.get("revocationCount") or 0))
            except (TypeError, ValueError, OverflowError):
                self._revocation_count = 0
            last_event = payload.get("lastEventAt")
            self._last_event_at = str(last_event).strip()[:80] if isinstance(last_event, str) and last_event.strip() else None
            last_message = payload.get("lastMessageId")
            self._last_message_id = str(last_message).strip()[:MAX_MESSAGE_ID_LENGTH] if isinstance(last_message, str) and last_message.strip() else None
            raw_subscriptions = payload.get("desiredSubscriptions")
            if isinstance(raw_subscriptions, list):
                self._desired_subscriptions = self._sanitize_subscription_types(raw_subscriptions)
            raw_active = payload.get("activeSubscriptions")
            if isinstance(raw_active, list):
                self._active_subscriptions = self._sanitize_subscription_records(raw_active)
            last_sync = payload.get("lastSyncAt")
            self._last_sync_at = str(last_sync).strip()[:80] if isinstance(last_sync, str) and last_sync.strip() else None
            last_error = payload.get("lastSyncError")
            self._last_sync_error = str(last_error).strip()[:160] if isinstance(last_error, str) and last_error.strip() else None

    def _persist_state_locked(self) -> None:
        path = self._state_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "schemaVersion": _TWITCH_STATE_SCHEMA,
                        "revoked": self._revoked,
                        "revocationCount": self._revocation_count,
                        "lastEventAt": self._last_event_at,
                        "lastMessageId": self._last_message_id,
                        "desiredSubscriptions": list(self._desired_subscriptions),
                        "activeSubscriptions": list(self._active_subscriptions),
                        "lastSyncAt": self._last_sync_at,
                        "lastSyncError": self._last_sync_error,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            temporary.replace(path)
        except (OSError, TypeError, ValueError):
            return

    def configure_secret(self, secret: str | None) -> None:
        """Update the EventSub signing secret without exposing it in state."""
        with self._seen_lock:
            self.secret = str(secret or "").strip()

    def configure_subscription_provider(self, provider: TwitchSubscriptionProvider | None) -> None:
        """Swap the explicit subscription provider without changing local plan state."""
        with self._seen_lock:
            self._subscription_provider = provider

    def snapshot(self) -> dict[str, Any]:
        with self._seen_lock:
            provider = self._subscription_provider
            provider_name = str(getattr(provider, "name", "provider") or "provider")[:80] if provider is not None else None
            active_types = []
            for item in self._active_subscriptions:
                item_type = item.get("type")
                if item_type and item_type not in active_types:
                    active_types.append(item_type)
            return {
                "inboundRateLimitPerMinute": self.max_events_per_minute,
                "throttledEvents": self._throttled_events,
                "revoked": self._revoked,
                "revocationCount": self._revocation_count,
                "connectionStatus": "revoked" if self._revoked else "configured" if self.secret else "unconfigured",
                "lastEventAt": self._last_event_at,
                "subscriptionPlan": {
                    "status": (
                        "revoked" if self._revoked
                        else "synced" if provider is not None and self._desired_subscriptions and set(self._desired_subscriptions) == set(active_types) and not self._last_sync_error
                        else "planned" if self._desired_subscriptions and self.secret
                        else "not_planned" if self.secret
                        else "unconfigured"
                    ),
                    "management": provider_name or "local_only",
                    "remoteSyncAvailable": provider is not None,
                    "desired": list(self._desired_subscriptions),
                    "active": active_types,
                    "lastSyncAt": self._last_sync_at,
                    "lastError": self._last_sync_error or ("remote_management_not_configured" if self._desired_subscriptions and provider is None else None),
                    "externalSideEffects": False,
                },
            }

    @property
    def subscription_provider_configured(self) -> bool:
        return self._subscription_provider is not None

    @staticmethod
    def _sanitize_subscription_types(values: list[Any]) -> list[str]:
        """Normalize a bounded, ordered EventSub subscription plan."""
        normalized: list[str] = []
        for value in values[:10]:
            if not isinstance(value, str):
                continue
            item = value.strip().lower()
            if item in _EVENTSUB_SUBSCRIPTION_SET and item not in normalized:
                normalized.append(item)
        return normalized

    def configure_subscriptions(self, subscriptions: Any) -> dict[str, Any]:
        """Persist a local EventSub plan without contacting Twitch."""
        if not isinstance(subscriptions, list) or isinstance(subscriptions, bool):
            raise TwitchEventSubError("EventSub subscriptions must be a list")
        if len(subscriptions) > 10:
            raise TwitchEventSubError("EventSub subscription plan is too large")
        if any(not isinstance(item, str) for item in subscriptions):
            raise TwitchEventSubError("EventSub subscription types must be strings")
        unknown = [item.strip().lower() for item in subscriptions if item.strip().lower() not in _EVENTSUB_SUBSCRIPTION_SET]
        if unknown:
            raise TwitchEventSubError(f"unsupported EventSub subscription type: {unknown[0]}")
        with self._seen_lock:
            self._desired_subscriptions = self._sanitize_subscription_types(subscriptions)
            self._persist_state_locked()
            snapshot = self.snapshot()
        return {**snapshot, "externalSideEffects": False}

    @staticmethod
    def _sanitize_subscription_records(values: list[Any]) -> list[dict[str, str]]:
        records: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for value in values[:20]:
            if not isinstance(value, Mapping):
                continue
            subscription_id = value.get("id")
            subscription_type = value.get("type")
            if not isinstance(subscription_id, str) or not isinstance(subscription_type, str):
                continue
            subscription_id = subscription_id.strip()
            subscription_type = subscription_type.strip().lower()
            if not subscription_id or len(subscription_id) > 160 or subscription_id in seen_ids or subscription_type not in _EVENTSUB_SUBSCRIPTION_SET:
                continue
            seen_ids.add(subscription_id)
            records.append({"id": subscription_id, "type": subscription_type})
        return records

    def _provider_subscriptions(self) -> list[dict[str, str]]:
        provider = self._subscription_provider
        if provider is None:
            raise TwitchEventSubError("Twitch subscription provider is not configured")
        try:
            raw = provider.list_subscriptions()
        except Exception as exc:
            raise RuntimeError(f"subscription provider list failed: {type(exc).__name__}") from exc
        if not isinstance(raw, list):
            raise TypeError("subscription provider returned an invalid list")
        records = self._sanitize_subscription_records(raw)
        if len(records) != len(raw):
            raise RuntimeError("subscription provider returned invalid subscription metadata")
        return records

    def preview_subscription_sync(self) -> dict[str, Any]:
        with self._seen_lock:
            desired = list(self._desired_subscriptions)
            provider = self._subscription_provider
        if provider is None:
            return {
                "available": False,
                "provider": None,
                "desired": desired,
                "active": [],
                "toCreate": desired,
                "toDelete": [],
                "reason": "subscription_provider_not_configured",
                "externalSideEffects": False,
            }
        active = self._provider_subscriptions()
        active_types = {item["type"] for item in active}
        desired_set = set(desired)
        return {
            "available": True,
            "provider": str(getattr(provider, "name", "provider") or "provider")[:80],
            "desired": desired,
            "active": active,
            "toCreate": [item for item in desired if item not in active_types],
            "toDelete": [item for item in active if item["type"] not in desired_set],
            "externalSideEffects": False,
        }

    def sync_subscription_plan(self) -> dict[str, Any]:
        provider = self._subscription_provider
        if provider is None:
            raise TwitchEventSubError("Twitch subscription provider is not configured")
        plan = self.preview_subscription_sync()
        created: list[dict[str, str]] = []
        deleted: list[dict[str, str]] = []
        try:
            for subscription_type in plan["toCreate"]:
                result = provider.create_subscription(subscription_type)
                records = self._sanitize_subscription_records([result])
                if len(records) != 1 or records[0]["type"] != subscription_type:
                    raise RuntimeError("subscription provider returned invalid create metadata")
                created.append(records[0])
            for item in plan["toDelete"]:
                result = provider.delete_subscription(item["id"])
                records = self._sanitize_subscription_records([result])
                if len(records) != 1 or records[0]["id"] != item["id"]:
                    raise RuntimeError("subscription provider returned invalid delete metadata")
                deleted.append(records[0])
            active = self._provider_subscriptions()
        except Exception as exc:
            with self._seen_lock:
                self._last_sync_error = type(exc).__name__[:160]
                self._persist_state_locked()
            if isinstance(exc, TwitchEventSubError):
                raise
            raise RuntimeError(f"subscription sync failed: {type(exc).__name__}") from exc
        with self._seen_lock:
            self._active_subscriptions = active
            self._last_sync_at = datetime.now(timezone.utc).isoformat()
            self._last_sync_error = None
            self._persist_state_locked()
            snapshot = self.snapshot()
        return {
            "provider": str(getattr(provider, "name", "provider") or "provider")[:80],
            "created": created,
            "deleted": deleted,
            "subscriptionPlan": snapshot["subscriptionPlan"],
            "externalSideEffects": True,
        }

    def reset_revocation(self) -> dict[str, Any]:
        """Clear the local revocation marker after the user reconfigures Twitch."""
        with self._seen_lock:
            self._revoked = False
            self._persist_state_locked()
            return self.snapshot()

    @staticmethod
    def _header(headers: Mapping[str, Any], name: str) -> str:
        wanted = name.lower()
        for key, value in headers.items():
            if str(key).lower() == wanted:
                return str(value or "").strip()
        return ""

    def verify(self, raw_body: bytes, headers: Mapping[str, Any], *, now: float | None = None) -> str:
        if not isinstance(raw_body, bytes):
            raise TwitchEventSubError("EventSub body must be bytes")
        if len(raw_body) > MAX_EVENTSUB_BODY_BYTES:
            raise TwitchEventSubError("EventSub body is too large")
        if not self.secret:
            raise TwitchEventSubError("Twitch EventSub secret is not configured")
        message_id = self._header(headers, "Twitch-Eventsub-Message-Id")
        timestamp = self._header(headers, "Twitch-Eventsub-Message-Timestamp")
        signature = self._header(headers, "Twitch-Eventsub-Message-Signature")
        if not message_id or not timestamp or not signature:
            raise TwitchEventSubError("required Twitch EventSub headers are missing")
        if len(message_id) > MAX_MESSAGE_ID_LENGTH:
            raise TwitchEventSubError("Twitch EventSub message id is too long")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timestamp must include timezone")
            parsed_timestamp = parsed.timestamp()
        except (TypeError, ValueError, OverflowError) as exc:
            raise TwitchEventSubError("invalid Twitch EventSub timestamp") from exc
        try:
            current = time.time() if now is None else float(now)
        except (TypeError, ValueError, OverflowError) as exc:
            raise TwitchEventSubError("invalid verification clock") from exc
        if not math.isfinite(current) or not math.isfinite(parsed_timestamp):
            raise TwitchEventSubError("invalid Twitch EventSub timestamp")
        if abs(current - parsed_timestamp) > self.max_age_seconds:
            raise TwitchEventSubError("Twitch EventSub timestamp is expired")
        digest = hmac.new(
            self.secret.encode("utf-8"),
            message_id.encode("utf-8") + timestamp.encode("utf-8") + raw_body,
            hashlib.sha256,
        ).hexdigest()
        expected = f"sha256={digest}"
        if not hmac.compare_digest(expected, signature):
            raise TwitchEventSubError("invalid Twitch EventSub signature")
        return message_id

    def ingest_eventsub(self, raw_body: bytes, headers: Mapping[str, Any]) -> dict[str, Any]:
        message_id = self.verify(raw_body, headers)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TwitchEventSubError("EventSub body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise TwitchEventSubError("EventSub body must be an object")
        message_type = self._header(headers, "Twitch-Eventsub-Message-Type").lower()
        if message_type == "webhook_callback_verification":
            challenge = payload.get("challenge")
            if not isinstance(challenge, str) or not challenge:
                raise TwitchEventSubError("EventSub challenge is missing")
            return {"challenge": challenge, "accepted": True, "externalSideEffects": False}
        if message_type == "revocation":
            with self._seen_lock:
                self._revoked = True
                self._revocation_count += 1
                self._last_event_at = datetime.now(timezone.utc).isoformat()
                self._last_message_id = message_id
                self._persist_state_locked()
            return {"accepted": True, "revoked": True, "messageId": message_id, "externalSideEffects": False}
        if message_type != "notification":
            raise TwitchEventSubError("unsupported Twitch EventSub message type")
        # Twitch retries notifications.  A message id is claimed before queueing
        # so a transient caller retry cannot duplicate a local event.
        with self._seen_lock:
            if message_id in self._seen_message_ids:
                return {"accepted": True, "duplicate": True, "messageId": message_id, "externalSideEffects": False}
            self._seen_message_ids[message_id] = time.time()
        if not self._claim_event_slot():
            with self._seen_lock:
                self._throttled_events += 1
            self._prune_seen()
            return {
                "accepted": True,
                "messageId": message_id,
                "throttled": True,
                "queued": False,
                "externalSideEffects": False,
            }
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        subscription = payload.get("subscription") if isinstance(payload.get("subscription"), dict) else {}
        normalized = self._normalize_event(str(subscription.get("type") or ""), event)
        with self._seen_lock:
            self._last_event_at = datetime.now(timezone.utc).isoformat()
            self._last_message_id = message_id
            self._persist_state_locked()
        queued = None
        if normalized is not None:
            queued = self.enqueue_event({"kind": "chat", "text": normalized["text"], "author": normalized["author"], "source": "twitch"})
        self._prune_seen()
        return {
            "accepted": True,
            "messageId": message_id,
            "subscriptionType": subscription.get("type"),
            "normalized": normalized,
            "queued": queued is not None,
            "event": queued.get("event") if isinstance(queued, dict) else None,
            "externalSideEffects": False,
        }

    def _prune_seen(self) -> None:
        cutoff = time.time() - max(self.max_age_seconds, 900)
        with self._seen_lock:
            self._seen_message_ids = {key: value for key, value in self._seen_message_ids.items() if value >= cutoff}

    @staticmethod
    def _normalize_event(subscription_type: str, event: Mapping[str, Any]) -> dict[str, str] | None:
        if subscription_type == "channel.chat.message":
            text = event.get("message", {}).get("text") if isinstance(event.get("message"), dict) else event.get("text")
            author = event.get("chatter_user_name") or event.get("user_name") or "twitch"
            if isinstance(text, str) and text.strip():
                return {"kind": "chat", "text": text.strip(), "author": str(author)}
        if subscription_type == "channel.follow":
            author = str(event.get("user_name") or "twitch")
            return {"kind": "chat", "text": f"{author} 关注了频道", "author": author}
        if subscription_type == "channel.subscribe":
            author = str(event.get("user_name") or "twitch")
            tier = str(event.get("tier") or "1000")
            return {"kind": "chat", "text": f"{author} 订阅了频道（Tier {tier}）", "author": author}
        return None

    def ingest_irc(self, line: str) -> dict[str, Any]:
        if not isinstance(line, str) or not line.strip():
            raise TwitchEventSubError("IRC line is required")
        raw = line.strip("\r\n")
        if raw.startswith("PING "):
            return {"accepted": True, "kind": "ping", "queued": False, "externalSideEffects": False}
        if " PRIVMSG #" not in raw:
            return {"accepted": True, "kind": "ignored", "queued": False, "externalSideEffects": False}
        prefix, _, trailing = raw.partition(" PRIVMSG #")
        _channel, separator, text = trailing.partition(" :")
        if not separator or not text.strip():
            raise TwitchEventSubError("IRC PRIVMSG text is missing")
        author = prefix.removeprefix(":").split("!", 1)[0] or "twitch"
        if not self._claim_event_slot():
            with self._seen_lock:
                self._throttled_events += 1
            return {
                "accepted": True,
                "kind": "chat",
                "throttled": True,
                "queued": False,
                "externalSideEffects": False,
            }
        queued = self.enqueue_event({"kind": "chat", "text": text.strip(), "author": author, "source": "twitch"})
        with self._seen_lock:
            self._last_event_at = datetime.now(timezone.utc).isoformat()
            self._persist_state_locked()
        return {"accepted": True, "kind": "chat", "queued": True, "event": queued.get("event") if isinstance(queued, dict) else None, "externalSideEffects": False}

    def _claim_event_slot(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            return False
        cutoff = current - 60.0
        with self._seen_lock:
            while self._event_times and self._event_times[0] <= cutoff:
                self._event_times.popleft()
            if len(self._event_times) >= self.max_events_per_minute:
                return False
            self._event_times.append(current)
            return True
