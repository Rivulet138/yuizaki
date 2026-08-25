from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.system.voice_diagnostics import (
    REAL_DEVICE_REQUIRED_STAGES,
    RECOVERY_REQUIRED_STAGES,
    VoiceDiagnostics,
    VoiceEvidenceProvenance,
)
from modules.system.voice_qualification_artifact import (
    JsonVoiceQualificationArtifactStore,
)


def _real_device_provenance(**overrides: str) -> VoiceEvidenceProvenance:
    values = {
        "kind": "real_device",
        "machine": "lab-win-01",
        "platform": "Windows 11 24H2",
        "runtime": "Electron 38 / Python 3.12",
        "provider": "provider-a",
        "model": "voice-model-a",
        "input_device": "USB microphone",
        "output_device": "USB headset",
        "power_profile": "balanced/ac",
        "sample_rate_hz": 48_000,
        "channel_count": 1,
        "echo_cancellation": True,
        "noise_suppression": True,
        "vad_profile": "default-voice",
    }
    values.update(overrides)
    return VoiceEvidenceProvenance(**values)  # type: ignore[arg-type]


def test_voice_diagnostics_reports_percentiles_errors_and_guidance() -> None:
    diagnostics = VoiceDiagnostics(p95_warning_ms=100)
    diagnostics.record("asr", 40, provider="local")
    diagnostics.record("asr", 220, provider="local", ok=False, error_kind="timeout")
    diagnostics.record("tts", 20, provider="edge")

    snapshot = diagnostics.snapshot()

    assert snapshot["sample_count"] == 3
    assert snapshot["stages"]["asr"]["p50_ms"] == 130
    assert snapshot["stages"]["asr"]["p95_ms"] == 211
    assert snapshot["stages"]["asr"]["error_rate"] == 0.5
    assert snapshot["evidence_claim"] == "synthetic_regression_only"
    assert any("asr" in item and "p95" in item for item in snapshot["recommendations"])
    assert any("failures" in item for item in snapshot["recommendations"])


def test_voice_runtime_snapshot_exposes_provider_readiness() -> None:
    diagnostics = VoiceDiagnostics()
    diagnostics.record("round_trip", 80)
    snapshot = diagnostics.runtime_snapshot(
        asr=SimpleNamespace(is_available=False, provider="sensevoice"),
        tts=SimpleNamespace(
            is_available=True,
            status_snapshot=lambda: {"available": True, "warmup_done": True},
        ),
    )

    assert snapshot["providers"]["asr"]["available"] is False
    assert snapshot["providers"]["tts"]["status"]["warmup_done"] is True
    assert snapshot["capability"] == {
        "voice": "degraded",
        "text_chat": "preserved",
        "text_chat_blocked_by_voice": False,
    }
    assert any(
        "asr" in item and "unavailable" in item for item in snapshot["recommendations"]
    )


def test_synthetic_fixtures_never_qualify_as_real_device_evidence() -> None:
    diagnostics = VoiceDiagnostics()
    for stage in (
        "asr_final",
        "first_token",
        "first_audio",
        "interruption",
        "playback_recovery",
    ):
        diagnostics.record(stage, 20, recovered=True, recovery_latency_ms=5)

    qualification = diagnostics.qualification_snapshot()

    assert qualification["status"] == "not_qualified"
    assert qualification["sample_count"] == 0
    assert qualification["claim"] == "must_not_be_used_as_real_device_qualification"
    assert {gap["kind"] for gap in qualification["gaps"]} >= {
        "missing_real_device_evidence"
    }


def test_complete_real_device_matrix_reports_latency_and_recovery_percentiles() -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    stages = (
        "asr_final",
        "first_token",
        "first_audio",
        "interruption",
        "playback_recovery",
    )
    for stage in stages:
        for index, latency_ms in enumerate((100, 125, 150, 175, 200)):
            recovery_stage = stage in ("interruption", "playback_recovery")
            diagnostics.record(
                stage,
                latency_ms,
                provenance=provenance,
                recovered=index % 2 == 0 if recovery_stage else None,
                recovery_latency_ms=(40 + index * 10) if recovery_stage else None,
                playback_underruns=1
                if stage == "playback_recovery" and index == 0
                else None,
            )

    qualification = diagnostics.qualification_snapshot()

    assert qualification["status"] == "qualified"
    assert qualification["provenance"]["machine"] == "lab-win-01"
    assert qualification["matrix"]["asr_final"]["p50_ms"] == 150
    assert qualification["matrix"]["asr_final"]["p95_ms"] == 195
    interruption = qualification["matrix"]["interruption"]
    assert interruption["recovery_success_rate"] == 0.6
    assert interruption["recovery_p50_ms"] == 60
    assert interruption["recovery_p95_ms"] == 78
    assert qualification["matrix"]["playback_recovery"]["playback_underruns"] == 1


def test_incomplete_or_mixed_real_device_provenance_fails_closed() -> None:
    diagnostics = VoiceDiagnostics()
    incomplete = _real_device_provenance(model="")
    other_machine = _real_device_provenance(machine="lab-win-02")
    diagnostics.record("interruption", 100, provenance=incomplete)
    diagnostics.record(
        "interruption",
        120,
        provenance=other_machine,
        recovered=True,
        recovery_latency_ms=20,
    )

    qualification = diagnostics.qualification_snapshot(
        required_stages=("interruption",)
    )

    assert qualification["status"] == "not_qualified"
    gap_kinds = {gap["kind"] for gap in qualification["gaps"]}
    assert gap_kinds >= {
        "missing_provenance",
        "mixed_provenance",
        "missing_recovery_measurement",
    }
    assert qualification["provenance"] is None


def test_recovery_values_are_validated() -> None:
    diagnostics = VoiceDiagnostics()

    with pytest.raises(ValueError, match="recovery_latency_ms"):
        diagnostics.record("interruption", 10, recovered=False, recovery_latency_ms=-1)
    with pytest.raises(ValueError, match="playback_underruns"):
        diagnostics.record("playback", 10, playback_underruns=-1)
    with pytest.raises(ValueError, match="at least 5"):
        diagnostics.qualification_snapshot(min_samples_per_stage=1)


def test_qualification_cannot_remove_mandatory_stage_or_recovery_gates() -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    for stage in ("asr_final", "first_token", "first_audio", "interruption"):
        for _ in range(5):
            diagnostics.record(
                stage,
                100,
                provenance=provenance,
                recovered=True if stage == "interruption" else None,
                recovery_latency_ms=20 if stage == "interruption" else None,
            )

    report = diagnostics.qualification_snapshot(required_stages=(), recovery_stages=())

    assert report["status"] == "not_qualified"
    assert set(report["required_stages"]) >= {
        "asr_final", "first_token", "first_audio", "interruption", "playback_recovery",
    }


def test_provider_status_errors_are_redacted_and_callable_availability_is_called() -> None:
    diagnostics = VoiceDiagnostics()
    called = False

    def availability() -> bool:
        nonlocal called
        called = True
        return True

    class FailingStatus:
        def status_snapshot(self) -> dict[str, object]:
            raise RuntimeError("secret provider token")

        def __init__(self) -> None:
            self.is_available = availability

    snapshot = diagnostics.runtime_snapshot(asr=FailingStatus())

    assert called is True
    assert snapshot["providers"]["asr"]["available"] is True
    assert snapshot["providers"]["asr"]["status"] == {"error_code": "provider_status_unavailable"}
    assert "secret provider token" not in str(snapshot)


def test_provider_status_projection_redacts_nested_secrets_and_empty_voice_is_degraded() -> None:
    diagnostics = VoiceDiagnostics()
    snapshot = diagnostics.runtime_snapshot(
        asr=SimpleNamespace(
            is_available=True,
            provider="Bearer provider-secret-token",
            status_snapshot=lambda: {
                "available": True,
                "warmup_done": True,
                "api_key": "sk-provider-secret",
                "nested": {"token": "token=secret-value"},
            },
        ),
        tts=None,
    )
    assert snapshot["providers"]["asr"]["provider"] == "[redacted]"
    assert snapshot["providers"]["asr"]["status"]["warmup_done"] is True
    assert "sk-provider-secret" not in str(snapshot)
    assert "secret-value" not in str(snapshot)
    assert snapshot["capability"]["voice"] == "degraded"


def test_provenance_labels_are_bounded_and_secret_safe() -> None:
    provenance = _real_device_provenance(
        machine="Bearer abc-secret-token",
        provider="provider\nwith-control",
        model="m" * 200,
    )

    snapshot = provenance.snapshot()

    assert snapshot["machine"] == "[redacted]"
    assert snapshot["provider"] == "[redacted]"
    assert snapshot["model"] == "[redacted]"


def test_provenance_labels_redact_credentials_and_unstable_identifiers() -> None:
    snapshot = _real_device_provenance(
        provider="Bearer super-secret-token",
        input_device="USB microphone (user=alice; serial=123)",
    ).snapshot()

    assert snapshot["provider"] == "[redacted]"
    assert snapshot["input_device"] == "[redacted]"


def test_qualification_artifact_store_persists_only_real_device_reports(tmp_path) -> None:
    diagnostics = VoiceDiagnostics()
    diagnostics.record("interruption", 120, provenance=_real_device_provenance(), recovered=True, recovery_latency_ms=30)
    report = diagnostics.qualification_snapshot()
    path = tmp_path / "voice-qualification.json"

    JsonVoiceQualificationArtifactStore(path).write(report)
    restored = JsonVoiceQualificationArtifactStore(path).read()

    assert restored["evidence_kind"] == "real_device"
    assert restored["status"] == "not_qualified"
    assert not list(tmp_path.glob(".voice-qualification.json.tmp-*"))


def test_qualification_artifact_store_rejects_synthetic_or_secret_bearing_reports(tmp_path) -> None:
    path = tmp_path / "voice-qualification.json"
    store = JsonVoiceQualificationArtifactStore(path)
    report = {
        "status": "not_qualified",
        "evidence_kind": "synthetic_fixture",
        "sample_count": 0,
        "min_samples_per_stage": 5,
        "required_stages": [],
        "provenance": None,
        "run_id": "voice-run-1",
        "matrix": {},
        "recovery_quality": {},
        "gaps": [],
        "claim": "must_not_be_used_as_real_device_qualification",
    }
    with pytest.raises(ValueError, match="real-device"):
        store.write(report)

    secret_report = {
        "status": "not_qualified",
        "evidence_kind": "real_device",
        "sample_count": 0,
        "min_samples_per_stage": 5,
        "required_stages": [],
        "provenance": None,
        "run_id": "voice-run-1",
        "matrix": {},
        "recovery_quality": {},
        "gaps": [],
        "claim": "must_not_be_used_as_real_device_qualification",
        "transcript": "private content",
    }
    with pytest.raises(ValueError, match="restricted field"):
        store.write(secret_report)


def test_qualified_artifact_requires_external_attestation(tmp_path) -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    for stage in REAL_DEVICE_REQUIRED_STAGES:
        for _ in range(5):
            diagnostics.record(
                stage,
                100,
                provenance=provenance,
                recovered=True if stage in RECOVERY_REQUIRED_STAGES else None,
                recovery_latency_ms=20 if stage in RECOVERY_REQUIRED_STAGES else None,
            )
    report = diagnostics.qualification_snapshot()
    assert report["status"] == "qualified"
    path = tmp_path / "qualified.json"

    with pytest.raises(ValueError, match="external attestation"):
        JsonVoiceQualificationArtifactStore(path).write(report)

    verifier = lambda value: value["claim"] == "reproducible_real_device_measurement"
    store = JsonVoiceQualificationArtifactStore(path, attestation_verifier=verifier)
    store.write(report)
    assert store.read()["status"] == "qualified"


def test_qualification_artifact_store_fails_closed_on_corruption(tmp_path) -> None:
    path = tmp_path / "voice-qualification.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        JsonVoiceQualificationArtifactStore(path).read()


def test_runtime_labels_and_errors_are_redacted_and_runs_are_isolated() -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    first_run = diagnostics.run_id
    diagnostics.record(
        "first_token",
        20,
        provider="Bearer abc-secret-token",
        error_kind="token=abc",
        provenance=provenance,
        run_id=first_run,
    )
    sample = diagnostics.samples(stage="first_token")[0]
    assert sample.provider == "[redacted]"
    assert sample.error_kind == "[redacted]"
    second_run = diagnostics.begin_run("lab-run-02")
    assert second_run == "lab-run-02"
    assert diagnostics.samples() == ()


def test_record_rejects_late_callback_from_previous_run() -> None:
    diagnostics = VoiceDiagnostics()
    first_run = diagnostics.run_id
    diagnostics.begin_run("lab-run-02")
    with pytest.raises(ValueError, match="run is stale"):
        diagnostics.record("first_token", 20, run_id=first_run)


def test_opaque_measurement_handle_rejects_callbacks_from_previous_run() -> None:
    diagnostics = VoiceDiagnostics()
    first_handle = diagnostics.begin_measurement("lab-run-01")
    diagnostics.record("first_token", 20, handle=first_handle)
    diagnostics.begin_measurement("lab-run-02")

    with pytest.raises(ValueError, match="measurement handle is stale"):
        diagnostics.record("first_token", 20, handle=first_handle)


def test_qualification_reports_recovery_quality_separately() -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    for stage in REAL_DEVICE_REQUIRED_STAGES:
        for _ in range(5):
            diagnostics.record(
                stage,
                20,
                provenance=provenance,
                recovered=False if stage in RECOVERY_REQUIRED_STAGES else None,
                recovery_latency_ms=30 if stage in RECOVERY_REQUIRED_STAGES else None,
            )
    report = diagnostics.qualification_snapshot()
    assert report["status"] == "qualified"
    assert report["recovery_quality"]["has_success"] is False
    assert report["recovery_quality"]["success_rate"] == 0.0


def test_release_gate_separates_latency_and_recovery_quality() -> None:
    diagnostics = VoiceDiagnostics()
    provenance = _real_device_provenance()
    for stage in REAL_DEVICE_REQUIRED_STAGES:
        for index in range(5):
            diagnostics.record(
                stage,
                100 if stage != "interruption" else 200,
                provenance=provenance,
                recovered=(index > 0) if stage in RECOVERY_REQUIRED_STAGES else None,
                recovery_latency_ms=30 if stage in RECOVERY_REQUIRED_STAGES else None,
            )
    passed = diagnostics.release_gate(min_recovery_success_rate=0.5)
    assert passed["status"] == "pass"
    failed = diagnostics.release_gate(latency_budgets_ms={"interruption": 150}, min_recovery_success_rate=0.5)
    assert failed["status"] == "fail"
    assert any(item["kind"] == "latency_budget_exceeded" for item in failed["failures"])
