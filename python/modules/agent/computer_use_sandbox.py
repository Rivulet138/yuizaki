"""Fail-closed evidence contracts for a future isolated GUI agent runtime.

This module does not create a VM, container, or host-input adapter.  It
validates the evidence that an external sandbox executor must provide before a
GUI task can be reported as verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "yuizaki.gui-sandbox.v1"
_ISOLATION_TYPES = {"vm", "container"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_MAX_GUI_STEPS = 128


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "not_verified",
        "claim": "must_not_be_used_as_success",
        "reasons": [{"code": code, "detail": detail}],
    }


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_id(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized if _SAFE_ID_RE.fullmatch(normalized) else None


def validate_sandbox_attestation(
    attestation: Mapping[str, Any] | None,
    *,
    task_id: str | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Validate a host-provided isolation attestation without trusting claims."""
    if not isinstance(attestation, Mapping):
        return _failure("sandbox_attestation_missing", "sandbox attestation is required")
    attestation_id = _safe_id(attestation.get("attestationId"))
    attested_task_id = _safe_id(attestation.get("taskId"))
    nonce = _safe_id(attestation.get("nonce"))
    if not attestation_id or not attested_task_id or not nonce:
        return _failure("sandbox_attestation_identity_missing", "attestationId, taskId and nonce are required")
    if task_id is not None and attested_task_id != str(task_id).strip():
        return _failure("sandbox_attestation_task_mismatch", "sandbox attestation taskId does not match GUI task")
    issued_at = _parse_time(attestation.get("issuedAt"))
    expires_at = _parse_time(attestation.get("expiresAt"))
    reference_now = _parse_time(now) if now is not None else datetime.now(timezone.utc)
    if issued_at is None or expires_at is None or reference_now is None:
        return _failure("sandbox_attestation_time_invalid", "issuedAt, expiresAt and now must be timezone-aware timestamps")
    if issued_at >= expires_at:
        return _failure("sandbox_attestation_time_inverted", "issuedAt must precede expiresAt")
    if reference_now < issued_at or reference_now >= expires_at:
        return _failure("sandbox_attestation_expired", "sandbox attestation is not valid at now")
    sandbox_id = _safe_id(attestation.get("sandboxId"))
    isolation = str(attestation.get("isolation") or "").strip().lower()
    if not sandbox_id:
        return _failure("sandbox_id_invalid", "sandboxId is required")
    if isolation not in _ISOLATION_TYPES:
        return _failure("sandbox_isolation_invalid", "isolation must be vm or container")
    required_flags = {
        "hostAccess": False,
        "emergencyStop": True,
        "userTakeover": True,
        "screenshotPerStep": True,
    }
    for field, expected in required_flags.items():
        if attestation.get(field) is not expected:
            return _failure("sandbox_control_missing", f"sandbox attestation flag {field} is not satisfied")
    network_policy = str(attestation.get("networkPolicy") or "").strip()
    if not network_policy or len(network_policy) > 160:
        return _failure("sandbox_network_policy_missing", "networkPolicy is required")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "attested",
        "attestationId": attestation_id,
        "taskId": attested_task_id,
        "issuedAt": issued_at.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "nonce": nonce,
        "sandboxId": sandbox_id,
        "isolation": isolation,
        "networkPolicy": network_policy,
        "controls": {field: expected for field, expected in required_flags.items()},
    }


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value.strip().lower()))


def evaluate_gui_task(
    task: Mapping[str, Any] | None,
    *,
    attestation: Mapping[str, Any] | None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Accept a GUI task only when every step has independently verifiable evidence."""
    if not isinstance(task, Mapping):
        return _failure("gui_task_missing", "GUI task evidence is required")
    task_id = _safe_id(task.get("taskId"))
    steps = task.get("steps")
    if (
        not task_id
        or not isinstance(steps, Sequence)
        or isinstance(steps, (str, bytes))
        or not steps
        or len(steps) > _MAX_GUI_STEPS
    ):
        return _failure("gui_task_steps_invalid", "taskId and at least one step are required")
    attestation_result = validate_sandbox_attestation(attestation, task_id=task_id, now=now)
    if attestation_result["status"] != "attested":
        return {**attestation_result, "taskId": task_id[:160], "taskStatus": "not_verified"}
    if not _valid_digest(task.get("objectiveDigest")):
        return {**_failure("gui_task_objective_missing", "objectiveDigest must be a SHA-256 digest"), "taskId": task_id[:160], "taskStatus": "not_verified"}

    normalized_steps: list[dict[str, Any]] = []
    reasons: list[dict[str, str]] = []
    seen_step_ids: set[str] = set()
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, Mapping):
            reasons.append({"code": "gui_step_invalid", "detail": f"step {index + 1} is not an object"})
            continue
        step_id = _safe_id(raw_step.get("stepId"))
        step_index = raw_step.get("stepIndex", index)
        verification_status = str(raw_step.get("verificationStatus") or "").strip().lower()
        if (
            not step_id
            or step_id in seen_step_ids
            or isinstance(step_index, bool)
            or not isinstance(step_index, int)
            or step_index != index
            or verification_status not in {"verified", "unverified", "error", "unknown_effect"}
        ):
            reasons.append({"code": "gui_step_contract_invalid", "detail": f"step {index + 1} lacks a valid stepId or verificationStatus"})
            continue
        seen_step_ids.add(step_id)
        if not _valid_digest(raw_step.get("preStateSha256")) or not _valid_digest(raw_step.get("postStateSha256")):
            reasons.append({"code": "gui_step_state_evidence_missing", "detail": f"step {step_id} lacks pre/post state digests"})
            continue
        if not _valid_digest(raw_step.get("actionDigest")):
            reasons.append({"code": "gui_step_action_evidence_missing", "detail": f"step {step_id} lacks actionDigest"})
            continue
        evidence_ids = raw_step.get("evidenceIds")
        if not isinstance(evidence_ids, Sequence) or isinstance(evidence_ids, (str, bytes)):
            reasons.append({"code": "gui_step_evidence_missing", "detail": f"step {step_id} lacks evidenceIds"})
            continue
        raw_evidence = [str(item).strip() for item in evidence_ids if str(item).strip()]
        if any(_safe_id(item) is None for item in raw_evidence):
            reasons.append({"code": "gui_step_evidence_invalid", "detail": f"step {step_id} has an unsafe evidence ID"})
            continue
        bounded_evidence = raw_evidence[:8]
        if not bounded_evidence:
            reasons.append({"code": "gui_step_evidence_missing", "detail": f"step {step_id} has no evidence IDs"})
            continue
        verifier_ids = raw_step.get("verifierEvidenceIds")
        if not isinstance(verifier_ids, Sequence) or isinstance(verifier_ids, (str, bytes)):
            reasons.append({"code": "gui_step_verifier_evidence_missing", "detail": f"step {step_id} lacks verifierEvidenceIds"})
            continue
        raw_verifier = [str(item).strip() for item in verifier_ids if str(item).strip()]
        if any(_safe_id(item) is None for item in raw_verifier):
            reasons.append({"code": "gui_step_verifier_evidence_invalid", "detail": f"step {step_id} has an unsafe verifier evidence ID"})
            continue
        bounded_verifier = raw_verifier[:8]
        if not bounded_verifier or any(item not in bounded_evidence for item in bounded_verifier):
            reasons.append({"code": "gui_step_verifier_evidence_unbound", "detail": f"step {step_id} verifier evidence is not bound to evidenceIds"})
            continue
        screenshot_evidence_id = _safe_id(raw_step.get("screenshotEvidenceId"))
        if not screenshot_evidence_id or screenshot_evidence_id not in bounded_evidence:
            reasons.append({"code": "gui_screenshot_evidence_missing", "detail": f"step {step_id} lacks a referenced screenshot evidence ID"})
            continue
        human_takeover = raw_step.get("humanTakeover") is True
        takeover_reason = str(raw_step.get("takeoverReason") or "").strip()[:240]
        if human_takeover and not takeover_reason:
            reasons.append({"code": "gui_takeover_reason_missing", "detail": f"step {step_id} takeover has no reason"})
            continue
        normalized_steps.append({
            "stepId": step_id[:160],
            "stepIndex": index,
            "verificationStatus": verification_status,
            "actionDigest": str(raw_step["actionDigest"]).lower(),
            "preStateSha256": str(raw_step["preStateSha256"]).lower(),
            "postStateSha256": str(raw_step["postStateSha256"]).lower(),
            "evidenceIds": bounded_evidence,
            "verifierEvidenceIds": bounded_verifier,
            "screenshotEvidenceId": screenshot_evidence_id,
            "humanTakeover": human_takeover,
            **({"takeoverReason": takeover_reason} if human_takeover else {}),
        })
        if verification_status != "verified":
            reasons.append({"code": "gui_step_not_verified", "detail": f"step {step_id} is {verification_status}"})

        if len(normalized_steps) > 1:
            previous = normalized_steps[-2]
            if normalized_steps[-1]["preStateSha256"] != previous["postStateSha256"]:
                reasons.append({"code": "gui_state_chain_break", "detail": f"step {step_id} does not continue the previous post-state"})

    if len(normalized_steps) != len(steps):
        reasons.append({"code": "gui_step_count_mismatch", "detail": "one or more GUI steps failed evidence validation"})
    if reasons:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "not_verified",
            "claim": "must_not_be_used_as_success",
            "sandbox": attestation_result,
            "taskId": task_id[:160],
            "objectiveDigest": str(task.get("objectiveDigest") or "").lower(),
            "taskStatus": "not_verified",
            "steps": normalized_steps,
            "reasons": reasons,
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "verified",
        "claim": "task_result_verified",
        "sandbox": attestation_result,
        "taskId": task_id[:160],
        "objectiveDigest": str(task["objectiveDigest"]).lower(),
        "taskStatus": "completed",
        "steps": normalized_steps,
        "reasons": [],
    }


def evidence_digest(payload: Mapping[str, Any]) -> str:
    """Return a deterministic digest for an evidence bundle, not its contents."""
    encoded = json.dumps(dict(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def summarize_gui_task_results(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate bounded task/step metrics for sandbox replay gates."""
    all_rows = list(results)
    rows = [row for row in all_rows if _is_aggregatable_result(row)]
    task_count = len(rows)
    verified_tasks = sum(row.get("status") == "verified" for row in rows)
    attested_tasks = sum(isinstance(row.get("sandbox"), Mapping) and row["sandbox"].get("status") == "attested" for row in rows)
    step_rows = [step for row in rows for step in (row.get("steps") or []) if isinstance(step, Mapping)]
    verified_steps = sum(step.get("verificationStatus") == "verified" for step in step_rows)
    unknown_steps = sum(step.get("verificationStatus") == "unknown_effect" for step in step_rows)
    takeover_steps = sum(step.get("humanTakeover") is True for step in step_rows)
    step_count = len(step_rows)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taskCount": task_count,
        "verifiedTaskRate": round(verified_tasks / task_count, 4) if task_count else 0.0,
        "attestedTaskRate": round(attested_tasks / task_count, 4) if task_count else 0.0,
        "stepCount": step_count,
        "stepVerificationRate": round(verified_steps / step_count, 4) if step_count else 0.0,
        "unknownEffectSteps": unknown_steps,
        "humanTakeoverSteps": takeover_steps,
        "rejectedRows": len(all_rows) - len(rows),
    }


def _is_aggregatable_result(row: Any) -> bool:
    if not isinstance(row, Mapping) or row.get("schemaVersion") != SCHEMA_VERSION or row.get("status") not in {"verified", "not_verified"}:
        return False
    sandbox = row.get("sandbox")
    task_id = str(row.get("taskId") or "").strip()
    if not isinstance(sandbox, Mapping) or sandbox.get("status") != "attested" or sandbox.get("taskId") != task_id:
        return False
    required_attestation = ("attestationId", "taskId", "issuedAt", "expiresAt", "nonce", "sandboxId", "isolation", "networkPolicy")
    if any(not str(sandbox.get(field) or "").strip() for field in required_attestation):
        return False
    expected_task_status = "completed" if row.get("status") == "verified" else "not_verified"
    if not task_id or row.get("taskStatus") != expected_task_status or not _valid_digest(row.get("objectiveDigest")):
        return False
    steps = row.get("steps")
    return isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)) and bool(steps) and all(
        isinstance(step, Mapping)
        and isinstance(step.get("stepId"), str)
        and isinstance(step.get("stepIndex"), int)
        and _valid_digest(step.get("actionDigest"))
        and _valid_digest(step.get("preStateSha256"))
        and _valid_digest(step.get("postStateSha256"))
        and isinstance(step.get("verifierEvidenceIds"), Sequence)
        and isinstance(step.get("evidenceIds"), Sequence)
        and isinstance(step.get("screenshotEvidenceId"), str)
        and bool(step.get("verifierEvidenceIds"))
        and all(item in (step.get("evidenceIds") or []) for item in step.get("verifierEvidenceIds") or [])
        for step in steps
    )


__all__ = ["SCHEMA_VERSION", "evaluate_gui_task", "evidence_digest", "summarize_gui_task_results", "validate_sandbox_attestation"]
