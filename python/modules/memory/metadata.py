from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .expiry import is_memory_expired

MEMORY_METADATA_SCHEMA_VERSION = 1
MEMORY_VERSION_HISTORY_LIMIT = 50
NON_RECALLABLE_REVIEW_STATUSES = frozenset({"pending", "rejected", "deleted", "superseded"})
PROVENANCE_FIELDS = ("source_kind", "source_id", "source_ids", "turn_id", "evidence")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_timestamp(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_memory_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Normalize legacy metadata without dropping extension fields."""
    normalized = dict(metadata or {})
    instant = _canonical_timestamp(now) or utc_now()
    legacy_timestamp = _canonical_timestamp(normalized.get("timestamp"))
    created_at = _canonical_timestamp(normalized.get("created_at")) or legacy_timestamp or instant
    updated_at = _canonical_timestamp(normalized.get("updated_at")) or created_at

    try:
        revision = max(1, int(normalized.get("revision", 1)))
    except (TypeError, ValueError):
        revision = 1

    normalized.update(
        {
            "schema_version": MEMORY_METADATA_SCHEMA_VERSION,
            "revision": revision,
            "created_at": created_at,
            "updated_at": updated_at,
            "occurred_at": _canonical_timestamp(normalized.get("occurred_at")) or legacy_timestamp or created_at,
            "ingested_at": _canonical_timestamp(normalized.get("ingested_at")) or created_at,
            "review_status": str(normalized.get("review_status") or "unreviewed").strip().lower(),
        }
    )
    for key in ("valid_from", "valid_to"):
        value = _canonical_timestamp(normalized.get(key))
        if value is None:
            normalized.pop(key, None)
        else:
            normalized[key] = value

    source_ids = normalized.get("source_ids")
    if isinstance(source_ids, (tuple, set)):
        source_ids = list(source_ids)
    elif isinstance(source_ids, str):
        source_ids = [source_ids]
    elif not isinstance(source_ids, list):
        source_ids = []
    source_ids = [str(item) for item in source_ids if str(item).strip()]
    source_id = normalized.get("source_id")
    if source_id is not None and str(source_id).strip() and str(source_id) not in source_ids:
        source_ids.append(str(source_id))
    normalized["source_ids"] = source_ids
    normalized.setdefault("supersedes", None)
    normalized.setdefault("superseded_by", None)
    return normalized


def normalize_memory_validity(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate and canonicalize the user-controlled validity window."""
    normalized = dict(metadata or {})
    instants: dict[str, datetime] = {}
    for key in ("valid_from", "valid_to"):
        value = normalized.get(key)
        if value in (None, ""):
            normalized.pop(key, None)
            continue
        canonical = _canonical_timestamp(value)
        parsed = _parse_instant(canonical)
        if canonical is None or parsed is None:
            raise ValueError(f"{key} must be an ISO 8601 datetime")
        normalized[key] = canonical
        instants[key] = parsed
    if (
        "valid_from" in instants
        and "valid_to" in instants
        and instants["valid_to"] <= instants["valid_from"]
    ):
        raise ValueError("valid_to must be later than valid_from")
    return normalized


def memory_state(metadata: Mapping[str, Any] | None, *, now: datetime | None = None) -> str:
    data = metadata or {}
    if bool(data.get("candidate_deleted")):
        return "deleted"
    if bool(data.get("soft_forgotten")):
        return "forgotten"
    review_status = str(data.get("review_status") or "").strip().lower()
    if bool(data.get("candidate")) and review_status in {"", "unreviewed", "pending", "review"}:
        return "pending_review"
    if review_status in NON_RECALLABLE_REVIEW_STATUSES:
        return review_status
    if data.get("superseded_by"):
        return "superseded"
    if _has_invalid_validity(data):
        return "invalid"
    if is_memory_expired(data, now=now) or _has_ended(data.get("valid_to"), now=now):
        return "expired"
    if _starts_later(data.get("valid_from"), now=now):
        return "scheduled"
    return "active"


def recall_rejection_reason(metadata: Mapping[str, Any] | None, *, now: datetime | None = None) -> str | None:
    state = memory_state(metadata, now=now)
    return None if state == "active" else state


def is_metadata_recallable(metadata: Mapping[str, Any] | None, *, now: datetime | None = None) -> bool:
    return recall_rejection_reason(metadata, now=now) is None


def append_memory_version(
    *,
    doc_id: str,
    old_text: str,
    old_metadata: Mapping[str, Any] | None,
    new_metadata: Mapping[str, Any] | None,
    now: str | None = None,
) -> dict[str, Any]:
    """Create metadata for a replacement while retaining a bounded audit window."""
    old = normalize_memory_metadata(old_metadata, now=now)
    new = normalize_memory_metadata(new_metadata, now=now)
    existing_history = old.get("version_history")
    history = list(existing_history) if isinstance(existing_history, list) else []
    snapshot_metadata = {key: value for key, value in old.items() if key != "version_history"}
    history.append(
        {
            "id": doc_id,
            "revision": old["revision"],
            "text": old_text,
            "metadata": snapshot_metadata,
        }
    )
    truncated_count = max(0, int(old.get("version_history_truncated", 0) or 0))
    if len(history) > MEMORY_VERSION_HISTORY_LIMIT:
        truncated_count += len(history) - MEMORY_VERSION_HISTORY_LIMIT
        history = history[-MEMORY_VERSION_HISTORY_LIMIT:]
    for key in PROVENANCE_FIELDS:
        if key in old:
            new[key] = old[key]
    new["created_at"] = old["created_at"]
    new["revision"] = int(old["revision"]) + 1
    new["updated_at"] = _canonical_timestamp(now) or utc_now()
    new["version_history"] = history
    if truncated_count:
        new["version_history_truncated"] = truncated_count
    else:
        new.pop("version_history_truncated", None)
    return new


def has_prior_version_snapshot(
    metadata: Mapping[str, Any] | None,
    *,
    revision: int,
    text: str,
) -> bool:
    history = (metadata or {}).get("version_history")
    if not isinstance(history, list) or not history:
        return False
    latest = history[-1]
    return (
        isinstance(latest, Mapping)
        and latest.get("revision") == revision
        and latest.get("text") == text
        and isinstance(latest.get("metadata"), Mapping)
    )


def _parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _has_ended(value: Any, *, now: datetime | None) -> bool:
    instant = _parse_instant(value)
    if instant is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) >= instant


def _has_invalid_validity(metadata: Mapping[str, Any]) -> bool:
    raw_from = metadata.get("valid_from")
    raw_to = metadata.get("valid_to")
    valid_from = _parse_instant(raw_from)
    valid_to = _parse_instant(raw_to)
    if raw_from not in (None, "") and valid_from is None:
        return True
    if raw_to not in (None, "") and valid_to is None:
        return True
    return valid_from is not None and valid_to is not None and valid_to <= valid_from


def _starts_later(value: Any, *, now: datetime | None) -> bool:
    instant = _parse_instant(value)
    if instant is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) < instant
