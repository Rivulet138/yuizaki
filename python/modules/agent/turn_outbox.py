"""Ordered, retryable projections for durable semantic-turn commits."""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .turn_store import TurnCommitStore

logger = logging.getLogger(__name__)

TurnProjectionHandler = Callable[[dict[str, Any], Any | None], Any | Awaitable[Any]]


@dataclass(frozen=True)
class TurnProjection:
    name: str
    handler: TurnProjectionHandler

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("turn projection name is required")


class TurnOutboxDispatcher:
    def __init__(
        self,
        store: TurnCommitStore,
        projections: list[TurnProjection] | tuple[TurnProjection, ...],
        *,
        claim_lease_seconds: float = 30.0,
        max_attempts: int = 8,
        base_retry_seconds: float = 0.25,
        max_retry_seconds: float = 30.0,
    ) -> None:
        names = [projection.name for projection in projections]
        if len(names) != len(set(names)):
            raise ValueError("turn projection names must be unique")
        self.store = store
        self.projections = tuple(projections)
        self.claim_lease_seconds = max(0.1, float(claim_lease_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.base_retry_seconds = max(0.01, float(base_retry_seconds))
        self.max_retry_seconds = max(self.base_retry_seconds, float(max_retry_seconds))
        self.worker_id = f"outbox:{uuid.uuid4().hex}"
        self._wake_callback: Callable[[], None] | None = None
        self._dispatch_lock = asyncio.Lock()

    def set_wake_callback(self, callback: Callable[[], None] | None) -> None:
        self._wake_callback = callback

    async def __call__(self, commit: Any) -> dict[str, Any]:
        idempotency_key = str(getattr(commit, "idempotency_key", "") or "").strip()
        if not idempotency_key:
            raise ValueError("turn outbox dispatch requires a commit idempotency key")
        context = getattr(commit, "context", None)
        try:
            result = await self.dispatch_pending(
                context=context,
                target_idempotency_key=idempotency_key,
            )
            if not result["target_delivered"]:
                first_error = next(iter(result["errors"]), None)
                detail = (
                    str(first_error.get("error") or "")
                    if isinstance(first_error, dict)
                    else "the target event was not claimable"
                )
                raise RuntimeError(
                    f"turn outbox did not acknowledge commit {idempotency_key}: {detail}"
                )
            return result
        finally:
            if self._wake_callback is not None:
                self._wake_callback()

    async def dispatch_pending(
        self,
        *,
        context: Any | None = None,
        limit: int = 100,
        target_idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        async with self._dispatch_lock:
            return await self._dispatch_pending_unlocked(
                context=context,
                limit=limit,
                target_idempotency_key=target_idempotency_key,
            )

    async def _dispatch_pending_unlocked(
        self,
        *,
        context: Any | None = None,
        limit: int = 100,
        target_idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        target_key = str(target_idempotency_key or "").strip() or None
        delivered = 0
        delivered_event_ids: list[int] = []
        delivered_idempotency_keys: list[str] = []
        projection_deliveries = 0
        errors: list[dict[str, Any]] = []
        dead_lettered = 0
        retry_after: float | None = None
        for _ in range(max(1, int(limit))):
            event = self.store.claim_next_outbox(
                self.worker_id,
                lease_seconds=self.claim_lease_seconds,
            )
            if event is None:
                break
            status = str(event.get("status") or "")
            if status in {"busy", "waiting"}:
                retry_after = max(0.01, float(event.get("retry_after") or 0.05))
                break
            if status != "claimed":
                raise RuntimeError(f"invalid outbox claim status: {status or '<empty>'}")
            event_id = int(event["event_id"])
            event_key = str(event.get("idempotency_key") or "")
            acknowledged = self.store.acknowledged_projections(event_id)
            projection_result = await self._deliver_projections(
                event,
                context,
                acknowledged,
            )
            projection_deliveries += int(projection_result["projection_deliveries"])
            errors.extend(projection_result["errors"])
            dead_lettered += int(projection_result["dead_lettered"])
            retry_after = projection_result["retry_after"] or retry_after
            if projection_result["failed"]:
                break
            if all(projection.name in acknowledged for projection in self.projections):
                if self.store.acknowledge(event_id, self.worker_id):
                    delivered += 1
                    delivered_event_ids.append(event_id)
                    delivered_idempotency_keys.append(event_key)
                else:
                    errors.append({
                        "event_id": event_id,
                        "projection": "<terminal-ack>",
                        "error": "outbox claim expired before terminal acknowledgement",
                    })
                    break
            if target_key is not None and event_key == target_key:
                break
        target_delivered = (
            target_key in delivered_idempotency_keys
            if target_key is not None
            else None
        )
        if target_key is not None and not target_delivered:
            target_delivered = self._recover_or_confirm_target_ack(
                target_key,
                context=context,
            )
        return {
            "delivered": delivered,
            "delivered_event_ids": delivered_event_ids,
            "delivered_idempotency_keys": delivered_idempotency_keys,
            "projection_deliveries": projection_deliveries,
            "errors": errors,
            "dead_lettered": dead_lettered,
            "retry_after": retry_after,
            "target_idempotency_key": target_key,
            "target_delivered": target_delivered,
        }

    def _recover_or_confirm_target_ack(
        self,
        idempotency_key: str,
        *,
        context: Any | None,
    ) -> bool:
        """Recover an ACK-only crash or confirm an already delivered replay."""
        workspace_id = str(getattr(context, "workspace_id", "") or "").strip()
        if not workspace_id:
            return False
        event = next(
            (
                item
                for item in self.store.list_commits(workspace_id, limit=10000)
                if str(item.get("idempotency_key") or "") == idempotency_key
            ),
            None,
        )
        if event is None:
            return False
        event_id = int(event["event_id"])
        acknowledged = self.store.acknowledged_projections(event_id)
        if not all(projection.name in acknowledged for projection in self.projections):
            return False
        # This is idempotent. It closes the narrow crash window after every
        # destination ACK was recorded but before the terminal outbox ACK.
        self.store.acknowledge(event_id)
        return True

    async def _deliver_projections(
        self,
        event: dict[str, Any],
        context: Any | None,
        acknowledged: set[str],
    ) -> dict[str, Any]:
        event_id = int(event["event_id"])
        claim_lost = asyncio.Event()
        renew_task = asyncio.create_task(
            self._renew_claim_loop(event_id, claim_lost),
            name=f"turn-outbox-renew:{event_id}",
        )
        projection_deliveries = 0
        errors: list[dict[str, Any]] = []
        try:
            for projection in self.projections:
                if projection.name in acknowledged:
                    continue
                try:
                    cancellation_deferred = await self._invoke_projection(
                        projection,
                        event,
                        context,
                    )
                    if claim_lost.is_set():
                        raise RuntimeError("outbox claim was lost during projection")
                except Exception as exc:
                    logger.warning(
                        "Turn outbox projection %s failed for event %s: %s",
                        projection.name,
                        event_id,
                        exc,
                        exc_info=True,
                    )
                    errors.append({
                        "event_id": event_id,
                        "projection": projection.name,
                        "error": str(exc),
                    })
                    failure, retry_delay = self._record_projection_failure(
                        event,
                        str(exc),
                    )
                    return {
                        "failed": True,
                        "projection_deliveries": projection_deliveries,
                        "errors": errors,
                        "dead_lettered": int(bool(failure.get("dead_lettered"))),
                        "retry_after": None if failure.get("dead_lettered") else retry_delay,
                    }
                if not self.store.acknowledge_projection(
                    event_id,
                    projection.name,
                    self.worker_id,
                ):
                    error = "outbox claim expired before projection acknowledgement"
                    errors.append({
                        "event_id": event_id,
                        "projection": projection.name,
                        "error": error,
                    })
                    failure, retry_delay = self._record_projection_failure(event, error)
                    return {
                        "failed": True,
                        "projection_deliveries": projection_deliveries,
                        "errors": errors,
                        "dead_lettered": int(bool(failure.get("dead_lettered"))),
                        "retry_after": None if failure.get("dead_lettered") else retry_delay,
                    }
                acknowledged.add(projection.name)
                projection_deliveries += 1
                if cancellation_deferred:
                    raise asyncio.CancelledError
            return {
                "failed": False,
                "projection_deliveries": projection_deliveries,
                "errors": errors,
                "dead_lettered": 0,
                "retry_after": None,
            }
        finally:
            renew_task.cancel()
            await asyncio.gather(renew_task, return_exceptions=True)

    def _record_projection_failure(
        self,
        event: dict[str, Any],
        error: str,
    ) -> tuple[dict[str, Any], float]:
        attempt = int(event.get("attempt_count") or 0)
        retry_delay = min(
            self.max_retry_seconds,
            self.base_retry_seconds * (2 ** min(attempt, 16)),
        )
        retry_delay *= random.uniform(0.8, 1.2)
        failure = self.store.fail_outbox(
            int(event["event_id"]),
            self.worker_id,
            error,
            retry_delay=retry_delay,
            max_attempts=self.max_attempts,
        )
        return failure, retry_delay

    async def _invoke_projection(
        self,
        projection: TurnProjection,
        event: dict[str, Any],
        context: Any | None,
    ) -> bool:
        async def invoke() -> None:
            if inspect.iscoroutinefunction(projection.handler):
                await projection.handler(event, context)
                return
            outcome = await asyncio.to_thread(projection.handler, event, context)
            if inspect.isawaitable(outcome):
                await outcome

        invoke_task = asyncio.create_task(
            invoke(),
            name=f"turn-outbox-projection:{event['event_id']}:{projection.name}",
        )
        cancellation_deferred = False
        try:
            await asyncio.shield(invoke_task)
        except asyncio.CancelledError:
            cancellation_deferred = True
            await invoke_task
        return cancellation_deferred

    async def _renew_claim_loop(
        self,
        event_id: int,
        claim_lost: asyncio.Event,
    ) -> None:
        interval = max(0.02, self.claim_lease_seconds / 3.0)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await asyncio.to_thread(
                    self.store.renew_outbox_claim,
                    event_id,
                    self.worker_id,
                    lease_seconds=self.claim_lease_seconds,
                )
            except Exception:
                claim_lost.set()
                raise
            if not renewed:
                claim_lost.set()
                return


class TurnOutboxWorker:
    """Lifecycle-managed recovery loop for committed turn projections."""

    def __init__(
        self,
        dispatcher: TurnOutboxDispatcher,
        *,
        idle_poll_seconds: float = 1.0,
        shutdown_timeout_seconds: float = 5.0,
    ) -> None:
        self.dispatcher = dispatcher
        self.idle_poll_seconds = max(0.05, float(idle_poll_seconds))
        self.shutdown_timeout_seconds = max(0.1, float(shutdown_timeout_seconds))
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_dispatch_at: float | None = None
        self._last_error: str | None = None
        dispatcher.set_wake_callback(self.wake)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="turn-outbox-worker")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=self.shutdown_timeout_seconds)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._task = None
        try:
            await asyncio.wait_for(
                self.dispatcher.dispatch_pending(limit=100),
                timeout=self.shutdown_timeout_seconds,
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Turn outbox shutdown drain failed: %s", exc, exc_info=True)

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                result = await self.dispatcher.dispatch_pending(limit=100)
                self._last_dispatch_at = time.time()
                self._last_error = (
                    str(result["errors"][0]["error"])
                    if result.get("errors")
                    else None
                )
                retry_after = result.get("retry_after")
            except Exception as exc:
                self._last_error = str(exc)
                retry_after = self.idle_poll_seconds
                logger.warning("Turn outbox worker iteration failed: %s", exc, exc_info=True)
            wait_seconds = (
                min(self.idle_poll_seconds, max(0.01, float(retry_after)))
                if retry_after is not None
                else self.idle_poll_seconds
            )
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass

    def diagnostics(self) -> dict[str, Any]:
        return {
            **self.dispatcher.store.outbox_diagnostics(),
            "running": self._task is not None and not self._task.done(),
            "last_dispatch_at": self._last_dispatch_at,
            "last_error": self._last_error,
        }


__all__ = [
    "TurnOutboxDispatcher",
    "TurnOutboxWorker",
    "TurnProjection",
    "TurnProjectionHandler",
]
