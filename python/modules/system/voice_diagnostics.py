"""Low-overhead, evidence-aware voice reliability diagnostics."""

from __future__ import annotations

import math
import re
import secrets
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

VoiceStage = Literal[
    "capture",
    "asr",
    "asr_final",
    "llm",
    "first_token",
    "tts",
    "first_audio",
    "interruption",
    "playback",
    "playback_recovery",
    "round_trip",
]
VoiceEvidenceKind = Literal["synthetic_fixture", "real_device"]

REAL_DEVICE_REQUIRED_STAGES: tuple[str, ...] = (
    "asr_final",
    "first_token",
    "first_audio",
    "interruption",
    "playback_recovery",
)
RECOVERY_REQUIRED_STAGES: tuple[str, ...] = ("interruption", "playback_recovery")
MIN_REAL_DEVICE_SAMPLES_PER_STAGE = 5
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,95}$")
_SECRET_RE = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[=:]\s*|token\s*[=:]\s*|secret\s*[=:]\s*)")


@dataclass(frozen=True)
class VoiceEvidenceProvenance:
    """Reproducibility fields for one fixture or real-device measurement run."""

    kind: VoiceEvidenceKind = "synthetic_fixture"
    machine: str | None = None
    platform: str | None = None
    runtime: str | None = None
    provider: str | None = None
    model: str | None = None
    input_device: str | None = None
    output_device: str | None = None
    power_profile: str | None = None
    sample_rate_hz: int | None = None
    channel_count: int | None = None
    echo_cancellation: bool | None = None
    noise_suppression: bool | None = None
    vad_profile: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("synthetic_fixture", "real_device"):
            raise ValueError("unsupported voice evidence kind")
        if self.sample_rate_hz is not None and self.sample_rate_hz < 1:
            raise ValueError("sample_rate_hz must be positive")
        if self.channel_count is not None and self.channel_count < 1:
            raise ValueError("channel_count must be positive")

    def missing_real_device_fields(self) -> tuple[str, ...]:
        if self.kind != "real_device":
            return ()
        required = {
            "machine": self.machine,
            "platform": self.platform,
            "runtime": self.runtime,
            "provider": self.provider,
            "model": self.model,
            "input_device": self.input_device,
            "output_device": self.output_device,
            "power_profile": self.power_profile,
            "sample_rate_hz": self.sample_rate_hz,
            "channel_count": self.channel_count,
            "echo_cancellation": self.echo_cancellation,
            "noise_suppression": self.noise_suppression,
            "vad_profile": self.vad_profile,
        }
        return tuple(
            name
            for name, value in required.items()
            if value is None or (isinstance(value, str) and not value.strip())
        )

    def snapshot(self) -> dict[str, object]:
        safe = _safe_label
        return {
            "kind": self.kind,
            "machine": safe(self.machine),
            "platform": safe(self.platform),
            "runtime": safe(self.runtime),
            "provider": safe(self.provider),
            "model": safe(self.model),
            "input_device": safe(self.input_device),
            "output_device": safe(self.output_device),
            "power_profile": safe(self.power_profile),
            "sample_rate_hz": self.sample_rate_hz,
            "channel_count": self.channel_count,
            "echo_cancellation": self.echo_cancellation,
            "noise_suppression": self.noise_suppression,
            "vad_profile": safe(self.vad_profile),
        }


@dataclass(frozen=True)
class VoiceDiagnosticSample:
    stage: str
    latency_ms: float
    ok: bool = True
    provider: str | None = None
    error_kind: str | None = None
    request_id: str | None = None
    run_id: str | None = None
    provenance: VoiceEvidenceProvenance = field(default_factory=VoiceEvidenceProvenance)
    recovered: bool | None = None
    recovery_latency_ms: float | None = None
    playback_underruns: int | None = None
    recorded_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not str(self.stage).strip():
            raise ValueError("stage is required")
        _validate_latency(self.latency_ms, "latency_ms")
        if self.recovery_latency_ms is not None:
            _validate_latency(self.recovery_latency_ms, "recovery_latency_ms")
        if self.playback_underruns is not None and self.playback_underruns < 0:
            raise ValueError("playback_underruns must be non-negative")


class VoiceMeasurementHandle:
    """Opaque capability for recording into one measurement run."""

    __slots__ = ("_run_id", "_token")

    def __init__(self, run_id: str, token: object) -> None:
        self._run_id = run_id
        self._token = token

    @property
    def run_id(self) -> str:
        return self._run_id


DEFAULT_VOICE_LATENCY_BUDGETS_MS: dict[str, float] = {"interruption": 250.0}


def _clean(value: object) -> str | None:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def _safe_label(value: object) -> str | None:
    cleaned = _clean(value)
    if cleaned is None or len(cleaned) > 96 or _SECRET_RE.search(cleaned) or not _SAFE_LABEL_RE.fullmatch(cleaned):
        return "[redacted]" if cleaned else None
    return cleaned


def _safe_status(value: object, *, depth: int = 0) -> object:
    """Project provider status without allowing arbitrary strings to escape."""
    if depth > 3:
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _safe_label(value)
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for key, item in value.items():
            safe_key = _safe_label(key) or "[redacted]"
            if re.search(r"(?i)(api[_-]?key|token|secret|password|authorization)", str(key)):
                projected[safe_key] = "[redacted]"
            else:
                projected[safe_key] = _safe_status(item, depth=depth + 1)
        return projected
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_safe_status(item, depth=depth + 1) for item in value]
    return "[redacted]"


def _validate_latency(value: float, field_name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values.sort()
    position = min(len(values) - 1, max(0.0, (len(values) - 1) * fraction))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(values[lower], 2)
    weight = position - lower
    return round(values[lower] + (values[upper] - values[lower]) * weight, 2)


def _stage_summary(entries: Sequence[VoiceDiagnosticSample]) -> dict[str, Any]:
    latencies = [entry.latency_ms for entry in entries]
    failures = [entry for entry in entries if not entry.ok]
    recovery_entries = [entry for entry in entries if entry.recovered is not None]
    recovery_latencies = [
        entry.recovery_latency_ms
        for entry in recovery_entries
        if entry.recovery_latency_ms is not None
    ]
    recovery_successes = sum(entry.recovered is True for entry in recovery_entries)
    return {
        "count": len(entries),
        "ok": len(entries) - len(failures),
        "error_count": len(failures),
        "error_rate": round(len(failures) / len(entries), 4) if entries else None,
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "providers": sorted({entry.provider for entry in entries if entry.provider}),
        "errors": sorted({entry.error_kind for entry in failures if entry.error_kind}),
        "recovery_attempts": len(recovery_entries),
        "recovery_successes": recovery_successes,
        "recovery_success_rate": (
            round(recovery_successes / len(recovery_entries), 4)
            if recovery_entries
            else None
        ),
        "recovery_p50_ms": _percentile(recovery_latencies, 0.50),
        "recovery_p95_ms": _percentile(recovery_latencies, 0.95),
        "playback_underruns": sum(entry.playback_underruns or 0 for entry in entries),
        "evidence_kinds": sorted({entry.provenance.kind for entry in entries}),
    }


class VoiceDiagnostics:
    """Bounded sample store suitable for API snapshots and local reports."""

    def __init__(
        self, *, max_samples: int = 512, p95_warning_ms: float = 1500.0
    ) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be positive")
        self._samples: deque[VoiceDiagnosticSample] = deque(maxlen=max_samples)
        self.p95_warning_ms = float(p95_warning_ms)
        self._run_id = self._new_run_id()
        self._measurement_token: object = object()

    @staticmethod
    def _new_run_id() -> str:
        return f"voice-run-{secrets.token_urlsafe(12)}"

    @property
    def run_id(self) -> str:
        return self._run_id

    def begin_run(self, run_id: str | None = None) -> str:
        """Start an isolated measurement run and discard prior samples."""
        candidate = _safe_label(run_id) if run_id is not None else None
        self._run_id = candidate or self._new_run_id()
        self._measurement_token = object()
        self._samples.clear()
        return self._run_id

    def begin_measurement(self, run_id: str | None = None) -> VoiceMeasurementHandle:
        """Start a run and return an opaque handle for its asynchronous callbacks."""
        selected_run_id = self.begin_run(run_id)
        return VoiceMeasurementHandle(selected_run_id, self._measurement_token)

    def _resolve_run_id(
        self,
        *,
        run_id: str | None,
        handle: VoiceMeasurementHandle | None,
    ) -> str:
        selected_run_id = _safe_label(run_id)
        if handle is not None:
            if not isinstance(handle, VoiceMeasurementHandle) or handle._token is not self._measurement_token:
                raise ValueError("voice diagnostics measurement handle is stale")
            if selected_run_id is not None and selected_run_id != handle.run_id:
                raise ValueError("voice diagnostics run does not match measurement handle")
            selected_run_id = handle.run_id
        if selected_run_id is not None and selected_run_id != self._run_id:
            raise ValueError("voice diagnostics run is stale")
        return selected_run_id or self._run_id

    def record(
        self,
        stage: VoiceStage | str,
        latency_ms: float,
        *,
        ok: bool = True,
        provider: str | None = None,
        error_kind: str | None = None,
        request_id: str | None = None,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
        provenance: VoiceEvidenceProvenance | None = None,
        recovered: bool | None = None,
        recovery_latency_ms: float | None = None,
        playback_underruns: int | None = None,
    ) -> VoiceDiagnosticSample:
        evidence = provenance or VoiceEvidenceProvenance()
        selected_run_id = self._resolve_run_id(run_id=run_id, handle=handle)
        sample = VoiceDiagnosticSample(
            stage=str(stage).strip(),
            latency_ms=float(latency_ms),
            ok=bool(ok),
            provider=_safe_label(provider) or _safe_label(evidence.provider),
            error_kind=_safe_label(error_kind),
            request_id=_safe_label(request_id),
            run_id=selected_run_id,
            provenance=evidence,
            recovered=recovered,
            recovery_latency_ms=(
                float(recovery_latency_ms) if recovery_latency_ms is not None else None
            ),
            playback_underruns=playback_underruns,
        )
        self._samples.append(sample)
        return sample

    def record_elapsed(
        self, stage: VoiceStage | str, started_at: float, **kwargs: Any
    ) -> VoiceDiagnosticSample:
        return self.record(
            stage, max(0.0, (time.monotonic() - started_at) * 1000.0), **kwargs
        )

    def samples(self, *, stage: str | None = None) -> tuple[VoiceDiagnosticSample, ...]:
        return tuple(
            sample for sample in self._samples if stage is None or sample.stage == stage
        )

    def snapshot(self) -> dict[str, Any]:
        grouped: dict[str, list[VoiceDiagnosticSample]] = {}
        for sample in self._samples:
            grouped.setdefault(sample.stage, []).append(sample)
        stages: dict[str, dict[str, Any]] = {}
        recommendations: list[str] = []
        for stage, entries in grouped.items():
            summary = _stage_summary(entries)
            stages[stage] = summary
            p95 = summary["p95_ms"]
            if p95 is not None and p95 > self.p95_warning_ms:
                recommendations.append(
                    f"{stage}: p95 latency {p95}ms exceeds {self.p95_warning_ms:g}ms; inspect provider/network or warmup"
                )
            if summary["error_count"]:
                recommendations.append(
                    f"{stage}: {summary['error_count']} failures; review errors and provider readiness"
                )
        evidence_kinds = sorted({sample.provenance.kind for sample in self._samples})
        return {
            "sample_count": len(self._samples),
            "run_id": self._run_id,
            "stages": stages,
            "evidence_kinds": evidence_kinds,
            "evidence_claim": (
                "real_device_measurement_requires_qualification"
                if "real_device" in evidence_kinds
                else "synthetic_regression_only"
            ),
            "recommendations": recommendations,
            "generated_at": time.time(),
        }

    def qualification_snapshot(
        self,
        *,
        min_samples_per_stage: int = MIN_REAL_DEVICE_SAMPLES_PER_STAGE,
        required_stages: Sequence[str] = REAL_DEVICE_REQUIRED_STAGES,
        recovery_stages: Sequence[str] = RECOVERY_REQUIRED_STAGES,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
    ) -> dict[str, Any]:
        """Return a fail-closed qualification matrix for real-device evidence."""
        if min_samples_per_stage < MIN_REAL_DEVICE_SAMPLES_PER_STAGE:
            raise ValueError(
                f"min_samples_per_stage must be at least {MIN_REAL_DEVICE_SAMPLES_PER_STAGE}"
            )
        required_stage_set = set(REAL_DEVICE_REQUIRED_STAGES).union(required_stages)
        recovery_stage_set = set(RECOVERY_REQUIRED_STAGES).union(recovery_stages)
        selected_run_id = self._resolve_run_id(run_id=run_id, handle=handle)
        samples = [
            sample
            for sample in self._samples
            if sample.provenance.kind == "real_device" and sample.run_id == selected_run_id
        ]
        gaps: list[dict[str, Any]] = []
        if not samples and any(
            sample.provenance.kind == "real_device" for sample in self._samples
        ):
            gaps.append({"kind": "run_not_found", "run_id": selected_run_id})
        incomplete = sorted(
            {
                field
                for sample in samples
                for field in sample.provenance.missing_real_device_fields()
            }
        )
        if not samples:
            gaps.append({"kind": "missing_real_device_evidence"})
        if incomplete:
            gaps.append({"kind": "missing_provenance", "fields": incomplete})
        provenance_snapshots = {
            tuple(sorted(sample.provenance.snapshot().items())) for sample in samples
        }
        if len(provenance_snapshots) > 1:
            gaps.append(
                {"kind": "mixed_provenance", "run_count": len(provenance_snapshots)}
            )

        matrix: dict[str, dict[str, Any]] = {}
        for stage in sorted(required_stage_set):
            entries = [sample for sample in samples if sample.stage == stage]
            matrix[stage] = _stage_summary(entries)
            if len(entries) < min_samples_per_stage:
                gaps.append(
                    {
                        "kind": "insufficient_stage_samples",
                        "stage": stage,
                        "required": min_samples_per_stage,
                        "actual": len(entries),
                    }
                )
            if stage in recovery_stage_set and any(
                entry.recovered is None or entry.recovery_latency_ms is None
                for entry in entries
            ):
                gaps.append({"kind": "missing_recovery_measurement", "stage": stage})

        provenance = (
            samples[0].provenance.snapshot()
            if len(provenance_snapshots) == 1 and samples
            else None
        )
        recovery_entries = [
            sample
            for sample in samples
            if sample.stage in recovery_stage_set and sample.recovered is not None
        ]
        recovery_successes = sum(sample.recovered is True for sample in recovery_entries)
        return {
            "status": "qualified" if not gaps else "not_qualified",
            "evidence_kind": "real_device",
            "sample_count": len(samples),
            "min_samples_per_stage": min_samples_per_stage,
            "required_stages": sorted(required_stage_set),
            "provenance": provenance,
            "run_id": selected_run_id,
            "matrix": matrix,
            "recovery_quality": {
                "attempts": len(recovery_entries),
                "successes": recovery_successes,
                "success_rate": (
                    round(recovery_successes / len(recovery_entries), 4)
                    if recovery_entries
                    else None
                ),
                "has_success": recovery_successes > 0,
            },
            "gaps": gaps,
            "claim": (
                "reproducible_real_device_measurement"
                if not gaps
                else "must_not_be_used_as_real_device_qualification"
            ),
        }

    def runtime_snapshot(self, *, asr: Any = None, tts: Any = None) -> dict[str, Any]:
        """Combine measured samples with provider readiness without probing network."""
        snapshot = self.snapshot()
        providers: dict[str, Any] = {}
        for name, client in (("asr", asr), ("tts", tts)):
            if client is None:
                providers[name] = {
                    "configured": False,
                    "available": False,
                    "message": "not configured",
                }
                continue
            status_provider = getattr(client, "status_snapshot", None)
            try:
                status = status_provider() if callable(status_provider) else {}
            except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                status = {"error_code": "provider_status_unavailable"}
            if not isinstance(status, Mapping):
                status = {}
            availability = getattr(client, "is_available", status.get("available", False))
            try:
                available = availability() if callable(availability) else availability
            except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
                available = False
            providers[name] = {
                "configured": True,
                "available": bool(available),
                "provider": _safe_label(status.get("provider") or getattr(client, "provider", None)),
                "status": _safe_status(status),
            }
            if not available:
                snapshot["recommendations"].append(
                    f"{name}: provider unavailable; check configuration and service logs"
                )
        snapshot["providers"] = providers
        configured_providers = [provider for provider in providers.values() if provider["configured"]]
        snapshot["capability"] = {
            "voice": "ready"
            if configured_providers and len(configured_providers) == len(providers)
            and all(provider["available"] for provider in configured_providers)
            else "degraded",
            "text_chat": "preserved",
            "text_chat_blocked_by_voice": False,
        }
        return snapshot

    def release_gate(
        self,
        *,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
        latency_budgets_ms: Mapping[str, float] | None = None,
        min_recovery_success_rate: float = 0.01,
    ) -> dict[str, Any]:
        """Separate reproducible evidence completeness from product quality."""
        if not 0 <= min_recovery_success_rate <= 1:
            raise ValueError("min_recovery_success_rate must be between 0 and 1")
        budgets = dict(latency_budgets_ms or DEFAULT_VOICE_LATENCY_BUDGETS_MS)
        for stage, budget in budgets.items():
            _validate_latency(float(budget), f"latency budget for {stage}")
        qualification = self.qualification_snapshot(run_id=run_id, handle=handle)
        failures: list[dict[str, Any]] = []
        if qualification["status"] != "qualified":
            failures.append({"kind": "qualification_incomplete", "gaps": qualification["gaps"]})
        for stage, budget in budgets.items():
            p95 = qualification["matrix"].get(stage, {}).get("p95_ms")
            if p95 is None or p95 > budget:
                failures.append({"kind": "latency_budget_exceeded", "stage": stage, "budget_ms": budget, "p95_ms": p95})
        recovery = qualification["recovery_quality"]
        success_rate = recovery["success_rate"]
        if success_rate is None or success_rate < min_recovery_success_rate:
            failures.append({"kind": "recovery_success_budget_failed", "required": min_recovery_success_rate, "actual": success_rate})
        return {
            "status": "pass" if not failures else "fail",
            "run_id": qualification["run_id"],
            "qualification_status": qualification["status"],
            "latency_budgets_ms": budgets,
            "min_recovery_success_rate": min_recovery_success_rate,
            "recovery_quality": recovery,
            "failures": failures,
            "claim": "product_voice_release_gate_passed" if not failures else "must_not_be_used_as_voice_release_qualification",
        }


VoiceDiagnosticStore = VoiceDiagnostics
