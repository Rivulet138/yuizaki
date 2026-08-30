"""Small, side-effect-free result verification contract.

Tool handlers and probes historically returned loosely shaped dictionaries.
This module gives both paths a stable, privacy-conscious representation without
making verification itself responsible for executing or authorizing a tool.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

VerificationStatus = Literal["verified", "unverified", "error", "cancelled"]


def normalize_verification_status(value: Any, *, default: VerificationStatus = "unverified") -> VerificationStatus:
    marker = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if marker in {"verified", "passed", "success", "succeeded", "ok"}:
        return "verified"
    if marker in {"error", "failed", "failure", "timeout", "timed_out"}:
        return "error"
    if marker in {"cancelled", "canceled", "interrupted"}:
        return "cancelled"
    return default


def summarize_parameters(parameters: Any) -> dict[str, Any]:
    """Return metadata only; never copy parameter values into an event."""
    if not isinstance(parameters, dict):
        return {"kind": type(parameters).__name__}
    keys = sorted(str(key) for key in parameters)
    try:
        encoded = json.dumps(parameters, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError, OverflowError):  # pragma: no cover - defensive fallback
        encoded = repr(parameters)
    return {
        "kind": "object",
        "count": len(keys),
        "keys": keys[:32],
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    }


@dataclass(frozen=True)
class ResultVerification:
    target: str
    parameters_summary: dict[str, Any]
    verification_status: VerificationStatus
    evidence: tuple[str, ...] = ()
    retryability: bool = False
    unknown_effect: bool = False

    def to_event_data(self) -> dict[str, Any]:
        """Expose the stable contract using transport-friendly camelCase keys."""
        return {
            "verificationTarget": self.target,
            "verificationParameters": self.parameters_summary,
            "verificationStatus": self.verification_status,
            "verificationEvidence": list(self.evidence),
            "verificationRetryable": self.retryability,
            "unknownEffect": self.unknown_effect,
        }


def build_result_verification(
    *,
    target: str,
    parameters: Any,
    raw: Any = None,
    default_status: VerificationStatus = "unverified",
    evidence_limit: int = 6,
    text_limit: int = 360,
    retryability: bool | None = None,
    unknown_effect: bool = False,
) -> ResultVerification:
    """Normalize bool/dict/provider verifier output into one immutable contract."""
    status = normalize_verification_status(
        raw.get("status") if isinstance(raw, dict) else ("verified" if raw is True else raw),
        default=default_status,
    )
    values: Any = raw.get("evidence") if isinstance(raw, dict) else None
    if values is None:
        values = []
    if not isinstance(values, (list, tuple)):
        values = [values]
    evidence: list[str] = []
    for item in values:
        text = " ".join(str(item or "").split())
        if text:
            evidence.append(text[: max(1, text_limit)])
        if len(evidence) >= max(0, evidence_limit):
            break
    resolved_retryability = False if unknown_effect else (
        bool(retryability)
        if retryability is not None
        else status in {"unverified", "error"}
    )
    return ResultVerification(
        target=str(target),
        parameters_summary=summarize_parameters(parameters),
        verification_status=status,
        evidence=tuple(evidence),
        retryability=resolved_retryability,
        unknown_effect=bool(unknown_effect),
    )
