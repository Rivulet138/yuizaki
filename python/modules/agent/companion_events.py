from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_TYPES = {
    "created": "AgentJobCreated",
    "running": "AgentJobRunning",
    "progress": "AgentJobProgress",
    "completed": "AgentJobCompleted",
    "failed": "AgentJobFailed",
    "cancelled": "AgentJobCancelled",
    "interrupted": "AgentJobInterrupted",
    "unknown_effect": "AgentJobUnknownEffect",
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted", "unknown_effect"}

_PRESENTATION_TERMINAL_TYPES = {
    "completed", "failed", "cancelled", "interrupted",
    "agentjobcompleted", "agentjobfailed", "agentjobcancelled", "agentjobinterrupted",
    "agentjobunknowneffect", "terminal", "turncompleted", "turnfailed", "turncancelled",
}
_HIGH_FREQUENCY_EVENT_MARKERS = {
    "token", "tokens", "audio", "audiochunk", "audiobuffer", "frame",
    "avatarframe", "viseme", "speechpartial", "partialtranscript", "streamchunk",
}
_LIFECYCLE_EVENT_SUFFIXES = ("started", "completed", "failed", "cancelled", "interrupted")
_JOB_STATUS_TO_PRESENTATION_TYPE = {
    status: event_type for status, event_type in _EVENT_TYPES.items()
}


class CompanionJobCapacityError(RuntimeError):
    """Raised when a bounded event log cannot admit a job without losing active state."""


class CompanionPresentationCapacityError(RuntimeError):
    """Raised when a presentation stream cannot be admitted safely."""


class CompanionPresentationStaleEventError(ValueError):
    """Raised for an out-of-order or stale presentation event."""


class CompanionPresentationTerminalError(ValueError):
    """Raised when a terminal presentation stream receives another event."""


def _compact_event_name(value: Any) -> str:
    return "".join(character for character in str(value or "").lower() if character.isalnum())


def _is_high_frequency_event(value: Any) -> bool:
    compact = _compact_event_name(value)
    if compact.endswith(_LIFECYCLE_EVENT_SUFFIXES):
        return False
    return any(marker in compact for marker in _HIGH_FREQUENCY_EVENT_MARKERS)


def _int_or_default(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class CompanionPresentationEvent:
    """Versioned, low-frequency projection consumed by companion presentation."""

    stream_id: str
    event_type: str
    revision: int
    workspace_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    request_id: str | None = None
    conversation_id: str | None = None
    operation_id: str | None = None
    run_id: str | None = None
    step_index: int | None = None
    generation_id: str | None = None
    interruption_epoch: int = 0
    source: str = "agent"
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    @property
    def terminal(self) -> bool:
        normalized = _compact_event_name(self.event_type)
        return normalized in _PRESENTATION_TERMINAL_TYPES or normalized.endswith(
            ("completed", "failed", "cancelled", "interrupted")
        )

    def identity(self) -> tuple[Any, ...]:
        return (
            self.stream_id,
            self.workspace_id,
            self.session_id,
            self.turn_id,
            self.request_id,
            self.conversation_id,
            self.operation_id,
            self.run_id,
            self.step_index,
            self.generation_id,
            max(0, int(self.interruption_epoch)),
            self.source,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "version": self.version,
            "schemaVersion": "yuizaki.companion-presentation.v1",
            "streamId": self.stream_id,
            "type": self.event_type,
            "revision": self.revision,
            "workspaceId": self.workspace_id,
            "sessionId": self.session_id,
            "turnId": self.turn_id,
            "interruptionEpoch": max(0, int(self.interruption_epoch)),
            "source": self.source,
            "terminal": self.terminal,
            "payload": deepcopy(self.payload),
        }
        if self.generation_id:
            data["generationId"] = self.generation_id
        if self.request_id:
            data["requestId"] = self.request_id
        if self.conversation_id:
            data["conversationId"] = self.conversation_id
        if self.operation_id:
            data["operationId"] = self.operation_id
        if self.run_id:
            data["runId"] = self.run_id
        if self.step_index is not None:
            data["stepIndex"] = max(0, int(self.step_index))
        return data


class CompanionPresentationReducer:
    """Pure reducer for one presentation stream's ordered event projection."""

    def reduce(
        self,
        previous: CompanionPresentationEvent | None,
        event: CompanionPresentationEvent,
    ) -> CompanionPresentationEvent:
        if _is_high_frequency_event(event.event_type):
            raise CompanionPresentationStaleEventError("high-frequency presentation events are not retained")
        if event.version != 1:
            raise ValueError(f"unsupported presentation event version: {event.version}")
        if event.revision < 1:
            raise CompanionPresentationStaleEventError("presentation revision must be positive")
        if previous is None:
            if event.revision != 1:
                raise CompanionPresentationStaleEventError("presentation stream must start at revision 1")
            return event
        if previous.identity() != event.identity():
            raise ValueError(f"presentation stream identity changed: {event.stream_id}")
        if previous.terminal:
            raise CompanionPresentationTerminalError(f"terminal presentation stream cannot transition: {event.stream_id}")
        if event.revision <= previous.revision:
            raise CompanionPresentationStaleEventError(
                f"stale presentation revision for {event.stream_id}: {event.revision} <= {previous.revision}"
            )
        if event.revision != previous.revision + 1:
            raise CompanionPresentationStaleEventError(
                f"presentation revision gap for {event.stream_id}: expected {previous.revision + 1}, got {event.revision}"
            )
        return event


class CompanionPresentationEventLog:
    """Bounded ordered log for low-frequency companion presentation events."""

    def __init__(self, max_streams: int = 256, reducer: CompanionPresentationReducer | None = None) -> None:
        self.max_streams = max(1, int(max_streams))
        self.reducer = reducer or CompanionPresentationReducer()
        self._events: OrderedDict[str, list[CompanionPresentationEvent]] = OrderedDict()
        self._terminal_streams: set[str] = set()
        self._lock = Lock()

    def append_event(self, event: CompanionPresentationEvent) -> dict[str, Any] | None:
        if _is_high_frequency_event(event.event_type):
            return None
        with self._lock:
            events = self._events.get(event.stream_id)
            new_stream = events is None
            if events is None:
                # Validate a first revision before evicting any retained
                # terminal stream; malformed input must have no side effect.
                accepted = self.reducer.reduce(None, event)
                if len(self._events) >= self.max_streams and not self._evict_terminal_stream():
                    raise CompanionPresentationCapacityError("companion presentation log is full of active streams")
                events = []
            previous = events[-1] if events else None
            if previous is not None and event.revision == previous.revision:
                if previous.to_dict() == event.to_dict():
                    return {**previous.to_dict(), "duplicate": True}
                raise CompanionPresentationStaleEventError(
                    f"conflicting duplicate presentation revision: {event.stream_id}:{event.revision}"
                )
            accepted = self.reducer.reduce(previous, event)
            if new_stream:
                self._events[event.stream_id] = events
            events.append(accepted)
            self._events.move_to_end(event.stream_id)
            if accepted.terminal:
                self._terminal_streams.add(event.stream_id)
            return accepted.to_dict()

    def append(
        self,
        event: CompanionPresentationEvent | None = None,
        *,
        stream_id: str | None = None,
        event_type: str | None = None,
        revision: int | None = None,
        workspace_id: str = "",
        session_id: str = "",
        turn_id: str = "",
        request_id: str | None = None,
        conversation_id: str | None = None,
        operation_id: str | None = None,
        run_id: str | None = None,
        step_index: int | None = None,
        generation_id: str | None = None,
        interruption_epoch: int = 0,
        source: str = "agent",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if event is None:
            if not stream_id or not event_type:
                raise ValueError("stream_id and event_type are required")
            with self._lock:
                current = self._events.get(stream_id)
                next_revision = (current[-1].revision + 1) if current else 1
            event = CompanionPresentationEvent(
                stream_id=stream_id,
                event_type=event_type,
                revision=next_revision if revision is None else int(revision),
                workspace_id=workspace_id,
                session_id=session_id,
                turn_id=turn_id,
                request_id=request_id,
                conversation_id=conversation_id,
                operation_id=operation_id,
                run_id=run_id,
                step_index=step_index,
                generation_id=generation_id,
                interruption_epoch=interruption_epoch,
                source=source,
                payload=dict(payload or {}),
            )
        return self.append_event(event)

    def _evict_terminal_stream(self) -> bool:
        stream_id = next((item for item in self._events if item in self._terminal_streams), None)
        if stream_id is None:
            return False
        self._events.pop(stream_id, None)
        self._terminal_streams.discard(stream_id)
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for events in self._events.values() for event in events]

    def contains(self, stream_id: str) -> bool:
        with self._lock:
            return stream_id in self._events

    def active_stream_ids(self) -> list[str]:
        with self._lock:
            return [stream_id for stream_id in self._events if stream_id not in self._terminal_streams]


def adapt_job_event(event: Mapping[str, Any]) -> CompanionPresentationEvent | None:
    """Adapt an existing ``CompanionJobEventLog`` envelope into presentation form."""
    raw_type = event.get("type")
    status = str(event.get("status") or "").strip().lower()
    if _is_high_frequency_event(raw_type) or _is_high_frequency_event(status):
        return None
    event_type = _JOB_STATUS_TO_PRESENTATION_TYPE.get(status) or str(raw_type or "")
    stream_id = str(event.get("streamId") or event.get("stream_id") or event.get("jobId") or "").strip()
    if not stream_id or not event_type:
        return None
    return CompanionPresentationEvent(
        stream_id=stream_id,
        event_type=event_type,
        revision=_int_or_default(event.get("revision"), 1),
        workspace_id=str(event.get("workspaceId") or event.get("workspace_id") or ""),
        session_id=str(event.get("sessionId") or event.get("session_id") or ""),
        turn_id=str(event.get("turnId") or event.get("turn_id") or ""),
        request_id=event.get("requestId") or event.get("request_id"),
        conversation_id=event.get("conversationId") or event.get("conversation_id"),
        operation_id=event.get("operationId") or event.get("operation_id"),
        run_id=event.get("runId") or event.get("run_id"),
        step_index=(
            _int_or_default(event.get("stepIndex") if event.get("stepIndex") is not None else event.get("step_index"))
            if event.get("stepIndex") is not None or event.get("step_index") is not None
            else None
        ),
        generation_id=event.get("generationId") or event.get("generation_id"),
        interruption_epoch=_int_or_default(event.get("interruptionEpoch") or event.get("interruption_epoch")),
        source=str(event.get("source") or "job"),
        payload=dict(event.get("data") or {}),
    )


class CompanionJobEventAdapter:
    """Compatibility adapter that projects job-log envelopes into a presentation log."""

    def __init__(self, presentation_log: CompanionPresentationEventLog) -> None:
        self.presentation_log = presentation_log

    def append(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        adapted = adapt_job_event(event)
        return self.presentation_log.append_event(adapted) if adapted is not None else None


class CompanionJobEventLog:
    """Bounded, replayable job events for the renderer runtime snapshot."""

    def __init__(
        self,
        max_jobs: int = 256,
        max_events_per_job: int = 64,
        presentation_log: CompanionPresentationEventLog | None = None,
    ) -> None:
        self.max_jobs = max(1, int(max_jobs))
        self.max_events_per_job = max(2, int(max_events_per_job))
        self.presentation_log = presentation_log
        self._events: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._terminal_jobs: set[str] = set()
        self._last_progress_at: dict[str, float] = {}
        self._next_revision: dict[str, int] = {}
        self._projection_events: dict[str, dict[str, Any]] = {}
        self._projection_keys_by_job: dict[str, OrderedDict[str, None]] = {}
        self._lock = Lock()

    @staticmethod
    def _scope_key(workspace_id: str, job_id: str) -> str:
        return f"{workspace_id}\x00{job_id}"

    def _storage_key(self, workspace_id: str, job_id: str) -> str:
        matches = [
            (key, events)
            for key, events in self._events.items()
            if events and events[-1].get("jobId") == job_id
        ]
        for key, events in matches:
            if events[-1].get("workspaceId") == workspace_id:
                return key
        if not matches:
            # Preserve the established single-workspace private key shape.
            return job_id
        direct = self._events.pop(job_id, None)
        if direct:
            existing_workspace = str(direct[-1].get("workspaceId") or "")
            existing_key = self._scope_key(existing_workspace, job_id)
            self._events[existing_key] = direct
            if job_id in self._terminal_jobs:
                self._terminal_jobs.discard(job_id)
                self._terminal_jobs.add(existing_key)
            if job_id in self._last_progress_at:
                self._last_progress_at[existing_key] = self._last_progress_at.pop(job_id)
            if job_id in self._next_revision:
                self._next_revision[existing_key] = self._next_revision.pop(job_id)
            if job_id in self._projection_keys_by_job:
                self._projection_keys_by_job[existing_key] = self._projection_keys_by_job.pop(job_id)
        return self._scope_key(workspace_id, job_id)

    def _remember_projection(
        self,
        scoped_job_id: str,
        projection_key: str,
        event: dict[str, Any],
    ) -> None:
        self._projection_events[projection_key] = deepcopy(event)
        job_keys = self._projection_keys_by_job.setdefault(scoped_job_id, OrderedDict())
        job_keys[projection_key] = None
        job_keys.move_to_end(projection_key)
        while len(job_keys) > self.max_events_per_job:
            expired_key, _ = job_keys.popitem(last=False)
            self._projection_events.pop(expired_key, None)

    def _trim_job_events(self, events: list[dict[str, Any]]) -> None:
        overflow = len(events) - self.max_events_per_job
        if overflow <= 0:
            return
        # The first event anchors identity; the newest events preserve current
        # state and the authoritative terminal when one has been appended.
        del events[1:overflow + 1]

    def append(
        self,
        *,
        workspace_id: str,
        session_id: str,
        turn_id: str,
        job_id: str,
        conversation_id: str | None = None,
        operation_id: str | None = None,
        step_index: int | None = None,
        run_id: str | None = None,
        request_id: str,
        interruption_epoch: int,
        source: str,
        timestamp: float,
        status: str,
        data: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        normalized_step_index = None if step_index is None else max(0, int(step_index))
        projection_key = str(idempotency_key or "").strip() or None
        with self._lock:
            scoped_job_id = self._storage_key(workspace_id, job_id)
            if projection_key is not None and projection_key in self._projection_events:
                return {**deepcopy(self._projection_events[projection_key]), "duplicate": True}
            if status not in _EVENT_TYPES:
                raise ValueError(f"unknown companion job status: {status}")
            events = self._events.get(scoped_job_id)
            if events is None:
                if not self._evict_terminal_job_if_needed():
                    raise CompanionJobCapacityError("companion job event log is full of active jobs")
                events = []
                self._events[scoped_job_id] = events
            if events:
                previous = events[-1]
                is_recheck = bool(data and data.get("recheck") is True)
                if previous["status"] in _TERMINAL_STATUSES and not (is_recheck and status == "completed"):
                    raise ValueError(f"terminal companion job cannot transition: {job_id}")
                if is_recheck:
                    data = {**dict(previous.get("data") or {}), **dict(data or {})}
                normalized_timestamp = max(0.0, float(timestamp))
                if status == "progress" and previous["status"] == "progress":
                    last_progress_at = self._last_progress_at.get(scoped_job_id)
                    if last_progress_at is not None and normalized_timestamp - last_progress_at < 0.1:
                        previous["timestamp"] = normalized_timestamp * 1000
                        if data:
                            previous["data"] = deepcopy(data)
                        if projection_key is not None:
                            self._remember_projection(scoped_job_id, projection_key, previous)
                        return deepcopy(previous)
                if status == "created":
                    raise ValueError(f"invalid companion job transition: {previous['status']} -> created")
                if any(previous.get(field) != value for field, value in (
                    ("workspaceId", workspace_id), ("sessionId", session_id),
                    ("turnId", turn_id), ("requestId", request_id),
                    ("conversationId", conversation_id), ("operationId", operation_id),
                    ("stepIndex", normalized_step_index),
                    ("runId", run_id), ("interruptionEpoch", max(0, int(interruption_epoch))),
                    ("source", source),
                )):
                    raise ValueError(f"companion job identity changed: {job_id}")
            event = {
                "version": 1,
                "type": _EVENT_TYPES[status],
                "workspaceId": workspace_id,
                "sessionId": session_id,
                "turnId": turn_id,
                "jobId": job_id,
                "requestId": request_id,
                "revision": self._next_revision.get(scoped_job_id, 1),
                "interruptionEpoch": max(0, int(interruption_epoch)),
                "source": source,
                "timestamp": max(0.0, float(timestamp)) * 1000,
                "status": status,
            }
            if conversation_id:
                event["conversationId"] = conversation_id
            if operation_id:
                event["operationId"] = operation_id
            if normalized_step_index is not None:
                event["stepIndex"] = normalized_step_index
            if run_id:
                event["runId"] = run_id
            if data:
                event["data"] = deepcopy(data)
            events.append(event)
            self._next_revision[scoped_job_id] = int(event["revision"]) + 1
            self._trim_job_events(events)
            if status == "progress":
                self._last_progress_at[scoped_job_id] = max(0.0, float(timestamp))
            else:
                self._last_progress_at.pop(scoped_job_id, None)
            self._events.move_to_end(scoped_job_id)
            if status in _TERMINAL_STATUSES:
                self._terminal_jobs.add(scoped_job_id)
            if self.presentation_log is not None and not (data and data.get("recheck") is True):
                # Presentation is a projection. A projection outage or full
                # presentation buffer must never change the established job
                # log's accepted event, capacity, or transition semantics.
                try:
                    presentation_event = adapt_job_event(event)
                    if presentation_event is not None:
                        self.presentation_log.append_event(presentation_event)
                except Exception:
                    logger.exception(
                        "Companion presentation projection failed for job %s revision %s",
                        job_id,
                        event["revision"],
                    )
            if projection_key is not None:
                self._remember_projection(scoped_job_id, projection_key, event)
            return deepcopy(event)

    def _evict_terminal_job_if_needed(self) -> bool:
        if len(self._events) < self.max_jobs:
            return True
        scoped_job_id = next((job_id for job_id in self._events if job_id in self._terminal_jobs), None)
        if scoped_job_id is None:
            return False
        self._events.pop(scoped_job_id, None)
        self._terminal_jobs.discard(scoped_job_id)
        self._last_progress_at.pop(scoped_job_id, None)
        self._next_revision.pop(scoped_job_id, None)
        for projection_key in self._projection_keys_by_job.pop(scoped_job_id, {}):
            self._projection_events.pop(projection_key, None)
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(event) for events in self._events.values() for event in events]

    def latest(self, job_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
        """Return the authoritative latest event for one scoped job."""
        with self._lock:
            for events in self._events.values():
                if not events or events[-1]["jobId"] != job_id:
                    continue
                if workspace_id is not None and events[-1]["workspaceId"] != workspace_id:
                    continue
                return deepcopy(events[-1])
        return None

    def append_recheck(
        self,
        *,
        job_id: str,
        workspace_id: str,
        timestamp: float,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Append verification evidence while preserving the original job identity."""
        latest = self.latest(job_id, workspace_id)
        if latest is None:
            raise LookupError(f"companion job not found: {job_id}")
        return self.append(
            workspace_id=str(latest["workspaceId"]),
            session_id=str(latest["sessionId"]),
            turn_id=str(latest["turnId"]),
            job_id=job_id,
            conversation_id=latest.get("conversationId"),
            operation_id=latest.get("operationId"),
            step_index=latest.get("stepIndex"),
            run_id=latest.get("runId"),
            request_id=str(latest["requestId"]),
            interruption_epoch=int(latest.get("interruptionEpoch") or 0),
            source=str(latest["source"]),
            timestamp=timestamp,
            status="completed",
            data={**data, "recheck": True},
        )

    def active_job_ids(self) -> list[str]:
        with self._lock:
            return [
                str(events[-1]["jobId"])
                for scoped_job_id, events in self._events.items()
                if scoped_job_id not in self._terminal_jobs and events
            ]

    def contains(self, job_id: str, workspace_id: str | None = None) -> bool:
        with self._lock:
            if workspace_id is not None:
                return any(
                    events
                    and events[-1]["jobId"] == job_id
                    and events[-1]["workspaceId"] == workspace_id
                    for events in self._events.values()
                )
            return any(events and events[-1]["jobId"] == job_id for events in self._events.values())

    def is_active(self, job_id: str, workspace_id: str | None = None) -> bool:
        with self._lock:
            if workspace_id is not None:
                return any(
                    scoped_job_id not in self._terminal_jobs
                    and events
                    and events[-1]["jobId"] == job_id
                    and events[-1]["workspaceId"] == workspace_id
                    for scoped_job_id, events in self._events.items()
                )
            return any(
                scoped_job_id not in self._terminal_jobs
                and events
                and events[-1]["jobId"] == job_id
                for scoped_job_id, events in self._events.items()
            )
