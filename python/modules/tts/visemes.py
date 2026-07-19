from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SUPPORTED_VISEMES = frozenset({"sil", "aa", "ih", "ou", "ee", "oh"})
MAX_VISEME_CUES = 256
MAX_VISEME_OFFSET_MS = 10 * 60 * 1000
MAX_VISEME_DURATION_MS = 60 * 1000


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (str, bytes, int, float)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def normalize_viseme_cues(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    cues: list[dict[str, Any]] = []
    for item in value[:MAX_VISEME_CUES]:
        if not isinstance(item, Mapping):
            continue
        viseme = str(item.get("viseme", "")).strip().lower()
        offset_ms = _finite_number(item.get("offset_ms"))
        if viseme not in SUPPORTED_VISEMES or offset_ms is None or offset_ms < 0:
            continue

        cue: dict[str, Any] = {
            "viseme": viseme,
            "offset_ms": round(min(offset_ms, MAX_VISEME_OFFSET_MS), 1),
        }
        duration_ms = _finite_number(item.get("duration_ms"))
        if duration_ms is not None and duration_ms > 0:
            cue["duration_ms"] = round(min(duration_ms, MAX_VISEME_DURATION_MS), 1)
        weight = _finite_number(item.get("weight"))
        if weight is not None:
            cue["weight"] = round(max(0.0, min(1.0, weight)), 4)
        cues.append(cue)

    cues.sort(key=lambda cue: cue["offset_ms"])
    return cues
