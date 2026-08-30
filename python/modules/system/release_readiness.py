"""Fail-closed release readiness and long-running soak evidence.

The platform capability endpoint describes what the current runtime can infer;
it is deliberately not a device qualification.  This module adds the missing
release gate without probing devices or treating implementation presence as
evidence.  A gate can pass only when an explicit platform qualification and a
complete soak report are supplied.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

from .platform_capabilities import build_platform_capability_snapshot

SCHEMA_VERSION = 1
REQUIRED_PLATFORM_CAPABILITIES = ("desktop", "live2d_vrm", "text_voice")
DEFAULT_SOAK_BUDGETS: dict[str, float] = {
    "min_duration_seconds": 86_400.0,
    "max_rss_growth_ratio": 0.15,
    "max_handle_growth_ratio": 0.10,
    "max_gpu_growth_ratio": 0.20,
    "max_cpu_p95": 40.0,
}
_SOAK_BUDGET_KEYS = frozenset(DEFAULT_SOAK_BUDGETS)


def _failure(reason: str, detail: str) -> dict[str, Any]:
    return {"status": "not_qualified", "reasons": [{"code": reason, "detail": detail}]}


def _evidence_digest(value: Mapping[str, Any] | None) -> str | None:
    """Fingerprint evidence without projecting its contents into the gate."""
    if not isinstance(value, Mapping):
        return None
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _qualification_summary(value: Mapping[str, Any], target: str) -> dict[str, str]:
    """Project only non-sensitive qualification identity into the public report."""
    return {
        "status": "qualified" if value.get("status") == "qualified" else "not_qualified",
        "targetPlatform": target,
    }


def _growth_ratio(samples: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for sample in samples:
        value = sample.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            return None
        values.append(float(value))
    if len(values) < 2:
        return None
    baseline = values[0]
    if baseline == 0:
        return 0.0 if values[-1] == 0 else math.inf
    return (values[-1] - baseline) / baseline


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _validated_budgets(budgets: Mapping[str, float] | None) -> tuple[dict[str, float] | None, str | None]:
    active = dict(DEFAULT_SOAK_BUDGETS)
    if budgets is None:
        return active, None
    if not isinstance(budgets, Mapping):
        return None, "驻留预算必须是对象"
    unknown = [str(key) for key in budgets if not isinstance(key, str) or key not in _SOAK_BUDGET_KEYS]
    if unknown:
        return None, f"驻留预算包含未知字段：{','.join(str(item) for item in unknown)[:160]}"
    for key, value in budgets.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None, f"驻留预算不是有限数值：{key}"
        if float(value) < 0 or (key == "min_duration_seconds" and float(value) <= 0):
            return None, f"驻留预算必须非负且最小时长必须为正：{key}"
        active[key] = float(value)
    return active, None


def evaluate_soak_report(
    report: Mapping[str, Any] | None,
    *,
    budgets: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate explicit host samples; missing or malformed evidence fails closed."""

    if not isinstance(report, Mapping):
        return _failure("soak_report_missing", "24 小时驻留采样报告未提供")
    if report.get("schemaVersion") != SCHEMA_VERSION:
        return _failure("soak_schema_invalid", "驻留采样报告 schemaVersion 不匹配")
    samples = report.get("samples")
    if not isinstance(samples, Sequence) or isinstance(samples, (str, bytes)):
        return _failure("soak_samples_missing", "驻留采样报告缺少 samples")
    normalized = [sample for sample in samples if isinstance(sample, Mapping)]
    if len(normalized) != len(samples) or len(normalized) < 2:
        return _failure("soak_samples_invalid", "驻留采样至少需要两条结构化采样")

    active_budgets, budget_error = _validated_budgets(budgets)
    if active_budgets is None:
        return _failure("soak_budget_invalid", budget_error or "驻留预算无效")
    timestamps: list[float] = []
    for sample in normalized:
        value = sample.get("timestampSeconds")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            return _failure("soak_timestamp_invalid", "每条驻留采样必须包含有限 timestampSeconds")
        timestamps.append(float(value))
    if any(current <= previous for previous, current in pairwise(timestamps)):
        return _failure("soak_timestamp_not_monotonic", "驻留采样 timestampSeconds 必须严格递增")
    sample_span = timestamps[-1] - timestamps[0]
    duration = report.get("durationSeconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(float(duration)):
        return _failure("soak_duration_invalid", "驻留时长不是有限数值")
    if float(duration) < active_budgets["min_duration_seconds"]:
        return _failure("soak_duration_short", "驻留时长未达到 24 小时验收门槛")
    if sample_span < active_budgets["min_duration_seconds"]:
        return _failure("soak_sample_span_short", "驻留采样时间跨度未达到验收门槛")
    if abs(float(duration) - sample_span) > max(1.0, float(duration) * 0.01):
        return _failure("soak_duration_mismatch", "报告声明时长与采样时间跨度不一致")

    checks: dict[str, Any] = {
        "durationSeconds": float(duration),
        "sampleSpanSeconds": sample_span,
        "sampleCount": len(normalized),
    }
    for field, budget_key in (
        ("rssBytes", "max_rss_growth_ratio"),
        ("openHandles", "max_handle_growth_ratio"),
        ("gpuBytes", "max_gpu_growth_ratio"),
    ):
        growth = _growth_ratio(normalized, field)
        if growth is None:
            return _failure("soak_metric_invalid", f"驻留采样缺少或包含非法指标：{field}")
        checks[field] = {"growthRatio": growth, "budget": active_budgets[budget_key], "passed": growth <= active_budgets[budget_key]}
        if not checks[field]["passed"]:
            return _failure("soak_growth_exceeded", f"{field} 增长超过预算")

    cpu_values: list[float] = []
    for sample in normalized:
        value = sample.get("cpuPct")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
            return _failure("soak_metric_invalid", "驻留采样缺少或包含非法指标：cpuPct")
        cpu_values.append(float(value))
    cpu_p95 = _p95(cpu_values)
    assert cpu_p95 is not None
    checks["cpuPct"] = {"p95": cpu_p95, "budget": active_budgets["max_cpu_p95"], "passed": cpu_p95 <= active_budgets["max_cpu_p95"]}
    if not checks["cpuPct"]["passed"]:
        return _failure("soak_cpu_budget_exceeded", "CPU p95 超过驻留预算")
    return {"status": "pass", "reasons": [], "checks": checks}


def build_release_readiness_snapshot(
    *,
    capability_snapshot: Mapping[str, Any] | None = None,
    platform_qualification: Mapping[str, Any] | None = None,
    soak_report: Mapping[str, Any] | None = None,
    target_platform: str | None = None,
) -> dict[str, Any]:
    """Return a machine-readable release gate for the current target platform."""

    capabilities = build_platform_capability_snapshot() if capability_snapshot is None else capability_snapshot
    if not isinstance(capabilities, Mapping):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "not_qualified",
            "targetPlatform": target_platform or "unknown",
            "platformCapabilities": None,
            "soak": evaluate_soak_report(soak_report),
            "evidence": {
                "platformAttestationSha256": _evidence_digest(platform_qualification),
                "soakReportSha256": _evidence_digest(soak_report),
            },
            "reasons": [{"code": "capability_snapshot_invalid", "detail": "平台能力快照必须是对象"}],
            "claim": "must_not_be_used_as_release_qualification",
        }
    host = capabilities.get("host")
    system = str(host.get("system", "unknown") if isinstance(host, Mapping) else "unknown").lower()
    target = target_platform or {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(system, system)
    rows = capabilities.get("platforms", [])
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
    row = next((item for item in rows if isinstance(item, Mapping) and item.get("id") == target), None)
    reasons: list[dict[str, str]] = []
    if not isinstance(row, Mapping) or not row.get("host"):
        reasons.append({"code": "target_not_host", "detail": f"目标平台未在当前主机上运行：{target}"})
    else:
        capability_rows = row.get("capabilities")
        if not isinstance(capability_rows, Mapping):
            reasons.append({"code": "platform_capabilities_missing", "detail": "目标平台能力矩阵缺失"})
        else:
            for capability in REQUIRED_PLATFORM_CAPABILITIES:
                status = capability_rows.get(capability, {}).get("status") if isinstance(capability_rows.get(capability), Mapping) else None
                if status != "available":
                    reasons.append({"code": "platform_capability_unqualified", "detail": f"目标平台能力未达到 available：{capability}"})
    qualification_target = None
    if isinstance(platform_qualification, Mapping):
        raw_target = platform_qualification.get("targetPlatform") or platform_qualification.get("platform")
        if isinstance(raw_target, str) and raw_target.strip():
            qualification_target = raw_target.strip().lower()
    if not isinstance(platform_qualification, Mapping) or platform_qualification.get("status") != "qualified":
        reasons.append({"code": "platform_attestation_missing", "detail": "缺少目标机显式平台/设备资格证明"})
    elif qualification_target is None:
        reasons.append({"code": "platform_attestation_target_missing", "detail": "平台资格证明缺少 targetPlatform"})
    elif qualification_target != target:
        reasons.append({"code": "platform_attestation_target_mismatch", "detail": "平台资格证明与目标平台不一致"})
    soak = evaluate_soak_report(soak_report)
    evidence = {
        "platformAttestationSha256": _evidence_digest(platform_qualification),
        "soakReportSha256": _evidence_digest(soak_report),
    }
    if isinstance(platform_qualification, Mapping) and evidence["platformAttestationSha256"] is None:
        reasons.append({"code": "platform_attestation_fingerprint_invalid", "detail": "平台资格证明无法生成稳定 SHA-256 指纹"})
    if isinstance(soak_report, Mapping) and evidence["soakReportSha256"] is None:
        reasons.append({"code": "soak_fingerprint_invalid", "detail": "驻留报告无法生成稳定 SHA-256 指纹"})
    if soak["status"] != "pass":
        reasons.extend(soak["reasons"])
    if reasons:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "not_qualified",
            "targetPlatform": target,
            "platformCapabilities": row,
            "soak": soak,
            "evidence": evidence,
            "reasons": reasons,
            "claim": "must_not_be_used_as_release_qualification",
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "qualified",
        "targetPlatform": target,
        "platformCapabilities": row,
        "platformQualification": _qualification_summary(platform_qualification, target),
        "soak": soak,
        "evidence": evidence,
        "reasons": [],
        "claim": "product_release_gate_passed",
    }


__all__ = ["DEFAULT_SOAK_BUDGETS", "SCHEMA_VERSION", "build_release_readiness_snapshot", "evaluate_soak_report"]
