from __future__ import annotations

import asyncio
from datetime import datetime
import time
import uuid
from typing import Callable
import logging

from .context import AgentRequestContext
from .pipeline import AgentPipeline
from .models import SchedulerRunRecord
from .route_policy import resolve_schedule_route
from .schedule_store import ScheduleStore, ScheduledTask
from ..system.memory_write_pipeline import build_task_completed_event

logger = logging.getLogger(__name__)


class AgentScheduler:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        pipeline: AgentPipeline,
        context_factory: Callable[[ScheduledTask], AgentRequestContext],
        interval_seconds: float = 1.0,
    ) -> None:
        self.store = store
        self.pipeline = pipeline
        self.context_factory = context_factory
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._active_task_ids: set[str] = set()
        self._background_runs: set[asyncio.Task[None]] = set()
        self._store_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="agent-scheduler")

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
        return await self._upsert_task(task)

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
        return await self._upsert_task(task)

    async def remove_task(self, task_id: str) -> None:
        await self._remove_task(task_id)

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

            return await asyncio.to_thread(_set_enabled)

    async def run_now(self, task_id: str) -> ScheduledTask | None:
        async with self._store_lock:
            task = self.store.tasks.get(task_id)
            if task is None:
                return None
        if task.id in self._active_task_ids:
            return task
        task.last_status = "queued"
        await self._upsert_task(task)
        background_run = asyncio.create_task(self._run_task(task), name=f"agent-scheduler-run-{task.id}")
        self._background_runs.add(background_run)
        background_run.add_done_callback(self._log_background_run_error)
        return task

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

    async def _loop(self) -> None:
        while self._running:
            now = time.time()
            for task in list(self.store.list()):
                if not task.enabled or task.next_run_at is None or task.next_run_at > now:
                    continue
                await self._run_task(task)
            await asyncio.sleep(self.interval_seconds)

    async def _run_task(self, task: ScheduledTask) -> None:
        if task.id in self._active_task_ids:
            return
        self._active_task_ids.add(task.id)
        ctx: AgentRequestContext | None = None
        try:
            ctx = self.context_factory(task)
            result = await self.pipeline.run(ctx)
            task.last_status = "ok"
            task.last_request_id = getattr(ctx, "request_id", None)
            task.last_run_summary = str(getattr(result, "reply", "") or "")[:160] or None
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
            if ctx.trace_store is not None:
                ctx.trace_store.append("scheduler", SchedulerRunRecord(
                    timestamp=datetime.now().isoformat(),
                    task_id=task.id,
                    task_name=task.name,
                    mode=task.mode,
                    status="ok",
                    summary=task.last_run_summary,
                    request_id=ctx.request_id,
                    owner_agent_id=task.owner_agent_id,
                    owner_agent_role=task.owner_agent_role,
                    route_reason=task.route_reason,
                ).to_dict())
        except Exception as exc:
            task.last_status = f"error:{exc}"
            task.last_request_id = getattr(ctx, "request_id", None) if ctx is not None else None
            task.last_run_summary = str(exc)
            if ctx is not None and ctx.trace_store is not None:
                ctx.trace_store.append("scheduler", SchedulerRunRecord(
                    timestamp=datetime.now().isoformat(),
                    task_id=task.id,
                    task_name=task.name,
                    mode=task.mode,
                    status=f"error:{exc}",
                    summary=str(exc),
                    request_id=ctx.request_id,
                    owner_agent_id=task.owner_agent_id,
                    owner_agent_role=task.owner_agent_role,
                    route_reason=task.route_reason,
                ).to_dict())
        finally:
            self._active_task_ids.discard(task.id)
            task.last_run_at = time.time()
            if task.mode == "once":
                task.enabled = False
                task.next_run_at = None
            elif task.interval_seconds:
                task.next_run_at = time.time() + task.interval_seconds
            await self._upsert_task(task)
