from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.paths import data_dir_from_env
from .models import (
    PlannerStepRecord,
    PlannerTrace,
    RuntimeLoopRecord,
    SchedulerRunRecord,
    StepConditionRecord,
    StepExecutionRecord,
)

logger = logging.getLogger(__name__)

TraceRecord = PlannerTrace | StepExecutionRecord | SchedulerRunRecord | RuntimeLoopRecord
TraceCoercer = Callable[[dict[str, Any]], TraceRecord]


def _coerce_planner(item: dict[str, Any]) -> PlannerTrace:
    steps_raw = item.get("steps")
    steps = [_coerce_planner_step(entry) for entry in steps_raw if isinstance(entry, dict)] if isinstance(steps_raw, list) else []
    return PlannerTrace(
        timestamp=str(item.get("timestamp") or ""),
        session_id=str(item.get("session_id") or ""),
        goal=str(item.get("goal") or ""),
        mode=str(item.get("mode") or ""),
        steps=steps,
        request_id=item.get("request_id") if item.get("request_id") is None else str(item.get("request_id")),
    )


def _coerce_condition(item: Any) -> StepConditionRecord | None:
    if not isinstance(item, dict):
        return None
    status_in = item.get("status_in")
    status_not_in = item.get("status_not_in")
    content_contains = item.get("content_contains")
    error_contains = item.get("error_contains")
    all_of = item.get("all_of")
    any_of = item.get("any_of")
    none_of = item.get("none_of")
    return StepConditionRecord(
        source_step_id=str(item.get("source_step_id") or ""),
        mode=str(item.get("mode") or "continue_if"),
        status_in=[str(value) for value in status_in] if isinstance(status_in, list) else [],
        status_not_in=[str(value) for value in status_not_in] if isinstance(status_not_in, list) else [],
        content_contains=[str(value) for value in content_contains] if isinstance(content_contains, list) else [],
        error_contains=[str(value) for value in error_contains] if isinstance(error_contains, list) else [],
        all_of=[coerced for value in all_of if (coerced := _coerce_condition(value)) is not None] if isinstance(all_of, list) else [],
        any_of=[coerced for value in any_of if (coerced := _coerce_condition(value)) is not None] if isinstance(any_of, list) else [],
        none_of=[coerced for value in none_of if (coerced := _coerce_condition(value)) is not None] if isinstance(none_of, list) else [],
    )


def _coerce_planner_step(item: dict[str, Any]) -> PlannerStepRecord:
    depends_on = item.get("depends_on")
    return PlannerStepRecord(
        id=str(item.get("id") or item.get("step_id") or ""),
        title=str(item.get("title") or ""),
        kind=str(item.get("kind") or ""),
        description=str(item.get("description") or ""),
        depends_on=[str(value) for value in depends_on] if isinstance(depends_on, list) else [],
        condition=_coerce_condition(item.get("condition")),
    )


def _coerce_step(item: dict[str, Any]) -> StepExecutionRecord:
    tool_calls_count = item.get("tool_calls_count")
    depends_on = item.get("depends_on")
    retry_count = item.get("retry_count")
    return StepExecutionRecord(
        timestamp=str(item.get("timestamp") or ""),
        kind=str(item.get("kind") or ""),
        status=str(item.get("status") or ""),
        step_id=item.get("step_id") if item.get("step_id") is None else str(item.get("step_id")),
        title=item.get("title") if item.get("title") is None else str(item.get("title")),
        depends_on=[str(value) for value in depends_on] if isinstance(depends_on, list) else None,
        condition=_coerce_condition(item.get("condition")),
        prompt=item.get("prompt") if item.get("prompt") is None else str(item.get("prompt")),
        tool=item.get("tool") if item.get("tool") is None else str(item.get("tool")),
        args=item.get("args") if isinstance(item.get("args"), dict) else None,
        success=item.get("success") if isinstance(item.get("success"), bool) else None,
        error=item.get("error") if item.get("error") is None else str(item.get("error")),
        task_id=item.get("task_id") if item.get("task_id") is None else str(item.get("task_id")),
        mode=item.get("mode") if item.get("mode") is None else str(item.get("mode")),
        reply_preview=item.get("reply_preview") if item.get("reply_preview") is None else str(item.get("reply_preview")),
        tool_calls_count=int(tool_calls_count) if isinstance(tool_calls_count, int) else None,
        has_pet_control=item.get("has_pet_control") if isinstance(item.get("has_pet_control"), bool) else None,
        retry_count=int(retry_count) if isinstance(retry_count, int) else None,
        rollback_status=item.get("rollback_status") if item.get("rollback_status") is None else str(item.get("rollback_status")),
        rollback_target=item.get("rollback_target") if item.get("rollback_target") is None else str(item.get("rollback_target")),
        request_id=item.get("request_id") if item.get("request_id") is None else str(item.get("request_id")),
        owner_agent_id=item.get("owner_agent_id") if item.get("owner_agent_id") is None else str(item.get("owner_agent_id")),
        owner_agent_role=item.get("owner_agent_role") if item.get("owner_agent_role") is None else str(item.get("owner_agent_role")),
        route_reason=item.get("route_reason") if item.get("route_reason") is None else str(item.get("route_reason")),
        capability_id=item.get("capability_id") if item.get("capability_id") is None else str(item.get("capability_id")),
        capability_type=item.get("capability_type") if item.get("capability_type") is None else str(item.get("capability_type")),
        capability_kind=item.get("capability_kind") if item.get("capability_kind") is None else str(item.get("capability_kind")),
    )


def _coerce_scheduler(item: dict[str, Any]) -> SchedulerRunRecord:
    return SchedulerRunRecord(
        timestamp=str(item.get("timestamp") or ""),
        task_id=str(item.get("task_id") or ""),
        task_name=str(item.get("task_name") or ""),
        mode=str(item.get("mode") or ""),
        status=str(item.get("status") or ""),
        run_id=item.get("run_id") if item.get("run_id") is None else str(item.get("run_id")),
        job_id=item.get("job_id") if item.get("job_id") is None else str(item.get("job_id")),
        request_id=item.get("request_id") if item.get("request_id") is None else str(item.get("request_id")),
        owner_agent_id=item.get("owner_agent_id") if item.get("owner_agent_id") is None else str(item.get("owner_agent_id")),
        owner_agent_role=item.get("owner_agent_role") if item.get("owner_agent_role") is None else str(item.get("owner_agent_role")),
        route_reason=item.get("route_reason") if item.get("route_reason") is None else str(item.get("route_reason")),
    )


COERCERS: dict[str, TraceCoercer] = {
    "planner": _coerce_planner,
    "steps": _coerce_step,
    "scheduler": _coerce_scheduler,
}


def _coerce_runtime_loop(item: dict[str, Any]) -> RuntimeLoopRecord:
    data = item.get("data")
    return RuntimeLoopRecord(
        timestamp=str(item.get("timestamp") or ""),
        session_id=str(item.get("session_id") or ""),
        request_id=item.get("request_id") if item.get("request_id") is None else str(item.get("request_id")),
        stage=str(item.get("stage") or "observe"),
        status=str(item.get("status") or "ok"),
        summary=str(item.get("summary") or ""),
        agent_id=item.get("agent_id") if item.get("agent_id") is None else str(item.get("agent_id")),
        agent_role=item.get("agent_role") if item.get("agent_role") is None else str(item.get("agent_role")),
        data=data if isinstance(data, dict) else None,
    )


COERCERS["runtime_loop"] = _coerce_runtime_loop


class AgentTraceStore:
    def __init__(self, path: str | Path | None = None, max_entries: int = 500) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "agent_trace.json"
        self.max_entries = max_entries
        self._lock = threading.RLock()
        self._projection_keys: set[str] = set()
        self.data: dict[str, list[TraceRecord]] = {
            "planner": [],
            "steps": [],
            "scheduler": [],
            "runtime_loop": [],
        }
        self.load()

    def load(self) -> None:
        try:
            if not self.path.exists():
                return
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                projection_keys = payload.get("projection_keys")
                if isinstance(projection_keys, list):
                    self._projection_keys = {
                        str(value) for value in projection_keys if str(value).strip()
                    }
                for key in self.data:
                    value = payload.get(key)
                    if isinstance(value, list):
                        coerce = COERCERS[key]
                        records: list[TraceRecord] = [coerce(item) for item in value if isinstance(item, dict)]
                        self.data[key] = records[-self.max_entries:]
        except Exception as exc:  # noqa: BLE001 - corrupt trace files must fail open.
            logger.warning("Failed to load agent trace store: %s", exc)
            self.data = {"planner": [], "steps": [], "scheduler": [], "runtime_loop": []}
            self._projection_keys = set()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                key: [item.to_dict() for item in value]
                for key, value in self.data.items()
            }
            payload["projection_keys"] = sorted(self._projection_keys)
            temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)

    def append(self, category: str, item: dict[str, Any]) -> None:
        if category not in self.data:
            self.data[category] = []
        coerce = COERCERS.get(category)
        if coerce is None:
            return
        self.data[category].append(coerce(item))
        self.data[category] = self.data[category][-self.max_entries:]
        # 每 10 条批量写一次，避免每次 append 都写磁盘
        if sum(len(v) for v in self.data.values()) % 10 == 0:
            self.save()

    def append_once(
        self,
        category: str,
        item: dict[str, Any],
        *,
        projection_key: str,
    ) -> bool:
        """Durably append a projection exactly once before its Outbox ACK."""
        normalized_key = str(projection_key or "").strip()
        if not normalized_key:
            raise ValueError("trace projection_key is required")
        coerce = COERCERS.get(category)
        if coerce is None:
            raise ValueError(f"unsupported trace category: {category}")
        with self._lock:
            if normalized_key in self._projection_keys:
                return False
            previous = list(self.data.get(category, []))
            self.data.setdefault(category, []).append(coerce(item))
            self.data[category] = self.data[category][-self.max_entries:]
            self._projection_keys.add(normalized_key)
            try:
                self.save()
            except Exception:
                self.data[category] = previous
                self._projection_keys.discard(normalized_key)
                raise
            return True

    def snapshot(self, limit: int = 100) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            take = max(1, min(limit, self.max_entries))
            return {
                key: [item.to_dict() for item in value[-take:]]
                for key, value in self.data.items()
            }
