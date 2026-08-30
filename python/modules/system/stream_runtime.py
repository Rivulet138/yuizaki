"""Local streaming capability state with explicit provider access.

    The runtime never connects automatically. Read-only probes are available on
    demand; broadcast writes require a preview ticket and explicit confirmation.
"""

from __future__ import annotations

import ipaddress
import json
import time
from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from .stream_moderation import StreamModerationPolicy
from .stream_platforms import (
    InMemoryTwitchSubscriptionProvider,
    TwitchChatAdapter,
    TwitchEventIngress,
    TwitchHelixSubscriptionProvider,
    TwitchSubscriptionProvider,
)
from .twitch_connection import TwitchConnectionSupervisor, TwitchIrcTransport

try:  # websocket-client is optional until an OBS adapter is configured.
    import websocket as _websocket
except ImportError:  # pragma: no cover - depends on the host installation
    _websocket = None

SCHEMA_VERSION = "1.0"

_ACTION_LABELS = {
    "stream.status": "读取直播状态",
    "stream.scene_preview": "预览直播场景",
    "stream.scene_switch": "切换直播场景",
    "stream.profile_preview": "读取 OBS 配置档",
    "stream.profile_switch": "切换 OBS 配置档",
    "stream.broadcast_start": "开始直播",
    "stream.broadcast_stop": "结束直播",
    "stream.caption_draft": "生成字幕草稿",
    "stream.chat_send": "发送直播聊天",
    "stream.twitch_subscriptions_sync": "同步 Twitch 事件订阅（staging）",
}

_ACTION_SPECS: dict[str, dict[str, Any]] = {
    "stream.status": {"risk": "low", "reversible": True, "confirmationRequired": False},
    "stream.scene_preview": {"risk": "low", "reversible": True, "confirmationRequired": False},
    "stream.scene_switch": {"risk": "medium", "reversible": True, "confirmationRequired": True},
    "stream.profile_preview": {"risk": "low", "reversible": True, "confirmationRequired": False},
    "stream.profile_switch": {"risk": "medium", "reversible": True, "confirmationRequired": True},
    "stream.broadcast_start": {"risk": "high", "reversible": True, "confirmationRequired": True},
    "stream.broadcast_stop": {"risk": "medium", "reversible": True, "confirmationRequired": True},
    "stream.caption_draft": {"risk": "low", "reversible": True, "confirmationRequired": False},
    "stream.chat_send": {"risk": "medium", "reversible": False, "confirmationRequired": True},
    "stream.twitch_subscriptions_sync": {"risk": "high", "reversible": True, "confirmationRequired": True},
}
_PREVIEW_TTL_SECONDS = 120
_EXTERNAL_ACTIONS = {"stream.scene_switch", "stream.profile_switch", "stream.broadcast_start", "stream.broadcast_stop", "stream.chat_send", "stream.twitch_subscriptions_sync"}
_EVENTS_SCHEMA_VERSION = "yuizaki.stream-events.v1"
_MAX_PERSISTED_EVENTS = 100
_MAX_EVENT_TEXT = 4000
_MAX_EVENT_AUTHOR = 200
_ACTIONS_SCHEMA_VERSION = "yuizaki.stream-actions.v1"
_MAX_PERSISTED_ACTIONS = 200
_MAX_ACTION_REQUEST_ID = 160
_MAX_ACTION_ERROR = 120
_ACTION_STATUSES = {"sending", "known_success", "unknown_effect", "failed"}
_MODERATION_SCHEMA_VERSION = "yuizaki.stream-moderation.v1"


class ObsWebSocketAdapter:
    """Short-lived OBS WebSocket v5 adapter for probes and explicit actions.

    The adapter never opens a connection automatically or stores credentials.
    Each probe/action performs a fresh authenticated request and closes the
    socket; only ``StreamRuntime.execute`` can invoke state-changing methods.
    """

    def __init__(self, endpoint: str | None, password: str | None = None, *, timeout: float = 2.0) -> None:
        self.endpoint = endpoint.strip() if isinstance(endpoint, str) else ""
        self._password = password or ""
        self.timeout = max(0.1, min(float(timeout), 10.0))

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    @staticmethod
    def _safe_endpoint(endpoint: str) -> str:
        """Redact URL credentials before exposing an endpoint in diagnostics."""
        try:
            parsed = urlsplit(endpoint)
            host = parsed.hostname or ""
            if parsed.port:
                host = f"{host}:{parsed.port}"
            netloc = f"***@{host}" if parsed.username or parsed.password else host
            query = [
                (key, "***" if key.lower() in {"password", "pass", "token", "secret"} else value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            ]
            return urlunsplit((parsed.scheme, netloc, parsed.path, urlencode(query), ""))
        except (TypeError, ValueError):
            return "<redacted>"

    @staticmethod
    def _authentication(password: str, hello: Mapping[str, Any]) -> str | None:
        auth = hello.get("authentication")
        if not password or not isinstance(auth, Mapping):
            return None
        import base64
        import hashlib

        salt = str(auth.get("salt") or "")
        challenge = str(auth.get("challenge") or "")
        if not salt or not challenge:
            return None
        secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
        return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()

    def probe(self) -> dict[str, Any]:
        if not self.endpoint:
            return {"status": "unconfigured", "adapter": "obs-websocket", "readOnly": True}
        if _websocket is None:
            return {
                "status": "dependency_missing",
                "code": "websocket_client_missing",
                "adapter": "obs-websocket",
                "readOnly": True,
                "endpoint": self._safe_endpoint(self.endpoint),
            }
        socket = None
        try:
            socket = _websocket.create_connection(self.endpoint, timeout=self.timeout)
            hello = _decode_json(socket.recv())
            if hello.get("op") != 0:
                return {"status": "protocol_error", "code": "obs_hello_missing", "adapter": "obs-websocket", "readOnly": True}
            identify: dict[str, Any] = {"op": 1, "d": {"rpcVersion": 1}}
            auth = self._authentication(self._password, hello.get("d") or {})
            if auth:
                identify["d"]["authentication"] = auth
            socket.send(_encode_json(identify))
            identified = _decode_json(socket.recv())
            if identified.get("op") != 2:
                return {"status": "protocol_error", "code": "obs_identify_failed", "adapter": "obs-websocket", "readOnly": True}
            request_id = uuid4().hex
            socket.send(_encode_json({"op": 6, "d": {"requestType": "GetVersion", "requestId": request_id}}))
            response = _decode_json(socket.recv())
            if response.get("op") != 7:
                raise RuntimeError("OBS request response was not received")
            data = response.get("d") if isinstance(response.get("d"), Mapping) else {}
            return {
                "status": "reachable",
                "adapter": "obs-websocket",
                "readOnly": True,
                "endpoint": self._safe_endpoint(self.endpoint),
                "obsWebSocketVersion": data.get("obsWebSocketVersion"),
                "obsVersion": data.get("obsVersion"),
            }
        except Exception as exc:  # noqa: BLE001 - provider libraries expose varied socket errors
            return {
                "status": "unreachable",
                "code": "obs_probe_failed",
                "adapter": "obs-websocket",
                "readOnly": True,
                "endpoint": self._safe_endpoint(self.endpoint),
                "error": type(exc).__name__,
            }
        finally:
            if socket is not None:
                try:
                    socket.close()
                except OSError:
                    pass

    def _request(self, request_type: str, request_data: Mapping[str, Any] | None = None) -> dict[str, Any]:
        if not self.endpoint:
            raise RuntimeError("OBS adapter is not configured")
        if _websocket is None:
            raise RuntimeError("websocket-client dependency is missing")
        socket = None
        try:
            socket = _websocket.create_connection(self.endpoint, timeout=self.timeout)
            hello = _decode_json(socket.recv())
            if hello.get("op") != 0:
                raise RuntimeError("OBS hello was not received")
            identify: dict[str, Any] = {"op": 1, "d": {"rpcVersion": 1}}
            auth = self._authentication(self._password, hello.get("d") or {})
            if auth:
                identify["d"]["authentication"] = auth
            socket.send(_encode_json(identify))
            if _decode_json(socket.recv()).get("op") != 2:
                raise RuntimeError("OBS identify failed")
            request_id = uuid4().hex
            socket.send(_encode_json({"op": 6, "d": {"requestType": request_type, "requestId": request_id, "requestData": dict(request_data or {})}}))
            response = _decode_json(socket.recv())
            if response.get("op") != 7:
                raise RuntimeError("OBS response frame was not received")
            data = response.get("d") if isinstance(response.get("d"), Mapping) else {}
            if data.get("requestId") not in {None, request_id}:
                raise RuntimeError("OBS response requestId did not match")
            status = data.get("requestStatus") if isinstance(data.get("requestStatus"), Mapping) else {}
            if not status.get("result", False):
                raise RuntimeError(str(status.get("comment") or "OBS request failed"))
            return dict(data.get("responseData") or {})
        finally:
            if socket is not None:
                try:
                    socket.close()
                except OSError:
                    pass

    def get_scene_list(self) -> dict[str, Any]:
        return self._request("GetSceneList")

    def get_profile_list(self) -> dict[str, Any]:
        return self._request("GetProfileList")

    def get_current_profile(self) -> dict[str, Any]:
        return self._request("GetCurrentProfile")

    def get_current_program_scene(self) -> dict[str, Any]:
        return self._request("GetCurrentProgramScene")

    def get_stream_status(self) -> dict[str, Any]:
        return self._request("GetStreamStatus")

    def set_current_program_scene(self, scene_name: str) -> dict[str, Any]:
        return self._request("SetCurrentProgramScene", {"sceneName": scene_name})

    def set_current_profile(self, profile_name: str) -> dict[str, Any]:
        return self._request("SetCurrentProfile", {"profileName": profile_name})

    def start_stream(self) -> dict[str, Any]:
        return self._request("StartStream")

    def stop_stream(self) -> dict[str, Any]:
        return self._request("StopStream")


def _encode_json(value: Mapping[str, Any]) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


def _decode_json(value: Any) -> dict[str, Any]:
    import json

    decoded = json.loads(value.decode() if isinstance(value, bytes) else value)
    if not isinstance(decoded, dict):
        raise TypeError("OBS response must be an object")
    return decoded


class StreamRuntime:
    """In-memory stream state, preview tickets, and controlled action executor.

    Preview, policy, and event methods are local-only. Provider access is
    restricted to an explicit preview-ticket execution after confirmation.
    """

    def __init__(
        self,
        obs_adapter: ObsWebSocketAdapter | None = None,
        *,
        twitch_eventsub_secret: str | None = None,
        twitch_client_id: str | None = None,
        twitch_eventsub_token: str | None = None,
        twitch_chat_token: str | None = None,
        twitch_broadcaster_id: str | None = None,
        twitch_sender_id: str | None = None,
        twitch_moderator_id: str | None = None,
        twitch_eventsub_callback_url: str | None = None,
        twitch_connection: TwitchConnectionSupervisor | None = None,
        twitch_transport: TwitchIrcTransport | None = None,
        twitch_subscription_provider: TwitchSubscriptionProvider | None = None,
        twitch_channel: str | None = None,
        twitch_username: str | None = None,
        events_path: str | Path | None = None,
        actions_path: str | Path | None = None,
        moderation: Mapping[str, Any] | None = None,
        moderation_path: str | Path | None = None,
    ) -> None:
        self._lock = RLock()
        self._obs_adapter = obs_adapter
        initial_obs_endpoint = str(getattr(obs_adapter, "endpoint", "") or "")
        self._obs_allow_remote = bool(obs_adapter and obs_adapter.configured and self._is_loopback_endpoint(initial_obs_endpoint) is False)
        twitch_state_path = (
            Path(events_path).with_name("stream_twitch_state.json")
            if events_path is not None
            else None
        )
        self._twitch_ingress = TwitchEventIngress(
            twitch_eventsub_secret,
            self.enqueue_event,
            state_path=twitch_state_path,
            subscription_provider=twitch_subscription_provider,
        )
        self._twitch_chat_adapter = TwitchChatAdapter(
            twitch_client_id,
            twitch_chat_token,
            twitch_broadcaster_id,
            twitch_sender_id,
        )
        connection_ref: dict[str, TwitchConnectionSupervisor] = {}

        def _on_twitch_disconnect(error: str) -> None:
            supervisor = connection_ref.get("supervisor")
            if supervisor is not None:
                supervisor.mark_disconnected(error)

        self._twitch_transport = twitch_transport or TwitchIrcTransport(
            access_token=twitch_chat_token,
            channel=twitch_channel,
            username=twitch_username,
            on_line=self.ingest_twitch_irc,
            on_disconnect=_on_twitch_disconnect,
        )
        self._twitch_eventsub_callback_url = str(twitch_eventsub_callback_url or "").strip()
        self._twitch_moderator_id = str(twitch_moderator_id or "").strip()
        self._twitch_eventsub_token = str(twitch_eventsub_token or "").strip().removeprefix("Bearer ").removeprefix("oauth:").strip()
        self._twitch_connection = twitch_connection or TwitchConnectionSupervisor(
            configured=bool(self._twitch_transport.configured),
            connect=self._twitch_transport.connect,
            close=self._twitch_transport.close,
            auto_retry=True,
        )
        connection_ref["supervisor"] = self._twitch_connection
        self._events: deque[dict[str, Any]] = deque(maxlen=100)
        self._events_path = Path(events_path) if events_path is not None else None
        self._actions: deque[dict[str, Any]] = deque(maxlen=_MAX_PERSISTED_ACTIONS)
        self._actions_path = (
            Path(actions_path)
            if actions_path is not None
            else Path(events_path).with_name("stream_actions.json")
            if events_path is not None
            else None
        )
        self._moderation_path = (
            Path(moderation_path)
            if moderation_path is not None
            else Path(events_path).with_name("stream_moderation.json")
            if events_path is not None
            else None
        )
        self._previews: dict[str, dict[str, Any]] = {}
        self._load_events()
        self._load_actions()
        self._moderation_policy = self._load_moderation_policy(moderation)
        self._chat_send_times: deque[float] = deque(
            timestamp
            for action in self._actions
            if action.get("action") == "stream.chat_send"
            for timestamp in [self._parse_action_timestamp(action.get("at"))]
            if timestamp is not None
        )
        adapter_configured = bool(obs_adapter and obs_adapter.configured)
        adapter_info = (
            {
                "id": "obs-websocket",
                "name": "OBS WebSocket",
                "configured": True,
                "connected": False,
                "endpoint": ObsWebSocketAdapter._safe_endpoint(initial_obs_endpoint),
                "remoteAllowed": self._obs_allow_remote,
                "passwordConfigured": bool(getattr(obs_adapter, "_password", "")),
            }
            if adapter_configured
            else None
        )
        self._state: dict[str, Any] = {
            "schemaVersion": SCHEMA_VERSION,
            "state": "disconnected",
            "adapter": adapter_info,
            "connection": {
                "status": "configured" if adapter_configured else "disconnected",
                "adapter": "obs-websocket" if adapter_configured else None,
                "configured": adapter_configured,
            },
            "platforms": {
                "twitch": {
                    "eventsubConfigured": bool(self._twitch_ingress.secret),
                    "eventsubPath": "/api/system/stream/twitch/eventsub",
                    "ircIngressPath": "/api/system/stream/twitch/irc",
                    "inboundRateLimitPerMinute": self._twitch_ingress.max_events_per_minute,
                    "revoked": False,
                    "revocationCount": 0,
                    "outboundActions": self._twitch_chat_adapter.configured,
                    "chatConfigured": self._twitch_chat_adapter.configured,
                },
            },
            "capabilities": [
                self._capability("stream.status", available=True),
                self._capability("stream.scene_preview", available=True),
                self._capability("stream.scene_switch", available=True),
                self._capability("stream.profile_preview", available=True),
                self._capability("stream.profile_switch", available=True),
                self._capability("stream.broadcast_start", available=True),
                self._capability("stream.broadcast_stop", available=True),
                self._capability("stream.caption_draft", available=True),
                self._capability("stream.chat_send", available=self._twitch_chat_adapter.configured),
                self._capability("stream.twitch_subscriptions_sync", available=twitch_subscription_provider is not None),
            ],
            "policy": {
                "mode": "preview_only",
                "externalSideEffects": False,
                "confirmationRequired": True,
                "humanTakeover": True,
                "moderation": self._moderation_policy.snapshot(),
            },
            "lastAction": deepcopy(self._actions[-1]) if self._actions else None,
        }

    @staticmethod
    def _is_loopback_endpoint(endpoint: str) -> bool:
        """Return whether an OBS websocket endpoint targets the local machine."""
        try:
            parsed = urlsplit(endpoint)
            host = (parsed.hostname or "").strip().lower().rstrip(".")
            if host == "localhost":
                return True
            return bool(host) and ipaddress.ip_address(host).is_loopback
        except (TypeError, ValueError):
            return False

    @classmethod
    def _validate_obs_endpoint(cls, endpoint: str, *, allow_remote: bool) -> str:
        normalized = endpoint.strip()
        if not normalized:
            return ""
        try:
            parsed = urlsplit(normalized)
            if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
                raise ValueError("OBS endpoint must use ws:// or wss:// with a hostname")
            if parsed.username or parsed.password:
                raise ValueError("OBS endpoint must not contain URL credentials")
            if parsed.query or parsed.fragment:
                raise ValueError("OBS endpoint must not contain query or fragment data")
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError("OBS endpoint port is invalid")
        except ValueError:
            raise
        except (TypeError, UnicodeError) as exc:
            raise ValueError("OBS endpoint is invalid") from exc
        if not allow_remote and not cls._is_loopback_endpoint(normalized):
            raise ValueError("remote OBS endpoint requires allowRemote=true")
        return normalized

    def configure_obs(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Configure OBS in memory only; credentials never enter snapshots or disk."""
        body = dict(payload or {})
        endpoint = body.get("endpoint")
        password = body.get("password")
        allow_remote = body.get("allowRemote", False)
        clear_password = body.get("clearPassword", False)
        if not isinstance(endpoint, str):
            raise TypeError("endpoint must be a string")
        if password is not None and not isinstance(password, str):
            raise TypeError("password must be a string")
        if not isinstance(allow_remote, bool):
            raise TypeError("allowRemote must be a boolean")
        if not isinstance(clear_password, bool):
            raise TypeError("clearPassword must be a boolean")
        normalized = self._validate_obs_endpoint(endpoint, allow_remote=allow_remote)
        with self._lock:
            previous_password = getattr(self._obs_adapter, "_password", "") if self._obs_adapter is not None else ""
            next_password = "" if clear_password or not normalized else (password if password is not None else previous_password)
            self._obs_adapter = ObsWebSocketAdapter(normalized, next_password)
            self._obs_allow_remote = allow_remote if normalized else False
            configured = bool(normalized)
            self._state["adapter"] = (
                {
                    "id": "obs-websocket",
                    "name": "OBS WebSocket",
                    "configured": configured,
                    "connected": False,
                    "endpoint": self._obs_adapter._safe_endpoint(normalized),
                    "remoteAllowed": self._obs_allow_remote,
                    "passwordConfigured": bool(next_password),
                }
                if configured
                else None
            )
            self._state["connection"] = {
                "status": "configured" if configured else "disconnected",
                "adapter": "obs-websocket" if configured else None,
                "configured": configured,
            }
            snapshot = self.snapshot()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "configured": configured,
            "endpoint": self._obs_adapter._safe_endpoint(normalized),
            "remoteAllowed": self._obs_allow_remote,
            "passwordConfigured": bool(next_password),
            "externalSideEffects": False,
            "state": snapshot,
        }

    @staticmethod
    def _sanitize_event(raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            return None
        if set(raw) - {"eventId", "kind", "text", "author", "receivedAt", "source", "delivered", "externalSideEffects", "draftState", "draftError"}:
            return None
        kind = raw.get("kind")
        text = raw.get("text")
        author = raw.get("author")
        event_id = raw.get("eventId")
        received_at = raw.get("receivedAt")
        if kind not in {"chat", "caption"} or not isinstance(text, str) or not text.strip() or len(text) > _MAX_EVENT_TEXT:
            return None
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 160:
            return None
        if author is not None and (not isinstance(author, str) or len(author) > _MAX_EVENT_AUTHOR):
            return None
        if not isinstance(received_at, str) or len(received_at) > 80:
            return None
        draft_state = str(raw.get("draftState") or "pending").strip().lower()
        if draft_state == "processing":
            draft_state = "pending"  # recover an interrupted claim after restart
        if draft_state not in {"pending", "processing", "generated", "failed"}:
            draft_state = "pending"
        draft_error = raw.get("draftError")
        if draft_error is not None and (not isinstance(draft_error, str) or len(draft_error) > 400):
            draft_error = None
        return {
            "eventId": event_id.strip(),
            "kind": kind,
            "text": text.strip(),
            "author": author.strip() if isinstance(author, str) and author.strip() else None,
            "receivedAt": received_at,
            "source": str(raw.get("source") or "local")[:80],
            "delivered": bool(raw.get("delivered", False)),
            "draftState": draft_state,
            **({"draftError": draft_error} if draft_error else {}),
            "externalSideEffects": False,
        }

    def _load_events(self) -> None:
        path = self._events_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError):
            return
        if not isinstance(payload, Mapping) or payload.get("schemaVersion") != _EVENTS_SCHEMA_VERSION:
            return
        raw_events = payload.get("events")
        if not isinstance(raw_events, list):
            return
        for raw in raw_events[-_MAX_PERSISTED_EVENTS:]:
            event = self._sanitize_event(raw)
            if event is not None:
                self._events.append(event)

    def _persist_events_locked(self) -> None:
        path = self._events_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schemaVersion": _EVENTS_SCHEMA_VERSION,
                "events": list(self._events)[-_MAX_PERSISTED_EVENTS:],
            }
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
        except (OSError, TypeError, ValueError):
            # Event persistence is best-effort; the in-memory queue remains the
            # authoritative live view when a local disk is unavailable.
            return

    @staticmethod
    def _sanitize_action(raw: Any) -> dict[str, Any] | None:
        """Keep action history useful without retaining provider payloads."""
        if not isinstance(raw, Mapping):
            return None
        allowed = {
            "action", "requestId", "at", "status", "outcome",
            "externalSideEffects", "verificationStatus", "errorCode", "confirmed",
        }
        if set(raw) - allowed:
            return None
        action = raw.get("action")
        request_id = raw.get("requestId")
        at = raw.get("at")
        status = raw.get("status", raw.get("outcome"))
        if not isinstance(action, str) or action not in set(_ACTION_LABELS) | {"stream.event_enqueue", "stream.takeover"}:
            return None
        if not isinstance(request_id, str) or len(request_id) > _MAX_ACTION_REQUEST_ID:
            return None
        if not isinstance(at, str) or not at or len(at) > 80:
            return None
        if status not in _ACTION_STATUSES:
            return None
        if not isinstance(raw.get("externalSideEffects", False), bool):
            return None
        confirmed = raw.get("confirmed")
        if confirmed is not None and not isinstance(confirmed, bool):
            return None
        verification_status = raw.get("verificationStatus")
        if verification_status is not None and (not isinstance(verification_status, str) or len(verification_status) > 80):
            return None
        error_code = raw.get("errorCode")
        if error_code is not None and (not isinstance(error_code, str) or len(error_code) > _MAX_ACTION_ERROR):
            return None
        return {
            "action": action,
            "requestId": request_id,
            "at": at,
            "status": status,
            "outcome": status,
            "externalSideEffects": raw.get("externalSideEffects", False),
            **({"confirmed": confirmed} if confirmed is not None else {}),
            **({"verificationStatus": verification_status} if verification_status is not None else {}),
            **({"errorCode": error_code} if error_code is not None else {}),
        }

    def _load_actions(self) -> None:
        path = self._actions_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError):
            return
        if not isinstance(payload, Mapping) or payload.get("schemaVersion") != _ACTIONS_SCHEMA_VERSION:
            return
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            return
        for raw in raw_actions[-_MAX_PERSISTED_ACTIONS:]:
            action = self._sanitize_action(raw)
            if action is not None:
                self._actions.append(action)

    @staticmethod
    def _parse_action_timestamp(value: object) -> float | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    def _load_moderation_policy(self, override: Mapping[str, Any] | None) -> StreamModerationPolicy:
        payload: Mapping[str, Any] = {}
        path = self._moderation_path
        if override is None and path is not None and path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, Mapping) and raw.get("schemaVersion") == _MODERATION_SCHEMA_VERSION:
                    candidate = raw.get("policy")
                    if isinstance(candidate, Mapping):
                        payload = candidate
            except (OSError, TypeError, ValueError, UnicodeError):
                payload = {}
        if override is not None:
            payload = override
        try:
            return StreamModerationPolicy.from_mapping(payload)
        except (TypeError, ValueError):
            # A malformed local file must not disable the safety layer.
            return StreamModerationPolicy()

    def _persist_moderation_locked(self, policy: StreamModerationPolicy) -> bool:
        path = self._moderation_path
        if path is None:
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"schemaVersion": _MODERATION_SCHEMA_VERSION, "policy": policy.snapshot()}
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def _persist_actions_locked(self) -> bool:
        path = self._actions_path
        if path is None:
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schemaVersion": _ACTIONS_SCHEMA_VERSION,
                "actions": list(self._actions)[-_MAX_PERSISTED_ACTIONS:],
            }
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
            return True
        except (OSError, TypeError, ValueError):
            return False

    def _record_action_locked(
        self,
        audit: Mapping[str, Any],
        *,
        require_persistence: bool = False,
    ) -> bool:
        normalized = self._sanitize_action(audit)
        if normalized is None:
            raise ValueError("invalid stream action audit")
        previous = deepcopy(self._state.get("lastAction"))
        self._actions.append(normalized)
        if not self._persist_actions_locked():
            if require_persistence:
                if self._actions and self._actions[-1] == normalized:
                    self._actions.pop()
                self._state["lastAction"] = previous
                raise RuntimeError("stream action audit persistence is unavailable")
            self._state["lastAction"] = deepcopy(normalized)
            return False
        self._state["lastAction"] = deepcopy(normalized)
        return True

    def _capability(self, action: str, *, available: bool) -> dict[str, Any]:
        spec = _ACTION_SPECS[action]
        twitch_revoked = bool(self._twitch_ingress.snapshot().get("revoked")) if action == "stream.chat_send" else False
        twitch_ready = action == "stream.chat_send" and self._twitch_chat_adapter.configured and not twitch_revoked
        subscriptions_ready = action == "stream.twitch_subscriptions_sync" and self._twitch_ingress.subscription_provider_configured
        obs_ready = self._obs_adapter is not None and self._obs_adapter.configured
        return {
            "id": action,
            "name": _ACTION_LABELS[action],
            "status": "available" if available else "needs_config",
            "available": available,
            "executionReady": available and (
                action == "stream.caption_draft"
                or twitch_ready
                or subscriptions_ready
                or obs_ready
            ),
            "needsConfig": action != "stream.caption_draft" and not twitch_ready and not subscriptions_ready and not obs_ready,
            "riskLevel": spec["risk"],
            "requiresApproval": spec["confirmationRequired"],
            "sideEffects": action in _EXTERNAL_ACTIONS,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = deepcopy(self._state)
            twitch = snapshot.get("platforms", {}).get("twitch")
            if isinstance(twitch, dict):
                ingress = self._twitch_ingress.snapshot()
                twitch.update(ingress)
                twitch["eventsubConfigured"] = bool(self._twitch_ingress.secret)
                if ingress.get("revoked") is True:
                    self._twitch_connection.mark_revoked()
                twitch["ircConnection"] = self._twitch_connection.snapshot()
                twitch["chatConfigured"] = self._twitch_chat_adapter.configured
                twitch["outboundActions"] = (
                    self._twitch_chat_adapter.configured
                    and twitch.get("revoked") is not True
                )
                for capability in snapshot.get("capabilities", []):
                    if isinstance(capability, dict) and capability.get("id") == "stream.chat_send":
                        capability["available"] = bool(twitch["outboundActions"])
                    if isinstance(capability, dict) and capability.get("id") == "stream.twitch_subscriptions_sync":
                        capability["available"] = self._twitch_ingress.subscription_provider_configured
            return snapshot

    def preview(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = dict(payload or {})
        action = body.get("action")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action is required")
        action = action.strip()
        spec = _ACTION_SPECS.get(action)
        if spec is None:
            raise ValueError(f"unsupported stream action: {action}")
        params = body.get("params", {})
        if not isinstance(params, Mapping):
            raise TypeError("params must be an object")
        if action == "stream.chat_send":
            text = params.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text is required")
            if len(text.strip()) > 500:
                raise ValueError("text must be 500 characters or less")
            with self._lock:
                moderation = self._moderation_policy.evaluate(text, self._chat_send_times)
            if not moderation.allowed:
                raise ValueError(f"{moderation.reason_code}: {moderation.error_message()}")
        subscription_preview = None
        if action == "stream.twitch_subscriptions_sync":
            subscription_preview = self._twitch_ingress.preview_subscription_sync()
            if not subscription_preview.get("available"):
                raise RuntimeError("Twitch subscription provider is not configured")
        # Return a plan only. In particular, do not update lastAction here:
        # callers can safely render/approve this response repeatedly.
        plan = {
            "action": action,
            "params": deepcopy(dict(params)),
            "risk": spec["risk"],
            "reversible": spec["reversible"],
            "confirmationRequired": spec["confirmationRequired"],
            "execute": False,
            "reason": "等待人工确认；预览本身不会产生外部副作用",
        }
        if action == "stream.chat_send":
            plan["moderation"] = moderation.snapshot()
        request_id = f"stream-preview-{uuid4().hex}"
        expires_at = datetime.fromtimestamp(time.time() + _PREVIEW_TTL_SECONDS, timezone.utc).isoformat()
        preview = {
            "requestId": request_id,
            "kind": action,
            "summary": _ACTION_LABELS[action],
            "steps": ["校验能力与权限", "生成动作计划", "等待人工确认"],
            "expiresAt": expires_at,
            **plan,
        }
        if subscription_preview is not None:
            preview["subscriptionSync"] = subscription_preview
        with self._lock:
            now = time.time()
            expired = [key for key, value in self._previews.items() if float(value.get("expiresAt", 0)) <= now]
            for key in expired:
                self._previews.pop(key, None)
            if len(self._previews) >= 128:
                self._previews.pop(next(iter(self._previews)), None)
            self._previews[request_id] = {
                "action": action,
                "params": deepcopy(dict(params)),
                "expiresAt": now + _PREVIEW_TTL_SECONDS,
            }
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "executed": False,
            "preview": preview,
            "plan": plan,
            "state": self.snapshot(),
        }

    def probe(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Explicitly probe configured OBS; never changes runtime state."""
        body = dict(payload or {})
        endpoint = body.get("endpoint")
        password = body.get("password")
        if endpoint is not None and not isinstance(endpoint, str):
            raise TypeError("endpoint must be a string")
        if password is not None and not isinstance(password, str):
            raise TypeError("password must be a string")
        adapter = self._obs_adapter
        if endpoint is not None or password is not None:
            adapter = ObsWebSocketAdapter(endpoint, password)
        result = adapter.probe() if adapter is not None else ObsWebSocketAdapter(None).probe()
        result["schemaVersion"] = SCHEMA_VERSION
        result["configured"] = result.get("status") != "unconfigured"
        snapshot = self.snapshot()
        result["state"] = snapshot.get("state", "disconnected")
        result["snapshot"] = snapshot
        return result

    def obs_profiles(self) -> dict[str, Any]:
        """Read OBS profiles without creating a preview or changing state."""
        adapter = self._obs_adapter
        if adapter is None or not adapter.configured:
            raise RuntimeError("OBS adapter is not configured")
        response = adapter.get_profile_list()
        profiles = response.get("profiles")
        current = response.get("currentProfileName")
        if not isinstance(profiles, list):
            raise TypeError("OBS profile response is invalid")
        normalized: list[dict[str, Any]] = []
        for item in profiles[:100]:
            if not isinstance(item, Mapping):
                continue
            name = item.get("profileName")
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                continue
            normalized.append({"profileName": name.strip()})
        current_name = current.strip() if isinstance(current, str) else None
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "profiles": normalized,
            "currentProfileName": current_name,
            "externalSideEffects": False,
        }

    def events(self, limit: int = 50) -> dict[str, Any]:
        """Return recent local events in newest-first order."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._lock:
            items = list(self._events)[-limit:]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "count": len(items),
                "limit": limit,
                "events": list(reversed(deepcopy(items))),
                "externalSideEffects": False,
            }

    def actions(self, limit: int = 50) -> dict[str, Any]:
        """Return bounded action history without provider payloads or secrets."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self._lock:
            items = list(self._actions)[-limit:]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "count": len(items),
                "limit": limit,
                "actions": list(reversed(deepcopy(items))),
                "externalSideEffects": False,
            }

    def moderation(self) -> dict[str, Any]:
        """Return the local outbound chat moderation policy."""
        with self._lock:
            policy = self._moderation_policy.snapshot()
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "moderation": policy,
                "externalSideEffects": False,
            }

    def configure_moderation(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Apply and persist a bounded moderation patch without touching providers."""
        if not isinstance(payload, Mapping):
            raise TypeError("moderation payload must be an object")
        with self._lock:
            candidate = self._moderation_policy.with_patch(payload)
            if not self._persist_moderation_locked(candidate):
                raise RuntimeError("stream moderation persistence is unavailable")
            self._moderation_policy = candidate
            self._state["policy"]["moderation"] = candidate.snapshot()
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "moderation": candidate.snapshot(),
                "state": self.snapshot(),
                "externalSideEffects": False,
            }

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        """Return one queued event without changing delivery state."""
        normalized = str(event_id or "").strip()
        if not normalized:
            return None
        with self._lock:
            for event in reversed(self._events):
                if event.get("eventId") == normalized:
                    return deepcopy(event)
        return None

    def claim_next_draft_event(self) -> dict[str, Any] | None:
        """Atomically claim the oldest pending event for local draft generation."""
        with self._lock:
            for event in self._events:
                if event.get("draftState", "pending") != "pending":
                    continue
                event["draftState"] = "processing"
                event.pop("draftError", None)
                self._persist_events_locked()
                return deepcopy(event)
        return None

    def release_draft_event(self, event_id: str) -> dict[str, Any] | None:
        """Return an interrupted draft claim to ``pending`` for safe retry.

        Cancellation is different from a provider failure: no draft outcome was
        observed, so the event must remain eligible after an in-process stop.
        Only the owner state ``processing`` is released; completed or failed
        records are never reopened implicitly.
        """
        normalized = str(event_id or "").strip()
        if not normalized:
            return None
        with self._lock:
            for event in self._events:
                if event.get("eventId") != normalized:
                    continue
                if event.get("draftState", "pending") != "processing":
                    return deepcopy(event)
                event["draftState"] = "pending"
                event.pop("draftError", None)
                self._persist_events_locked()
                return deepcopy(event)
        return None

    def complete_draft_event(self, event_id: str, status: str, error: str | None = None) -> dict[str, Any] | None:
        normalized = str(event_id or "").strip()
        state = str(status or "").strip().lower()
        if state not in {"generated", "failed"}:
            raise ValueError("draft status must be generated or failed")
        with self._lock:
            for event in self._events:
                if event.get("eventId") == normalized:
                    event["draftState"] = state
                    if error:
                        event["draftError"] = str(error)[:400]
                    else:
                        event.pop("draftError", None)
                    self._persist_events_locked()
                    return deepcopy(event)
        return None

    def execute(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = dict(payload or {})
        request_id = body.get("requestId")
        action_from_request = body.get("action")
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("requestId is required")
        if not isinstance(action_from_request, str) or not action_from_request.strip():
            raise ValueError("action is required")
        if body.get("confirmed") is not True:
            raise ValueError("confirmed must be true")
        params = body.get("params", {})
        if not isinstance(params, Mapping):
            raise TypeError("params must be an object")
        with self._lock:
            ticket = self._previews.get(request_id)
        if ticket is None:
            raise ValueError("preview requestId is unknown or already used")
        if time.time() >= float(ticket["expiresAt"]):
            with self._lock:
                self._previews.pop(request_id, None)
            raise ValueError("preview has expired")
        if ticket["params"] != dict(params):
            raise ValueError("execute params do not match preview")
        if ticket["action"] != action_from_request.strip():
            raise ValueError("execute action does not match preview")
        adapter = self._obs_adapter
        action = str(ticket["action"])
        if action == "stream.chat_send":
            if not self._twitch_chat_adapter.configured:
                raise RuntimeError("Twitch chat sender is not configured")
            if self._twitch_ingress.snapshot().get("revoked") is True:
                raise RuntimeError("Twitch EventSub is revoked; reconfigure Twitch before sending")
        elif action == "stream.twitch_subscriptions_sync":
            if not self._twitch_ingress.subscription_provider_configured:
                raise RuntimeError("Twitch subscription provider is not configured")
        elif action not in {"stream.caption_draft"} and (adapter is None or not adapter.configured):
            raise RuntimeError("OBS adapter is not configured")
        scene_name: str | None = None
        profile_name: str | None = None
        if action == "stream.scene_switch":
            scene_name = params.get("sceneName")
            if not isinstance(scene_name, str) or not scene_name.strip() or len(scene_name.strip()) > 200:
                raise ValueError("sceneName is required and must be 200 characters or less")
        if action == "stream.profile_switch":
            profile_name = params.get("profileName")
            if not isinstance(profile_name, str) or not profile_name.strip() or len(profile_name.strip()) > 200:
                raise ValueError("profileName is required and must be 200 characters or less")
        # Claim atomically before invoking the provider. A timeout or provider
        # exception therefore cannot replay the same requestId.
        with self._lock:
            # Re-read the ticket under the claim lock. Two concurrent execute
            # requests must never both reach a provider.
            current_ticket = self._previews.get(request_id)
            if current_ticket is None:
                raise ValueError("preview requestId is unknown or already used")
            if time.time() >= float(current_ticket["expiresAt"]):
                self._previews.pop(request_id, None)
                raise ValueError("preview has expired")
            if current_ticket["params"] != dict(params):
                raise ValueError("execute params do not match preview")
            if current_ticket["action"] != action:
                raise ValueError("execute action does not match preview")
            # Re-check revocation while holding the claim lock.  EventSub can
            # revoke Twitch between the initial capability check and this
            # point; no new chat send may cross the provider boundary after
            # the runtime has observed that safety state.
            if action == "stream.chat_send" and self._twitch_ingress.snapshot().get("revoked") is True:
                raise RuntimeError("Twitch EventSub is revoked; reconfigure Twitch before sending")
            if bool(self._state["policy"].get("humanTakeover")):
                raise RuntimeError("human takeover is active; agent execution is blocked")
            chat_send_at: float | None = None
            if action == "stream.chat_send":
                text = params.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("text is required")
                moderation = self._moderation_policy.evaluate(text, self._chat_send_times)
                if not moderation.allowed:
                    raise ValueError(f"{moderation.reason_code}: {moderation.error_message()}")
                chat_send_at = time.time()
            self._previews.pop(request_id, None)
            self._record_action_locked(
                {
                    "action": action,
                    "requestId": request_id,
                    "at": datetime.now(timezone.utc).isoformat(),
                    "status": "sending",
                    "outcome": "sending",
                    "externalSideEffects": action in _EXTERNAL_ACTIONS,
                },
                require_persistence=action in _EXTERNAL_ACTIONS,
            )
            if chat_send_at is not None:
                self._chat_send_times.append(chat_send_at)
        try:
            if action == "stream.caption_draft":
                text = params.get("text", "")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("text is required")
                if len(text) > _MAX_EVENT_TEXT:
                    raise ValueError(f"text must be {_MAX_EVENT_TEXT} characters or less")
                response = {"draft": text.strip()}
                verification_status = "local_only"
            elif action == "stream.chat_send":
                text = params.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("text is required")
                response = self._twitch_chat_adapter.send_message(text)
                verification_status = "provider_acknowledged" if response.get("sent") is True else "unknown_effect"
            elif action == "stream.twitch_subscriptions_sync":
                response = self._twitch_ingress.sync_subscription_plan()
                verification_status = "provider_acknowledged" if response.get("subscriptionPlan", {}).get("status") == "synced" else "unknown_effect"
            elif action == "stream.status":
                response = adapter.get_stream_status()
                verification_status = "provider_acknowledged"
            elif action == "stream.scene_preview":
                response = adapter.get_scene_list()
                verification_status = "provider_acknowledged"
            elif action == "stream.scene_switch":
                assert scene_name is not None
                response = adapter.set_current_program_scene(scene_name.strip())
                verification = adapter.get_current_program_scene()
                verification_status = "provider_acknowledged" if verification.get("currentProgramSceneName") == scene_name.strip() else "unknown_effect"
            elif action == "stream.profile_preview":
                response = adapter.get_profile_list()
                verification_status = "provider_acknowledged"
            elif action == "stream.profile_switch":
                assert profile_name is not None
                response = adapter.set_current_profile(profile_name.strip())
                verification = adapter.get_current_profile()
                verification_status = "provider_acknowledged" if verification.get("currentProfileName") == profile_name.strip() else "unknown_effect"
            elif action == "stream.broadcast_start":
                response = adapter.start_stream()
                verification = adapter.get_stream_status()
                verification_status = "provider_acknowledged" if verification.get("outputActive") is True else "unknown_effect"
            elif action == "stream.broadcast_stop":
                response = adapter.stop_stream()
                verification = adapter.get_stream_status()
                verification_status = "provider_acknowledged" if verification.get("outputActive") is False else "unknown_effect"
            else:
                raise ValueError(f"action cannot be executed: {action}")
        except ValueError:
            raise
        except Exception as exc:
            now = datetime.now(timezone.utc).isoformat()
            audit = {
                "action": action,
                "requestId": request_id,
                "at": now,
                "status": "unknown_effect",
                "confirmed": True,
                "outcome": "unknown_effect",
                "externalSideEffects": action in _EXTERNAL_ACTIONS,
                "errorCode": type(exc).__name__,
            }
            with self._lock:
                self._state["state"] = "error"
                self._record_action_locked(audit)
            raise RuntimeError(f"unknown_effect: {type(exc).__name__}") from exc
        if verification_status == "unknown_effect":
            now = datetime.now(timezone.utc).isoformat()
            audit = {
                "action": action,
                "requestId": request_id,
                "at": now,
                "status": "unknown_effect",
                "confirmed": True,
                "outcome": "unknown_effect",
                "externalSideEffects": action in _EXTERNAL_ACTIONS,
                "errorCode": "verification_mismatch",
            }
            with self._lock:
                self._state["state"] = "error"
                self._record_action_locked(audit)
            raise RuntimeError("unknown_effect: provider verification did not confirm the requested state")
        now = datetime.now(timezone.utc).isoformat()
        audit = {
            "action": action,
            "requestId": request_id,
            "at": now,
            "status": "known_success",
            "confirmed": True,
            "outcome": "known_success",
            "externalSideEffects": action in _EXTERNAL_ACTIONS,
            "verificationStatus": verification_status,
        }
        with self._lock:
            if action == "stream.broadcast_start":
                self._state["state"] = "live"
            elif action == "stream.broadcast_stop":
                self._state["state"] = "ended"
            elif action in {"stream.status", "stream.scene_preview", "stream.scene_switch"}:
                self._state["state"] = "live" if response.get("outputActive") is True else "ready"
            self._record_action_locked(audit)
        snapshot = self.snapshot()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "executed": True,
            "requestId": request_id,
            "action": action,
            "result": response,
            "outcome": "known_success",
            "verificationStatus": verification_status,
            "audit": deepcopy(audit),
            "auditEvent": deepcopy(audit),
            "externalSideEffects": action in _EXTERNAL_ACTIONS,
            "state": snapshot,
        }

    def enqueue_event(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body = dict(payload or {})
        kind = body.get("kind")
        text = body.get("text")
        author = body.get("author", "")
        source = body.get("source", "local")
        if kind not in {"chat", "caption"}:
            raise ValueError("kind must be chat or caption")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must not be empty")
        if len(text) > _MAX_EVENT_TEXT:
            raise ValueError(f"text must be {_MAX_EVENT_TEXT} characters or less")
        if not isinstance(author, str):
            raise TypeError("author must be a string")
        if len(author) > _MAX_EVENT_AUTHOR:
            raise ValueError(f"author must be {_MAX_EVENT_AUTHOR} characters or less")
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        if len(source) > 80:
            raise ValueError("source must be 80 characters or less")
        event = {
            "eventId": f"stream-event-{uuid4().hex}",
            "kind": kind,
            "text": text.strip(),
            "author": author.strip() or None,
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "source": source.strip() or "local",
            "delivered": False,
            "draftState": "pending",
            "externalSideEffects": False,
        }
        with self._lock:
            self._events.append(event)
            self._persist_events_locked()
            self._state["lastAction"] = {
                "action": "stream.event_enqueue",
                "eventId": event["eventId"],
                "at": event["receivedAt"],
                "externalSideEffects": False,
            }
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "event": deepcopy(event), "queued": True}

    def ingest_twitch_eventsub(self, raw_body: bytes, headers: Mapping[str, Any]) -> dict[str, Any]:
        """Verify and queue a Twitch EventSub notification; ingress only."""
        result = self._twitch_ingress.ingest_eventsub(raw_body, headers)
        # A revocation is an immediate safety boundary.  Do not wait for a
        # later status snapshot to stop an IRC reconnect loop or leave the
        # connection intent enabled after Twitch has revoked EventSub.
        if isinstance(result, Mapping) and result.get("revoked") is True:
            self._twitch_connection.mark_revoked()
        return result

    def ingest_twitch_irc(self, line: str) -> dict[str, Any]:
        """Parse a received IRC line; this method never writes to Twitch."""
        return self._twitch_ingress.ingest_irc(line)

    @staticmethod
    def _twitch_config_value(
        payload: Mapping[str, Any],
        values: Mapping[str, str],
        field: str,
        *,
        max_length: int = 512,
    ) -> str:
        clear_key = f"clear{field[0].upper()}{field[1:]}"
        if clear_key in payload and not isinstance(payload[clear_key], bool):
            raise TypeError(f"{clear_key} must be a boolean")
        if payload.get(clear_key) is True:
            return ""
        if field not in payload:
            return str(values.get(field) or "")
        value = payload[field]
        if not isinstance(value, str):
            raise TypeError(f"{field} must be a string")
        clean = value.strip()
        if len(clean) > max_length:
            raise ValueError(f"{field} is too long")
        return clean

    def reconfigure_twitch(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Apply explicit Twitch credentials in memory and clear revocation state.

        The no-payload form remains a compatibility endpoint that only clears a
        persisted revocation marker. Credential values are never returned.
        """
        if payload is None:
            result = self._twitch_ingress.reset_revocation()
            self._twitch_connection.mark_revoked(False)
            with self._lock:
                twitch = self._state.get("platforms", {}).get("twitch")
                if isinstance(twitch, dict):
                    twitch.update(result)
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "twitch": result,
                "externalSideEffects": False,
            }
        if not isinstance(payload, Mapping):
            raise TypeError("Twitch configuration must be an object")
        allowed = {
            "clientId", "eventsubSecret", "eventsubToken", "chatToken",
            "broadcasterId", "senderId", "moderatorId", "channel", "username",
            "eventsubCallbackUrl", "subscriptionProvider",
            "clearClientId", "clearEventsubSecret", "clearEventsubToken", "clearChatToken",
            "clearBroadcasterId", "clearSenderId", "clearModeratorId", "clearChannel",
            "clearUsername", "clearEventsubCallbackUrl", "clearSubscriptionProvider",
        }
        unknown = sorted(str(key) for key in payload if str(key) not in allowed)
        if unknown:
            raise ValueError(f"unsupported Twitch configuration field: {unknown[0]}")
        current = {
            "clientId": self._twitch_chat_adapter.client_id,
            "eventsubSecret": self._twitch_ingress.secret,
            "eventsubToken": self._twitch_eventsub_token,
            "chatToken": self._twitch_chat_adapter.access_token,
            "broadcasterId": self._twitch_chat_adapter.broadcaster_id,
            "senderId": self._twitch_chat_adapter.sender_id,
            "moderatorId": self._twitch_moderator_id,
            "channel": self._twitch_transport.channel,
            "username": self._twitch_transport.username,
            "eventsubCallbackUrl": self._twitch_eventsub_callback_url,
            "subscriptionProvider": str(getattr(getattr(self._twitch_ingress, "_subscription_provider", None), "name", "") or ""),
        }
        next_values = {
            field: self._twitch_config_value(payload, current, field)
            for field in current
        }
        provider_mode = next_values["subscriptionProvider"].lower()
        if provider_mode not in {"", "none", "in-memory-staging", "helix", "twitch-helix"}:
            raise ValueError("subscriptionProvider is unsupported")
        callback_url = next_values["eventsubCallbackUrl"]
        if callback_url and not callback_url.startswith("https://"):
            raise ValueError("eventsubCallbackUrl must use https")

        next_provider: TwitchSubscriptionProvider | None = None
        provider_requested = "subscriptionProvider" in payload or "clearSubscriptionProvider" in payload
        if provider_requested:
            if provider_mode in {"", "none"}:
                next_provider = None
            elif provider_mode == "in-memory-staging":
                next_provider = InMemoryTwitchSubscriptionProvider()
            else:
                candidate = TwitchHelixSubscriptionProvider(
                    client_id=next_values["clientId"],
                    access_token=next_values["eventsubToken"] or next_values["chatToken"],
                    broadcaster_id=next_values["broadcasterId"],
                    callback_url=callback_url,
                    secret=next_values["eventsubSecret"],
                    moderator_id=next_values["moderatorId"] or next_values["broadcasterId"],
                )
                if not candidate.configured:
                    raise ValueError("Twitch Helix subscription configuration is incomplete")
                next_provider = candidate

        # Stop an explicit IRC connection before replacing its credentials.
        self._twitch_connection.stop()
        self._twitch_ingress.configure_secret(next_values["eventsubSecret"])
        self._twitch_chat_adapter.configure(
            next_values["clientId"],
            next_values["chatToken"] or next_values["eventsubToken"],
            next_values["broadcasterId"],
            next_values["senderId"],
        )
        self._twitch_transport.configure(
            access_token=next_values["chatToken"] or next_values["eventsubToken"],
            channel=next_values["channel"],
            username=next_values["username"],
        )
        self._twitch_moderator_id = next_values["moderatorId"]
        self._twitch_eventsub_callback_url = callback_url
        self._twitch_eventsub_token = next_values["eventsubToken"].removeprefix("Bearer ").removeprefix("oauth:").strip()
        if provider_requested:
            self._twitch_ingress.configure_subscription_provider(next_provider)
        self._twitch_connection.configure(self._twitch_transport.configured)
        self._twitch_connection.mark_revoked(False)
        reset = self._twitch_ingress.reset_revocation()
        snapshot = self.snapshot()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "twitch": snapshot.get("platforms", {}).get("twitch", {}),
            "configured": {
                "eventsub": bool(next_values["eventsubSecret"]),
                "chat": self._twitch_chat_adapter.configured,
                "irc": self._twitch_transport.configured,
                "subscriptions": self._twitch_ingress.subscription_provider_configured,
            },
            "revocation": reset,
            "externalSideEffects": False,
        }

    def probe_twitch(self) -> dict[str, Any]:
        """Return a local readiness snapshot without opening provider connections."""
        snapshot = self.snapshot()
        twitch = snapshot.get("platforms", {}).get("twitch", {})
        if not isinstance(twitch, Mapping):
            twitch = {}
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "configured": {
                "eventsub": twitch.get("eventsubConfigured") is True,
                "chat": twitch.get("chatConfigured") is True,
                "irc": bool((twitch.get("ircConnection") or {}).get("configured")) if isinstance(twitch.get("ircConnection"), Mapping) else False,
                "subscriptions": bool((twitch.get("subscriptionPlan") or {}).get("remoteSyncAvailable")) if isinstance(twitch.get("subscriptionPlan"), Mapping) else False,
            },
            "revoked": twitch.get("revoked") is True,
            "externalSideEffects": False,
        }

    def configure_twitch_subscriptions(self, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Save a local EventSub plan; remote subscription APIs are not called."""
        body = dict(payload or {})
        subscriptions = body.get("subscriptions")
        result = self._twitch_ingress.configure_subscriptions(subscriptions)
        with self._lock:
            twitch = self._state.get("platforms", {}).get("twitch")
            if isinstance(twitch, dict):
                twitch["subscriptionPlan"] = deepcopy(result.get("subscriptionPlan"))
        return {
            "schemaVersion": SCHEMA_VERSION,
            "ok": True,
            "subscriptionPlan": result.get("subscriptionPlan"),
            "externalSideEffects": False,
        }

    def connect_twitch(self) -> dict[str, Any]:
        """Request an explicit Twitch IRC connection attempt."""
        result = self._twitch_connection.start()
        return {"schemaVersion": SCHEMA_VERSION, "ok": result["status"] in {"connecting", "connected"}, "ircConnection": result, "externalSideEffects": False}

    def disconnect_twitch(self) -> dict[str, Any]:
        """Stop Twitch IRC reconnect intent without changing EventSub state."""
        result = self._twitch_connection.stop()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "ircConnection": result, "externalSideEffects": False}

    def shutdown(self) -> None:
        """Close the optional Twitch IRC transport during backend shutdown."""
        self._twitch_connection.stop()


    def tick_twitch(self) -> dict[str, Any]:
        """Advance a pending retry window; transport workers may call this."""
        result = self._twitch_connection.tick()
        return {"schemaVersion": SCHEMA_VERSION, "ok": True, "ircConnection": result, "externalSideEffects": False}

    def set_takeover(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["policy"]["humanTakeover"] = enabled
            self._state["lastAction"] = {
                "action": "stream.takeover",
                "enabled": enabled,
                "at": now,
                "externalSideEffects": False,
            }
            snapshot = deepcopy(self._state)
            return {
                "schemaVersion": SCHEMA_VERSION,
                "ok": True,
                "enabled": enabled,
                "state": snapshot.get("state", "disconnected"),
                "policy": snapshot.get("policy", {}),
                "snapshot": snapshot,
                "externalSideEffects": False,
            }


__all__ = ["SCHEMA_VERSION", "ObsWebSocketAdapter", "StreamRuntime"]
