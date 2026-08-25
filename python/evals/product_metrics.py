"""Privacy-preserving product metric aggregation and consented event storage.

The aggregator accepts redacted event metadata only. The optional local store
persists normalized records after explicit consent; production transport and
cohort governance remain a separate integration concern.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, Protocol

_PSEUDONYMOUS_USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_JOURNAL_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def _event_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def _user_id(event: Mapping[str, Any]) -> str | None:
    value = event.get("user_id")
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if not _PSEUDONYMOUS_USER_ID.fullmatch(normalized):
        return None
    return normalized


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


_ALLOWED_ACTIONS = {
    "voice": {"turn"},
    "memory": {"write", "correction"},
    "proactive": {"prompt", "accepted"},
    "recovery": {"attempt"},
}


def normalize_product_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the allowlisted metric envelope, dropping content-bearing fields."""
    user = _user_id(event)
    day = _event_date(event.get("timestamp"))
    kind = event.get("kind")
    if user is None or day is None or kind not in {
        "conversation", "voice", "memory", "proactive", "recovery",
    }:
        return None
    action = event.get("action")
    if kind in _ALLOWED_ACTIONS and action not in _ALLOWED_ACTIONS[kind]:
        return None
    normalized: dict[str, Any] = {
        "user_id": user,
        "timestamp": day.isoformat(),
        "kind": kind,
    }
    if kind != "conversation":
        normalized["action"] = action
    if kind in {"conversation", "recovery"} and isinstance(event.get("success"), bool):
        normalized["success"] = event["success"]
    return normalized


def compute_product_metrics(
    events: Iterable[Mapping[str, Any]],
    *,
    retention_days: int = 7,
    observation_end_date: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Aggregate redacted product events with explicit denominators.

    Supported event kinds are ``conversation``, ``voice``, ``memory``,
    ``proactive`` and ``recovery``. Unknown or malformed events are counted as
    dropped rather than influencing a numerator or denominator.
    """
    if retention_days < 1:
        raise ValueError("retention_days must be positive")
    observation_end = (
        _event_date(observation_end_date)
        if observation_end_date is not None
        else None
    )
    if observation_end_date is not None and observation_end is None:
        raise ValueError("observation_end_date must be a valid date")

    valid: list[tuple[str, Mapping[str, Any], date]] = []
    dropped = 0
    outside_observation = 0
    for event in events:
        normalized = normalize_product_event(event)
        if normalized is None:
            dropped += 1
            continue
        normalized_day = _event_date(normalized["timestamp"])
        if normalized_day is None:
            dropped += 1
            continue
        if observation_end is not None and normalized_day > observation_end:
            outside_observation += 1
            continue
        valid.append((normalized["user_id"], normalized, normalized_day))

    active_days: dict[str, set[date]] = {}
    conversation_events: dict[str, list[tuple[date, Mapping[str, Any]]]] = {}
    voice_users: set[str] = set()
    memory_writes = 0
    memory_corrections = 0
    proactive_prompts = 0
    proactive_accepts = 0
    recovery_attempts = 0
    recovery_successes = 0

    for user, event, day in valid:
        active_days.setdefault(user, set()).add(day)
        kind = event["kind"]
        if kind == "conversation":
            conversation_events.setdefault(user, []).append((day, event))
        elif kind == "voice" and event.get("action") == "turn":
            voice_users.add(user)
        elif kind == "memory":
            if event.get("action") == "write":
                memory_writes += 1
            elif event.get("action") == "correction":
                memory_corrections += 1
        elif kind == "proactive":
            if event.get("action") == "prompt":
                proactive_prompts += 1
            elif event.get("action") == "accepted":
                proactive_accepts += 1
        elif kind == "recovery" and event.get("action") == "attempt":
            recovery_attempts += 1
            recovery_successes += int(event.get("success") is True)

    first_success_users = sum(
        1
        for user_events in conversation_events.values()
        if user_events and min(user_events, key=lambda item: item[0])[1].get("success") is True
    )
    conversation_users = set(conversation_events)
    effective_observation_end = observation_end or max(
        (day for _user, _event, day in valid),
        default=None,
    )
    eligible_retention_users = {
        user for user, days in active_days.items()
        if effective_observation_end is not None
        and min(days) + timedelta(days=retention_days) <= effective_observation_end
    }
    retained_users = {
        user for user in eligible_retention_users
        if min(active_days[user]) + timedelta(days=retention_days) in active_days[user]
    }
    d7_retained = len(retained_users)

    return {
        "event_count": len(valid),
        "dropped_event_count": dropped,
        "outside_observation_event_count": outside_observation,
        "active_user_count": len(active_days),
        "first_successful_conversation_rate": _ratio(first_success_users, len(conversation_users)),
        "first_successful_conversation": {
            "successful_users": first_success_users,
            "conversation_users": len(conversation_users),
        },
        "d7_retention_rate": _ratio(d7_retained, len(eligible_retention_users)),
        "d7_retention": {
            "retained_users": d7_retained,
            "cohort_users": len(eligible_retention_users),
            "excluded_immature_users": len(active_days) - len(eligible_retention_users),
            "observation_end_date": (
                effective_observation_end.isoformat()
                if effective_observation_end is not None
                else None
            ),
        },
        "voice_adoption_rate": _ratio(len(voice_users), len(conversation_users)),
        "voice_adoption": {"voice_users": len(voice_users), "conversation_users": len(conversation_users)},
        "memory_correction_rate": _ratio(memory_corrections, memory_writes),
        "memory_correction": {"corrections": memory_corrections, "writes": memory_writes},
        "proactive_acceptance_rate": _ratio(proactive_accepts, proactive_prompts),
        "proactive_acceptance": {"accepted": proactive_accepts, "prompts": proactive_prompts},
        "recovery_success_rate": _ratio(recovery_successes, recovery_attempts),
        "recovery": {"successes": recovery_successes, "attempts": recovery_attempts},
        "retention_days": retention_days,
    }


class ProductConsentStateStore(Protocol):
    """Durable, user-controlled consent state for local metrics collection."""

    def load(self) -> bool:
        """Return persisted consent, defaulting to false when absent."""
        ...

    def save(self, consented: bool) -> None:
        """Atomically persist the current consent decision."""
        ...


class JsonProductConsentStateStore:
    """Atomic JSON consent state; malformed state fails closed."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if (
                not isinstance(value, Mapping)
                or set(value) != {"schema_version", "consented"}
                or value["schema_version"] != 1
                or not isinstance(value["consented"], bool)
            ):
                raise ValueError("consent state is invalid")
            return value["consented"]
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("consent state is corrupt") from error

    def save(self, consented: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {"schema_version": 1, "consented": bool(consented)},
                    handle,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


class JsonlProductEventStore:
    """Bounded local sink that persists only normalized events after consent.

    This is a local evidence adapter. It does not provide remote transport,
    identity resolution, deletion propagation, or production cohort
    governance; those remain release work outside this module.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        consented: bool = False,
        max_events: int = 10000,
        consent_state_store: ProductConsentStateStore | None = None,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self.path = Path(path)
        self.consent_state_store = consent_state_store
        self._consented = consent_state_store.load() if consent_state_store is not None else consented
        self.max_events = max_events

    @property
    def consented(self) -> bool:
        return self._consented

    def grant_consent(self) -> None:
        """Explicitly enable collection for this store instance."""
        if self.consent_state_store is not None:
            self.consent_state_store.save(True)
        self._consented = True

    def append(self, event: Mapping[str, Any]) -> bool:
        """Normalize and durably append an event only when collection is enabled."""
        if not self.consented:
            return False
        normalized = normalize_product_event(event)
        if normalized is None:
            return False
        existing = self.read()
        if len(existing) >= self.max_events:
            raise ValueError("product event store capacity reached")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, Mapping):
                        raise TypeError("product event record is invalid")
                    normalized = normalize_product_event(value)
                    if normalized is None:
                        raise ValueError("product event record is invalid")
                    events.append(normalized)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("product event store is corrupt") from error
        return events

    def purge_before(self, cutoff: date | datetime | str) -> int:
        """Atomically remove records older than ``cutoff`` and return the count."""
        cutoff_day = _event_date(cutoff)
        if cutoff_day is None:
            raise ValueError("retention cutoff must be a valid date")
        events = self.read()
        retained: list[dict[str, Any]] = []
        for event in events:
            event_day = _event_date(event["timestamp"])
            if event_day is not None and event_day >= cutoff_day:
                retained.append(event)
        removed = len(events) - len(retained)
        if removed:
            self._rewrite(retained)
        return removed

    def revoke_consent(self) -> None:
        """Disable collection and remove the local event file immediately."""
        if self.consent_state_store is not None:
            self.consent_state_store.save(False)
        self._consented = False
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _rewrite(self, events: Iterable[Mapping[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def metrics(self, *, retention_days: int = 7) -> dict[str, Any]:
        return compute_product_metrics(self.read(), retention_days=retention_days)

    def cohort_report(
        self,
        *,
        min_cohort_users: int = 5,
        retention_days: int = 7,
        start_date: date | datetime | str | None = None,
        end_date: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Return metrics only when consent and a minimum cohort size are present."""
        if min_cohort_users < 1:
            raise ValueError("min_cohort_users must be positive")
        start_day = _event_date(start_date) if start_date is not None else None
        end_day = _event_date(end_date) if end_date is not None else None
        if start_date is not None and start_day is None:
            raise ValueError("cohort start_date must be a valid date")
        if end_date is not None and end_day is None:
            raise ValueError("cohort end_date must be a valid date")
        if start_day is not None and end_day is not None and end_day < start_day:
            raise ValueError("cohort end_date must not precede start_date")
        window = {
            "start_date": start_day.isoformat() if start_day is not None else None,
            "end_date": end_day.isoformat() if end_day is not None else None,
        }
        if not self.consented:
            return {"status": "disabled", "window": window, "metrics": None}
        events = self.read()
        if start_day is not None or end_day is not None:
            filtered_events: list[dict[str, Any]] = []
            for event in events:
                event_day = _event_date(event["timestamp"])
                if event_day is None:
                    continue
                if start_day is not None and event_day < start_day:
                    continue
                if end_day is not None and event_day > end_day:
                    continue
                filtered_events.append(event)
            events = filtered_events
        metrics = compute_product_metrics(
            events,
            retention_days=retention_days,
            observation_end_date=end_day,
        )
        if metrics["active_user_count"] < min_cohort_users:
            return {
                "status": "suppressed",
                "reason": "minimum_cohort_size",
                "min_cohort_users": min_cohort_users,
                "window": window,
                "metrics": None,
            }
        return {
            "status": "ready",
            "min_cohort_users": min_cohort_users,
            "window": window,
            "metrics": metrics,
        }


class ProductEventTransport(Protocol):
    """Injectable transport boundary; implementations own auth and delivery."""

    def send(self, events: Iterable[Mapping[str, Any]]) -> None:
        """Deliver already-normalized events or raise without partial success."""


class ProductEventBatchTransport(Protocol):
    """Optional transport with a stable key for idempotent delivery."""

    def send_batch(self, events: Iterable[Mapping[str, Any]], *, idempotency_key: str) -> None:
        """Deliver one retryable batch or raise without partial success."""


class ProductEventDeletionTransport(Protocol):
    """Optional remote deletion capability for one exported batch."""

    def delete_batch(self, *, idempotency_key: str) -> None:
        """Delete the already-exported batch or raise without claiming success."""


ProductExportJournalStatus = Literal[
    "export_pending",
    "export_sent",
    "deletion_pending",
    "deletion_failed",
    "deleted",
]


@dataclass(frozen=True)
class ProductExportJournalEntry:
    """Redacted durable state for one deterministic event batch."""

    event_count: int
    status: ProductExportJournalStatus
    attempts: int
    last_error: str | None


class JsonProductExportJournal:
    """Atomic, fail-closed journal for export and deletion recovery.

    The journal stores only a batch digest, count, bounded status, and error
    code. It deliberately contains neither event content nor credentials.
    """

    _STATUSES = frozenset({
        "export_pending", "export_sent", "deletion_pending", "deletion_failed", "deleted",
    })

    def __init__(self, path: str | Path, *, max_entries: int = 1000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.path = Path(path)
        self.max_entries = max_entries

    @staticmethod
    def _validate_key(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("product export journal key is invalid")
        return value

    @classmethod
    def _parse(cls, value: object) -> dict[str, ProductExportJournalEntry]:
        if not isinstance(value, Mapping) or set(value) != {"schema_version", "entries"}:
            raise ValueError("product export journal is invalid")
        if value["schema_version"] != 1 or not isinstance(value["entries"], Mapping):
            raise ValueError("product export journal is invalid")
        parsed: dict[str, ProductExportJournalEntry] = {}
        for raw_key, raw_entry in value["entries"].items():
            key = cls._validate_key(raw_key)
            if not isinstance(raw_entry, Mapping) or set(raw_entry) != {
                "event_count", "status", "attempts", "last_error",
            }:
                raise ValueError("product export journal is invalid")
            count = raw_entry["event_count"]
            attempts = raw_entry["attempts"]
            status = raw_entry["status"]
            error = raw_entry["last_error"]
            if (not isinstance(count, int) or isinstance(count, bool) or count < 0
                    or not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0
                    or status not in cls._STATUSES
                    or (error is not None and (not isinstance(error, str) or not _JOURNAL_ERROR_CODE.fullmatch(error)))):
                raise ValueError("product export journal is invalid")
            parsed[key] = ProductExportJournalEntry(count, status, attempts, error)
        return parsed

    def read(self) -> dict[str, ProductExportJournalEntry]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return self._parse(json.load(handle))
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("product export journal is corrupt") from error

    def _write(self, entries: Mapping[str, ProductExportJournalEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        payload = {
            "schema_version": 1,
            "entries": {
                key: {
                    "event_count": entry.event_count,
                    "status": entry.status,
                    "attempts": entry.attempts,
                    "last_error": entry.last_error,
                }
                for key, entry in sorted(entries.items())
            },
        }
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def _record(
        self,
        key: str,
        *,
        event_count: int | None,
        status: ProductExportJournalStatus,
        last_error: str | None,
        increment_attempt: bool,
    ) -> None:
        self._validate_key(key)
        if event_count is not None and (not isinstance(event_count, int) or isinstance(event_count, bool) or event_count < 0):
            raise ValueError("product export journal event count is invalid")
        entries = self.read()
        previous = entries.get(key)
        if previous is None and len(entries) >= self.max_entries:
            raise ValueError("product export journal capacity reached")
        if last_error is not None and not _JOURNAL_ERROR_CODE.fullmatch(last_error):
            raise ValueError("product export journal error code is invalid")
        entries[key] = ProductExportJournalEntry(
            event_count=event_count if event_count is not None else (previous.event_count if previous else 0),
            status=status,
            attempts=(previous.attempts if previous else 0) + int(increment_attempt),
            last_error=last_error,
        )
        self._write(entries)

    def record_export_attempt(self, key: str, event_count: int) -> None:
        self._record(key, event_count=event_count, status="export_pending", last_error=None, increment_attempt=True)

    def record_export_sent(self, key: str) -> None:
        self._record(key, event_count=None, status="export_sent", last_error=None, increment_attempt=False)

    def record_export_failed(self, key: str, error_code: str) -> None:
        self._record(key, event_count=None, status="export_pending", last_error=error_code, increment_attempt=False)

    def record_deletion_pending(self, key: str, event_count: int) -> None:
        self._record(key, event_count=event_count, status="deletion_pending", last_error=None, increment_attempt=False)

    def record_deletion_failed(self, key: str, error_code: str) -> None:
        self._record(key, event_count=None, status="deletion_failed", last_error=error_code, increment_attempt=False)

    def record_deleted(self, key: str) -> None:
        self._record(key, event_count=None, status="deleted", last_error=None, increment_attempt=False)

    def pending_deletions(self) -> list[tuple[str, int]]:
        return [
            (key, entry.event_count)
            for key, entry in self.read().items()
            if entry.status in {"deletion_pending", "deletion_failed"}
        ]


@dataclass(frozen=True)
class ProductEventExportResult:
    status: Literal["disabled", "empty", "sent", "failed"]
    event_count: int
    error_code: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ProductConsentRevocationResult:
    local_status: Literal["revoked", "failed"]
    remote_status: Literal["not_configured", "deleted", "failed"]
    idempotency_key: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ProductDeletionRetryResult:
    attempted: int
    deleted: int
    failed: int


def _batch_id(events: Iterable[Mapping[str, Any]]) -> str:
    canonical = json.dumps(
        tuple(events),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


class ConsentGatedProductEventExporter:
    """Export local redacted events only after explicit consent.

    The exporter deliberately does not delete events after delivery. A real
    transport must provide authentication, idempotency, retry policy and server
    side deletion semantics before this boundary is used in production.
    """

    def __init__(
        self,
        store: JsonlProductEventStore,
        transport: ProductEventTransport | ProductEventBatchTransport,
        *,
        journal: JsonProductExportJournal | None = None,
    ) -> None:
        self.store = store
        self.transport = transport
        self.journal = journal

    def export(self) -> ProductEventExportResult:
        if not self.store.consented:
            return ProductEventExportResult("disabled", 0)
        events = self.store.read()
        if not events:
            return ProductEventExportResult("empty", 0)
        batch = tuple(events)
        idempotency_key = _batch_id(batch)
        try:
            if self.journal is not None:
                self.journal.record_export_attempt(idempotency_key, len(batch))
            send_batch = getattr(self.transport, "send_batch", None)
            if callable(send_batch):
                send_batch(batch, idempotency_key=idempotency_key)
            else:
                send = getattr(self.transport, "send", None)
                if not callable(send):
                    raise TypeError("product event transport has no send method")
                send(batch)
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            if self.journal is not None:
                try:
                    self.journal.record_export_failed(idempotency_key, "transport_unavailable")
                except (OSError, RuntimeError, TypeError, ValueError):
                    pass
            return ProductEventExportResult("failed", 0, "transport_unavailable", idempotency_key)
        if self.journal is not None:
            self.journal.record_export_sent(idempotency_key)
        return ProductEventExportResult("sent", len(events), idempotency_key=idempotency_key)

    def revoke_consent(self) -> ProductConsentRevocationResult:
        """Delete local evidence first, then request optional remote deletion."""
        if not self.store.consented:
            return ProductConsentRevocationResult("revoked", "not_configured")
        events = tuple(self.store.read())
        idempotency_key = _batch_id(events) if events else None
        if idempotency_key is not None and self.journal is not None:
            try:
                self.journal.record_deletion_pending(idempotency_key, len(events))
            except (OSError, RuntimeError, TypeError, ValueError):
                return ProductConsentRevocationResult("failed", "not_configured", idempotency_key, "journal_unavailable")
        try:
            self.store.revoke_consent()
        except (OSError, RuntimeError, TypeError, ValueError):
            return ProductConsentRevocationResult("failed", "not_configured", idempotency_key, "local_delete_failed")
        if idempotency_key is None:
            return ProductConsentRevocationResult("revoked", "not_configured")
        delete_batch = getattr(self.transport, "delete_batch", None)
        if not callable(delete_batch):
            return ProductConsentRevocationResult("revoked", "not_configured", idempotency_key)
        try:
            delete_batch(idempotency_key=idempotency_key)
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
            if self.journal is not None:
                self.journal.record_deletion_failed(idempotency_key, "remote_delete_failed")
            return ProductConsentRevocationResult("revoked", "failed", idempotency_key, "remote_delete_failed")
        if self.journal is not None:
            self.journal.record_deleted(idempotency_key)
        return ProductConsentRevocationResult("revoked", "deleted", idempotency_key)

    def retry_pending_deletions(self) -> ProductDeletionRetryResult:
        """Retry remote deletion after a crash or transient endpoint failure."""
        if self.journal is None:
            return ProductDeletionRetryResult(0, 0, 0)
        delete_batch = getattr(self.transport, "delete_batch", None)
        pending = self.journal.pending_deletions()
        if not callable(delete_batch):
            return ProductDeletionRetryResult(0, 0, len(pending))
        deleted = 0
        for key, _event_count in pending:
            try:
                delete_batch(idempotency_key=key)
            except (OSError, RuntimeError, TimeoutError, TypeError, ValueError):
                self.journal.record_deletion_failed(key, "remote_delete_failed")
            else:
                self.journal.record_deleted(key)
                deleted += 1
        return ProductDeletionRetryResult(len(pending), deleted, len(pending) - deleted)


__all__ = [
    "ConsentGatedProductEventExporter",
    "JsonProductConsentStateStore",
    "JsonProductExportJournal",
    "JsonlProductEventStore",
    "ProductConsentRevocationResult",
    "ProductConsentStateStore",
    "ProductDeletionRetryResult",
    "ProductEventBatchTransport",
    "ProductEventDeletionTransport",
    "ProductEventExportResult",
    "ProductEventTransport",
    "ProductExportJournalEntry",
    "ProductExportJournalStatus",
    "compute_product_metrics",
    "normalize_product_event",
]
