"""Explicit Twitch IRC connection lifecycle state machine.

The state machine owns intent, retry timing, and user-visible health only. A
transport is injected by the runtime, so creating the object never opens a
socket and tests can exercise reconnect behavior without network access.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event, Lock, RLock, Thread, current_thread
from typing import Any

try:  # websocket-client is optional until Twitch IRC is explicitly enabled.
    import websocket as _websocket
except ImportError:  # pragma: no cover - depends on the host installation
    _websocket = None

_STATUSES = {"stopped", "connecting", "connected", "backoff", "unconfigured", "revoked"}
TWITCH_IRC_WEBSOCKET_URL = "wss://irc-ws.chat.twitch.tv:443"
_NON_RETRYABLE_ERRORS = {"auth_failed", "permission_denied"}


class TwitchConnectionSupervisor:
    """Coordinate an explicit, retryable Twitch IRC connection attempt."""

    def __init__(
        self,
        *,
        configured: bool,
        connect: Callable[[], bool] | None = None,
        close: Callable[[], None] | None = None,
        clock: Callable[[], float] | None = None,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 60.0,
        auto_retry: bool = False,
    ) -> None:
        self._configured = bool(configured)
        self._connect = connect
        self._close = close
        self._clock = clock or time.monotonic
        self._base_backoff = max(0.1, min(float(base_backoff_seconds), 60.0))
        self._max_backoff = max(self._base_backoff, min(float(max_backoff_seconds), 3600.0))
        self._auto_retry = bool(auto_retry)
        self._desired = False
        self._status = "stopped" if self._configured else "unconfigured"
        self._attempt = 0
        self._next_retry_at: float | None = None
        self._last_error: str | None = None
        self._retry_stop = Event()
        self._retry_thread: Thread | None = None
        self._state_lock = RLock()

    def configure(self, configured: bool) -> None:
        with self._state_lock:
            self._configured = bool(configured)
            should_close = not self._configured
            if should_close:
                self._desired = False
                self._next_retry_at = None
                self._status = "unconfigured"
            elif self._status == "unconfigured":
                self._status = "stopped"
        if should_close:
            self._stop_retry_worker()
            self._close_safely()

    def start(self, *, now: float | None = None) -> dict[str, Any]:
        with self._state_lock:
            if self._status == "revoked":
                self._desired = False
                return self.snapshot()
            self._desired = True
            if not self._configured:
                self._desired = False
                self._status = "unconfigured"
                return self.snapshot()
            self._next_retry_at = None
        self._attempt_connect(self._now(now))
        return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._state_lock:
            self._desired = False
            self._next_retry_at = None
            self._status = "stopped" if self._configured else "unconfigured"
        self._stop_retry_worker()
        self._close_safely()
        return self.snapshot()

    def mark_connected(self) -> dict[str, Any]:
        with self._state_lock:
            if not self._configured or not self._desired or self._status == "revoked":
                self._status = "revoked" if self._status == "revoked" else "unconfigured" if not self._configured else "stopped"
                return self.snapshot()
            self._status = "connected"
            self._attempt = 0
            self._next_retry_at = None
            self._last_error = None
        self._stop_retry_worker()
        return self.snapshot()

    def mark_disconnected(self, error: str | None = None, *, now: float | None = None) -> dict[str, Any]:
        self._close_safely()
        with self._state_lock:
            if self._status == "revoked":
                return self.snapshot()
            if not self._desired:
                self._status = "stopped" if self._configured else "unconfigured"
                return self.snapshot()
        self._schedule_retry(error, self._now(now))
        return self.snapshot()

    def mark_revoked(self, revoked: bool = True) -> dict[str, Any]:
        if revoked:
            with self._state_lock:
                self._desired = False
                self._next_retry_at = None
                self._status = "revoked"
            self._stop_retry_worker()
            self._close_safely()
        else:
            with self._state_lock:
                if self._status == "revoked":
                    self._status = "stopped" if self._configured else "unconfigured"
        return self.snapshot()

    def tick(self, *, now: float | None = None) -> dict[str, Any]:
        current = self._now(now)
        with self._state_lock:
            should_retry = self._desired and self._status == "backoff" and self._next_retry_at is not None and current >= self._next_retry_at
        if should_retry:
            self._attempt_connect(current)
        return self.snapshot(now=current)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = self._now(now)
        with self._state_lock:
            next_retry_in = None
            if self._next_retry_at is not None:
                next_retry_in = max(0.0, self._next_retry_at - current)
            return {
                "status": self._status if self._status in _STATUSES else "stopped",
                "configured": self._configured,
                "desired": self._desired,
                "attempt": self._attempt,
                "nextRetryInSeconds": round(next_retry_in, 3) if next_retry_in is not None else None,
                "backoffSeconds": round(self._backoff_for_attempt(), 3) if self._status == "backoff" else None,
                "lastError": self._last_error,
            }

    def _attempt_connect(self, now: float) -> None:
        with self._state_lock:
            if not self._desired or not self._configured or self._status == "revoked":
                return
            self._status = "connecting"
            self._attempt += 1
            attempt = self._attempt
        if self._connect is None:
            self._schedule_retry("transport_unconfigured", now)
            return
        try:
            connected = bool(self._connect())
        except Exception as exc:  # noqa: BLE001 - transport failures become retry state.
            self._schedule_retry(type(exc).__name__, now)
            return
        with self._state_lock:
            still_current = self._desired and self._configured and self._status == "connecting" and self._attempt == attempt
        if connected and still_current:
            self.mark_connected()
        elif connected:
            self._close_safely()
        else:
            self._schedule_retry("transport_rejected", now)

    def _schedule_retry(self, error: str | None, now: float) -> None:
        with self._state_lock:
            self._last_error = str(error or "connection_lost")[:120]
            if self._last_error in _NON_RETRYABLE_ERRORS:
                self._desired = False
                self._status = "stopped" if self._configured else "unconfigured"
                self._next_retry_at = None
                return
            if not self._desired or not self._configured:
                self._status = "stopped" if self._configured else "unconfigured"
                self._next_retry_at = None
                return
            self._status = "backoff"
            self._next_retry_at = now + self._backoff_for_attempt()
        self._ensure_retry_worker()

    def _backoff_for_attempt(self) -> float:
        exponent = max(0, min(self._attempt - 1, 16))
        return min(self._max_backoff, self._base_backoff * (2**exponent))

    def _close_safely(self) -> None:
        if self._close is None:
            return
        try:
            self._close()
        except Exception:  # noqa: BLE001 - transport close is best effort.
            return

    def _ensure_retry_worker(self) -> None:
        with self._state_lock:
            if not self._auto_retry or not self._desired or self._status != "backoff":
                return
            if self._retry_thread is not None and self._retry_thread.is_alive():
                return
            self._retry_stop.clear()
            self._retry_thread = Thread(target=self._retry_loop, name="yuizaki-twitch-retry", daemon=True)
            self._retry_thread.start()

    def _stop_retry_worker(self) -> None:
        self._retry_stop.set()
        with self._state_lock:
            worker = self._retry_thread
            self._retry_thread = None
        if worker is not None and worker is not current_thread():
            worker.join(timeout=2.0)

    def _retry_loop(self) -> None:
        while not self._retry_stop.is_set():
            snapshot = self.snapshot()
            if not snapshot["desired"] or snapshot["status"] != "backoff":
                return
            wait_seconds = float(snapshot["nextRetryInSeconds"] or 0.1)
            if self._retry_stop.wait(max(0.05, min(wait_seconds, 60.0))):
                return
            self.tick()

    def _now(self, value: float | None) -> float:
        current = self._clock() if value is None else value
        try:
            numeric = float(current)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        return numeric if math.isfinite(numeric) else 0.0


class TwitchIrcTransport:
    """Small websocket-client transport for explicit Twitch IRC sessions."""

    def __init__(
        self,
        *,
        access_token: str | None,
        channel: str | None,
        username: str | None,
        on_line: Callable[[str], Any],
        on_disconnect: Callable[[str], Any] | None = None,
        websocket_factory: Callable[..., Any] | None = None,
        endpoint: str = TWITCH_IRC_WEBSOCKET_URL,
        timeout: float = 8.0,
    ) -> None:
        self.access_token = str(access_token or "").strip().removeprefix("oauth:").strip()
        self.channel = str(channel or "").strip().removeprefix("#").strip().lower()
        self.username = str(username or "").strip()
        self.on_line = on_line
        self.on_disconnect = on_disconnect
        self.endpoint = endpoint.strip() or TWITCH_IRC_WEBSOCKET_URL
        self.timeout = max(1.0, min(float(timeout), 30.0))
        self._websocket_factory = websocket_factory or (_websocket.create_connection if _websocket is not None else None)
        self._socket: Any = None
        self._reader: Thread | None = None
        self._stop = Event()
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.channel and self.username and self._websocket_factory)

    def configure(
        self,
        *,
        access_token: str | None,
        channel: str | None,
        username: str | None,
    ) -> None:
        """Replace connection credentials and target without opening a socket."""
        self.close()
        with self._lock:
            self.access_token = str(access_token or "").strip().removeprefix("oauth:").strip()
            self.channel = str(channel or "").strip().removeprefix("#").strip().lower()
            self.username = str(username or "").strip()

    def connect(self) -> bool:
        if not self.configured:
            return False
        self.close()
        self._stop.clear()
        socket: Any = None
        try:
            socket = self._websocket_factory(self.endpoint, timeout=self.timeout, enable_multithread=True)
            setter = getattr(socket, "settimeout", None)
            if callable(setter):
                setter(1.0)
            for command in self._auth_commands():
                socket.send(command)
        except Exception:  # noqa: BLE001 - connection failure is surfaced through supervisor state.
            try:
                socket.close()
            except Exception as cleanup_error:  # noqa: BLE001 - best effort cleanup.
                _ = cleanup_error
            return False
        with self._lock:
            self._socket = socket
            self._reader = Thread(target=self._read_loop, name="yuizaki-twitch-irc", daemon=True)
            self._reader.start()
        return True

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            socket = self._socket
            reader = self._reader
            self._socket = None
            self._reader = None
        if socket is not None:
            try:
                socket.close()
            except Exception as cleanup_error:  # noqa: BLE001 - best effort cleanup.
                _ = cleanup_error
        if reader is not None and reader is not current_thread():
            reader.join(timeout=2.0)

    def _auth_commands(self) -> tuple[str, ...]:
        return (
            f"PASS oauth:{self.access_token}\r\n",
            f"NICK {self.username}\r\n",
            "CAP REQ :twitch.tv/tags twitch.tv/commands\r\n",
            f"JOIN #{self.channel}\r\n",
        )

    def _read_loop(self) -> None:
        error = "connection_closed"
        while not self._stop.is_set():
            with self._lock:
                socket = self._socket
            if socket is None:
                break
            try:
                raw = socket.recv()
            except Exception as exc:  # noqa: BLE001 - websocket errors become reconnect state.
                error = type(exc).__name__
                if "timeout" in error.lower():
                    continue
                break
            if raw is None or raw == "":
                break
            disconnect_requested = False
            for line in str(raw).splitlines():
                upper_line = line.upper()
                if upper_line.startswith("RECONNECT"):
                    error = "server_reconnect"
                    disconnect_requested = True
                    break
                if "LOGIN AUTHENTICATION FAILED" in upper_line:
                    error = "auth_failed"
                    disconnect_requested = True
                    break
                if upper_line.startswith("PING"):
                    try:
                        socket.send("PONG :tmi.twitch.tv\r\n")
                    except Exception as pong_error:  # noqa: BLE001 - reader will report disconnect on next recv.
                        error = type(pong_error).__name__
                    continue
                try:
                    self.on_line(line)
                except Exception as line_error:  # noqa: BLE001 - malformed lines do not stop the transport.
                    # A malformed provider line must not kill the transport.
                    error = f"line_handler:{type(line_error).__name__}"
            if disconnect_requested:
                break
        if not self._stop.is_set() and self.on_disconnect is not None:
            self.on_disconnect(error)


__all__ = ["TWITCH_IRC_WEBSOCKET_URL", "TwitchConnectionSupervisor", "TwitchIrcTransport"]
