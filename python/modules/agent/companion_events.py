from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from typing import Any


_EVENT_TYPES = {
    "created": "AgentJobCreated",
    "running": "AgentJobRunning",
    "progress": "AgentJobProgress",
    "completed": "AgentJobCompleted",
    "failed": "AgentJobFailed",
    "cancelled": "AgentJobCancelled",
    "interrupted": "AgentJobInterrupted",
}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class CompanionJobCapacityError(RuntimeError):
    """Raised when a bounded event log cannot admit a job without losing active state."""


class CompanionJobEventLog:
    """Bounded, replayable job events for the renderer runtime snapshot."""

    def __init__(self, max_jobs: int = 256) -> None:
        self.max_jobs = max(1, int(max_jobs))
        self._events: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        self._terminal_jobs: set[str] = set()
        self._last_progress_at: dict[str, float] = {}
        self._lock = Lock()

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
    ) -> dict[str, Any]:
        normalized_step_index = None if step_index is None else max(0, int(step_index))
        with self._lock:
            if status not in _EVENT_TYPES:
                raise ValueError(f"unknown companion job status: {status}")
            events = self._events.get(job_id)
            if events is None:
                if not self._evict_terminal_job_if_needed():
                    raise CompanionJobCapacityError("companion job event log is full of active jobs")
                events = []
                self._events[job_id] = events
            if events:
                previous = events[-1]
                if previous["status"] in _TERMINAL_STATUSES:
                    raise ValueError(f"terminal companion job cannot transition: {job_id}")
                normalized_timestamp = max(0.0, float(timestamp))
                if status == "progress" and previous["status"] == "progress":
                    last_progress_at = self._last_progress_at.get(job_id)
                    if last_progress_at is not None and normalized_timestamp - last_progress_at < 0.1:
                        previous["timestamp"] = normalized_timestamp * 1000
                        if data:
                            previous["data"] = deepcopy(data)
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
                "revision": len(events) + 1,
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
            if status == "progress":
                self._last_progress_at[job_id] = max(0.0, float(timestamp))
            else:
                self._last_progress_at.pop(job_id, None)
            self._events.move_to_end(job_id)
            if status in _TERMINAL_STATUSES:
                self._terminal_jobs.add(job_id)
            return deepcopy(event)

    def _evict_terminal_job_if_needed(self) -> bool:
        if len(self._events) < self.max_jobs:
            return True
        terminal_id = next((job_id for job_id in self._events if job_id in self._terminal_jobs), None)
        if terminal_id is None:
            return False
        self._events.pop(terminal_id, None)
        self._terminal_jobs.discard(terminal_id)
        self._last_progress_at.pop(terminal_id, None)
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(event) for events in self._events.values() for event in events]

    def active_job_ids(self) -> list[str]:
        with self._lock:
            return [job_id for job_id in self._events if job_id not in self._terminal_jobs]

    def contains(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._events

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._events and job_id not in self._terminal_jobs
