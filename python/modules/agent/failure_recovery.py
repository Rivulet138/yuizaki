"""Failure classification and authenticated step-resume primitives.

The recovery token is deliberately small and self-contained.  It is an
authorization artifact for one failed plan step, not a serialized execution
history; callers must provide the successful upstream results separately.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from .planner import canonical_json_bytes, strict_json_loads

FailureKind = Literal[
    "validation",
    "policy",
    "permission",
    "timeout",
    "cancel",
    "provider",
    "tool",
    "internal",
    "verification",
]

FAILURE_KINDS: frozenset[str] = frozenset(
    {
        "validation",
        "policy",
        "permission",
        "timeout",
        "cancel",
        "provider",
        "tool",
        "internal",
        "verification",
    }
)

_PROCESS_SECRET = secrets.token_bytes(32)


class ResumeTokenError(ValueError):
    """Raised when a resume token is malformed, stale, or out of scope."""


class ResumeTokenTampered(ResumeTokenError):
    pass


class ResumeTokenExpired(ResumeTokenError):
    pass


class ResumeTokenScopeMismatch(ResumeTokenError):
    pass


@dataclass(frozen=True)
class StepFailure:
    """Stable, transport-friendly description of a failed plan step."""

    step_id: str
    kind: FailureKind
    message: str
    retryable: bool = True
    status: str | None = None
    cause: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.kind not in FAILURE_KINDS:
            raise ValueError(f"unknown failure kind: {self.kind}")
        if not self.step_id:
            raise ValueError("step_id is required")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_failure(
    *,
    status: str | None = None,
    error: str | None = None,
    cause: str | None = None,
    retryable: bool | None = None,
) -> FailureKind:
    """Map execution signals to the closed recovery taxonomy.

    Explicit policy/permission and lifecycle statuses win over message text;
    unknown failures remain ``internal`` rather than creating an open-ended
    taxonomy that callers cannot safely handle.
    """

    normalized = " ".join(str(status or "").lower().replace("-", "_").split())
    status_key = normalized.replace(" ", "_")
    if "validation" in status_key or status_key.startswith("invalid_plan"):
        return "validation"
    if "permission" in status_key:
        return "permission"
    if "policy" in status_key or "forbidden" in status_key or "denied" in status_key:
        return "policy"
    if "timeout" in status_key or "timed_out" in status_key:
        return "timeout"
    if "cancel" in status_key:
        return "cancel"
    if "provider" in status_key or "model" in status_key or "rate_limit" in status_key:
        return "provider"
    if "verification" in status_key or "verify" in status_key:
        return "verification"
    if "tool" in status_key:
        return "tool"
    text = " ".join(str(value or "").lower() for value in (error, cause))
    if any(token in text for token in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(token in text for token in ("cancel", "aborted", "interrupted")):
        return "cancel"
    if any(token in text for token in ("permission", "forbidden", "access denied")):
        return "permission"
    if any(token in text for token in ("policy", "not allowed", "blocked")):
        return "policy"
    if any(token in text for token in ("provider", "rate limit", "model unavailable")):
        return "provider"
    if any(token in text for token in ("process crash", "restart after", "runtime terminated")):
        return "internal"
    return "tool" if status_key in {"error", "failed", "tool_error"} else "internal"


def plan_hash(steps: Sequence[Any]) -> str:
    """Return a SHA-256 hash over a stable topological plan representation."""

    unordered_fields = {
        "depends_on",
        "status_in",
        "status_not_in",
        "content_contains",
        "error_contains",
        "values",
        "all_of",
        "any_of",
        "none_of",
    }

    def normalize(value: Any, *, field: str | None = None) -> Any:
        if isinstance(value, Mapping):
            return {key: normalize(item, field=key) for key, item in value.items()}
        if isinstance(value, list):
            items = [normalize(item) for item in value]
            if field in unordered_fields:
                return sorted(
                    items,
                    key=lambda item: canonical_json_bytes(
                        item, path=f"plan hash field {field}"
                    ),
                )
            return items
        return value

    raw_values = [step.to_dict() if hasattr(step, "to_dict") else step for step in steps]
    canonical_json_bytes(raw_values, path="plan hash input")
    values = [normalize(value) for value in raw_values]
    by_id = {
        str(value.get("id")): value
        for value in values
        if isinstance(value, Mapping) and value.get("id") is not None
    }
    canonical: list[Any] = []
    completed: set[str] = set()
    remaining = set(by_id)
    while remaining:
        ready = sorted(
            step_id
            for step_id in remaining
            if all(str(dep) in completed for dep in (by_id[step_id].get("depends_on") or []))
        )
        if not ready:
            ready = sorted(remaining)
        for step_id in ready:
            canonical.append(by_id[step_id])
            completed.add(step_id)
            remaining.remove(step_id)
    canonical.extend(value for value in values if not isinstance(value, Mapping) or value.get("id") is None)
    encoded = canonical_json_bytes(canonical, path="canonical plan hash")
    return hashlib.sha256(encoded).hexdigest()


def retry_closure(steps: Sequence[Any], failed_step_id: str) -> set[str]:
    """Return the failed step and every transitive downstream dependent."""

    def value(step: Any, key: str, default: Any = None) -> Any:
        if isinstance(step, Mapping):
            return step.get(key, default)
        return getattr(step, key, default)

    ids = {str(value(step, "id")) for step in steps}
    if failed_step_id not in ids:
        raise ResumeTokenScopeMismatch(f"failed step is not in plan: {failed_step_id}")
    closure = {failed_step_id}
    changed = True
    while changed:
        changed = False
        for step in steps:
            step_id = str(value(step, "id"))
            dependencies = value(step, "depends_on", [])
            if step_id not in closure and any(str(dep) in closure for dep in (dependencies or [])):
                closure.add(step_id)
                changed = True
    return closure


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ResumeTokenCodec:
    """Issue and validate HMAC-authenticated resume tokens."""

    version = 1

    def __init__(self, secret: bytes | str | None = None, *, clock: Any = time.time) -> None:
        self._secret = (secret.encode("utf-8") if isinstance(secret, str) else secret) or _PROCESS_SECRET
        self._clock = clock

    def encode(
        self,
        *,
        workspace_id: str | None,
        session_id: str,
        turn_id: str,
        plan_hash_value: str | None = None,
        plan_hash: str | None = None,
        failed_step_id: str = "",
        ttl_seconds: int = 900,
        issued_at: int | None = None,
    ) -> str:
        now = int(self._clock() if issued_at is None else issued_at)
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        resolved_plan_hash = plan_hash_value if plan_hash_value is not None else plan_hash
        if not resolved_plan_hash:
            raise ValueError("plan_hash is required")
        payload = {
            "v": self.version,
            "workspace_id": workspace_id or "",
            "session_id": session_id,
            "turn_id": turn_id,
            "plan_hash": resolved_plan_hash,
            "failed_step_id": failed_step_id,
            "iat": now,
            "exp": now + int(ttl_seconds),
        }
        body = _b64(canonical_json_bytes(payload, path="resume token payload"))
        signature = _b64(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    issue = encode
    create = encode

    def decode(
        self,
        token: str,
        *,
        workspace_id: str | None,
        session_id: str,
        turn_id: str,
        plan_hash_value: str | None = None,
        plan_hash: str | None = None,
        failed_step_id: str = "",
    ) -> dict[str, Any]:
        try:
            body, signature = str(token).split(".", 1)
            expected = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_unb64(signature), expected):
                raise ResumeTokenTampered("invalid resume token signature")
            payload = strict_json_loads(_unb64(body), path="resume token payload")
        except ResumeTokenError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            raise ResumeTokenTampered("malformed resume token") from exc
        if not isinstance(payload, Mapping) or payload.get("v") != self.version:
            raise ResumeTokenTampered("unsupported resume token version")
        payload_dict = dict(payload)
        try:
            expires_at = int(payload_dict["exp"])
            issued_at = int(payload_dict["iat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ResumeTokenTampered("invalid resume token lifetime") from exc
        if expires_at <= issued_at or int(self._clock()) >= expires_at:
            raise ResumeTokenExpired("resume token expired")
        resolved_plan_hash = plan_hash_value if plan_hash_value is not None else plan_hash
        if not resolved_plan_hash:
            raise ValueError("plan_hash is required")
        expected_scope = {
            "workspace_id": workspace_id or "",
            "session_id": session_id,
            "turn_id": turn_id,
            "plan_hash": resolved_plan_hash,
            "failed_step_id": failed_step_id,
        }
        if any(payload_dict.get(key) != value for key, value in expected_scope.items()):
            raise ResumeTokenScopeMismatch("resume token scope does not match request")
        return payload_dict

    verify = decode


class FailureRecoveryManager:
    """Convenience facade used by executors and transports."""

    def __init__(self, secret: bytes | str | None = None, *, clock: Any = time.time) -> None:
        self.codec = ResumeTokenCodec(secret, clock=clock)

    def create_resume_token(self, failure: StepFailure, *, workspace_id: str | None, session_id: str, turn_id: str, steps: Sequence[Any], ttl_seconds: int = 900) -> str:
        return self.codec.encode(
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            plan_hash_value=plan_hash(steps),
            failed_step_id=failure.step_id,
            ttl_seconds=ttl_seconds,
        )

    def validate_resume_token(self, token: str, *, workspace_id: str | None, session_id: str, turn_id: str, steps: Sequence[Any], failed_step_id: str) -> dict[str, Any]:
        return self.codec.decode(
            token,
            workspace_id=workspace_id,
            session_id=session_id,
            turn_id=turn_id,
            plan_hash_value=plan_hash(steps),
            failed_step_id=failed_step_id,
        )

    @staticmethod
    def retry_step_ids(steps: Sequence[Any], failed_step_id: str) -> set[str]:
        return retry_closure(steps, failed_step_id)


__all__ = [
    "FAILURE_KINDS",
    "FailureKind",
    "FailureRecoveryManager",
    "ResumeTokenCodec",
    "ResumeTokenError",
    "ResumeTokenExpired",
    "ResumeTokenScopeMismatch",
    "ResumeTokenTampered",
    "StepFailure",
    "classify_failure",
    "plan_hash",
    "retry_closure",
]
