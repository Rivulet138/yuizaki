from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import inspect
import logging
import os
import time
import uuid
from typing import Any, Callable

from .companion_events import CompanionJobCapacityError, CompanionJobEventLog
from .context import AgentRequestContext
from .models import SchedulerRunRecord
from .pipeline import AgentPipeline
from .route_policy import resolve_schedule_route
from .schedule_store import ScheduleStore, ScheduledTask
from ..system.memory_write_pipeline import build_task_completed_event

logger = logging.getLogger(__name__)

_TERMINAL_RUN_STATUSES = frozenset({
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "unknown_effect",
})


@dataclass
class _ScheduledRun:
    task_id: str
    run_id: str
    job_id: str
    request_id: str
    workspace_id: str
    session_id: str
    turn_id: str
    interruption_epoch: int = 0
    status: str = "created"
    created_at: float = 0.0
    finished_at: float | None = None
    outcome: str | None = None
    retryable: bool | None = None
    summary: str | None = None
    configured_budget: dict[str, Any] = field(default_factory=dict)
    consumed_usage: dict[str, Any] = field(default_factory=dict)
    background_task: asyncio.Task[None] | None = None


class AgentScheduler:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        pipeline: AgentPipeline,
        context_factory: Callable[[ScheduledTask], AgentRequestContext],
        workspace_id_provider: Callable[[], str] | None = None,
        interruption_epoch_provider: Callable[[], int] | None = None,
        job_event_log: CompanionJobEventLog | None = None,
        turn_service: Any | None = None,
        allow_legacy_pipeline: bool | None = None,
    ) -> None:
        self.store = store
        self.pipeline = pipeline
        self.context_factory = context_factory
        self.workspace_id_provider = workspace_id_provider
        self.interruption_epoch_provider = interruption_epoch_provider
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._active_task_ids: set[str] = set()
        self._background_runs: set[asyncio.Task[None]] = set()
        self._runs_by_task: dict[str, _ScheduledRun] = {}
        self._runs_by_job: dict[str, _ScheduledRun] = {}
        self._runs_by_id: OrderedDict[str, _ScheduledRun] = OrderedDict()
        self._latest_runs_by_task: dict[str, _ScheduledRun] = {}
        self._wake_event = asyncio.Event()
        self._job_events = job_event_log or CompanionJobEventLog()
        self.turn_service = turn_service
        self.allow_legacy_pipeline = (
            str(os.getenv("YUIZAKI_ALLOW_LEGACY_TURN_PIPELINE", "")).strip().lower()
            in {"1", "true", "yes", "on"}
            if allow_legacy_pipeline is None
            else bool(allow_legacy_pipeline)
        )
        self._store_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        await self._recover_interrupted_tasks()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="agent-scheduler")

    async def _recover_interrupted_tasks(self) -> None:
        now = time.time()
        changed: list[ScheduledTask] = []
        for task in self.store.list():
            if task.last_status not in {"queued", "running"}:
                continue
            previous_status = task.last_status
            job_id = task.last_job_id or f"schedjob_recovered_{task.id}"
            run_id = task.last_run_id or f"schedrun_recovered_{task.id}"
            request_id = task.last_request_id or f"schedreq_recovered_{task.id}"
            workspace_id = "default"
            if self.workspace_id_provider is not None:
                try:
                    workspace_id = str(self.workspace_id_provider() or "default").strip() or "default"
                except Exception:
                    logger.exception("Failed to resolve scheduler workspace id during recovery")
            try:
                self._job_events.append(
                    workspace_id=workspace_id,
                    session_id=f"schedule:{task.id}",
                    turn_id=f"turn:{job_id}",
                    job_id=job_id,
                    run_id=run_id,
                    request_id=request_id,
                    interruption_epoch=0,
                    source="scheduler",
                    timestamp=now,
                    status="interrupted",
                    data={
                        "taskId": task.id,
                        "runId": run_id,
                        "taskName": task.name,
                        "mode": task.mode,
                        "previousStatus": previous_status,
                        "retryable": True,
                        "reason": "scheduler_restarted_before_run_finished",
                    },
                )
            except CompanionJobCapacityError:
                logger.warning("Unable to record interrupted scheduler job %s; event log is full", job_id)
            task.last_status = "interrupted:manual_rerun_required"
            task.last_run_summary = "Previous scheduler run was interrupted; run manually to retry."
            if task.mode == "once":
                task.enabled = False
                task.next_run_at = None
            elif task.interval_seconds:
                task.next_run_at = now + task.interval_seconds
            else:
                task.enabled = False
                task.next_run_at = None
            changed.append(task)
        for task in changed:
            await self._upsert_task(task)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        background_runs = list(self._background_runs)
        self._background_runs.clear()
        for task in background_runs:
            if task.done():
                continue
            task.cancel()
        for task in background_runs:
            if task.done():
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._wake_event.set()

    async def add_once(self, name: str, prompt: str, run_after_seconds: int, source: str = "schedule") -> ScheduledTask:
        now = time.time()
        route = resolve_schedule_route("once")
        task = ScheduledTask(
            id=f"sched_{uuid.uuid4().hex[:12]}",
            name=name,
            source=source,
            prompt=prompt,
            enabled=True,
            mode="once",
            created_at=now,
            run_after_seconds=run_after_seconds,
            next_run_at=now + run_after_seconds,
            owner_agent_id=route.owner_agent_id,
            owner_agent_role=route.owner_agent_role,
            route_reason=route.route_reason,
        )
        result = await self._upsert_task(task)
        self._wake_event.set()
        return result

    async def add_interval(self, name: str, prompt: str, interval_seconds: int, source: str = "schedule") -> ScheduledTask:
        now = time.time()
        route = resolve_schedule_route("interval")
        task = ScheduledTask(
            id=f"sched_{uuid.uuid4().hex[:12]}",
            name=name,
            source=source,
            prompt=prompt,
            enabled=True,
            mode="interval",
            created_at=now,
            interval_seconds=interval_seconds,
            next_run_at=now + interval_seconds,
            owner_agent_id=route.owner_agent_id,
            owner_agent_role=route.owner_agent_role,
            route_reason=route.route_reason,
        )
        result = await self._upsert_task(task)
        self._wake_event.set()
        return result

    async def remove_task(self, task_id: str) -> None:
        await self.cancel(task_id)
        await self._remove_task(task_id)
        self._wake_event.set()

    async def set_enabled(self, task_id: str, enabled: bool) -> ScheduledTask | None:
        async with self._store_lock:
            def _set_enabled() -> ScheduledTask | None:
                task = self.store.tasks.get(task_id)
                if task is None:
                    return None
                task.enabled = enabled
                if enabled and task.next_run_at is None:
                    task.next_run_at = time.time() + (task.interval_seconds or task.run_after_seconds or 1)
                return self.store.upsert(task)

            result = await asyncio.to_thread(_set_enabled)
            self._wake_event.set()
            return result

    async def run_now(self, task_id: str) -> ScheduledTask | None:
        async with self._store_lock:
            task = self.store.tasks.get(task_id)
            if task is None:
                return None
        if task.id in self._active_task_ids:
            return task
        task.last_status = "queued"
        await self._upsert_task(task)
        await self._queue_task(task)
        return task

    async def _queue_task(self, task: ScheduledTask) -> asyncio.Task[None] | None:
        if task.id in self._active_task_ids:
            active_run = self._runs_by_task.get(task.id)
            return active_run.background_task if active_run is not None else None
        workspace_id = "default"
        if self.workspace_id_provider is not None:
            try:
                workspace_id = str(self.workspace_id_provider() or "default").strip() or "default"
            except Exception:
                logger.exception("Failed to resolve scheduler workspace id")
        job_id = f"schedjob_{uuid.uuid4().hex[:12]}"
        run_id = f"schedrun_{uuid.uuid4().hex[:12]}"
        request_id = f"schedreq_{uuid.uuid4().hex[:12]}"
        run = _ScheduledRun(
            task_id=task.id,
            run_id=run_id,
            job_id=job_id,
            request_id=request_id,
            workspace_id=workspace_id,
            session_id=f"schedule:{task.id}",
            turn_id=f"turn:{job_id}",
            interruption_epoch=self._interruption_epoch(),
            created_at=time.time(),
        )
        try:
            self._emit_event(run, task, "created")
        except CompanionJobCapacityError:
            task.last_status = "blocked:job_capacity"
            task.last_run_summary = "Scheduler job capacity is full; the task has not started."
            task.next_run_at = time.time() + 5.0
            await self._upsert_task(task)
            logger.warning("Scheduler job capacity refused task %s; retry deferred", task.id)
            return None
        self._active_task_ids.add(task.id)
        self._runs_by_task[task.id] = run
        self._runs_by_job[job_id] = run
        self._runs_by_id[run_id] = run
        self._latest_runs_by_task[task.id] = run
        task.last_run_id = run_id
        task.last_job_id = job_id
        task.last_request_id = request_id
        self._trim_run_history()
        background_run = asyncio.create_task(self._run_task(task, run), name=f"agent-scheduler-run-{task.id}")
        run.background_task = background_run
        self._background_runs.add(background_run)
        background_run.add_done_callback(self._log_background_run_error)
        return background_run

    async def _upsert_task(self, task: ScheduledTask) -> ScheduledTask:
        async with self._store_lock:
            return await asyncio.to_thread(self.store.upsert, task)

    async def _remove_task(self, task_id: str) -> None:
        async with self._store_lock:
            await asyncio.to_thread(self.store.remove, task_id)

    def _log_background_run_error(self, task: asyncio.Task[None]) -> None:
        self._background_runs.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Scheduled task background run failed: %s", exc)

    async def _load_durable_commit(
        self,
        ctx: AgentRequestContext | None,
    ) -> Mapping[str, Any] | None:
        if not isinstance(ctx, AgentRequestContext) or self.turn_service is None:
            return None
        ports = getattr(self.turn_service, "ports", None)
        loader = getattr(ports, "load", None)
        idempotency_key = getattr(self.turn_service, "idempotency_key", None)
        semantic_fingerprint = getattr(self.turn_service, "semantic_fingerprint", None)
        if not callable(loader) or not callable(idempotency_key) or not callable(semantic_fingerprint):
            return None
        expected_key = str(idempotency_key(ctx))
        expected_fingerprint = str(semantic_fingerprint(ctx))
        stored = loader(expected_key)
        if inspect.isawaitable(stored):
            stored = await stored
        if not isinstance(stored, Mapping):
            return None
        if str(stored.get("idempotency_key") or "") != expected_key:
            return None
        if str(stored.get("semantic_fingerprint") or "") != expected_fingerprint:
            return None
        if not isinstance(stored.get("result"), Mapping):
            return None
        return stored

    @staticmethod
    def _apply_authoritative_result(
        run: _ScheduledRun,
        task: ScheduledTask,
        result: Any,
        *,
        finished_at: float | None = None,
    ) -> None:
        def field_value(name: str, default: Any) -> Any:
            return result.get(name, default) if isinstance(result, Mapping) else getattr(result, name, default)

        outcome = str(field_value("outcome", "completed") or "completed").strip().lower()
        if outcome not in _TERMINAL_RUN_STATUSES:
            raise ValueError(f"unsupported authoritative scheduler outcome: {outcome}")
        summary = str(field_value("reply", "") or "")[:160] or None
        run.status = outcome
        run.outcome = outcome
        run.retryable = bool(field_value("retryable", False))
        run.summary = summary
        run.configured_budget = dict(field_value("configured_budget", {}) or {})
        run.consumed_usage = dict(field_value("consumed_usage", {}) or {})
        run.finished_at = float(finished_at) if finished_at is not None else time.time()
        task.last_status = "ok" if outcome == "completed" else outcome
        task.last_request_id = run.request_id
        task.last_run_summary = summary

    def _reconcile_durable_commit(
        self,
        run: _ScheduledRun,
        task: ScheduledTask,
        stored: Mapping[str, Any] | None,
    ) -> bool:
        if stored is None:
            return False
        result = stored.get("result")
        if not isinstance(result, Mapping):
            return False
        created_at = stored.get("created_at")
        self._apply_authoritative_result(
            run,
            task,
            result,
            finished_at=float(created_at) if created_at is not None else None,
        )
        return True

    def _emit_event(self, run: _ScheduledRun, task: ScheduledTask, status: str, **data: Any) -> None:
        run.status = status
        if status in _TERMINAL_RUN_STATUSES:
            run.finished_at = time.time()
        self._job_events.append(
            workspace_id=run.workspace_id,
            session_id=run.session_id,
            turn_id=run.turn_id,
            job_id=run.job_id,
            run_id=run.run_id,
            request_id=run.request_id,
            interruption_epoch=run.interruption_epoch,
            source="scheduler",
            timestamp=time.time(),
            status=status,
            data={"taskId": task.id, "runId": run.run_id, "taskName": task.name, "mode": task.mode, **data},
        )

    def _interruption_epoch(self) -> int:
        if self.interruption_epoch_provider is None:
            return 0
        try:
            return max(0, int(self.interruption_epoch_provider()))
        except Exception:
            logger.exception("Failed to resolve scheduler interruption epoch")
            return 0

    def _trim_run_history(self, max_runs: int = 256) -> None:
        while len(self._runs_by_id) > max_runs:
            removable_id = next(
                (
                    run_id
                    for run_id, run in self._runs_by_id.items()
                    if run.status in _TERMINAL_RUN_STATUSES
                ),
                None,
            )
            if removable_id is None:
                return
            removed = self._runs_by_id.pop(removable_id)
            self._runs_by_job.pop(removed.job_id, None)
            if self._latest_runs_by_task.get(removed.task_id) is removed:
                self._latest_runs_by_task.pop(removed.task_id, None)

    @staticmethod
    def _serialize_run(run: _ScheduledRun) -> dict[str, Any]:
        return {
            "taskId": run.task_id,
            "runId": run.run_id,
            "jobId": run.job_id,
            "requestId": run.request_id,
            "workspaceId": run.workspace_id,
            "sessionId": run.session_id,
            "turnId": run.turn_id,
            "status": run.status,
            "outcome": run.outcome,
            "retryable": run.retryable,
            "summary": run.summary,
            "configuredBudget": dict(run.configured_budget),
            "consumedUsage": dict(run.consumed_usage),
            "createdAt": run.created_at,
            "finishedAt": run.finished_at,
        }

    def _resolve_run(self, task_job_or_run_id: str) -> _ScheduledRun | None:
        return (
            self._runs_by_task.get(task_job_or_run_id)
            or self._runs_by_job.get(task_job_or_run_id)
            or self._runs_by_id.get(task_job_or_run_id)
            or self._latest_runs_by_task.get(task_job_or_run_id)
        )

    def get_run(self, task_job_or_run_id: str) -> dict[str, Any] | None:
        run = self._resolve_run(task_job_or_run_id)
        return self._serialize_run(run) if run is not None else None

    def snapshot_job_events(self) -> list[dict[str, Any]]:
        return self._job_events.snapshot()

    def active_job_ids(self) -> list[str]:
        return self._job_events.active_job_ids()

    async def wait_for_task(self, task_job_or_run_id: str, timeout: float | None = None) -> None:
        run = self._resolve_run(task_job_or_run_id)
        if run is None or run.background_task is None:
            return
        waiter = asyncio.shield(run.background_task)
        if timeout is None:
            await waiter
        else:
            await asyncio.wait_for(waiter, timeout=timeout)

    async def cancel(self, task_or_job_id: str) -> bool:
        run = self._resolve_run(task_or_job_id)
        if run is None or run.background_task is None or run.background_task.done():
            return False
        run.background_task.cancel()
        try:
            await run.background_task
        except asyncio.CancelledError:
            pass
        return True

    async def _loop(self) -> None:
        while self._running:
            now = time.time()
            self._wake_event.clear()
            for task in list(self.store.list()):
                if not task.enabled or task.next_run_at is None or task.next_run_at > now:
                    continue
                await self._queue_task(task)
            due_times = [
                task.next_run_at
                for task in self.store.list()
                if task.enabled and task.next_run_at is not None and task.id not in self._active_task_ids
            ]
            delay = max(0.05, min(due_times) - time.time()) if due_times else None
            try:
                if delay is None:
                    await self._wake_event.wait()
                else:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _run_task(self, task: ScheduledTask, run: _ScheduledRun) -> None:
        ctx: AgentRequestContext | None = None
        terminal_emitted = False
        uses_turn_authority = self.turn_service is not None
        try:
            task.last_status = "running"
            task.last_request_id = run.request_id
            await self._upsert_task(task)
            self._emit_event(run, task, "running")
            ctx = self.context_factory(task)
            if isinstance(ctx, AgentRequestContext):
                ctx.request_id = run.request_id
                ctx.workspace_id = getattr(ctx, "workspace_id", None) or run.workspace_id
                ctx.turn_id = run.turn_id
                ctx.generation_id = f"generation:{run.turn_id}"
                ctx.interruption_epoch = run.interruption_epoch
                ctx.permission_scope = f"scheduler:{ctx.workspace_id}"
                ctx.extra.update({
                    "turn_id": ctx.turn_id,
                    "generation_id": ctx.generation_id,
                    "interruption_epoch": ctx.interruption_epoch,
                    "job_id": run.job_id,
                    "run_id": run.run_id,
                    "task_id": task.id,
                    "task_name": task.name,
                    "task_mode": task.mode,
                    "owner_agent_id": task.owner_agent_id,
                    "owner_agent_role": task.owner_agent_role,
                    "route_reason": task.route_reason,
                    "permission_scope": ctx.permission_scope,
                })
            task.last_request_id = str(getattr(ctx, "request_id", None) or run.request_id)
            if self.turn_service is not None:
                commit = await self.turn_service.execute_context("scheduler", ctx)
                result = commit.result
            elif self.allow_legacy_pipeline:
                commit = None
                result = await self.pipeline.run(ctx)
            else:
                raise RuntimeError("TurnService is required for semantic scheduler execution")
            terminal_status = str(getattr(commit, "outcome", "completed") if commit is not None else "completed")
            task.last_status = "ok" if terminal_status == "completed" else terminal_status
            task.last_request_id = str(getattr(ctx, "request_id", None) or run.request_id)
            task.last_run_summary = str(getattr(result, "reply", "") or "")[:160] or None
            if commit is None:
                try:
                    from .context import get_runtime_bindings
                    bindings = get_runtime_bindings(ctx)
                except Exception:
                    bindings = None
                relationship_writer = bindings.relationship_event_writer if bindings is not None else None
                if relationship_writer:
                    relationship_writer(build_task_completed_event(
                        task_name=task.name,
                        task_id=task.id,
                        task_mode=task.mode,
                        owner_agent_id=task.owner_agent_id,
                        owner_agent_role=task.owner_agent_role,
                        session_id=getattr(ctx, "session_id", None),
                    ))
                trace_store = getattr(ctx, "trace_store", None)
                if trace_store is not None:
                    trace_store.append("scheduler", SchedulerRunRecord(
                        timestamp=datetime.now().isoformat(),
                        task_id=task.id,
                        task_name=task.name,
                        mode=task.mode,
                        status="ok",
                        run_id=run.run_id,
                        job_id=run.job_id,
                        summary=task.last_run_summary,
                        request_id=getattr(ctx, "request_id", None) or run.request_id,
                        owner_agent_id=task.owner_agent_id,
                        owner_agent_role=task.owner_agent_role,
                        route_reason=task.route_reason,
                    ).to_dict())
            result_failure = getattr(result, "failure", None)
            result_recovery = getattr(result, "recovery", None)
            commit_fields = ({
                "idempotencyKey": commit.idempotency_key,
                "semanticFingerprint": commit.semantic_fingerprint,
                "turnStage": "committed",
                "outcome": commit.outcome,
                "generationId": commit.context.generation_id,
                **({"failure": dict(result_failure)} if isinstance(result_failure, dict) else {}),
                **({"recovery": dict(result_recovery)} if isinstance(result_recovery, dict) else {}),
            } if commit is not None else {"turnStage": "legacy"})
            if commit is None:
                self._emit_event(
                    run,
                    task,
                    "completed",
                    summary=task.last_run_summary,
                    **commit_fields,
                )
            else:
                self._apply_authoritative_result(run, task, result)
            terminal_emitted = True
        except asyncio.CancelledError:
            task.last_status = "cancelled"
            task.last_request_id = run.request_id
            task.last_run_summary = "cancelled"
            durable_commit = await self._load_durable_commit(ctx) if uses_turn_authority else None
            if durable_commit is not None:
                self._reconcile_durable_commit(run, task, durable_commit)
            else:
                self._emit_event(run, task, "cancelled", reason="cancelled")
            terminal_emitted = True
            raise
        except Exception as exc:
            task.last_status = f"error:{exc}"
            task.last_request_id = str(getattr(ctx, "request_id", None) or run.request_id) if ctx is not None else run.request_id
            task.last_run_summary = str(exc)
            trace_store = getattr(ctx, "trace_store", None) if ctx is not None else None
            if not uses_turn_authority and trace_store is not None:
                trace_store.append("scheduler", SchedulerRunRecord(
                    timestamp=datetime.now().isoformat(),
                    task_id=task.id,
                    task_name=task.name,
                    mode=task.mode,
                    status=f"error:{exc}",
                    run_id=run.run_id,
                    job_id=run.job_id,
                    summary=str(exc),
                    request_id=getattr(ctx, "request_id", None) or run.request_id,
                    owner_agent_id=task.owner_agent_id,
                    owner_agent_role=task.owner_agent_role,
                    route_reason=task.route_reason,
                ).to_dict())
            durable_commit = await self._load_durable_commit(ctx) if uses_turn_authority else None
            if durable_commit is not None:
                self._reconcile_durable_commit(run, task, durable_commit)
            else:
                self._emit_event(run, task, "failed", error=str(exc))
            terminal_emitted = True
        finally:
            self._active_task_ids.discard(task.id)
            self._runs_by_task.pop(task.id, None)
            task.last_run_at = time.time()
            if task.mode == "once":
                task.enabled = False
                task.next_run_at = None
            elif task.interval_seconds:
                task.next_run_at = time.time() + task.interval_seconds
            if task.id in self.store.tasks:
                await self._upsert_task(task)
            if not terminal_emitted:
                self._emit_event(run, task, "failed", error="run terminated without a terminal status")
            self._trim_run_history()
