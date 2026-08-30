"""Rebuildable activity-frame projection and proactive follow-up policy.

Activity frames are bounded, non-authoritative projections of committed turns.
They deliberately never contain chat text, screenshots, audio, credentials, tool
output, or action authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SOURCE_KIND = "completed_turn_followup"
PROJECTION_VERSION = "activity-frame.v1"
POLICY_VERSION = "proactive-policy.v1"
SCHEMA_VERSION = "yuizaki.activity-frame.v1"
DEFAULT_ACTIVITY_CATEGORY = "general"
_ALLOWED_WORK_STATES = {"unknown", "working", "idle", "meeting", "focus", "away"}
_ALLOWED_BENEFITS = {"continue_task", "check_in", "reminder", "companionship"}
_ALLOWED_INTERRUPT_COSTS = {"low", "medium", "high"}
_FEEDBACK_SCORE_WEIGHTS = {
    "accepted": 1,
    "ignored": -1,
    "cancelled": -1,
    "snoozed": -2,
}
FEEDBACK_LEARNING_WINDOW_SECONDS = 30 * 86400
FEEDBACK_HALF_LIFE_SECONDS = 7 * 86400
# Feedback is a user-behavior signal, not an immutable audit archive. Keep a
# bounded local history while retaining longer than the learning window.
FEEDBACK_RETENTION_SECONDS = 90 * 86400
FEEDBACK_KINDS = {
    "useful",
    "not_useful",
    "too_frequent",
    "wrong_time",
    "never_source",
    # Behavioral outcomes are retained as learner signals. They do not grant
    # authorization and only cancel a still-pending opportunity where noted.
    "accepted",
    "ignored",
    "cancelled",
    "snoozed",
}
BEHAVIOR_FEEDBACK_KINDS = {"accepted", "ignored", "cancelled", "snoozed"}
GATE_ORDER = (
    "global_disabled",
    "source_disabled",
    "user_paused",
    "frame_inactive",
    "dnd",
    "quiet_hours",
    "not_interruptible",
    "context_not_interruptible",
    "cooldown",
    "daily_budget",
    "category_budget",
    "feedback_category_disfavored",
    "duplicate",
)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_WINDOWS_TZDATA_FALLBACKS = {
    "UTC",
    "Etc/UTC",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "America/New_York",
    "Europe/London",
}


def _bounded_id(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{field} must be a safe identifier of 1-160 characters")
    return normalized


def _feedback_gate(
    kind: str | None,
    created_at: float | None,
    *,
    now: float,
    settings: ProactiveSettings,
) -> str | None:
    """Translate recent negative feedback into a temporary, reversible gate."""
    if not kind or created_at is None:
        return None
    age = max(0.0, now - float(created_at))
    if kind == "too_frequent" and age < max(float(settings.cooldown_seconds), 3600.0):
        return "feedback_too_frequent"
    if kind == "wrong_time" and age < 86400.0:
        return "feedback_wrong_time"
    if kind == "not_useful" and age < max(float(settings.cooldown_seconds), 3600.0):
        return "feedback_not_useful"
    if kind == "ignored" and age < max(float(settings.cooldown_seconds), 900.0):
        return "feedback_ignored"
    if kind == "snoozed" and age < max(float(settings.cooldown_seconds), 1800.0):
        return "feedback_snoozed"
    return None


def deterministic_frame_id(source_kind: str, source_id: str) -> str:
    material = f"{source_kind}\0{source_id}\0{PROJECTION_VERSION}".encode()
    return "af_" + hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool = False
    completed_turn_followup_enabled: bool = True
    paused: bool = False
    dnd: bool = False
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"
    timezone: str = "UTC"
    daily_budget: int = 3
    cooldown_seconds: int = 3600
    retention_days: int = 7
    category_budgets: dict[str, int] = field(default_factory=dict)

    def validate(self) -> ProactiveSettings:
        _parse_hhmm(self.quiet_hours_start)
        _parse_hhmm(self.quiet_hours_end)
        _validate_timezone(self.timezone)
        if not 1 <= self.daily_budget <= 20:
            raise ValueError("dailyBudget must be between 1 and 20")
        if not 0 <= self.cooldown_seconds <= 604800:
            raise ValueError("cooldownSeconds must be between 0 and 604800")
        if not 1 <= self.retention_days <= 90:
            raise ValueError("retentionDays must be between 1 and 90")
        if not isinstance(self.category_budgets, Mapping) or len(self.category_budgets) > 20:
            raise ValueError("categoryBudgets must contain at most 20 entries")
        normalized_categories: dict[str, int] = {}
        for category, budget in self.category_budgets.items():
            safe_category = _bounded_id(category, "categoryBudget category")
            if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 20:
                raise ValueError("categoryBudgets values must be integers between 1 and 20")
            normalized_categories[safe_category] = budget
        object.__setattr__(self, "category_budgets", normalized_categories)
        return self

    def to_api(self) -> dict[str, Any]:
        return {
            "schemaVersion": "yuizaki.proactive-settings.v1",
            "enabled": self.enabled,
            "sourceEnabled": {SOURCE_KIND: self.completed_turn_followup_enabled},
            "paused": self.paused,
            "dnd": self.dnd,
            "quietHours": {
                "enabled": self.quiet_hours_enabled,
                "start": self.quiet_hours_start,
                "end": self.quiet_hours_end,
                "timezone": self.timezone,
            },
            "dailyBudget": self.daily_budget,
            "categoryBudgets": dict(self.category_budgets),
            "cooldownSeconds": self.cooldown_seconds,
            "retentionDays": self.retention_days,
            "policyVersion": POLICY_VERSION,
        }


@dataclass(frozen=True)
class ActivityFrame:
    frame_id: str
    workspace_id: str
    session_id: str
    source_kind: str
    source_id: str
    source_event_id: str
    source_created_at: float
    created_at: float
    expires_at: float
    projection_version: str
    policy_version: str
    signals: Mapping[str, Any]

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_api(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "frameId": self.frame_id,
            "workspaceId": self.workspace_id,
            "sessionId": self.session_id,
            "sourceKind": self.source_kind,
            "sourceId": self.source_id,
            "sourceEventId": self.source_event_id,
            "sourceCreatedAt": self.source_created_at,
            "createdAt": self.created_at,
            "expiresAt": self.expires_at,
            "projectionVersion": self.projection_version,
            "policyVersion": self.policy_version,
            "redaction": {
                "version": "activity-frame-redaction.v1",
                "rawContentRetained": False,
                "excluded": [
                    "chat_text",
                    "screenshots",
                    "audio",
                    "credentials",
                    "tool_output",
                ],
            },
            "provenance": {
                "sourceKind": self.source_kind,
                "sourceId": self.source_id,
                "sourceEventId": self.source_event_id,
            },
            "signals": dict(self.signals),
            "authoritative": False,
            "allowedActions": [],
        }


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    evaluated_at: float
    local_date: str
    remaining_budget: int
    category: str = DEFAULT_ACTIVITY_CATEGORY
    remaining_category_budget: int = 0
    preference_score: float = 0.0

    def to_api(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "evaluatedAt": self.evaluated_at,
            "localDate": self.local_date,
            "remainingBudget": self.remaining_budget,
            "category": self.category,
            "remainingCategoryBudget": self.remaining_category_budget,
            "preferenceScore": self.preference_score,
            "gateOrder": list(GATE_ORDER),
            "policyVersion": POLICY_VERSION,
        }


def _parse_hhmm(value: str) -> int:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("quiet hour values must use HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or value != f"{hour:02d}:{minute:02d}":
        raise ValueError("quiet hour values must use HH:MM")
    return hour * 60 + minute


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
        return
    except ZoneInfoNotFoundError:
        if timezone_name not in _WINDOWS_TZDATA_FALLBACKS:
            raise ValueError("timezone must be a supported IANA timezone") from None


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    day = 1 + (weekday - first.weekday()) % 7 + (occurrence - 1) * 7
    return datetime(year, month, day, tzinfo=timezone.utc)


def _last_weekday(year: int, month: int, weekday: int) -> datetime:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    candidate = next_month - timedelta(days=1)
    return candidate - timedelta(days=(candidate.weekday() - weekday) % 7)


def _fallback_offset(now_utc: datetime, timezone_name: str) -> timedelta:
    if timezone_name in {"UTC", "Etc/UTC"}:
        return timedelta(0)
    if timezone_name == "Asia/Shanghai":
        return timedelta(hours=8)
    if timezone_name == "Asia/Tokyo":
        return timedelta(hours=9)
    year = now_utc.year
    if timezone_name == "America/New_York":
        dst_start = _nth_weekday(year, 3, 6, 2) + timedelta(hours=7)
        dst_end = _nth_weekday(year, 11, 6, 1) + timedelta(hours=6)
        return timedelta(hours=-4 if dst_start <= now_utc < dst_end else -5)
    if timezone_name == "Europe/London":
        dst_start = _last_weekday(year, 3, 6) + timedelta(hours=1)
        dst_end = _last_weekday(year, 10, 6) + timedelta(hours=1)
        return timedelta(hours=1 if dst_start <= now_utc < dst_end else 0)
    raise ValueError("timezone must be a supported IANA timezone")


def _local_clock(now: float, timezone_name: str) -> tuple[str, int]:
    utc_value = datetime.fromtimestamp(now, tz=timezone.utc)
    try:
        local = utc_value.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        local = utc_value + _fallback_offset(utc_value, timezone_name)
    return local.date().isoformat(), local.hour * 60 + local.minute


def _in_quiet_hours(settings: ProactiveSettings, minute: int) -> bool:
    if not settings.quiet_hours_enabled:
        return False
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _activity_category(signals: Mapping[str, Any]) -> str:
    value = str(signals.get("activityCategory") or DEFAULT_ACTIVITY_CATEGORY).strip()
    return value if _SAFE_ID.fullmatch(value) else DEFAULT_ACTIVITY_CATEGORY


def _category_budget(settings: ProactiveSettings, category: str) -> int:
    # An empty map intentionally inherits the global budget for every category.
    return int(settings.category_budgets.get(category, settings.daily_budget))


def _activity_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract bounded, non-authoritative context for a proactive explanation."""
    raw = payload.get("activity_context")
    if not isinstance(raw, Mapping):
        # Cross-process payloads use both Python's snake_case and the
        # renderer-facing camelCase convention.  Normalize at this boundary
        # so policy never depends on which transport produced the commit.
        raw = payload.get("activityContext")
    if not isinstance(raw, Mapping):
        raw = {}
    try:
        confidence = float(
            raw.get("scene_confidence", raw.get("sceneConfidence", 0.0)) or 0.0
        )
    except (TypeError, ValueError, OverflowError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    work_state = str(
        raw.get("user_work_state", raw.get("userWorkState")) or "unknown"
    ).strip()
    benefit = str(
        raw.get("expected_benefit", raw.get("expectedBenefit")) or "continue_task"
    ).strip()
    interrupt_cost = str(
        raw.get("interrupt_cost", raw.get("interruptCost")) or "low"
    ).strip()
    return {
        "scene_confidence": max(0.0, min(1.0, confidence)),
        "user_work_state": work_state if work_state in _ALLOWED_WORK_STATES else "unknown",
        "expected_benefit": benefit if benefit in _ALLOWED_BENEFITS else "continue_task",
        "interrupt_cost": interrupt_cost if interrupt_cost in _ALLOWED_INTERRUPT_COSTS else "low",
    }


def _context_gate_reason(signals: Mapping[str, Any]) -> str | None:
    """Use high-confidence context only to avoid interrupting focused users."""
    try:
        confidence = float(signals.get("scene_confidence", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        confidence = 0.0
    state = str(signals.get("user_work_state") or "unknown")
    interrupt_cost = str(signals.get("interrupt_cost") or "low")
    if (
        math.isfinite(confidence)
        and confidence >= 0.7
        and state in {"working", "focus", "meeting"}
        and interrupt_cost in {"medium", "high"}
    ):
        return "context_not_interruptible"
    return None


class ActivityFrameStore:
    """SQLite projection store with tombstones and transactional budgets."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_frames (
                  workspace_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  session_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  source_event_id TEXT NOT NULL,
                  source_created_at REAL NOT NULL,
                  created_at REAL NOT NULL,
                  expires_at REAL NOT NULL,
                  projection_version TEXT NOT NULL,
                  policy_version TEXT NOT NULL,
                  signals_json TEXT NOT NULL,
                  PRIMARY KEY (workspace_id, frame_id),
                  UNIQUE (workspace_id, source_kind, source_id)
                );
                CREATE TABLE IF NOT EXISTS activity_frame_tombstones (
                  workspace_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  deleted_at REAL NOT NULL,
                  PRIMARY KEY (workspace_id, source_kind, source_id)
                );
                CREATE TABLE IF NOT EXISTS proactive_settings (
                  workspace_id TEXT PRIMARY KEY,
                  settings_json TEXT NOT NULL,
                  revision INTEGER NOT NULL DEFAULT 1,
                  updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proactive_opportunities (
                  workspace_id TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  request_id TEXT NOT NULL,
                  frame_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  local_date TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  resolved_at REAL,
                  expires_at REAL,
                  PRIMARY KEY (workspace_id, job_id)
                );
                CREATE TABLE IF NOT EXISTS proactive_feedback (
                  workspace_id TEXT NOT NULL,
                  feedback_id TEXT NOT NULL,
                  job_id TEXT NOT NULL,
                  request_id TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  created_at REAL NOT NULL,
                  PRIMARY KEY (workspace_id, feedback_id)
                );
                """
            )
            settings_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(proactive_settings)").fetchall()
            }
            if "revision" not in settings_columns:
                conn.execute(
                    "ALTER TABLE proactive_settings ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )
            opportunity_info = conn.execute(
                "PRAGMA table_info(proactive_opportunities)"
            ).fetchall()
            primary_key = [
                str(row["name"])
                for row in sorted(
                    (row for row in opportunity_info if int(row["pk"]) > 0),
                    key=lambda row: int(row["pk"]),
                )
            ]
            if primary_key != ["workspace_id", "job_id"]:
                conn.executescript(
                    """
                    ALTER TABLE proactive_opportunities
                      RENAME TO proactive_opportunities_legacy;
                    CREATE TABLE proactive_opportunities (
                      workspace_id TEXT NOT NULL,
                      job_id TEXT NOT NULL,
                      request_id TEXT NOT NULL,
                      frame_id TEXT NOT NULL,
                      source_kind TEXT NOT NULL,
                      local_date TEXT NOT NULL,
                      status TEXT NOT NULL,
                      created_at REAL NOT NULL,
                      resolved_at REAL,
                      expires_at REAL,
                      PRIMARY KEY (workspace_id, job_id)
                    );
                    INSERT OR IGNORE INTO proactive_opportunities(
                      workspace_id, job_id, request_id, frame_id, source_kind,
                      local_date, status, created_at, resolved_at
                    )
                    SELECT workspace_id, job_id, request_id, frame_id, source_kind,
                           local_date, status, created_at, resolved_at
                    FROM proactive_opportunities_legacy;
                    DROP TABLE proactive_opportunities_legacy;
                    """
                )
                opportunity_info = conn.execute(
                    "PRAGMA table_info(proactive_opportunities)"
                ).fetchall()
            opportunity_columns = {str(row["name"]) for row in opportunity_info}
            if "expires_at" not in opportunity_columns:
                conn.execute("ALTER TABLE proactive_opportunities ADD COLUMN expires_at REAL")
            conn.execute(
                """CREATE INDEX IF NOT EXISTS proactive_opportunity_budget_idx
                   ON proactive_opportunities(workspace_id, local_date, status)"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS proactive_feedback_retention_idx
                   ON proactive_feedback(workspace_id, created_at)"""
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _settings_from_json(raw: str | None) -> ProactiveSettings:
        data = json.loads(raw) if raw else {}
        return ProactiveSettings(**data).validate()

    @staticmethod
    def _category_usage_locked(
        conn: sqlite3.Connection,
        workspace_id: str,
        local_date: str,
        category: str,
        *,
        exclude_job_id: str | None = None,
    ) -> int:
        rows = conn.execute(
            """SELECT o.job_id, f.signals_json
               FROM proactive_opportunities AS o
               LEFT JOIN activity_frames AS f
                 ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
               WHERE o.workspace_id = ? AND o.local_date = ?
                 AND o.status IN ('pending', 'delivered')""",
            (workspace_id, local_date),
        ).fetchall()
        used = 0
        for row in rows:
            if exclude_job_id is not None and str(row["job_id"]) == exclude_job_id:
                continue
            try:
                signals = json.loads(row["signals_json"] or "{}")
            except (TypeError, ValueError):
                signals = {}
            if isinstance(signals, Mapping) and _activity_category(signals) == category:
                used += 1
        return used

    @staticmethod
    def _category_preference_locked(
        conn: sqlite3.Connection,
        workspace_id: str,
        category: str,
        *,
        now: float,
    ) -> float:
        """Score recent explicit behavior with a bounded exponential decay."""
        rows = conn.execute(
            """SELECT p.kind, p.created_at, f.signals_json
               FROM proactive_feedback AS p
               JOIN proactive_opportunities AS o
                 ON o.workspace_id = p.workspace_id AND o.job_id = p.job_id
                AND o.request_id = p.request_id AND o.source_kind = p.source_kind
               LEFT JOIN activity_frames AS f
                 ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
               WHERE p.workspace_id = ? AND p.created_at >= ?""",
            (workspace_id, now - FEEDBACK_LEARNING_WINDOW_SECONDS),
        ).fetchall()
        score = 0.0
        for row in rows:
            try:
                signals = json.loads(row["signals_json"] or "{}")
            except (TypeError, ValueError):
                signals = {}
            if isinstance(signals, Mapping) and _activity_category(signals) == category:
                age = max(0.0, now - float(row["created_at"]))
                decay = 0.5 ** (age / FEEDBACK_HALF_LIFE_SECONDS)
                score += _FEEDBACK_SCORE_WEIGHTS.get(str(row["kind"]), 0) * decay
        return round(max(-20.0, min(20.0, score)), 2)

    @staticmethod
    def _prune_feedback_locked(
        conn: sqlite3.Connection,
        workspace_id: str,
        current: float,
    ) -> int:
        cursor = conn.execute(
            """DELETE FROM proactive_feedback
               WHERE workspace_id = ? AND created_at < ?""",
            (workspace_id, current - FEEDBACK_RETENTION_SECONDS),
        )
        return int(cursor.rowcount)

    def get_settings(self, workspace_id: str) -> ProactiveSettings:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
        return self._settings_from_json(row["settings_json"] if row else None)

    def get_settings_record(self, workspace_id: str) -> tuple[ProactiveSettings, int, float | None]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT settings_json, revision, updated_at FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
        if row is None:
            return ProactiveSettings().validate(), 0, None
        return (
            self._settings_from_json(row["settings_json"]),
            int(row["revision"]),
            float(row["updated_at"]),
        )

    def patch_settings(
        self,
        workspace_id: str,
        patch: Mapping[str, Any],
        *,
        expected_revision: int,
        cancelled_pending: list[dict[str, str]] | None = None,
    ) -> tuple[ProactiveSettings, int, float]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT settings_json, revision FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
            revision = int(row["revision"]) if row else 0
            if revision != expected_revision:
                raise LookupError(f"settings revision conflict: expected {expected_revision}, current {revision}")
            current = asdict(self._settings_from_json(row["settings_json"] if row else None))
            current.update(dict(patch))
            settings = ProactiveSettings(**current).validate()
            updated_at = time.time()
            next_revision = revision + 1
            conn.execute(
                """INSERT INTO proactive_settings(workspace_id, settings_json, revision, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(workspace_id) DO UPDATE SET
                     settings_json = excluded.settings_json,
                     revision = excluded.revision,
                     updated_at = excluded.updated_at""",
                (
                    workspace,
                    json.dumps(asdict(settings), sort_keys=True),
                    next_revision,
                    updated_at,
                ),
            )
            conn.execute(
                """UPDATE activity_frames
                   SET expires_at = source_created_at + ?
                   WHERE workspace_id = ?""",
                (settings.retention_days * 86400, workspace),
            )
            _, minute = _local_clock(updated_at, settings.timezone)
            authority_blocked = (
                not settings.enabled
                or not settings.completed_turn_followup_enabled
                or settings.paused
                or settings.dnd
                or _in_quiet_hours(settings, minute)
            )
            if authority_blocked:
                pending = conn.execute(
                    """SELECT workspace_id, job_id, request_id, source_kind, frame_id
                       FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'
                       ORDER BY created_at, job_id""",
                    (workspace, SOURCE_KIND),
                ).fetchall()
                conn.execute(
                    """UPDATE proactive_opportunities
                       SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (updated_at, workspace, SOURCE_KIND),
                )
                if cancelled_pending is not None:
                    cancelled_pending.extend(self._opportunity_identities(pending))
            pruned = self._prune_expired_locked(conn, workspace, updated_at)
            if cancelled_pending is not None:
                cancelled_pending.extend(pruned)
        return settings, next_revision, updated_at

    def upsert_frame(self, frame: ActivityFrame) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            tombstone = conn.execute(
                """SELECT 1 FROM activity_frame_tombstones
                   WHERE workspace_id = ? AND source_kind = ? AND source_id = ?""",
                (frame.workspace_id, frame.source_kind, frame.source_id),
            ).fetchone()
            if tombstone is not None:
                return False
            conn.execute(
                """INSERT INTO activity_frames(
                     workspace_id, frame_id, session_id, source_kind, source_id,
                     source_event_id, source_created_at, created_at, expires_at,
                     projection_version, policy_version, signals_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(workspace_id, source_kind, source_id) DO UPDATE SET
                     frame_id = excluded.frame_id,
                     session_id = excluded.session_id,
                     source_event_id = excluded.source_event_id,
                     source_created_at = excluded.source_created_at,
                     expires_at = excluded.expires_at,
                     projection_version = excluded.projection_version,
                     policy_version = excluded.policy_version,
                     signals_json = excluded.signals_json""",
                (
                    frame.workspace_id,
                    frame.frame_id,
                    frame.session_id,
                    frame.source_kind,
                    frame.source_id,
                    frame.source_event_id,
                    frame.source_created_at,
                    frame.created_at,
                    frame.expires_at,
                    frame.projection_version,
                    frame.policy_version,
                    json.dumps(dict(frame.signals), sort_keys=True),
                ),
            )
        return True

    @staticmethod
    def _row_to_frame(row: sqlite3.Row) -> ActivityFrame:
        return ActivityFrame(
            frame_id=row["frame_id"],
            workspace_id=row["workspace_id"],
            session_id=row["session_id"],
            source_kind=row["source_kind"],
            source_id=row["source_id"],
            source_event_id=row["source_event_id"],
            source_created_at=float(row["source_created_at"]),
            created_at=float(row["created_at"]),
            expires_at=float(row["expires_at"]),
            projection_version=row["projection_version"],
            policy_version=row["policy_version"],
            signals=json.loads(row["signals_json"]),
        )

    def list_frames(self, workspace_id: str, *, limit: int = 50, now: float | None = None) -> list[ActivityFrame]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM activity_frames WHERE workspace_id = ? AND expires_at > ?
                   ORDER BY source_created_at DESC, frame_id LIMIT ?""",
                (workspace, current, max(1, min(200, int(limit)))),
            ).fetchall()
        return [self._row_to_frame(row) for row in rows]

    def get_frame(self, workspace_id: str, frame_id: str) -> ActivityFrame | None:
        workspace = _bounded_id(workspace_id, "workspaceId")
        frame = _bounded_id(frame_id, "frameId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM activity_frames WHERE workspace_id = ? AND frame_id = ?",
                (workspace, frame),
            ).fetchone()
        return self._row_to_frame(row) if row else None

    def delete_frame(
        self,
        workspace_id: str,
        frame_id: str,
        *,
        reason: str = "user_deleted",
        now: float | None = None,
        cancelled_pending: list[dict[str, str]] | None = None,
    ) -> bool:
        workspace = _bounded_id(workspace_id, "workspaceId")
        frame = _bounded_id(frame_id, "frameId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT source_kind, source_id FROM activity_frames
                   WHERE workspace_id = ? AND frame_id = ?""",
                (workspace, frame),
            ).fetchone()
            if row is None:
                tombstone = conn.execute(
                    """SELECT 1 FROM activity_frame_tombstones
                       WHERE workspace_id = ? AND frame_id = ?""",
                    (workspace, frame),
                ).fetchone()
                return tombstone is not None
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace, row["source_kind"], row["source_id"], frame, reason, current),
            )
            conn.execute(
                "DELETE FROM activity_frames WHERE workspace_id = ? AND frame_id = ?",
                (workspace, frame),
            )
            pending = conn.execute(
                """SELECT workspace_id, job_id, request_id, source_kind, frame_id
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'
                   ORDER BY created_at, job_id""",
                (workspace, frame),
            ).fetchall()
            conn.execute(
                """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (current, workspace, frame),
            )
            if cancelled_pending is not None:
                cancelled_pending.extend(self._opportunity_identities(pending))
        return True

    def tombstone_source(
        self,
        workspace_id: str,
        source_kind: str,
        source_id: str,
        *,
        reason: str = "source_deleted",
        now: float | None = None,
    ) -> str:
        workspace = _bounded_id(workspace_id, "workspaceId")
        source = _bounded_id(source_id, "sourceId")
        if source_kind != SOURCE_KIND:
            raise ValueError("unknown activity frame source")
        frame_id = deterministic_frame_id(source_kind, source)
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace, source_kind, source, frame_id, reason, current),
            )
            conn.execute(
                "DELETE FROM activity_frames WHERE workspace_id = ? AND source_kind = ? AND source_id = ?",
                (workspace, source_kind, source),
            )
        return frame_id

    @staticmethod
    def _opportunity_identities(rows: Any) -> list[dict[str, str]]:
        return [
            {
                "workspace_id": str(row["workspace_id"]),
                "job_id": str(row["job_id"]),
                "request_id": str(row["request_id"]),
                "source_kind": str(row["source_kind"]),
                "frame_id": str(row["frame_id"]),
            }
            for row in rows
        ]

    @classmethod
    def _prune_expired_locked(
        cls,
        conn: sqlite3.Connection,
        workspace: str,
        current: float,
    ) -> list[dict[str, str]]:
        pending = conn.execute(
            """SELECT o.workspace_id, o.job_id, o.request_id, o.source_kind, o.frame_id
               FROM proactive_opportunities AS o
               JOIN activity_frames AS f
                 ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
               WHERE f.workspace_id = ? AND f.expires_at <= ? AND o.status = 'pending'
               ORDER BY o.created_at, o.job_id""",
            (workspace, current),
        ).fetchall()
        rows = conn.execute(
            """SELECT frame_id, source_kind, source_id FROM activity_frames
               WHERE workspace_id = ? AND expires_at <= ?""",
            (workspace, current),
        ).fetchall()
        for row in rows:
            conn.execute(
                """INSERT OR IGNORE INTO activity_frame_tombstones(
                     workspace_id, source_kind, source_id, frame_id, reason, deleted_at
                   ) VALUES (?, ?, ?, ?, 'retention_expired', ?)""",
                (workspace, row["source_kind"], row["source_id"], row["frame_id"], current),
            )
            conn.execute(
                """UPDATE proactive_opportunities
                   SET status = 'cancelled', resolved_at = ?
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (current, workspace, row["frame_id"]),
            )
        conn.execute(
            "DELETE FROM activity_frames WHERE workspace_id = ? AND expires_at <= ?",
            (workspace, current),
        )
        cls._prune_feedback_locked(conn, workspace, current)
        return cls._opportunity_identities(pending)

    def prune_expired(
        self,
        workspace_id: str,
        *,
        now: float | None = None,
    ) -> list[dict[str, str]]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._prune_expired_locked(conn, workspace, current)

    def evaluate(
        self,
        workspace_id: str,
        frame: ActivityFrame,
        *,
        now: float | None = None,
        interruptible: bool = True,
    ) -> PolicyDecision:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        settings = self.get_settings(workspace)
        local_date, minute = _local_clock(current, settings.timezone)
        category = _activity_category(frame.signals)
        category_limit = _category_budget(settings, category)
        with self._lock, self._connect() as conn:
            delivered = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ? AND status = 'delivered'""",
                    (workspace, local_date),
                ).fetchone()["count"]
            )
            pending = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ? AND status = 'pending'""",
                    (workspace, local_date),
                ).fetchone()["count"]
            )
            last_delivered = conn.execute(
                """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                   WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                (workspace, frame.source_kind),
            ).fetchone()["at"]
            latest_feedback = conn.execute(
                """SELECT kind, created_at FROM proactive_feedback
                   WHERE workspace_id = ? AND source_kind = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (workspace, frame.source_kind),
            ).fetchone()
            duplicate = conn.execute(
                """SELECT 1 FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? LIMIT 1""",
                (workspace, frame.frame_id),
            ).fetchone() is not None
            category_used = self._category_usage_locked(
                conn, workspace, local_date, category
            )
            preference_score = self._category_preference_locked(
                conn, workspace, category, now=current
            )
        remaining = max(0, settings.daily_budget - delivered)
        remaining_category = max(0, category_limit - category_used)
        reason = "allowed"
        if not settings.enabled:
            reason = "global_disabled"
        elif not settings.completed_turn_followup_enabled:
            reason = "source_disabled"
        elif settings.paused:
            reason = "user_paused"
        elif frame.expires_at <= current or self.get_frame(workspace, frame.frame_id) is None:
            reason = "frame_inactive"
        elif settings.dnd:
            reason = "dnd"
        elif _in_quiet_hours(settings, minute):
            reason = "quiet_hours"
        elif not interruptible:
            reason = "not_interruptible"
        elif (context_reason := _context_gate_reason(frame.signals)) is not None:
            reason = context_reason
        elif latest_feedback is not None and (
            feedback_reason := _feedback_gate(
                str(latest_feedback["kind"]),
                float(latest_feedback["created_at"]),
                now=current,
                settings=settings,
            )
        ) is not None:
            reason = feedback_reason
        elif last_delivered is not None and current - float(last_delivered) < settings.cooldown_seconds:
            reason = "cooldown"
        elif delivered + pending >= settings.daily_budget:
            reason = "daily_budget"
        elif category_used >= category_limit:
            reason = "category_budget"
        elif preference_score <= -2:
            reason = "feedback_category_disfavored"
        elif duplicate:
            reason = "duplicate"
        return PolicyDecision(
            reason == "allowed",
            reason,
            current,
            local_date,
            remaining,
            category,
            remaining_category,
            preference_score,
        )

    def reserve_opportunity(
        self,
        workspace_id: str,
        *,
        job_id: str,
        request_id: str,
        frame_id: str,
        source_kind: str,
        local_date: str,
        interruptible: bool = True,
        expires_at: float | None = None,
        now: float | None = None,
    ) -> bool:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT workspace_id, request_id, frame_id, source_kind,
                          local_date, status, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ?""",
                (workspace, job_id),
            ).fetchone()
            settings_row = conn.execute(
                "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                (workspace,),
            ).fetchone()
            settings = self._settings_from_json(
                settings_row["settings_json"] if settings_row else None
            )
            if (
                not settings.enabled
                or not settings.completed_turn_followup_enabled
                or settings.paused
                or settings.dnd
            ):
                return False
            computed_local_date, minute = _local_clock(current, settings.timezone)
            if _in_quiet_hours(settings, minute) or not interruptible:
                return False
            frame = conn.execute(
                """SELECT source_kind, source_id, session_id, source_created_at, expires_at,
                          signals_json
                   FROM activity_frames
                   WHERE workspace_id = ? AND frame_id = ? AND source_kind = ?
                     AND expires_at > ?""",
                (workspace, frame_id, source_kind, current),
            ).fetchone()
            if frame is None:
                return False
            try:
                frame_signals = json.loads(frame["signals_json"] or "{}")
            except (TypeError, ValueError):
                frame_signals = {}
            category = _activity_category(frame_signals)
            category_limit = _category_budget(settings, category)
            if _context_gate_reason(frame_signals) is not None:
                return False
            tombstoned = conn.execute(
                """SELECT 1 FROM activity_frame_tombstones
                   WHERE workspace_id = ? AND source_kind = ? AND source_id = ?""",
                (workspace, source_kind, frame["source_id"]),
            ).fetchone()
            if tombstoned is not None:
                return False
            effective_frame_expiry = min(
                float(frame["expires_at"]),
                float(frame["source_created_at"]) + settings.retention_days * 86400,
            )
            if effective_frame_expiry <= current:
                return False
            last_delivered = conn.execute(
                """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                   WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                (workspace, source_kind),
            ).fetchone()["at"]
            latest_feedback = conn.execute(
                """SELECT kind, created_at FROM proactive_feedback
                   WHERE workspace_id = ? AND source_kind = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (workspace, source_kind),
            ).fetchone()
            if latest_feedback is not None and _feedback_gate(
                str(latest_feedback["kind"]),
                float(latest_feedback["created_at"]),
                now=current,
                settings=settings,
            ) is not None:
                return False
            if (
                last_delivered is not None
                and current - float(last_delivered) < settings.cooldown_seconds
            ):
                return False
            exact_existing = bool(
                existing is not None
                and existing["request_id"] == request_id
                and existing["frame_id"] == frame_id
                and existing["source_kind"] == source_kind
                and existing["status"] == "pending"
                and (
                    existing["expires_at"] is None
                    or float(existing["expires_at"]) > current
                )
            )
            if existing is not None and not exact_existing:
                return False
            duplicate = conn.execute(
                """SELECT 1 FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ?
                     AND NOT (workspace_id = ? AND job_id = ?)
                   LIMIT 1""",
                (workspace, frame_id, workspace, job_id),
            ).fetchone()
            if duplicate is not None:
                return False
            used = int(
                conn.execute(
                    """SELECT COUNT(*) AS count FROM proactive_opportunities
                       WHERE workspace_id = ? AND local_date = ?
                         AND status IN ('pending', 'delivered')
                         AND NOT (workspace_id = ? AND job_id = ?)""",
                    (workspace, computed_local_date, workspace, job_id),
                ).fetchone()["count"]
            )
            if used >= settings.daily_budget:
                return False
            category_used = self._category_usage_locked(
                conn,
                workspace,
                computed_local_date,
                category,
                exclude_job_id=job_id,
            )
            if category_used >= category_limit:
                return False
            if self._category_preference_locked(
                conn, workspace, category, now=current
            ) <= -2:
                return False
            opportunity_expires_at = (
                min(float(expires_at), effective_frame_expiry)
                if expires_at is not None
                else effective_frame_expiry
            )
            if opportunity_expires_at <= current:
                return False
            if exact_existing:
                conn.execute(
                    """UPDATE proactive_opportunities
                       SET local_date = ?, expires_at = ?
                       WHERE workspace_id = ? AND job_id = ? AND status = 'pending'""",
                    (computed_local_date, opportunity_expires_at, workspace, job_id),
                )
                return True
            conn.execute(
                """INSERT OR IGNORE INTO proactive_opportunities(
                     workspace_id, job_id, request_id, frame_id, source_kind,
                     local_date, status, created_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    workspace,
                    job_id,
                    request_id,
                    frame_id,
                    source_kind,
                    computed_local_date,
                    current,
                    opportunity_expires_at,
                ),
            )
            return conn.execute("SELECT changes() AS count").fetchone()["count"] == 1

    def pending_for_frame(self, workspace_id: str, frame_id: str) -> dict[str, str] | None:
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """SELECT job_id, request_id, local_date, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND frame_id = ? AND status = 'pending'""",
                (workspace, frame_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "job_id": str(row["job_id"]),
            "request_id": str(row["request_id"]),
            "local_date": str(row["local_date"]),
            "expires_at": str(row["expires_at"] or ""),
        }

    def list_pending_opportunities(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """SELECT o.workspace_id, o.job_id, o.request_id, o.frame_id,
                          o.source_kind, o.local_date, o.expires_at,
                          f.source_id, f.session_id
                   FROM proactive_opportunities AS o
                   LEFT JOIN activity_frames AS f
                     ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
                   WHERE o.status = 'pending'
                   ORDER BY o.created_at, o.workspace_id, o.job_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_opportunity(
        self,
        *,
        workspace_id: str,
        job_id: str,
        request_id: str,
        source_kind: str,
        outcome: str,
        now: float | None = None,
    ) -> bool:
        current = time.time() if now is None else float(now)
        if outcome not in {"delivered", "suppressed", "expired", "cancelled", "failed"}:
            raise ValueError("unknown proactive opportunity outcome")
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT workspace_id, request_id, frame_id, source_kind,
                          status, expires_at
                   FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ?""",
                (workspace_id, job_id),
            ).fetchone()
            if row is None or any(
                (
                    row["workspace_id"] != workspace_id,
                    row["request_id"] != request_id,
                    row["source_kind"] != source_kind,
                )
            ):
                return False
            if row["status"] == outcome:
                return True
            if row["status"] != "pending":
                return False
            local_date: str | None = None
            if outcome == "delivered":
                settings_row = conn.execute(
                    "SELECT settings_json FROM proactive_settings WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()
                settings = self._settings_from_json(
                    settings_row["settings_json"] if settings_row else None
                )
                local_date, minute = _local_clock(current, settings.timezone)
                if (
                    not settings.enabled
                    or not settings.completed_turn_followup_enabled
                    or settings.paused
                    or settings.dnd
                    or _in_quiet_hours(settings, minute)
                    or (row["expires_at"] is not None and float(row["expires_at"]) <= current)
                ):
                    return False
                frame = conn.execute(
                    """SELECT source_created_at, expires_at FROM activity_frames
                       WHERE workspace_id = ? AND frame_id = ? AND source_kind = ?""",
                    (workspace_id, row["frame_id"], source_kind),
                ).fetchone()
                if frame is None or min(
                    float(frame["expires_at"]),
                    float(frame["source_created_at"]) + settings.retention_days * 86400,
                ) <= current:
                    return False
                delivered = int(
                    conn.execute(
                        """SELECT COUNT(*) AS count FROM proactive_opportunities
                           WHERE workspace_id = ? AND local_date = ? AND status = 'delivered'""",
                        (workspace_id, local_date),
                    ).fetchone()["count"]
                )
                if delivered >= settings.daily_budget:
                    return False
                last_delivered = conn.execute(
                    """SELECT MAX(resolved_at) AS at FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'delivered'""",
                    (workspace_id, source_kind),
                ).fetchone()["at"]
                if (
                    last_delivered is not None
                    and current - float(last_delivered) < settings.cooldown_seconds
                ):
                    return False
            cursor = conn.execute(
                """UPDATE proactive_opportunities
                   SET status = ?, resolved_at = ?, local_date = COALESCE(?, local_date)
                   WHERE workspace_id = ? AND job_id = ? AND request_id = ?
                     AND source_kind = ? AND status = 'pending'""",
                (
                    outcome,
                    current,
                    local_date,
                    workspace_id,
                    job_id,
                    request_id,
                    source_kind,
                ),
            )
            return cursor.rowcount == 1

    def cancel_pending(
        self,
        workspace_id: str,
        source_kind: str,
        *,
        frame_id: str | None = None,
        now: float | None = None,
    ) -> int:
        workspace = _bounded_id(workspace_id, "workspaceId")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if frame_id is None:
                cursor = conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (current, workspace, source_kind),
                )
            else:
                cursor = conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND frame_id = ?
                         AND status = 'pending'""",
                    (current, workspace, source_kind, frame_id),
                )
            return cursor.rowcount

    def record_feedback(
        self,
        workspace_id: str,
        *,
        feedback_id: str,
        job_id: str,
        request_id: str,
        source_kind: str,
        kind: str,
        now: float | None = None,
    ) -> tuple[bool, str, list[tuple[str, str]]]:
        workspace = _bounded_id(workspace_id, "workspaceId")
        feedback = _bounded_id(feedback_id, "feedbackId")
        if kind not in FEEDBACK_KINDS:
            raise ValueError("unknown feedback kind")
        current = time.time() if now is None else float(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """SELECT job_id, request_id, kind, source_kind FROM proactive_feedback
                   WHERE workspace_id = ? AND feedback_id = ?""",
                (workspace, feedback),
            ).fetchone()
            if existing is not None:
                same = (
                    existing["job_id"] == job_id
                    and existing["request_id"] == request_id
                    and existing["kind"] == kind
                )
                if not same:
                    raise ValueError("feedbackId is already bound to another feedback record")
                return False, str(existing["source_kind"]), []
            opportunity = conn.execute(
                """SELECT source_kind FROM proactive_opportunities
                   WHERE workspace_id = ? AND job_id = ? AND request_id = ? AND source_kind = ?""",
                (workspace, job_id, request_id, source_kind),
            ).fetchone()
            if opportunity is None:
                raise LookupError("proactive opportunity was not found")
            source_kind = str(opportunity["source_kind"])
            conn.execute(
                """INSERT INTO proactive_feedback(
                     workspace_id, feedback_id, job_id, request_id, source_kind, kind, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (workspace, feedback, job_id, request_id, source_kind, kind, current),
            )
            cancelled: list[tuple[str, str]] = []
            if kind in {
                "not_useful",
                "too_frequent",
                "wrong_time",
                "ignored",
                "cancelled",
                "snoozed",
            }:
                cursor = conn.execute(
                    """UPDATE proactive_opportunities
                       SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND job_id = ? AND request_id = ?
                         AND source_kind = ? AND status = 'pending'""",
                    (current, workspace, job_id, request_id, source_kind),
                )
                if cursor.rowcount == 1:
                    cancelled = [(job_id, request_id)]
            if kind == "never_source":
                row = conn.execute(
                    "SELECT settings_json, revision FROM proactive_settings WHERE workspace_id = ?",
                    (workspace,),
                ).fetchone()
                settings = self._settings_from_json(row["settings_json"] if row else None)
                disabled = ProactiveSettings(
                    **{**asdict(settings), "completed_turn_followup_enabled": False}
                ).validate()
                revision = int(row["revision"]) if row and "revision" in row else 0
                conn.execute(
                    """INSERT INTO proactive_settings(workspace_id, settings_json, revision, updated_at)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(workspace_id) DO UPDATE SET
                         settings_json = excluded.settings_json,
                         revision = proactive_settings.revision + 1,
                         updated_at = excluded.updated_at""",
                    (workspace, json.dumps(asdict(disabled), sort_keys=True), revision + 1, current),
                )
                pending = conn.execute(
                    """SELECT job_id, request_id FROM proactive_opportunities
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (workspace, source_kind),
                ).fetchall()
                cancelled = [(str(row["job_id"]), str(row["request_id"])) for row in pending]
                conn.execute(
                    """UPDATE proactive_opportunities SET status = 'cancelled', resolved_at = ?
                       WHERE workspace_id = ? AND source_kind = ? AND status = 'pending'""",
                    (current, workspace, source_kind),
                )
        return True, source_kind, cancelled

    def list_feedback(
        self,
        workspace_id: str,
        *,
        source_kind: str | None = None,
        limit: int = 100,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return bounded, replayable feedback records for policy evaluation."""
        workspace = _bounded_id(workspace_id, "workspaceId")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer between 1 and 500")
        current = time.time() if now is None else float(now)
        if not math.isfinite(current):
            raise ValueError("now must be a finite timestamp")
        query = (
            "SELECT feedback_id, job_id, request_id, source_kind, kind, created_at "
            "FROM proactive_feedback WHERE workspace_id = ?"
        )
        params: list[Any] = [workspace]
        if source_kind is not None:
            query += " AND source_kind = ?"
            params.append(_bounded_id(source_kind, "sourceKind"))
        query += " ORDER BY created_at DESC, feedback_id DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            self._prune_feedback_locked(conn, workspace, current)
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "feedbackId": str(row["feedback_id"]),
                "jobId": str(row["job_id"]),
                "requestId": str(row["request_id"]),
                "sourceKind": str(row["source_kind"]),
                "kind": str(row["kind"]),
                "createdAt": float(row["created_at"]),
            }
            for row in rows
        ]

    def feedback_summary(
        self,
        workspace_id: str,
        *,
        source_kind: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Aggregate behavioral signals without exposing prompt or tool data."""
        evaluation_time = time.time() if now is None else float(now)
        if not math.isfinite(evaluation_time):
            raise ValueError("now must be a finite timestamp")
        records = self.list_feedback(
            workspace_id,
            source_kind=source_kind,
            limit=500,
            now=evaluation_time,
        )
        counts: dict[str, int] = {}
        for record in records:
            kind = str(record["kind"])
            counts[kind] = counts.get(kind, 0) + 1
        behavioral_total = sum(counts.get(kind, 0) for kind in BEHAVIOR_FEEDBACK_KINDS)
        accepted = counts.get("accepted", 0)
        category_scores: dict[str, float] = {}
        workspace = _bounded_id(workspace_id, "workspaceId")
        with self._lock, self._connect() as conn:
            query = """SELECT f.signals_json
                       FROM proactive_feedback AS p
                       JOIN proactive_opportunities AS o
                         ON o.workspace_id = p.workspace_id AND o.job_id = p.job_id
                        AND o.request_id = p.request_id AND o.source_kind = p.source_kind
                       LEFT JOIN activity_frames AS f
                         ON f.workspace_id = o.workspace_id AND f.frame_id = o.frame_id
                       WHERE p.workspace_id = ?"""
            params: list[Any] = [workspace]
            if source_kind is not None:
                query += " AND p.source_kind = ?"
                params.append(_bounded_id(source_kind, "sourceKind"))
            rows = conn.execute(query, params).fetchall()
            categories: set[str] = set()
            for row in rows:
                try:
                    signals = json.loads(row["signals_json"] or "{}")
                except (TypeError, ValueError):
                    signals = {}
                if isinstance(signals, Mapping):
                    categories.add(_activity_category(signals))
            category_scores = {
                category: self._category_preference_locked(
                    conn, workspace, category, now=evaluation_time
                )
                for category in sorted(categories)
            }
        return {
            "schemaVersion": "yuizaki.proactive-feedback-summary.v1",
            "workspaceId": workspace_id,
            "sourceKind": source_kind,
            "counts": counts,
            "total": len(records),
            "behavioralTotal": behavioral_total,
            "acceptanceRate": (accepted / behavioral_total) if behavioral_total else None,
            "categoryPreferenceScores": category_scores,
        }


class ActivityFrameService:
    """Coordinates deterministic projection, policy, and existing heartbeat jobs."""

    def __init__(self, store: ActivityFrameStore, turn_store: Any) -> None:
        self.store = store
        self.turn_store = turn_store
        self._scheduler: Any | None = None

    def bind_scheduler(self, scheduler: Any | None) -> None:
        self._scheduler = scheduler
        if scheduler is not None:
            scheduler.set_proactive_outcome_observer(self.observe_outcome)
            self._restore_pending_opportunities(scheduler)

    def _restore_pending_opportunities(self, scheduler: Any) -> None:
        interruptible = bool(
            not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        for pending in self.store.list_pending_opportunities():
            workspace_id = str(pending.get("workspace_id") or "")
            frame_id = str(pending.get("frame_id") or "")
            frame = self.store.get_frame(workspace_id, frame_id)
            if frame is None:
                self.store.cancel_pending(
                    workspace_id,
                    str(pending.get("source_kind") or SOURCE_KIND),
                    frame_id=frame_id,
                )
                continue
            decision = self.store.evaluate(
                workspace_id,
                frame,
                interruptible=interruptible,
            )
            if not self._emit_opportunity(frame, decision, pending=pending):
                self.store.cancel_pending(
                    workspace_id,
                    frame.source_kind,
                    frame_id=frame.frame_id,
                )

    @staticmethod
    def project_event(event: Mapping[str, Any], retention_days: int) -> ActivityFrame | None:
        if event.get("event_type") != "turn.committed":
            return None
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise TypeError("activity frame projection requires a turn.committed payload")
        workspace_id = _bounded_id(payload.get("workspace_id") or "default", "workspaceId")
        session_id = _bounded_id(payload.get("session_id"), "sessionId")
        source_id = _bounded_id(event.get("idempotency_key"), "sourceId")
        source_event_id = _bounded_id(str(event.get("event_id")), "sourceEventId")
        authoritative_created_at = payload.get("committed_at") or event.get("created_at")
        if authoritative_created_at is None:
            raise ValueError(
                "turn.committed projection requires an authoritative committed timestamp"
            )
        source_created_at = float(authoritative_created_at)
        messages = payload.get("messages")
        user_message_count = 0
        if isinstance(messages, list):
            user_message_count = min(20, sum(1 for item in messages if isinstance(item, Mapping) and item.get("role") == "user"))
        signals = {
            "kind": SOURCE_KIND,
            "turnCompleted": True,
            "assistantReplyPresent": bool(str(payload.get("reply") or "").strip()),
            "userMessageCount": user_message_count,
            "hadToolCalls": bool(payload.get("tool_calls")),
            "trigger": (
                str(payload.get("trigger"))
                if str(payload.get("trigger") or "") in {"socket", "voice", "schedule", "plugin"}
                else "other"
            ),
        }
        trigger = str(signals["trigger"])
        signals["activityCategory"] = (
            "scheduled"
            if trigger == "schedule"
            else "tool_followup"
            if bool(signals["hadToolCalls"])
            else "conversation"
        )
        signals.update(_activity_context(payload))
        return ActivityFrame(
            frame_id=deterministic_frame_id(SOURCE_KIND, source_id),
            workspace_id=workspace_id,
            session_id=session_id,
            source_kind=SOURCE_KIND,
            source_id=source_id,
            source_event_id=source_event_id,
            source_created_at=source_created_at,
            created_at=source_created_at,
            expires_at=source_created_at + retention_days * 86400,
            projection_version=PROJECTION_VERSION,
            policy_version=POLICY_VERSION,
            signals=signals,
        )

    def project(self, event: Mapping[str, Any], _context: Any | None = None) -> dict[str, Any]:
        payload = event.get("payload")
        workspace_id = str(payload.get("workspace_id") or "default") if isinstance(payload, Mapping) else "default"
        settings = self.store.get_settings(workspace_id)
        frame = self.project_event(event, settings.retention_days)
        if frame is None:
            return {"projected": False, "reason": "unsupported_event"}
        if not self.store.upsert_frame(frame):
            return {"projected": False, "reason": "tombstoned", "frameId": frame.frame_id}
        scheduler = self._scheduler
        interruptible = bool(
            scheduler is None
            or not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        decision = self.store.evaluate(
            frame.workspace_id,
            frame,
            interruptible=interruptible,
        )
        if decision.allowed:
            self._emit_opportunity(frame, decision)
        elif decision.reason in {"daily_budget", "duplicate"}:
            pending = self.store.pending_for_frame(frame.workspace_id, frame.frame_id)
            if pending is not None:
                self._emit_opportunity(frame, decision, pending=pending)
        return {"projected": True, "frameId": frame.frame_id, "policy": decision.to_api()}

    def _emit_opportunity(
        self,
        frame: ActivityFrame,
        decision: PolicyDecision,
        *,
        pending: Mapping[str, Any] | None = None,
    ) -> bool:
        scheduler = self._scheduler
        if scheduler is None:
            return False
        suffix = hashlib.sha256(
            f"{frame.workspace_id}\0{frame.frame_id}\0{frame.source_kind}".encode()
        ).hexdigest()[:20]
        job_id = str((pending or {}).get("job_id") or f"activityframejob_{suffix}")
        request_id = str((pending or {}).get("request_id") or f"activityframereq_{suffix}")
        local_date = str((pending or {}).get("local_date") or decision.local_date)
        interruptible = bool(
            not hasattr(scheduler, "proactive_interruptible")
            or scheduler.proactive_interruptible()
        )
        pending_expiry = (pending or {}).get("expires_at")
        if pending_expiry is None or pending_expiry == "":
            ttl_seconds = (
                float(scheduler.proactive_opportunity_ttl_seconds())
                if hasattr(scheduler, "proactive_opportunity_ttl_seconds")
                else 120.0
            )
            opportunity_expires_at = time.time() + ttl_seconds
        else:
            opportunity_expires_at = float(str(pending_expiry))
        if not self.store.reserve_opportunity(
            frame.workspace_id,
            job_id=job_id,
            request_id=request_id,
            frame_id=frame.frame_id,
            source_kind=frame.source_kind,
            local_date=local_date,
            interruptible=interruptible,
            expires_at=opportunity_expires_at,
        ):
            return False
        event = {
            "type": "completed_turn_followup",
            "tick": max(0, round(frame.source_created_at * 1000)),
            "at": datetime.fromtimestamp(frame.source_created_at, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "trigger_reason": "completed_turn_followup",
            "reason_code": "completed_turn_followup",
            "scene_confidence": float(frame.signals.get("scene_confidence", 0.0) or 0.0),
            "user_work_state": str(frame.signals.get("user_work_state") or "unknown"),
            "expected_benefit": str(frame.signals.get("expected_benefit") or "continue_task"),
            "interrupt_cost": str(frame.signals.get("interrupt_cost") or "low"),
            "activity_category": _activity_category(frame.signals),
            "source_kind": frame.source_kind,
            "source_id": frame.source_id,
            "frame_id": frame.frame_id,
            "session_id": frame.session_id,
            "job_id": job_id,
            "request_id": request_id,
            "expires_at": opportunity_expires_at,
            "content_code": SOURCE_KIND,
            "message": "Would you like to continue where we left off?",
        }
        if not scheduler.emit_proactive_opportunity(event, workspace_id=frame.workspace_id):
            self.store.resolve_opportunity(
                workspace_id=frame.workspace_id,
                job_id=job_id,
                request_id=request_id,
                source_kind=frame.source_kind,
                outcome="failed",
            )
            return False
        return True

    def observe_outcome(self, record: Mapping[str, Any], outcome: str) -> bool:
        if str(record.get("source_kind") or "") != SOURCE_KIND:
            return True
        return self.store.resolve_opportunity(
            workspace_id=str(record.get("workspace_id") or ""),
            job_id=str(record.get("job_id") or ""),
            request_id=str(record.get("request_id") or ""),
            source_kind=str(record.get("source_kind") or ""),
            outcome=outcome,
        )

    def get_settings(self, workspace_id: str) -> dict[str, Any]:
        settings, revision, updated_at = self.store.get_settings_record(workspace_id)
        return {
            **settings.to_api(),
            "workspaceId": workspace_id,
            "revision": revision,
            "updatedAt": updated_at,
        }

    def patch_settings(self, workspace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {
            "expectedRevision",
            "enabled",
            "sourceEnabled",
            "paused",
            "dnd",
            "quietHours",
            "dailyBudget",
            "categoryBudgets",
            "cooldownSeconds",
            "retentionDays",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unknown settings fields: {', '.join(sorted(unknown))}")
        expected_revision = payload.get("expectedRevision")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("expectedRevision must be a non-negative integer")
        patch: dict[str, Any] = {}
        for key in ("enabled", "paused", "dnd"):
            if key in payload:
                if not isinstance(payload[key], bool):
                    raise ValueError(f"{key} must be a boolean")
                patch[key] = payload[key]
        source = payload.get("sourceEnabled")
        if source is not None:
            if not isinstance(source, Mapping) or set(source) != {SOURCE_KIND} or not isinstance(source[SOURCE_KIND], bool):
                raise ValueError(f"sourceEnabled must contain only boolean {SOURCE_KIND}")
            patch["completed_turn_followup_enabled"] = source[SOURCE_KIND]
        quiet = payload.get("quietHours")
        if quiet is not None:
            if not isinstance(quiet, Mapping) or set(quiet) - {"enabled", "start", "end", "timezone"}:
                raise ValueError("quietHours contains unknown fields")
            if "enabled" in quiet and not isinstance(quiet["enabled"], bool):
                raise ValueError("quietHours.enabled must be a boolean")
            mapping = {
                "enabled": "quiet_hours_enabled",
                "start": "quiet_hours_start",
                "end": "quiet_hours_end",
                "timezone": "timezone",
            }
            patch.update({mapping[key]: value for key, value in quiet.items()})
        integer_fields = {
            "dailyBudget": "daily_budget",
            "cooldownSeconds": "cooldown_seconds",
            "retentionDays": "retention_days",
        }
        for external, internal in integer_fields.items():
            if external in payload:
                value = payload[external]
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{external} must be an integer")
                patch[internal] = value
        if "categoryBudgets" in payload:
            category_budgets = payload["categoryBudgets"]
            if not isinstance(category_budgets, Mapping):
                raise ValueError("categoryBudgets must be an object")
            patch["category_budgets"] = dict(category_budgets)
        cancelled_pending: list[dict[str, str]] = []
        settings, revision, updated_at = self.store.patch_settings(
            workspace_id,
            patch,
            expected_revision=expected_revision,
            cancelled_pending=cancelled_pending,
        )
        self._settle_cancelled_opportunities(
            cancelled_pending,
            reason="proactive_policy_changed",
        )
        return {
            **settings.to_api(),
            "workspaceId": workspace_id,
            "revision": revision,
            "updatedAt": updated_at,
        }

    def list_frames(self, workspace_id: str, limit: int = 50) -> dict[str, Any]:
        self._settle_cancelled_opportunities(
            self.store.prune_expired(workspace_id),
            reason="retention_expired",
        )
        frames = self.store.list_frames(workspace_id, limit=limit)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "workspaceId": workspace_id,
            "frames": [frame.to_api() for frame in frames],
        }

    def delete_frame(self, workspace_id: str, frame_id: str) -> bool:
        cancelled_pending: list[dict[str, str]] = []
        deleted = self.store.delete_frame(
            workspace_id,
            frame_id,
            cancelled_pending=cancelled_pending,
        )
        self._settle_cancelled_opportunities(
            cancelled_pending,
            reason="activity_frame_deleted",
        )
        return deleted

    def rebuild(self, workspace_id: str, limit: int = 1000) -> dict[str, Any]:
        projected = 0
        tombstoned = 0
        for commit in self.turn_store.list_commits(workspace_id, limit=limit):
            frame = self.project_event(commit, self.store.get_settings(workspace_id).retention_days)
            if frame is None:
                continue
            if self.store.upsert_frame(frame):
                projected += 1
            else:
                tombstoned += 1
        return {
            "workspaceId": workspace_id,
            "projected": projected,
            "tombstoned": tombstoned,
            "projectionVersion": PROJECTION_VERSION,
        }

    def feedback(self, workspace_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"feedbackId", "jobId", "requestId", "sourceKind", "kind"}
        unknown = set(payload) - allowed
        if unknown or set(payload) != allowed:
            raise ValueError("feedback requires only feedbackId, jobId, requestId, sourceKind, and kind")
        if payload["sourceKind"] != SOURCE_KIND:
            raise ValueError("unknown proactive sourceKind")
        created, source_kind, cancelled = self.store.record_feedback(
            workspace_id,
            feedback_id=str(payload["feedbackId"]),
            job_id=str(payload["jobId"]),
            request_id=str(payload["requestId"]),
            source_kind=str(payload["sourceKind"]),
            kind=str(payload["kind"]),
        )
        if payload["kind"] == "never_source":
            self._cancel_source_pending(
                workspace_id,
                source_kind,
                "feedback_never_source",
            )
        elif cancelled:
            self._settle_cancelled_opportunities(
                [{"job_id": job_id, "request_id": request_id} for job_id, request_id in cancelled],
                reason=f"feedback_{payload['kind']}",
            )
        recorded_at = time.time()
        return {
            "ok": True,
            "duplicate": not created,
            "feedbackId": payload["feedbackId"],
            "sourceKind": source_kind,
            "feedbackKind": payload["kind"],
            "recordedAt": recorded_at,
            "behavioral": payload["kind"] in BEHAVIOR_FEEDBACK_KINDS,
            "cancelledPending": len(cancelled),
        }

    def feedback_summary(self, workspace_id: str) -> dict[str, Any]:
        """Return bounded proactive feedback metrics without source content."""
        return self.store.feedback_summary(workspace_id)

    def _cancel_source_pending(
        self,
        workspace_id: str,
        source_kind: str,
        reason: str,
        *,
        frame_id: str | None = None,
    ) -> int:
        self.store.cancel_pending(
            workspace_id,
            source_kind,
            frame_id=frame_id,
        )
        scheduler = self._scheduler
        if scheduler is None:
            return 0
        return int(
            scheduler.cancel_proactive_opportunities(
                workspace_id=workspace_id,
                source_kind=source_kind,
                reason=reason,
                frame_id=frame_id,
            )
        )

    def _settle_cancelled_opportunities(
        self,
        cancelled: list[dict[str, str]],
        *,
        reason: str,
    ) -> int:
        scheduler = self._scheduler
        if scheduler is None:
            return 0
        resolved = 0
        seen: set[tuple[str, str]] = set()
        for identity in cancelled:
            job_id = identity["job_id"]
            request_id = identity["request_id"]
            key = (job_id, request_id)
            if key in seen:
                continue
            seen.add(key)
            if scheduler.resolve_opportunity(
                job_id=job_id,
                request_id=request_id,
                outcome="cancelled",
                reason=reason,
            ):
                resolved += 1
        return resolved


# Retained as a compatibility helper for callers from earlier phases. It is not
# used as the durable policy authority.
class ProactiveBudget:
    def __init__(self, *, max_events: int = 3, window_seconds: float = 3600.0) -> None:
        if max_events < 1 or window_seconds <= 0:
            raise ValueError("proactive budget values must be positive")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def consume(self, scope: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        events = [stamp for stamp in self._events.get(scope, []) if current - stamp < self.window_seconds]
        if len(events) >= self.max_events:
            self._events[scope] = events
            return False
        self._events[scope] = [*events, current]
        return True

    def remaining(self, scope: str, *, now: float | None = None) -> int:
        current = time.time() if now is None else now
        events = [stamp for stamp in self._events.get(scope, []) if current - stamp < self.window_seconds]
        self._events[scope] = events
        return max(0, self.max_events - len(events))


__all__ = [
    "BEHAVIOR_FEEDBACK_KINDS",
    "FEEDBACK_KINDS",
    "GATE_ORDER",
    "POLICY_VERSION",
    "PROJECTION_VERSION",
    "SOURCE_KIND",
    "ActivityFrame",
    "ActivityFrameService",
    "ActivityFrameStore",
    "ProactiveBudget",
    "ProactiveSettings",
    "deterministic_frame_id",
]
