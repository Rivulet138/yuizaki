from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from ..core.paths import data_dir_from_env

logger = logging.getLogger(__name__)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


class HeartbeatGoalStore:
    """Small bounded JSON store for proactive goal history."""

    def __init__(self, path: str | Path | None = None, max_goals: int = 32) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "heartbeat-goals.json"
        self.max_goals = max(1, int(max_goals))

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Unable to load heartbeat goals from %s: %s", self.path, exc)
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if self._valid_goal(item)][-self.max_goals:]

    def save(self, goals: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [goal for goal in goals[-self.max_goals:] if self._valid_goal(goal)]
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        try:
            temporary.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            logger.warning("Unable to persist heartbeat goals to %s: %s", self.path, exc)

    @staticmethod
    def _valid_goal(value: Any) -> bool:
        if not isinstance(value, dict) or not str(value.get("goal_id") or "").strip() or not str(value.get("kind") or "").strip():
            return False
        numeric = ("due_at", "created_at", "updated_at", "cooldown_seconds", "priority")
        if not all(_is_finite_number(value.get(key)) for key in numeric if key in value):
            return False
        expires_at = value.get("expires_at")
        if expires_at is not None and not _is_finite_number(expires_at):
            return False
        return True
