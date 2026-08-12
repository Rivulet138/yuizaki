from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ..core.paths import data_dir_from_env
logger = logging.getLogger(__name__)


ScheduleMode = Literal["once", "interval"]


@dataclass
class ScheduledTask:
    id: str
    name: str
    source: str
    prompt: str
    enabled: bool
    mode: ScheduleMode
    created_at: float
    run_after_seconds: int | None = None
    interval_seconds: int | None = None
    next_run_at: float | None = None
    last_run_at: float | None = None
    last_status: str | None = None
    last_run_id: str | None = None
    last_job_id: str | None = None
    last_request_id: str | None = None
    last_run_summary: str | None = None
    owner_agent_id: str | None = None
    owner_agent_role: str | None = None
    route_reason: str | None = None


class ScheduleStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "schedules.json"
        self.tasks: dict[str, ScheduledTask] = {}
        self.load()

    def load(self) -> None:
        try:
            if not self.path.exists():
                self.tasks = {}
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.tasks = {
                item["id"]: ScheduledTask(**item)
                for item in data
                if isinstance(item, dict) and item.get("id")
            }
        except Exception as exc:
            logger.warning("Failed to load schedule store: %s", exc)
            self.tasks = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(task) for task in self.tasks.values()]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, task: ScheduledTask) -> ScheduledTask:
        self.tasks[task.id] = task
        self.save()
        return task

    def remove(self, task_id: str) -> None:
        self.tasks.pop(task_id, None)
        self.save()

    def list(self) -> list[ScheduledTask]:
        return list(self.tasks.values())
