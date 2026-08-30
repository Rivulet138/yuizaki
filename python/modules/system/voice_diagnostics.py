"""Low-overhead, evidence-aware voice reliability diagnostics."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
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
VoiceComfortScenarioName = Literal[
    "deliberate_interrupt",
    "hesitation",
    "backchannel",
    "background_speech",
    "empty_asr",
    "first_audio",
]
VoiceComfortSignalName = Literal["hesitation", "backchannel", "background_speech"]
VoiceComfortSignalSource = Literal["provider_vad", "local_vad", "classifier"]

# Behaviour scenarios are the required comfort-coverage set.  ``first_audio``
# is a latency-only sample and must not make coverage appear complete.
VOICE_COMFORT_SCENARIOS: tuple[VoiceComfortScenarioName, ...] = (
    "deliberate_interrupt",
    "hesitation",
    "backchannel",
    "background_speech",
    "empty_asr",
)
VOICE_COMFORT_SAMPLE_SCENARIOS: tuple[VoiceComfortScenarioName, ...] = (
    *VOICE_COMFORT_SCENARIOS,
    "first_audio",
)
VOICE_COMFORT_SIGNALS: tuple[VoiceComfortSignalName, ...] = (
    "hesitation",
    "backchannel",
    "background_speech",
)
VOICE_COMFORT_SIGNAL_SOURCES: tuple[VoiceComfortSignalSource, ...] = (
    "provider_vad",
    "local_vad",
    "classifier",
)

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


@dataclass(frozen=True)
class VoiceComfortScenarioSample:
    """Transcript-free result for one repeatable conversation comfort scenario."""

    scenario: VoiceComfortScenarioName
    stop_audio_latency_ms: float | None = None
    interrupt_ack_latency_ms: float | None = None
    false_interruption: bool = False
    first_audio_latency_ms: float | None = None
    continuous_turn_completed: bool | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.scenario not in VOICE_COMFORT_SAMPLE_SCENARIOS:
            raise ValueError("unsupported voice comfort scenario")
        for field_name in (
            "stop_audio_latency_ms",
            "interrupt_ack_latency_ms",
            "first_audio_latency_ms",
        ):
            value = getattr(self, field_name)
            if value is not None:
                _validate_latency(value, field_name)
        if self.scenario == "deliberate_interrupt" and self.false_interruption:
            raise ValueError("a deliberate interruption cannot be marked false")


@dataclass(frozen=True)
class VoiceComfortSignalSample:
    """Transcript/audio-free observation emitted by an explicit VAD/classifier."""

    signal: VoiceComfortSignalName
    source: VoiceComfortSignalSource
    confidence: float
    duration_ms: float | None = None
    run_id: str | None = None
    recorded_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.signal not in VOICE_COMFORT_SIGNALS:
            raise ValueError("unsupported voice comfort signal")
        if self.source not in VOICE_COMFORT_SIGNAL_SOURCES:
            raise ValueError("unsupported voice comfort signal source")
        if not math.isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1:
            raise ValueError("comfort signal confidence must be between 0 and 1")
        if self.duration_ms is not None:
            _validate_latency(float(self.duration_ms), "comfort signal duration_ms")
            if float(self.duration_ms) > 120_000:
                raise ValueError("comfort signal duration_ms is too large")
        if not math.isfinite(float(self.recorded_at)) or not 0 <= float(self.recorded_at) <= 10**12:
            raise ValueError("comfort signal recorded_at is invalid")


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
DEFAULT_COMFORT_BUDGETS_MS: dict[str, float] = {
    "stop_audio_p95": 250.0,
    "interrupt_ack_p95": 300.0,
    "first_audio_p95": 1000.0,
}
_DIAGNOSTICS_SCHEMA_VERSION = "yuizaki.voice-diagnostics.v1"
_MAX_PERSISTED_LABEL = 96


def _clean(value: object) -> str | None:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or None


def _safe_label(value: object) -> str | None:
    cleaned = _clean(value)
    if cleaned is None or len(cleaned) > 96 or _SECRET_RE.search(cleaned) or not _SAFE_LABEL_RE.fullmatch(cleaned):
        return "[redacted]" if cleaned else None
    return cleaned


_SAFE_STATUS_KEYS = frozenset({
    "available",
    "configured",
    "healthy",
    "initialized",
    "ready",
    "streaming",
    "warmup_done",
    "provider",
    "model",
    "error_code",
    "state",
    "status",
})
_SAFE_STATUS_CLOSED_VALUES = frozenset({
    "ok",
    "ready",
    "healthy",
    "degraded",
    "unavailable",
    "configured",
    "not_configured",
    "initializing",
    "error",
    "unknown",
})


def _safe_status(value: object, *, depth: int = 0, key: str | None = None) -> object:
    """Project only closed provider status fields; never expose free text."""
    if depth > 3:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        cleaned = _clean(value)
        if not cleaned or _SECRET_RE.search(cleaned):
            return None
        if key in {"state", "status"}:
            return cleaned if cleaned in _SAFE_STATUS_CLOSED_VALUES else None
        if key in {"provider", "model", "error_code"} and re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", cleaned):
            return cleaned
        return None
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for raw_key, item in value.items():
            normalized_key = re.sub(r"[^a-z0-9_]", "", str(raw_key).lower())
            if normalized_key not in _SAFE_STATUS_KEYS:
                continue
            projected[normalized_key] = _safe_status(item, depth=depth + 1, key=normalized_key)
            if projected[normalized_key] is None:
                projected.pop(normalized_key)
        return projected
    return None


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
        self,
        *,
        max_samples: int = 512,
        p95_warning_ms: float = 1500.0,
        persistence_path: str | Path | None = None,
    ) -> None:
        if max_samples < 1:
            raise ValueError("max_samples must be positive")
        self._samples: deque[VoiceDiagnosticSample] = deque(maxlen=max_samples)
        self._comfort_samples: deque[VoiceComfortScenarioSample] = deque(
            maxlen=max_samples
        )
        self._comfort_signal_samples: deque[VoiceComfortSignalSample] = deque(
            maxlen=max_samples
        )
        self.p95_warning_ms = float(p95_warning_ms)
        self._persistence_path = Path(persistence_path) if persistence_path is not None else None
        self._run_id = self._new_run_id()
        self._measurement_token: object = object()
        self._load_persisted()

    @staticmethod
    def _safe_persisted_run_id(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.strip()
        if not cleaned or len(cleaned) > _MAX_PERSISTED_LABEL or not _SAFE_LABEL_RE.fullmatch(cleaned):
            return None
        return cleaned

    @staticmethod
    def _provenance_from_snapshot(value: object) -> VoiceEvidenceProvenance:
        if not isinstance(value, Mapping):
            return VoiceEvidenceProvenance()
        kind = value.get("kind") if value.get("kind") in {"synthetic_fixture", "real_device"} else "synthetic_fixture"
        string_fields = (
            "machine", "platform", "runtime", "provider", "model",
            "input_device", "output_device", "power_profile", "vad_profile",
        )
        kwargs: dict[str, Any] = {"kind": kind}
        for field_name in string_fields:
            field_value = value.get(field_name)
            safe_value = _safe_label(field_value)
            if safe_value is not None:
                kwargs[field_name] = safe_value
        for field_name in ("sample_rate_hz", "channel_count"):
            field_value = value.get(field_name)
            if isinstance(field_value, int) and not isinstance(field_value, bool) and 1 <= field_value <= 1_000_000:
                kwargs[field_name] = field_value
        for field_name in ("echo_cancellation", "noise_suppression"):
            field_value = value.get(field_name)
            if isinstance(field_value, bool):
                kwargs[field_name] = field_value
        try:
            return VoiceEvidenceProvenance(**kwargs)
        except (TypeError, ValueError):
            return VoiceEvidenceProvenance()

    @classmethod
    def _sample_from_snapshot(cls, value: object, current_run_id: str) -> VoiceDiagnosticSample | None:
        if not isinstance(value, Mapping):
            return None
        stage = value.get("stage")
        latency = value.get("latency_ms")
        safe_stage = _safe_label(stage)
        if safe_stage is None or not isinstance(latency, (int, float)) or isinstance(latency, bool):
            return None
        try:
            recorded_at = value.get("recorded_at", time.time())
            if not isinstance(recorded_at, (int, float)) or isinstance(recorded_at, bool) or not math.isfinite(float(recorded_at)) or not 0 <= float(recorded_at) <= 10**12:
                return None
            recovery_latency = value.get("recovery_latency_ms")
            if recovery_latency is not None and (not isinstance(recovery_latency, (int, float)) or isinstance(recovery_latency, bool)):
                return None
            underruns = value.get("playback_underruns")
            if underruns is not None and (not isinstance(underruns, int) or isinstance(underruns, bool) or underruns < 0 or underruns > 10_000):
                return None
            recovered = value.get("recovered")
            if recovered is not None and not isinstance(recovered, bool):
                return None
            return VoiceDiagnosticSample(
                stage=safe_stage,
                latency_ms=float(latency),
                ok=value.get("ok") is not False,
                provider=_safe_label(value.get("provider")),
                error_kind=_safe_label(value.get("error_kind")),
                request_id=_safe_label(value.get("request_id")),
                run_id=current_run_id,
                provenance=cls._provenance_from_snapshot(value.get("provenance")),
                recovered=recovered,
                recovery_latency_ms=float(recovery_latency) if recovery_latency is not None else None,
                playback_underruns=underruns,
                recorded_at=float(recorded_at),
            )
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _comfort_from_snapshot(cls, value: object, current_run_id: str) -> VoiceComfortScenarioSample | None:
        if not isinstance(value, Mapping):
            return None
        scenario = value.get("scenario")
        if not isinstance(scenario, str):
            return None
        kwargs: dict[str, Any] = {"scenario": scenario, "run_id": current_run_id}
        for field_name in ("stop_audio_latency_ms", "interrupt_ack_latency_ms", "first_audio_latency_ms"):
            item = value.get(field_name)
            if item is not None:
                if not isinstance(item, (int, float)) or isinstance(item, bool):
                    return None
                kwargs[field_name] = float(item)
        for field_name in ("false_interruption", "continuous_turn_completed"):
            item = value.get(field_name)
            if item is not None and not isinstance(item, bool):
                return None
            kwargs[field_name] = item
        try:
            return VoiceComfortScenarioSample(**kwargs)
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _comfort_signal_from_snapshot(
        cls, value: object, current_run_id: str
    ) -> VoiceComfortSignalSample | None:
        if not isinstance(value, Mapping):
            return None
        signal = value.get("signal")
        source = value.get("source")
        confidence = value.get("confidence")
        if (
            not isinstance(signal, str)
            or not isinstance(source, str)
            or not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
        ):
            return None
        duration_ms = value.get("duration_ms")
        recorded_at = value.get("recorded_at", time.time())
        if duration_ms is not None and (
            not isinstance(duration_ms, (int, float)) or isinstance(duration_ms, bool)
        ):
            return None
        if not isinstance(recorded_at, (int, float)) or isinstance(recorded_at, bool):
            return None
        try:
            return VoiceComfortSignalSample(
                signal=signal,
                source=source,
                confidence=float(confidence),
                duration_ms=float(duration_ms) if duration_ms is not None else None,
                run_id=current_run_id,
                recorded_at=float(recorded_at),
            )
        except (TypeError, ValueError, OverflowError):
            return None

    def _persisted_payload(self) -> dict[str, Any]:
        def sample_payload(sample: VoiceDiagnosticSample) -> dict[str, Any]:
            return {
                "stage": sample.stage,
                "latency_ms": sample.latency_ms,
                "ok": sample.ok,
                "provider": sample.provider,
                "error_kind": sample.error_kind,
                "request_id": sample.request_id,
                "run_id": sample.run_id,
                "provenance": sample.provenance.snapshot(),
                "recovered": sample.recovered,
                "recovery_latency_ms": sample.recovery_latency_ms,
                "playback_underruns": sample.playback_underruns,
                "recorded_at": sample.recorded_at,
            }

        return {
            "schemaVersion": _DIAGNOSTICS_SCHEMA_VERSION,
            "run_id": self._run_id,
            "samples": [sample_payload(sample) for sample in self._samples],
            "comfort_samples": [
                {
                    "scenario": sample.scenario,
                    "stop_audio_latency_ms": sample.stop_audio_latency_ms,
                    "interrupt_ack_latency_ms": sample.interrupt_ack_latency_ms,
                    "false_interruption": sample.false_interruption,
                    "first_audio_latency_ms": sample.first_audio_latency_ms,
                    "continuous_turn_completed": sample.continuous_turn_completed,
                    "run_id": sample.run_id,
                }
                for sample in self._comfort_samples
            ],
            "comfort_signal_samples": [
                {
                    "signal": sample.signal,
                    "source": sample.source,
                    "confidence": sample.confidence,
                    "duration_ms": sample.duration_ms,
                    "run_id": sample.run_id,
                    "recorded_at": sample.recorded_at,
                }
                for sample in self._comfort_signal_samples
            ],
        }

    def _persist(self) -> None:
        path = self._persistence_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
            temporary.write_text(
                json.dumps(self._persisted_payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError):
            try:
                temporary.unlink()
            except (OSError, UnboundLocalError):
                pass

    def _load_persisted(self) -> None:
        path = self._persistence_path
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, UnicodeError):
            return
        if not isinstance(payload, Mapping) or payload.get("schemaVersion") != _DIAGNOSTICS_SCHEMA_VERSION:
            return
        persisted_run_id = self._safe_persisted_run_id(payload.get("run_id"))
        if persisted_run_id:
            self._run_id = persisted_run_id
        raw_samples = payload.get("samples")
        if isinstance(raw_samples, list):
            for raw_sample in raw_samples[-self._samples.maxlen :]:
                sample = self._sample_from_snapshot(raw_sample, self._run_id)
                if sample is not None:
                    self._samples.append(sample)
        raw_comfort = payload.get("comfort_samples")
        if isinstance(raw_comfort, list):
            for raw_sample in raw_comfort[-self._comfort_samples.maxlen :]:
                sample = self._comfort_from_snapshot(raw_sample, self._run_id)
                if sample is not None:
                    self._comfort_samples.append(sample)
        raw_signals = payload.get("comfort_signal_samples")
        if isinstance(raw_signals, list):
            for raw_sample in raw_signals[-self._comfort_signal_samples.maxlen :]:
                sample = self._comfort_signal_from_snapshot(raw_sample, self._run_id)
                if sample is not None:
                    self._comfort_signal_samples.append(sample)

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
        self._comfort_samples.clear()
        self._comfort_signal_samples.clear()
        self._persist()
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
        self._persist()
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

    def record_comfort_scenario(
        self,
        scenario: VoiceComfortScenarioName | str,
        *,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
        stop_audio_latency_ms: float | None = None,
        interrupt_ack_latency_ms: float | None = None,
        false_interruption: bool = False,
        first_audio_latency_ms: float | None = None,
        continuous_turn_completed: bool | None = None,
    ) -> VoiceComfortScenarioSample:
        """Record a transcript-free synthetic scenario result.

        These fixtures support repeatable regression checks only. Real-device release
        qualification remains exclusively based on ``VoiceDiagnosticSample`` evidence.
        ``run_id`` is a human-readable label used for current-run validation, not an
        asynchronous replay-prevention credential. Async callbacks must pass the
        opaque handle returned by :meth:`begin_measurement`; a caller that needs
        protection from same-label restarts must retain and use that handle.
        """
        scenario_value = str(scenario).strip()
        if scenario_value not in VOICE_COMFORT_SAMPLE_SCENARIOS:
            raise ValueError("unsupported voice comfort scenario")
        selected_run_id = self._resolve_run_id(run_id=run_id, handle=handle)
        sample = VoiceComfortScenarioSample(
            scenario=scenario_value,
            stop_audio_latency_ms=(
                float(stop_audio_latency_ms)
                if stop_audio_latency_ms is not None
                else None
            ),
            interrupt_ack_latency_ms=(
                float(interrupt_ack_latency_ms)
                if interrupt_ack_latency_ms is not None
                else None
            ),
            false_interruption=bool(false_interruption),
            first_audio_latency_ms=(
                float(first_audio_latency_ms)
                if first_audio_latency_ms is not None
                else None
            ),
            continuous_turn_completed=continuous_turn_completed,
            run_id=selected_run_id,
        )
        self._comfort_samples.append(sample)
        self._persist()
        return sample

    def comfort_snapshot(self) -> dict[str, Any]:
        """Summarize deterministic comfort fixtures without claiming device quality."""

        def latency_summary(field_name: str) -> dict[str, int | float | None]:
            values = [
                value
                for sample in self._comfort_samples
                if (value := getattr(sample, field_name)) is not None
            ]
            return {
                "count": len(values),
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
            }

        non_interrupt_samples = [
            sample
            for sample in self._comfort_samples
            if sample.scenario != "deliberate_interrupt"
        ]
        false_interruptions = sum(
            sample.false_interruption for sample in non_interrupt_samples
        )
        continuous_turns = [
            sample
            for sample in self._comfort_samples
            if sample.continuous_turn_completed is not None
        ]
        completed_turns = sum(
            sample.continuous_turn_completed is True for sample in continuous_turns
        )
        scenario_counts = {
            scenario: sum(sample.scenario == scenario for sample in self._comfort_samples)
            for scenario in VOICE_COMFORT_SCENARIOS
        }
        missing_scenarios = [
            scenario for scenario, count in scenario_counts.items() if count == 0
        ]
        snapshot = {
            "sample_count": len(self._comfort_samples),
            "run_id": self._run_id,
            "scenario_counts": scenario_counts,
            "missing_scenarios": missing_scenarios,
            "coverage_complete": not missing_scenarios,
            "stop_audio_latency": latency_summary("stop_audio_latency_ms"),
            "interrupt_ack_latency": latency_summary("interrupt_ack_latency_ms"),
            "first_audio_latency": latency_summary("first_audio_latency_ms"),
            "false_interruption_rate": (
                round(false_interruptions / len(non_interrupt_samples), 4)
                if non_interrupt_samples
                else None
            ),
            "false_interruption_count": false_interruptions,
            "false_interruption_opportunities": len(non_interrupt_samples),
            "continuous_turn_completion_rate": (
                round(completed_turns / len(continuous_turns), 4)
                if continuous_turns
                else None
            ),
            "continuous_turn_completed": completed_turns,
            "continuous_turn_attempts": len(continuous_turns),
            "evidence_kind": "synthetic_fixture",
            "claim": "synthetic_comfort_regression_only",
            "real_device_qualification": "not_evaluated",
        }
        snapshot["comfort_signals"] = self.comfort_signal_snapshot()
        snapshot["comfort_gate"] = self.comfort_gate(snapshot=snapshot)
        return snapshot

    def record_comfort_signal(
        self,
        signal: VoiceComfortSignalName | str,
        source: VoiceComfortSignalSource | str,
        confidence: float,
        *,
        duration_ms: float | None = None,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
    ) -> VoiceComfortSignalSample:
        """Record an explicit, transcript-free comfort observation.

        Callers must provide a signal from a provider VAD, local VAD, or an
        explicit classifier. Missing events are intentionally not inferred.
        """
        selected_run_id = self._resolve_run_id(run_id=run_id, handle=handle)
        sample = VoiceComfortSignalSample(
            signal=str(signal).strip(),
            source=str(source).strip(),
            confidence=float(confidence),
            duration_ms=(float(duration_ms) if duration_ms is not None else None),
            run_id=selected_run_id,
        )
        self._comfort_signal_samples.append(sample)
        self._persist()
        return sample

    def comfort_signal_snapshot(self) -> dict[str, Any]:
        """Return bounded signal coverage without exposing transcript/audio."""
        counts = {
            signal: sum(sample.signal == signal for sample in self._comfort_signal_samples)
            for signal in VOICE_COMFORT_SIGNALS
        }
        source_counts = {
            source: sum(sample.source == source for sample in self._comfort_signal_samples)
            for source in VOICE_COMFORT_SIGNAL_SOURCES
        }
        confidences = [sample.confidence for sample in self._comfort_signal_samples]
        durations = [
            sample.duration_ms
            for sample in self._comfort_signal_samples
            if sample.duration_ms is not None
        ]
        missing = [signal for signal, count in counts.items() if count == 0]
        return {
            "sample_count": len(self._comfort_signal_samples),
            "signal_counts": counts,
            "source_counts": source_counts,
            "missing_signals": missing,
            "coverage_complete": not missing,
            "confidence": {
                "p50": _percentile(confidences, 0.50),
                "p95": _percentile(confidences, 0.95),
            },
            "duration_ms": {
                "p50": _percentile(durations, 0.50),
                "p95": _percentile(durations, 0.95),
            },
            "evidence_kind": "transcript_free_explicit_signal",
            "claim": "comfort_signal_regression_only",
        }

    def comfort_gate(
        self,
        *,
        snapshot: Mapping[str, Any] | None = None,
        latency_budgets_ms: Mapping[str, float] | None = None,
        max_false_interruption_rate: float = 0.10,
        min_continuous_turn_completion_rate: float = 0.90,
    ) -> dict[str, Any]:
        """Turn synthetic comfort metrics into actionable local guidance.

        This is a regression signal inspired by pause/backchannel/overlap
        evaluation work; it is intentionally never a real-device qualification.
        Missing measurements produce ``insufficient_data`` instead of a pass.
        """
        if not 0 <= max_false_interruption_rate <= 1:
            raise ValueError("max_false_interruption_rate must be between 0 and 1")
        if not 0 <= min_continuous_turn_completion_rate <= 1:
            raise ValueError(
                "min_continuous_turn_completion_rate must be between 0 and 1"
            )
        budgets = dict(latency_budgets_ms or DEFAULT_COMFORT_BUDGETS_MS)
        for name, budget in budgets.items():
            _validate_latency(float(budget), f"comfort latency budget for {name}")
        report = snapshot if snapshot is not None else self.comfort_snapshot()
        checks: list[dict[str, Any]] = []
        failures: list[str] = []
        missing_scenarios = report.get("missing_scenarios", [])
        coverage_complete = report.get("coverage_complete") is True
        if not coverage_complete or missing_scenarios:
            missing = [str(item) for item in missing_scenarios]
            detail = ", ".join(missing) if missing else "coverage_complete is false"
            checks.append(
                {
                    "metric": "scenario_coverage",
                    "missing_scenarios": missing,
                    "status": "insufficient_data",
                }
            )
            failures.append(f"missing comfort scenarios: {detail}")
        else:
            checks.append(
                {
                    "metric": "scenario_coverage",
                    "missing_scenarios": [],
                    "status": "pass",
                }
            )

        latency_fields = {
            "stop_audio_p95": ("stop_audio_latency", "stop audio"),
            "interrupt_ack_p95": ("interrupt_ack_latency", "interrupt acknowledgement"),
            "first_audio_p95": ("first_audio_latency", "first audio"),
        }
        for budget_name, (metric_name, label) in latency_fields.items():
            budget = budgets.get(budget_name)
            if budget is None:
                continue
            metric = report.get(metric_name) or {}
            value = metric.get("p95_ms") if isinstance(metric, Mapping) else None
            passed = value is not None and float(value) <= float(budget)
            checks.append({"metric": budget_name, "value_ms": value, "budget_ms": budget, "status": "pass" if passed else "needs_attention"})
            if value is None:
                failures.append(f"{label} p95 has no samples")
            elif not passed:
                failures.append(f"{label} p95 exceeds {budget:g}ms")

        false_rate = report.get("false_interruption_rate")
        false_pass = false_rate is not None and float(false_rate) <= max_false_interruption_rate
        checks.append({"metric": "false_interruption_rate", "value": false_rate, "budget": max_false_interruption_rate, "status": "pass" if false_pass else "needs_attention"})
        if false_rate is None:
            failures.append("false interruption rate has no opportunities")
        elif not false_pass:
            failures.append(f"false interruption rate exceeds {max_false_interruption_rate:g}")

        completion_rate = report.get("continuous_turn_completion_rate")
        completion_pass = completion_rate is not None and float(completion_rate) >= min_continuous_turn_completion_rate
        checks.append({"metric": "continuous_turn_completion_rate", "value": completion_rate, "budget": min_continuous_turn_completion_rate, "status": "pass" if completion_pass else "needs_attention"})
        if completion_rate is None:
            failures.append("continuous turn completion has no attempts")
        elif not completion_pass:
            failures.append(f"continuous turn completion is below {min_continuous_turn_completion_rate:g}")

        status = (
            "insufficient_data"
            if (not coverage_complete or missing_scenarios)
            else "pass"
            if not failures
            else "insufficient_data"
            if all("no " in item for item in failures)
            else "needs_attention"
        )
        return {
            "status": status,
            "checks": checks,
            "failures": failures,
            "latency_budgets_ms": budgets,
            "max_false_interruption_rate": max_false_interruption_rate,
            "min_continuous_turn_completion_rate": min_continuous_turn_completion_rate,
            "evidence_kind": "synthetic_fixture",
            "claim": "synthetic_comfort_regression_only",
            "real_device_qualification": "not_evaluated",
        }

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
            "comfort": self.comfort_snapshot(),
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
