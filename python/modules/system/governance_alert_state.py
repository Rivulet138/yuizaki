from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypeGuard, cast


GovernanceAlertState = dict[str, dict[str, object]]


def _is_json_object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


class GovernanceAlertStateStore:
    def __init__(self, path: Path, logger: logging.Logger) -> None:
        self.path: Path = path
        self.logger: logging.Logger = logger
        self.state: GovernanceAlertState = {}

    def load(self) -> None:
        try:
            if not self.path.exists():
                self.state = {}
                return
            loaded = cast(object, json.loads(self.path.read_text(encoding="utf-8")))
            if not _is_json_object(loaded):
                self.state = {}
                return
            next_state: GovernanceAlertState = {}
            for key, value in loaded.items():
                if isinstance(key, str) and _is_json_object(value):
                    next_state[key] = {str(item_key): item_value for item_key, item_value in value.items()}
            self.state = next_state
        except Exception as exc:
            self.logger.warning("Failed to load governance alert state: %s", exc)
            self.state = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _ = self.path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self.logger.warning("Failed to save governance alert state: %s", exc)
