"""Inbound webhook boundary for experimental external message connectors."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from modules.agent.turn_service import SemanticTurnRequest
from modules.system.message_connectors import (
    ConnectorMessage,
    MessageConnectorError,
    MessageConnectorRegistry,
)

MAX_CONNECTOR_BODY_BYTES = 512 * 1024
LOGGER = logging.getLogger(__name__)


class ConnectorRecoveryController:
    """Discover only expired inbound leases and replay them through retry."""

    def __init__(
        self,
        *,
        store_provider: Callable[[], Any] | None,
        active_tasks: Mapping[str, asyncio.Task[JSONResponse]],
        retry_callback: Callable[[str, str], Awaitable[JSONResponse]],
        interval_seconds: float,
        metrics_path: str | Path | None = None,
    ) -> None:
        self._store_provider = store_provider
        self._active_tasks = active_tasks
        self._retry_callback = retry_callback
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._metrics_path = Path(metrics_path) if metrics_path is not None else None
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._metrics_lock = Lock()
        self._metrics: dict[str, Any] = {
            "runs": 0,
            "inspected": 0,
            "recovered": 0,
            "failed": 0,
            "lastRunAt": None,
            "lastError": None,
        }
        self._load_metrics()

    def _load_metrics(self) -> None:
        if self._metrics_path is None:
            return
        try:
            payload = json.loads(self._metrics_path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping) or payload.get("schemaVersion") != "yuizaki.connector-recovery.v1":
                return
            for key in ("runs", "inspected", "recovered", "failed"):
                value = payload.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000_000:
                    self._metrics[key] = value
            last_run = payload.get("lastRunAt")
            if (
                isinstance(last_run, (int, float))
                and not isinstance(last_run, bool)
                and math.isfinite(float(last_run))
                and 0.0 <= float(last_run) <= 10**12
            ):
                self._metrics["lastRunAt"] = float(last_run)
            last_error = payload.get("lastError")
            if last_error is None or isinstance(last_error, str):
                self._metrics["lastError"] = str(last_error)[:160] if last_error else None
        except (OSError, TypeError, ValueError):
            return

    def _persist_metrics(self) -> None:
        if self._metrics_path is None:
            return
        payload = {"schemaVersion": "yuizaki.connector-recovery.v1", **self._metrics}
        try:
            self._metrics_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self._metrics_path.with_suffix(f"{self._metrics_path.suffix}.tmp")
            temporary_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
            temporary_path.replace(self._metrics_path)
        except OSError:
            LOGGER.debug("connector recovery telemetry persistence failed", exc_info=True)

    def snapshot(self) -> dict[str, Any]:
        """Return bounded recovery telemetry without message or credential data."""
        with self._metrics_lock:
            return {
                "schemaVersion": "yuizaki.connector-recovery.v1",
                **self._metrics,
            }

    async def run_once(self) -> dict[str, int]:
        """Recover expired processing rows; leave active and sending rows alone."""

        store = self._store_provider() if self._store_provider is not None else None
        if store is None:
            result = {"inspected": 0, "recovered": 0, "failed": 0}
            with self._metrics_lock:
                self._metrics.update({"runs": self._metrics["runs"] + 1, **result, "lastRunAt": time.time(), "lastError": "delivery_store_unavailable"})
                self._persist_metrics()
            return result
        rows = store.list_connector_deliveries(status="processing", limit=100)
        recovered = 0
        failed = 0
        last_error: str | None = None
        for row in rows:
            connector_id = str(row.get("connector_id") or "").strip().lower()
            event_id = str(row.get("event_id") or "").strip()
            delivery_key = str(row.get("delivery_key") or "").strip()
            if not connector_id or not event_id or not delivery_key:
                continue
            active = self._active_tasks.get(f"{connector_id}:{event_id}")
            if active is not None and not active.done():
                continue
            if not store.recover_stale_connector_turn(delivery_key):
                continue
            recovered += 1
            try:
                response = await self._retry_callback(connector_id, delivery_key)
                status_code = getattr(response, "status_code", None)
                if isinstance(status_code, bool) or not isinstance(status_code, int) or not 200 <= status_code < 300:
                    failed += 1
                    last_error = f"retry_status_{status_code}"[:160]
            except Exception as exc:
                failed += 1
                last_error = f"retry_exception_{type(exc).__name__}"[:160]
                LOGGER.exception(
                    "connector recovery retry failed connector=%s event_id=%s",
                    connector_id,
                    event_id,
                )
        result = {"inspected": len(rows), "recovered": recovered, "failed": failed}
        with self._metrics_lock:
            self._metrics.update({
                "runs": self._metrics["runs"] + 1,
                "inspected": self._metrics["inspected"] + result["inspected"],
                "recovered": self._metrics["recovered"] + recovered,
                "failed": self._metrics["failed"] + failed,
                "lastRunAt": time.time(),
                "lastError": last_error,
            })
            self._persist_metrics()
        return result

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="connector-recovery")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        self._stop.set()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("connector recovery scan failed")
                with self._metrics_lock:
                    self._metrics["lastError"] = "recovery_scan_failed"
                    self._persist_metrics()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                continue


async def _read_limited_body(request: Request) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CONNECTOR_BODY_BYTES:
            return None
    return bytes(body)


def _message_snapshot(
    message: ConnectorMessage,
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    snapshot = {
        "connector_id": message.connector_id,
        "event_id": message.event_id,
        "session_id": message.session_id,
        "external_user_id": message.external_user_id,
        "conversation_id": message.conversation_id,
        "text": message.text,
        "reply_target": dict(message.reply_target),
    }
    if workspace_id:
        snapshot["workspace_id"] = workspace_id
    return snapshot


def _message_from_snapshot(payload: Mapping[str, Any]) -> ConnectorMessage:
    target = payload.get("reply_target")
    if not isinstance(target, Mapping):
        raise TypeError("delivery message snapshot is missing reply_target")
    return ConnectorMessage(
        connector_id=str(payload.get("connector_id") or "").strip().lower(),
        event_id=str(payload.get("event_id") or "").strip(),
        session_id=str(payload.get("session_id") or "").strip(),
        external_user_id=str(payload.get("external_user_id") or "unknown").strip(),
        conversation_id=str(payload.get("conversation_id") or "").strip(),
        text=str(payload.get("text") or "").strip(),
        reply_target={str(key): str(value) for key, value in target.items() if value is not None},
    )


def _public_delivery(
    row: Mapping[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    if row is None:
        return None
    status = row.get("status")
    lease_expires_at = row.get("claim_expires_at")
    effective_now = time.time() if now is None else now
    lease_expired = lease_expires_at is None or (
        isinstance(lease_expires_at, (int, float))
        and not isinstance(lease_expires_at, bool)
        and math.isfinite(float(lease_expires_at))
        and float(lease_expires_at) <= effective_now
    )
    return {
        key: row.get(key)
        for key in (
            "delivery_key", "idempotency_key", "connector_id", "event_id", "status",
            "attempt_count", "claim_expires_at", "last_error", "updated_at", "delivered_at",
        )
    } | {"resolvable": status == "sending" and lease_expired}


def _turn_request(message: ConnectorMessage, workspace_id: str) -> SemanticTurnRequest:
    request_id = f"connector:{message.connector_id}:{message.event_id}"
    return SemanticTurnRequest(
        session_id=message.session_id,
        workspace_id=workspace_id,
        request_id=request_id,
        turn_id=f"turn:{request_id}",
        messages=[{"role": "user", "content": message.text}],
        extra={
            "source": message.connector_id,
            "source_kind": "external_connector",
            "source_id": message.event_id,
            "invocation_source": f"{message.connector_id}_webhook",
            "conversation_id": message.conversation_id,
            "owner_agent_id": f"connector.{message.connector_id}",
            "owner_agent_role": "external_connector",
            "route_reason": "Experimental external message connector",
        },
    )


def create_message_connector_router(
    *,
    registry_provider: Callable[[], MessageConnectorRegistry],
    turn_service_provider: Callable[[], Any],
    active_workspace_id_provider: Callable[[], str],
    delivery_store_provider: Callable[[], Any] | None = None,
    fast_ack_connectors: Collection[str] | None = None,
    recovery_interval_seconds: float | None = None,
    recovery_metrics_path: str | Path | None = None,
    wall_clock: Callable[[], float] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["connectors"])
    fast_ack = frozenset(
        str(item).strip().lower()
        for item in (fast_ack_connectors or ())
        if str(item).strip()
    )
    active_tasks: dict[str, asyncio.Task[JSONResponse]] = {}
    active_phases: dict[str, str] = {}
    active_event_ids: dict[str, str] = {}
    current_time = wall_clock or time.time

    @router.get("/api/system/connectors/{connector_id}/config")
    async def connector_config(connector_id: str) -> JSONResponse:
        snapshot = registry_provider().config_snapshot(connector_id)
        if snapshot is None:
            return JSONResponse({"ok": False, "error": "unknown_connector"}, status_code=404)
        return JSONResponse(snapshot)

    @router.put("/api/system/connectors/{connector_id}/config")
    async def update_connector_config(connector_id: str, request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "payload_must_be_object"}, status_code=400)
        allowed = {
            "enabled", "botToken", "webhookSecret", "publicKey",
            "accountMode", "bridgeUrl", "bridgeProtocol", "bridgeToken",
            "clearBotToken", "clearWebhookSecret", "clearPublicKey",
            "clearBridgeUrl", "clearBridgeProtocol", "clearBridgeToken",
        }
        if set(payload) - allowed:
            return JSONResponse({"ok": False, "error": "unknown_fields"}, status_code=422)
        if "enabled" in payload and not isinstance(payload["enabled"], bool):
            return JSONResponse({"ok": False, "error": "enabled_must_be_boolean"}, status_code=422)
        try:
            snapshot = registry_provider().update_config(connector_id, payload)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc)}, status_code=422)
        if snapshot is None:
            return JSONResponse({"ok": False, "error": "unknown_connector"}, status_code=404)
        return JSONResponse({"ok": True, "config": snapshot})

    @router.post("/api/system/connectors/{connector_id}/probe")
    async def probe_connector(connector_id: str) -> JSONResponse:
        """Run a provider health check without sending a message or changing state."""
        try:
            result = await asyncio.to_thread(registry_provider().probe, connector_id)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc)}, status_code=exc.status_code)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": "probe_failed", "message": str(exc)[:160]}, status_code=502)
        return JSONResponse(result)

    @router.get("/api/system/connectors/{connector_id}/account")
    async def connector_account(connector_id: str) -> JSONResponse:
        snapshot = registry_provider().account_status(connector_id)
        if snapshot is None:
            return JSONResponse({"ok": False, "error": "account_binding_not_supported"}, status_code=404)
        return JSONResponse({"ok": True, "account": snapshot})

    @router.post("/api/system/connectors/{connector_id}/account/login")
    async def login_connector_account(connector_id: str) -> JSONResponse:
        registry = registry_provider()
        try:
            snapshot = await asyncio.to_thread(registry.login_account, connector_id)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc), "account": registry.account_status(connector_id)}, status_code=exc.status_code)
        return JSONResponse({"ok": True, "account": snapshot})

    @router.get("/api/system/connectors/{connector_id}/account/status")
    async def refresh_connector_account_status(connector_id: str) -> JSONResponse:
        registry = registry_provider()
        snapshot = await asyncio.to_thread(registry.refresh_account_status, connector_id)
        return JSONResponse({"ok": True, "account": snapshot}) if snapshot is not None else JSONResponse({"ok": False, "error": "account_binding_not_supported"}, status_code=404)

    @router.post("/api/system/connectors/{connector_id}/account/logout")
    async def logout_connector_account(connector_id: str) -> JSONResponse:
        registry = registry_provider()
        try:
            snapshot = await asyncio.to_thread(registry.logout_account, connector_id)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc)}, status_code=exc.status_code)
        return JSONResponse({"ok": True, "account": snapshot}) if snapshot is not None else JSONResponse({"ok": False, "error": "account_binding_not_supported"}, status_code=404)

    @router.delete("/api/system/connectors/{connector_id}/account")
    async def unbind_connector_account(connector_id: str) -> JSONResponse:
        registry = registry_provider()
        try:
            snapshot = await asyncio.to_thread(registry.unbind_account, connector_id)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc)}, status_code=exc.status_code)
        if snapshot is None:
            return JSONResponse({"ok": False, "error": "account_binding_not_supported"}, status_code=404)
        return JSONResponse({"ok": True, "account": snapshot, "config": registry.config_snapshot(connector_id)})

    @router.get("/api/system/connectors/{connector_id}/deliveries")
    @router.get("/api/system/connectors/{connector_id}/events")
    async def list_connector_deliveries(connector_id: str, request: Request) -> JSONResponse:
        store = delivery_store_provider() if delivery_store_provider is not None else None
        if store is None:
            return JSONResponse({"ok": False, "error": "delivery_store_unavailable"}, status_code=503)
        connector_id = connector_id.strip().lower()
        if connector_id not in {"telegram", "discord", "qq", "wechat"}:
            return JSONResponse({"ok": False, "error": "unknown_connector"}, status_code=404)
        try:
            limit = int(request.query_params.get("limit", "50"))
        except ValueError:
            return JSONResponse({"ok": False, "error": "invalid_limit"}, status_code=422)
        status = request.query_params.get("status")
        rows = store.list_connector_deliveries(connector_id=connector_id, status=status, limit=limit)
        recovered = False
        for row in rows:
            if row.get("status") != "processing":
                continue
            event_id = str(row.get("event_id") or "")
            task = active_tasks.get(f"{connector_id}:{event_id}")
            if task is None or task.done():
                recovered = store.recover_stale_connector_turn(str(row.get("delivery_key") or "")) or recovered
        if recovered:
            rows = store.list_connector_deliveries(connector_id=connector_id, status=status, limit=limit)
        persisted_keys = {str(row.get("delivery_key") or "") for row in rows}
        active_rows = []
        for task_key, phase in active_phases.items():
            if not task_key.startswith(f"{connector_id}:"):
                continue
            event_id = active_event_ids.get(task_key, "")
            delivery_key = f"connector:{connector_id}:{event_id}"
            if delivery_key in persisted_keys or (status and status != phase):
                continue
            active_rows.append({
                "delivery_key": delivery_key,
                "idempotency_key": delivery_key,
                "connector_id": connector_id,
                "event_id": event_id,
                "status": phase,
                "attempt_count": 0,
                "claim_expires_at": None,
                "last_error": None,
                "updated_at": 0,
                "delivered_at": None,
            })
        # Do not expose credentials or the original message body in governance telemetry.
        recovery_controller = getattr(router, "connector_recovery_controller", None)
        return JSONResponse({
            "ok": True,
            "connector_id": connector_id,
            "items": [*active_rows, *[_public_delivery(row) for row in rows]],
            "recovery": recovery_controller.snapshot() if recovery_controller is not None else None,
        })

    @router.post("/api/system/connectors/{connector_id}/deliveries/{delivery_key}/retry")
    async def retry_connector_delivery(connector_id: str, delivery_key: str) -> JSONResponse:
        store = delivery_store_provider() if delivery_store_provider is not None else None
        if store is None:
            return JSONResponse({"ok": False, "error": "delivery_store_unavailable"}, status_code=503)
        connector_id = connector_id.strip().lower()
        row = store.connector_delivery(delivery_key)
        if row is None or row.get("connector_id") != connector_id:
            return JSONResponse({"ok": False, "error": "delivery_not_found"}, status_code=404)
        event_id = str(row.get("event_id") or "")
        active_task = active_tasks.get(f"{connector_id}:{event_id}")
        if row.get("status") == "processing" and active_task is not None and not active_task.done():
            return JSONResponse({"ok": False, "error": "delivery_in_progress", "delivery": _public_delivery(row)}, status_code=409)
        if row.get("status") == "processing":
            store.recover_stale_connector_turn(delivery_key)
            row = store.connector_delivery(delivery_key) or row
            if row.get("status") == "processing":
                return JSONResponse({"ok": False, "error": "delivery_in_progress", "delivery": _public_delivery(row)}, status_code=409)
        if row.get("status") == "delivered":
            return JSONResponse({"ok": True, "already_sent": True, "delivery": _public_delivery(row)})
        try:
            snapshot = json.loads(row.get("message_json") or "")
            message = _message_from_snapshot(snapshot)
            reply = str(row.get("reply_text") or "").strip()
            retry_turn = not reply and row.get("last_error") in {
                "connector_turn_failed",
                "connector_turn_interrupted",
            }
            if not reply and not retry_turn:
                raise ValueError("delivery reply is unavailable")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return JSONResponse({"ok": False, "error": "delivery_not_retryable", "message": str(exc)}, status_code=422)
        owner = f"manual-retry:{uuid.uuid4().hex}"
        if retry_turn:
            claim = store.claim_connector_turn_retry(delivery_key, owner)
        else:
            claim = store.claim_connector_delivery(
                delivery_key, str(row.get("idempotency_key") or ""), connector_id,
                str(row.get("event_id") or message.event_id), owner,
                message=_message_snapshot(
                    message,
                    workspace_id=str(snapshot.get("workspace_id") or "").strip() or None,
                ),
                reply_text=reply,
            )
        if claim.get("status") == "busy":
            return JSONResponse({"ok": False, "error": "delivery_in_progress", "delivery": _public_delivery(row)}, status_code=409)
        if claim.get("status") == "delivered":
            return JSONResponse({"ok": True, "already_sent": True, "delivery": _public_delivery(store.connector_delivery(delivery_key))})
        if claim.get("status") != "claimed":
            return JSONResponse({"ok": False, "error": "delivery_not_retryable", "delivery": _public_delivery(row)}, status_code=422)
        turn_retry_promoted = False
        try:
            if retry_turn:
                turn_service = turn_service_provider()
                if turn_service is None:
                    raise RuntimeError("turn_service_unavailable")
                workspace_id = (
                    str(snapshot.get("workspace_id") or "").strip()
                    or str(active_workspace_id_provider() or "default").strip()
                    or "default"
                )
                commit = await turn_service.execute("http", _turn_request(message, workspace_id))
                result = getattr(commit, "result", None)
                outcome = str(getattr(result, "outcome", "") or "").strip().lower()
                if outcome in {"cancelled", "unknown_effect"}:
                    reason = "connector_event_cancelled" if outcome == "cancelled" else "connector_event_state_unknown"
                    store.release_connector_turn_retry(delivery_key, owner, reason)
                    return JSONResponse({
                        "ok": False,
                        "error": reason,
                        "delivery": _public_delivery(store.connector_delivery(delivery_key)),
                    }, status_code=409)
                reply = str(getattr(result, "reply", "") or "").strip()
                if not reply:
                    raise ValueError("empty_reply")
                if not store.promote_connector_turn_retry(delivery_key, owner, reply):
                    raise RuntimeError("delivery_retry_claim_lost")
                turn_retry_promoted = True
            delivery = await asyncio.to_thread(registry_provider().send_reply, message, reply)
            provider_ok = isinstance(delivery, Mapping) and delivery.get("ok") is True
            if isinstance(delivery, Mapping) and not provider_ok:
                status_code = delivery.get("status_code")
                provider_ok = isinstance(status_code, int) and 200 <= status_code < 300
            sent = not isinstance(delivery, Mapping) or delivery.get("sent", True) is not False
            if not provider_ok or not sent:
                reason = str(delivery.get("reason") or "provider_rejected") if isinstance(delivery, Mapping) else "provider_rejected"
                if not store.mark_connector_delivery_failed(delivery_key, owner, reason):
                    return JSONResponse({
                        "ok": False,
                        "error": "delivery_state_unknown",
                        "delivery": _public_delivery(store.connector_delivery(delivery_key)),
                    }, status_code=409)
                registry_provider().record_failure(connector_id, reason)
                return JSONResponse({"ok": False, "error": "delivery_failed", "delivery": _public_delivery(store.connector_delivery(delivery_key))}, status_code=502)
            if not store.mark_connector_delivery_sent(delivery_key, owner):
                registry_provider().record_failure(connector_id, "delivery_commit_lost")
                return JSONResponse({
                    "ok": False,
                    "error": "delivery_state_unknown",
                    "delivery": _public_delivery(store.connector_delivery(delivery_key)),
                }, status_code=409)
            registry_provider().record_success(connector_id)
            return JSONResponse({"ok": True, "retried": True, "delivery": _public_delivery(store.connector_delivery(delivery_key))})
        except asyncio.CancelledError:
            if retry_turn and not turn_retry_promoted:
                store.release_connector_turn_retry(delivery_key, owner, "connector_retry_cancelled")
            else:
                store.mark_connector_delivery_failed(delivery_key, owner, "connector_retry_cancelled")
            raise
        except Exception as exc:
            LOGGER.exception(
                "connector manual retry failed connector=%s event_id=%s delivery_key=%s",
                connector_id,
                message.event_id,
                delivery_key,
            )
            reason = "connector_turn_failed" if retry_turn and not turn_retry_promoted else str(exc)
            if retry_turn and not turn_retry_promoted:
                store.release_connector_turn_retry(delivery_key, owner, reason)
            else:
                store.mark_connector_delivery_failed(delivery_key, owner, reason)
            registry_provider().record_failure(connector_id, reason)
            return JSONResponse({"ok": False, "error": "delivery_failed", "delivery": _public_delivery(store.connector_delivery(delivery_key))}, status_code=502)

    @router.post("/api/system/connectors/{connector_id}/events/{event_id}/resolve")
    async def resolve_connector_event(connector_id: str, event_id: str, request: Request) -> JSONResponse:
        """Manually settle an orphaned provider send after external inspection.

        The endpoint is deliberately outcome-only: the operator confirms the
        provider state, while the server refuses to race an active task or an
        unexpired delivery lease.  No automatic retry or effect inference is
        performed here.
        """
        connector_id = connector_id.strip().lower()
        store = delivery_store_provider() if delivery_store_provider is not None else None
        if store is None:
            return JSONResponse({"ok": False, "error": "delivery_store_unavailable"}, status_code=503)
        try:
            payload = await request.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
        if not isinstance(payload, dict) or set(payload) != {"outcome"}:
            return JSONResponse({"ok": False, "error": "outcome_required"}, status_code=422)
        outcome = payload.get("outcome")
        if outcome not in {"delivered", "failed"}:
            return JSONResponse({"ok": False, "error": "invalid_outcome"}, status_code=422)
        delivery_key = f"connector:{connector_id}:{event_id}"
        resolution_now = current_time()
        row = store.connector_delivery(delivery_key)
        if row is None:
            return JSONResponse({"ok": False, "error": "delivery_not_found"}, status_code=404)
        if row.get("connector_id") != connector_id:
            return JSONResponse({"ok": False, "error": "delivery_not_found"}, status_code=404)
        task = active_tasks.get(f"{connector_id}:{event_id}")
        if task is not None and not task.done():
            return JSONResponse({
                "ok": False,
                "error": "delivery_in_progress",
                "delivery": _public_delivery(row, now=resolution_now),
            }, status_code=409)
        if row.get("status") != "sending":
            if outcome == "delivered" and row.get("status") == "delivered":
                return JSONResponse({"ok": True, "already_resolved": True, "delivery": _public_delivery(row, now=resolution_now)})
            return JSONResponse({"ok": False, "error": "delivery_not_resolvable", "delivery": _public_delivery(row, now=resolution_now)}, status_code=409)
        lease_expires_at = row.get("claim_expires_at")
        if lease_expires_at is not None and (
            isinstance(lease_expires_at, bool)
            or not isinstance(lease_expires_at, (int, float))
            or not math.isfinite(float(lease_expires_at))
        ):
            return JSONResponse({"ok": False, "error": "delivery_lease_invalid", "delivery": _public_delivery(row, now=resolution_now)}, status_code=409)
        if isinstance(lease_expires_at, (int, float)) and float(lease_expires_at) > resolution_now:
            return JSONResponse({"ok": False, "error": "delivery_lease_active", "delivery": _public_delivery(row, now=resolution_now)}, status_code=409)
        resolved = store.resolve_connector_delivery(delivery_key, outcome)
        if not resolved:
            return JSONResponse({"ok": False, "error": "delivery_state_changed", "delivery": _public_delivery(store.connector_delivery(delivery_key), now=resolution_now)}, status_code=409)
        if outcome == "delivered":
            registry_provider().record_success(connector_id)
        else:
            registry_provider().record_failure(connector_id, "manual_resolution_failed")
        return JSONResponse({"ok": True, "resolved": True, "outcome": outcome, "delivery": _public_delivery(store.connector_delivery(delivery_key), now=resolution_now)})

    @router.post("/api/system/connectors/{connector_id}/events/{event_id}/retry")
    async def retry_connector_event(connector_id: str, event_id: str) -> JSONResponse:
        """Retry by provider event id; webhook delivery keys are connector:event_id."""
        key = f"connector:{connector_id.strip().lower()}:{event_id}"
        return await retry_connector_delivery(connector_id, key)

    @router.post("/api/system/connectors/{connector_id}/events/{event_id}/cancel")
    async def cancel_connector_event(connector_id: str, event_id: str) -> JSONResponse:
        connector_id = connector_id.strip().lower()
        key = f"{connector_id}:{event_id}"
        task = active_tasks.get(key)
        if task is None or task.done():
            store = delivery_store_provider() if delivery_store_provider is not None else None
            row = store.connector_delivery(f"connector:{connector_id}:{event_id}") if store is not None else None
            if store is not None and row is not None and row.get("status") == "processing":
                store.recover_stale_connector_turn(f"connector:{connector_id}:{event_id}")
                row = store.connector_delivery(f"connector:{connector_id}:{event_id}")
            if row is not None and row.get("status") == "sending":
                return JSONResponse({
                    "ok": False,
                    "error": "delivery_state_unknown",
                    "outcome": "unknown",
                    "status": "sending",
                    "message": "发送已开始，但当前无法确认最终结果，请先检查平台后再决定是否重投",
                    "delivery": _public_delivery(row),
                }, status_code=409)
            if row is not None and row.get("status") == "delivered":
                return JSONResponse({
                    "ok": False,
                    "error": "cancel_too_late",
                    "outcome": "too_late",
                    "status": "delivered",
                    "message": "回复已经送达，无法取消",
                    "delivery": _public_delivery(row),
                }, status_code=409)
            return JSONResponse({"ok": False, "error": "event_not_running"}, status_code=404)
        phase = active_phases.get(key, "processing")
        if phase == "sending":
            return JSONResponse({
                "ok": False,
                "error": "cancel_too_late",
                "outcome": "too_late",
                "status": "sending",
                "message": "回复已进入平台发送阶段，无法安全取消",
            }, status_code=409)
        task.cancel()
        completed_response: JSONResponse | None = None
        try:
            completed_response = await task
        except asyncio.CancelledError:
            pass
        finally:
            if active_tasks.get(key) is task:
                active_tasks.pop(key, None)
                active_phases.pop(key, None)
                active_event_ids.pop(key, None)
        if completed_response is not None and completed_response.status_code == 409:
            try:
                completed_payload = json.loads(bytes(completed_response.body))
            except (TypeError, ValueError, json.JSONDecodeError):
                completed_payload = None
            if isinstance(completed_payload, Mapping) and completed_payload.get("outcome") == "unknown":
                return completed_response
        return JSONResponse({
            "ok": True,
            "cancelled": True,
            "outcome": "cancelled",
            "status": "cancelled",
            "event_id": event_id,
        })

    @router.post("/api/system/connectors/{connector_id}/webhook")
    async def receive_connector_webhook(connector_id: str, request: Request) -> JSONResponse:
        connector_id = connector_id.strip().lower()
        if connector_id not in {"telegram", "discord", "qq", "wechat"}:
            return JSONResponse({"ok": False, "error": "unknown_connector"}, status_code=404)
        registry = registry_provider()
        received_at = registry.current_time()
        content_length = request.headers.get("content-length")
        try:
            if content_length is not None:
                declared_length = int(content_length)
                if declared_length < 0:
                    return JSONResponse({"ok": False, "error": "invalid_content_length"}, status_code=400)
                if declared_length > MAX_CONNECTOR_BODY_BYTES:
                    return JSONResponse({"ok": False, "error": "payload_too_large"}, status_code=413)
        except ValueError:
            return JSONResponse({"ok": False, "error": "invalid_content_length"}, status_code=400)
        raw_body = await _read_limited_body(request)
        if raw_body is None:
            return JSONResponse({"ok": False, "error": "payload_too_large"}, status_code=413)
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"ok": False, "error": "payload_must_be_object"}, status_code=400)
        # Discord requires a PING response before the endpoint can be enabled.
        if connector_id == "discord" and payload.get("type") == 1:
            if not registry.verify_request(connector_id, request.headers, raw_body):
                return JSONResponse({"ok": False, "error": "invalid_signature"}, status_code=401)
            return JSONResponse({"type": 1})
        if not registry.is_enabled(connector_id):
            return JSONResponse({"ok": False, "error": "connector_disabled"}, status_code=409)
        if not registry.verify_request(connector_id, request.headers, raw_body):
            return JSONResponse({"ok": False, "error": "invalid_webhook_auth"}, status_code=401)
        try:
            message = registry.parse(connector_id, payload, received_at=received_at)
        except MessageConnectorError as exc:
            return JSONResponse({"ok": False, "error": exc.code, "message": str(exc)}, status_code=exc.status_code)
        if message is None:
            return JSONResponse({"ok": True, "accepted": False, "reason": "unsupported_event"})
        request_id = f"connector:{connector_id}:{message.event_id}"
        task_key = f"{connector_id}:{message.event_id}"
        canonical_task = active_tasks.get(task_key)
        if canonical_task is not None and not canonical_task.done():
            duplicate_store = delivery_store_provider() if delivery_store_provider is not None else None
            if connector_id in fast_ack and duplicate_store is not None:
                return JSONResponse({
                    "ok": True,
                    "accepted": True,
                    "queued": True,
                    "duplicate": True,
                    "event_id": message.event_id,
                    "session_id": message.session_id,
                    "delivery": _public_delivery(
                        duplicate_store.connector_delivery(request_id)
                    ),
                })
            if connector_id == "discord":
                return JSONResponse({"type": 5, "data": {"allowed_mentions": {"parse": []}}})
            try:
                return await asyncio.shield(canonical_task)
            except asyncio.CancelledError:
                return JSONResponse({"ok": False, "error": "connector_event_cancelled"}, status_code=409)
        delivery_store = delivery_store_provider() if delivery_store_provider is not None else None
        existing_delivery = delivery_store.connector_delivery(request_id) if delivery_store is not None else None
        if (
            delivery_store is not None
            and existing_delivery is not None
            and existing_delivery.get("status") == "processing"
        ):
            delivery_store.recover_stale_connector_turn(request_id)
            existing_delivery = delivery_store.connector_delivery(request_id)
            if existing_delivery is not None and existing_delivery.get("status") == "processing":
                if connector_id == "discord":
                    return JSONResponse({"type": 5, "data": {"allowed_mentions": {"parse": []}}})
                return JSONResponse({
                    "ok": False,
                    "error": "connector_event_in_progress",
                    "delivery": _public_delivery(existing_delivery),
                }, status_code=409)
        if delivery_store is not None and existing_delivery is not None:
            existing_event_id = str(existing_delivery.get("event_id") or "")
            if existing_event_id and existing_event_id != message.event_id:
                return JSONResponse({
                    "ok": False,
                    "error": "delivery_key_conflict",
                    "delivery": _public_delivery(existing_delivery),
                }, status_code=409)
            existing_status = str(existing_delivery.get("status") or "").strip().lower()
            if existing_status == "delivered":
                return JSONResponse({
                    "ok": True,
                    "accepted": False,
                    "duplicate": True,
                    "already_sent": True,
                    "event_id": message.event_id,
                    "session_id": message.session_id,
                    "delivery": _public_delivery(existing_delivery),
                })
            if existing_status == "sending":
                return JSONResponse({
                    "ok": False,
                    "accepted": True,
                    "error": "delivery_state_unknown",
                    "outcome": "unknown",
                    "status": "sending",
                    "message": "上次发送的最终结果未知，请先检查平台后再手动重投",
                    "event_id": message.event_id,
                    "session_id": message.session_id,
                    "delivery": _public_delivery(existing_delivery),
                }, status_code=409)
            if existing_status == "failed" and not str(existing_delivery.get("reply_text") or "").strip():
                # A replay must never regenerate a failed turn implicitly;
                # manual retry owns the explicit recovery boundary.
                return JSONResponse({
                    "ok": True,
                    "accepted": True,
                    "queued": False,
                    "duplicate": True,
                    "event_id": message.event_id,
                    "session_id": message.session_id,
                    "delivery": _public_delivery(existing_delivery),
                })
        try:
            turn_service = turn_service_provider()
            if turn_service is None:
                if connector_id == "discord":
                    return JSONResponse({
                        "type": 4,
                        "data": {
                            "content": "Yuizaki 暂时不可用，请稍后重试。",
                            "allowed_mentions": {"parse": []},
                        },
                    })
                return JSONResponse({"ok": False, "error": "turn_service_unavailable"}, status_code=503)
            workspace_id = str(active_workspace_id_provider() or "default").strip() or "default"
            turn_request = _turn_request(message, workspace_id)
        except Exception:
            LOGGER.exception(
                "connector turn setup failed connector=%s event_id=%s request_id=%s",
                connector_id,
                message.event_id,
                request_id,
            )
            registry.record_failure(connector_id, "connector_setup_failed")
            if connector_id == "discord":
                return JSONResponse({
                    "type": 4,
                    "data": {
                        "content": "Yuizaki 暂时不可用，请稍后重试。",
                        "allowed_mentions": {"parse": []},
                    },
                })
            return JSONResponse(
                {"ok": False, "error": "connector_setup_failed", "message": "连接器暂时不可用，请稍后重试"},
                status_code=503,
            )
        queued_store = delivery_store_provider() if delivery_store_provider is not None else None
        queued_owner: str | None = None
        queued_pending_created = False
        if (connector_id in fast_ack or connector_id == "discord") and queued_store is not None:
            # Persist the inbound envelope before acknowledging the provider.
            # This is the durable boundary; the async worker is only a
            # continuation and may be recreated by the retry route.
            queued_owner = f"{connector_id}:{message.event_id}:{uuid.uuid4().hex}"
            try:
                queued_pending_created = queued_store.record_connector_turn_pending(
                    request_id,
                    request_id,
                    connector_id,
                    message.event_id,
                    queued_owner,
                    message=_message_snapshot(message, workspace_id=workspace_id),
                )
            except Exception:
                LOGGER.exception(
                    "connector durable enqueue failed connector=%s event_id=%s",
                    connector_id,
                    message.event_id,
                )
                registry.record_failure(connector_id, "connector_enqueue_failed")
                return JSONResponse(
                    {"ok": False, "error": "connector_enqueue_failed", "message": "连接器暂时不可用，请稍后重试"},
                    status_code=503,
                )
        async def _run_connector() -> JSONResponse:
            delivery_owner = queued_owner or f"{connector_id}:{message.event_id}:{uuid.uuid4().hex}"
            delivery_key = request_id
            delivery_store = queued_store if queued_store is not None else (
                delivery_store_provider() if delivery_store_provider is not None else None
            )
            delivery_claimed = False
            turn_pending_created = queued_pending_created

            async def _converge_discord(status: str) -> None:
                if connector_id != "discord":
                    return
                try:
                    await asyncio.to_thread(registry.update_deferred_status, message, status)
                except (MessageConnectorError, OSError, RuntimeError, TypeError, ValueError):
                    LOGGER.warning(
                        "discord deferred response convergence failed event_id=%s status=%s",
                        message.event_id,
                        status,
                    )

            try:
                if delivery_store is not None and not turn_pending_created:
                    turn_pending_created = delivery_store.record_connector_turn_pending(
                        delivery_key,
                        request_id,
                        connector_id,
                        message.event_id,
                        delivery_owner,
                        message=_message_snapshot(message, workspace_id=workspace_id),
                    )
                commit = await turn_service.execute("http", turn_request)
                replayed = bool(getattr(commit, "replayed", False))
                result = getattr(commit, "result", None)
                turn_outcome = str(getattr(result, "outcome", "") or "").strip().lower()
                if turn_outcome == "cancelled":
                    if delivery_store is not None and turn_pending_created:
                        delivery_store.discard_connector_turn_pending(delivery_key, delivery_owner)
                    await _converge_discord("cancelled")
                    return JSONResponse({
                        "ok": False,
                        "error": "connector_event_cancelled",
                        "outcome": "cancelled",
                        "status": "cancelled",
                    }, status_code=409)
                if turn_outcome == "unknown_effect":
                    if delivery_store is not None and turn_pending_created:
                        delivery_store.discard_connector_turn_pending(delivery_key, delivery_owner)
                    await _converge_discord("unknown")
                    return JSONResponse({
                        "ok": False,
                        "error": "connector_event_state_unknown",
                        "outcome": "unknown",
                        "status": "processing",
                        "message": "事件处理的最终效果未知，未发送外部回复",
                    }, status_code=409)
                if delivery_store is None and replayed:
                    return JSONResponse({
                        "ok": True,
                        "accepted": False,
                        "duplicate": True,
                        "replayed": True,
                        "event_id": message.event_id,
                        "session_id": message.session_id,
                        "turn_id": getattr(getattr(commit, "context", None), "turn_id", turn_request.turn_id),
                        "delivery": {"ok": True, "replayed": True},
                    })
                if delivery_store is not None:
                    reply = str(getattr(result, "reply", "") or "").strip()
                    existing_delivery = delivery_store.connector_delivery(delivery_key)
                    if replayed and existing_delivery is not None and existing_delivery.get("status") == "sending":
                        return JSONResponse({
                            "ok": False,
                            "accepted": True,
                            "error": "delivery_state_unknown",
                            "outcome": "unknown",
                            "status": "sending",
                            "message": "上次发送的最终结果未知，请先检查平台后再手动重投",
                            "event_id": message.event_id,
                            "session_id": message.session_id,
                            "delivery": _public_delivery(existing_delivery),
                        }, status_code=409)
                    delivery_claim = delivery_store.claim_connector_delivery(
                        delivery_key,
                        request_id,
                        connector_id,
                        message.event_id,
                        delivery_owner,
                        message=_message_snapshot(message, workspace_id=workspace_id),
                        reply_text=reply,
                    )
                    if delivery_claim.get("status") == "delivered":
                        return JSONResponse({
                            "ok": True,
                            "accepted": False,
                            "duplicate": True,
                            "replayed": replayed,
                            "event_id": message.event_id,
                            "session_id": message.session_id,
                            "turn_id": getattr(getattr(commit, "context", None), "turn_id", turn_request.turn_id),
                            "delivery": {"ok": True, "replayed": replayed, "already_sent": True},
                        })
                    if delivery_claim.get("status") == "busy":
                        return JSONResponse({
                            "ok": False,
                            "accepted": True,
                            "event_id": message.event_id,
                            "session_id": message.session_id,
                            "delivery": {"ok": False, "reason": "delivery_in_progress"},
                        }, status_code=409)
                    delivery_claimed = delivery_claim.get("status") == "claimed"
                result = getattr(commit, "result", None)
                reply = str(getattr(result, "reply", "") or "").strip()
                try:
                    active_phases[task_key] = "sending"
                    delivery = await asyncio.to_thread(registry.send_reply, message, reply)
                except Exception as exc:
                    if delivery_store is not None and delivery_claimed:
                        delivery_store.mark_connector_delivery_failed(delivery_key, delivery_owner, str(exc))
                    raise
                provider_ok = isinstance(delivery, Mapping) and delivery.get("ok") is True
                if isinstance(delivery, Mapping) and not provider_ok:
                    status_code = delivery.get("status_code")
                    provider_ok = isinstance(status_code, int) and 200 <= status_code < 300
                sent = isinstance(delivery, Mapping) and delivery.get("sent", True) is not False
                delivery_ok = bool(reply) and provider_ok and sent
                if not delivery_ok:
                    reason = "empty_reply" if not reply else (
                        str(delivery.get("reason") or "provider_rejected")
                        if isinstance(delivery, Mapping)
                        else "provider_rejected"
                    )
                    if delivery_store is not None and delivery_claimed:
                        delivery_store.mark_connector_delivery_failed(delivery_key, delivery_owner, reason)
                    registry.record_failure(connector_id, reason)
                    await _converge_discord("failed")
                    return JSONResponse({
                        "ok": False,
                        "accepted": True,
                        "event_id": message.event_id,
                        "session_id": message.session_id,
                        "delivery": {"ok": False, "reason": reason},
                    }, status_code=502)
                if (
                    delivery_store is not None
                    and delivery_claimed
                    and not delivery_store.mark_connector_delivery_sent(delivery_key, delivery_owner)
                ):
                    registry.record_failure(connector_id, "delivery_commit_lost")
                    return JSONResponse({
                        "ok": False,
                        "accepted": True,
                        "error": "delivery_state_unknown",
                        "outcome": "unknown",
                        "status": "sending",
                        "message": "平台可能已经收到回复，但本地未能确认完成状态",
                        "delivery": _public_delivery(delivery_store.connector_delivery(delivery_key)),
                    }, status_code=409)
                registry.record_success(connector_id)
                return JSONResponse({
                    "ok": True,
                    "accepted": True,
                    "event_id": message.event_id,
                    "session_id": message.session_id,
                    "turn_id": getattr(getattr(commit, "context", None), "turn_id", turn_request.turn_id),
                    "reply_sent": True,
                    "delivery": {"ok": True, "provider": connector_id},
                })
            except asyncio.CancelledError:
                if delivery_store is not None and turn_pending_created and not delivery_claimed:
                    delivery_store.discard_connector_turn_pending(delivery_key, delivery_owner)
                registry.record_failure(connector_id, "事件已取消")
                await _converge_discord("cancelled")
                raise
            except Exception:
                LOGGER.exception(
                    "connector turn failed connector=%s event_id=%s request_id=%s",
                    connector_id,
                    message.event_id,
                    turn_request.request_id,
                )
                registry.record_failure(connector_id, "connector_turn_failed")
                if delivery_store is not None and delivery_claimed:
                    delivery_store.mark_connector_delivery_failed(delivery_key, delivery_owner, "connector_turn_failed")
                elif delivery_store is not None:
                    delivery_store.mark_connector_turn_failed(
                        delivery_key,
                        delivery_owner,
                        "connector_turn_failed",
                    )
                await _converge_discord("failed")
                return JSONResponse({"ok": False, "error": "connector_turn_failed", "message": "连接器处理失败，请查看治理面板"}, status_code=502)

        active_phases[task_key] = "processing"
        active_event_ids[task_key] = message.event_id
        task = asyncio.create_task(_run_connector())
        active_tasks[task_key] = task
        if connector_id == "discord" or (connector_id in fast_ack and queued_store is not None):
            def _cleanup(completed: asyncio.Task[JSONResponse]) -> None:
                if active_tasks.get(task_key) is completed:
                    active_tasks.pop(task_key, None)
                    active_phases.pop(task_key, None)
                    active_event_ids.pop(task_key, None)

            task.add_done_callback(_cleanup)
            if connector_id == "discord":
                return JSONResponse({"type": 5, "data": {"allowed_mentions": {"parse": []}}})
            # The pending delivery row is written before this response. The
            # worker continues locally and remains recoverable through retry.
            return JSONResponse({
                "ok": True,
                "accepted": True,
                "queued": True,
                "event_id": message.event_id,
                "session_id": message.session_id,
                "delivery": _public_delivery(
                    queued_store.connector_delivery(request_id)
                ),
            })
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            return JSONResponse({"ok": False, "error": "connector_event_cancelled"}, status_code=409)
        finally:
            if active_tasks.get(task_key) is task:
                active_tasks.pop(task_key, None)
                active_phases.pop(task_key, None)
                active_event_ids.pop(task_key, None)

    recovery_controller = ConnectorRecoveryController(
        store_provider=delivery_store_provider,
        active_tasks=active_tasks,
        retry_callback=retry_connector_delivery,
        interval_seconds=recovery_interval_seconds,
        metrics_path=recovery_metrics_path,
    ) if recovery_interval_seconds is not None and recovery_interval_seconds > 0 else None
    router.connector_recovery_controller = recovery_controller
    return router


__all__ = ["MAX_CONNECTOR_BODY_BYTES", "ConnectorRecoveryController", "create_message_connector_router"]
