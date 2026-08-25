"""Workspace-scoped dependency injection for semantic agent turns.

The registry deliberately owns references, while a ``RuntimeContext`` is an
immutable snapshot.  A hot reload therefore swaps one complete snapshot
atomically; in-flight turns keep the snapshot they already captured.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Iterator

RuntimeDisposer = Callable[[], Any | Awaitable[Any]]
_RELEASE_BINDING = "_runtime_context_release"


class RuntimeContextError(RuntimeError):
    """Base error for invalid runtime context operations."""


class RuntimeContextNotFoundError(RuntimeContextError):
    pass


class RuntimeContextConflictError(RuntimeContextError):
    pass


@dataclass(frozen=True)
class RuntimeContext:
    """A complete dependency snapshot for one workspace.

    Optional services remain optional so text chat can continue when voice,
    OCR, or perception providers are unavailable.  ``revision`` changes on
    every registration/swap and is suitable for diagnostics and cache keys.
    """

    workspace_id: str
    revision: int = 0
    context_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    db_repo: Any | None = None
    relationship_event_writer: Callable[[dict[str, Any]], Any] | None = None
    relationship_history_provider: Callable[[], Any] | None = None
    relationship_summary_provider: Callable[[], Any] | None = None
    llm_client: Any | None = None
    vision_llm_client: Any | None = None
    tts_client: Any | None = None
    asr_manager: Any | None = None
    ocr_client: Any | None = None
    tool_registry: Any | None = None
    tool_executor: Any | None = None
    step_executor: Any | None = None
    turn_service: Any | None = None
    perception: Any | None = None
    disposer: RuntimeDisposer | None = field(default=None, repr=False, compare=False)
    extras: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        workspace_id = str(self.workspace_id or "").strip()
        if not workspace_id:
            raise ValueError("workspace_id is required")
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "extras", dict(self.extras))

    def with_revision(self, revision: int) -> "RuntimeContext":
        if revision < 1:
            raise ValueError("revision must be positive")
        return replace(
            self,
            revision=revision,
            context_id=uuid.uuid4().hex,
            created_at=time.time(),
        )

    def request_bindings(self) -> dict[str, Any]:
        """Return a shallow binding map suitable for ``AgentRequestContext.extra``."""
        return {
            "runtime_context": self,
            "runtime_revision": self.revision,
            "workspace_id": self.workspace_id,
            "db_repo": self.db_repo,
            "relationship_event_writer": self.relationship_event_writer,
            "relationship_history": self.relationship_history_provider() if self.relationship_history_provider else [],
            "relationship_summary": self.relationship_summary_provider() if self.relationship_summary_provider else {},
            "perception": self.perception,
            **dict(self.extras),
        }


class RuntimeContextRegistry:
    """Thread-safe atomic registry with workspace isolation and hot reload."""

    def __init__(self, contexts: Mapping[str, RuntimeContext] | None = None) -> None:
        self._lock = threading.RLock()
        self._contexts: dict[str, RuntimeContext] = {}
        self._leases: dict[str, int] = {}
        self._retired: dict[str, RuntimeContext] = {}
        self._disposing: set[str] = set()
        self._disposal_tasks: set[asyncio.Task[Any]] = set()
        self._revision = 0
        for context in (contexts or {}).values():
            self.register(context)

    def register(self, context: RuntimeContext, *, expected_revision: int | None = None) -> RuntimeContext:
        return self._swap(context, expected_revision=expected_revision, require_existing=False)

    def swap(self, context: RuntimeContext, *, expected_revision: int | None = None) -> RuntimeContext:
        return self._swap(context, expected_revision=expected_revision, require_existing=True)

    def _swap(self, context: RuntimeContext, *, expected_revision: int | None, require_existing: bool) -> RuntimeContext:
        if not isinstance(context, RuntimeContext):
            raise TypeError("context must be RuntimeContext")
        with self._lock:
            current = self._contexts.get(context.workspace_id)
            if require_existing and current is None:
                raise RuntimeContextNotFoundError(context.workspace_id)
            if expected_revision is not None and (current is None or current.revision != expected_revision):
                raise RuntimeContextConflictError(
                    f"workspace {context.workspace_id!r} revision changed (expected {expected_revision})"
                )
            self._revision += 1
            committed = context.with_revision(self._revision)
            self._contexts[committed.workspace_id] = committed
            if current is not None:
                self._retired[current.context_id] = current
            retired = self._take_disposable_locked(current)
        self._start_disposal(retired)
        return committed

    def get(self, workspace_id: str | None) -> RuntimeContext | None:
        key = str(workspace_id or "").strip()
        with self._lock:
            return self._contexts.get(key)

    def require(self, workspace_id: str | None) -> RuntimeContext:
        context = self.get(workspace_id)
        if context is None:
            raise RuntimeContextNotFoundError(str(workspace_id or ""))
        return context

    def remove(self, workspace_id: str, *, expected_revision: int | None = None) -> RuntimeContext | None:
        with self._lock:
            context = self._contexts.get(str(workspace_id or "").strip())
            if context is None:
                return None
            if expected_revision is not None and context.revision != expected_revision:
                raise RuntimeContextConflictError(f"workspace {workspace_id!r} revision changed")
            removed = self._contexts.pop(context.workspace_id)
            self._retired[removed.context_id] = removed
            retired = self._take_disposable_locked(removed)
        self._start_disposal(retired)
        return removed

    def snapshot(self) -> dict[str, RuntimeContext]:
        with self._lock:
            return dict(self._contexts)

    def bind_request(self, request_context: Any, workspace_id: str | None = None) -> Any:
        """Bind an immutable snapshot to an existing AgentRequestContext."""
        workspace = workspace_id or getattr(request_context, "workspace_id", None)
        context = self._acquire(workspace)
        if hasattr(request_context, "workspace_id") and not request_context.workspace_id:
            request_context.workspace_id = context.workspace_id
        extra = getattr(request_context, "extra", None)
        if not isinstance(extra, dict):
            self._release_without_wait(context)
            raise TypeError("request_context.extra must be a dict")
        try:
            bindings = context.request_bindings()
            request_context.runtime_context = context
            extra.update(bindings)
            extra[_RELEASE_BINDING] = lambda: self.release(context)
        except Exception:
            self._release_without_wait(context)
            raise
        return request_context

    def _acquire(self, workspace_id: str | None) -> RuntimeContext:
        key = str(workspace_id or "").strip()
        with self._lock:
            context = self._contexts.get(key)
            if context is None:
                raise RuntimeContextNotFoundError(key)
            self._leases[context.context_id] = self._leases.get(context.context_id, 0) + 1
            return context

    async def release(self, context: RuntimeContext) -> None:
        retired = self._release_locked(context)
        await self._dispose(retired)

    def _release_without_wait(self, context: RuntimeContext) -> None:
        retired = self._release_locked(context)
        self._start_disposal(retired)

    def _release_locked(self, context: RuntimeContext) -> RuntimeContext | None:
        with self._lock:
            count = self._leases.get(context.context_id, 0)
            if count <= 0:
                return None
            if count == 1:
                self._leases.pop(context.context_id, None)
            else:
                self._leases[context.context_id] = count - 1
            return self._take_disposable_locked(context)

    def _take_disposable_locked(self, context: RuntimeContext | None) -> RuntimeContext | None:
        if context is None or context.context_id not in self._retired:
            return None
        if self._leases.get(context.context_id, 0) > 0 or context.context_id in self._disposing:
            return None
        self._disposing.add(context.context_id)
        return self._retired.pop(context.context_id)

    async def _dispose(self, context: RuntimeContext | None) -> None:
        if context is None:
            return
        try:
            if context.disposer is not None:
                result = context.disposer()
                if inspect.isawaitable(result):
                    await result
        finally:
            with self._lock:
                self._disposing.discard(context.context_id)

    def _start_disposal(self, context: RuntimeContext | None) -> None:
        if context is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self._dispose(context))
            return
        task = loop.create_task(self._dispose(context), name=f"runtime-context-dispose:{context.context_id[:8]}")
        self._disposal_tasks.add(task)
        task.add_done_callback(self._disposal_tasks.discard)

    async def aclose(self) -> None:
        with self._lock:
            active = list(self._contexts.values())
            self._contexts.clear()
            for context in active:
                self._retired[context.context_id] = context
            disposable = [self._take_disposable_locked(context) for context in active]
            tasks = tuple(self._disposal_tasks)
        await asyncio.gather(*(self._dispose(context) for context in disposable), return_exceptions=False)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)

    @contextmanager
    def scoped(self, workspace_id: str | None) -> Iterator[RuntimeContext]:
        """Yield a stable snapshot for the duration of a turn."""
        context = self._acquire(workspace_id)
        try:
            yield context
        finally:
            self._release_without_wait(context)
