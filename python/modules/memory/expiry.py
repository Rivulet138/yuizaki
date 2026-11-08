from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_UTC_RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_EXPIRY_FORMAT_ERROR = "expires_at must use uppercase UTC Z RFC3339 format"


def normalize_expires_at(value: Any) -> str | None:
    """Validate and normalize an optional memory expiry timestamp to UTC."""
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(_EXPIRY_FORMAT_ERROR)

    raw = value
    if _UTC_RFC3339_PATTERN.fullmatch(raw) is None:
        raise ValueError(_EXPIRY_FORMAT_ERROR)
    try:
        parsed = datetime.fromisoformat(f"{raw[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError(_EXPIRY_FORMAT_ERROR) from exc
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_memory_expiry(
    metadata: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    reject_expired: bool = False,
) -> dict[str, Any]:
    normalized = dict(metadata or {})
    if "expires_at" not in normalized:
        return normalized

    expires_at = normalize_expires_at(normalized.get("expires_at"))
    if expires_at is None:
        normalized.pop("expires_at", None)
        return normalized
    normalized["expires_at"] = expires_at
    if reject_expired and is_memory_expired(normalized, now=now):
        raise ValueError("expires_at must be in the future")
    return normalized


def is_memory_expired(metadata: Mapping[str, Any] | None, *, now: datetime | None = None) -> bool:
    if not metadata or metadata.get("expires_at") is None:
        return False
    try:
        expires_at = normalize_expires_at(metadata.get("expires_at"))
    except ValueError:
        # Invalid legacy expiry values must not make a memory recallable forever.
        return True
    if expires_at is None:
        return False
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC) >= datetime.fromisoformat(expires_at)
