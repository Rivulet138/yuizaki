from __future__ import annotations

import pytest

from modules.system.voice_diagnostics import VoiceDiagnostics, VoiceEvidenceProvenance
from modules.system.voice_qualification_artifact import (
    JsonVoiceQualificationArtifactStore,
)
from modules.system.voice_release_runner import VoiceQualificationReleaseRunner

STAGES = ("asr_final", "first_token", "first_audio", "interruption", "playback_recovery")


def _provenance() -> VoiceEvidenceProvenance:
    return VoiceEvidenceProvenance(
        kind="real_device",
        machine="win-lab-01",
        platform="Windows 11 24H2",
        runtime="Electron 42 / Python 3.12",
        provider="provider-lab",
        model="model-lab",
        input_device="USB-mic-A",
        output_device="USB-headset-A",
        power_profile="balanced-ac",
        sample_rate_hz=48000,
        channel_count=1,
        echo_cancellation=True,
        noise_suppression=True,
        vad_profile="default-voice",
    )


def _complete_diagnostics() -> VoiceDiagnostics:
    diagnostics = VoiceDiagnostics()
    handle = diagnostics.begin_measurement("win-lab-run-01")
    provenance = _provenance()
    for stage in STAGES:
        for _ in range(5):
            diagnostics.record(
                stage,
                100,
                provenance=provenance,
                recovered=True if stage in {"interruption", "playback_recovery"} else None,
                recovery_latency_ms=50 if stage in {"interruption", "playback_recovery"} else None,
                handle=handle,
            )
    return diagnostics


def test_runner_persists_not_qualified_report_without_external_attestation(tmp_path) -> None:
    path = tmp_path / "voice-report.json"
    store = JsonVoiceQualificationArtifactStore(path)
    report = VoiceQualificationReleaseRunner(store).run(VoiceDiagnostics())

    assert report["status"] == "not_qualified"
    assert report["release_gate"]["status"] == "fail"
    assert store.read()["status"] == "not_qualified"


def test_runner_requires_external_attestation_for_qualified_report(tmp_path) -> None:
    store = JsonVoiceQualificationArtifactStore(tmp_path / "voice-report.json")

    with pytest.raises(ValueError, match="external attestation"):
        VoiceQualificationReleaseRunner(store).run(_complete_diagnostics())


def test_runner_persists_qualified_report_only_after_attestation(tmp_path) -> None:
    path = tmp_path / "voice-report.json"
    store = JsonVoiceQualificationArtifactStore(path, attestation_verifier=lambda report: report["claim"] == "product_voice_release_gate_passed")
    report = VoiceQualificationReleaseRunner(store).run(_complete_diagnostics())

    assert report["status"] == "qualified"
    assert report["release_gate"]["status"] == "pass"
    assert store.read()["claim"] == "product_voice_release_gate_passed"


def test_runner_marks_complete_matrix_over_budget_not_qualified(tmp_path) -> None:
    diagnostics = _complete_diagnostics()
    # The persisted report must remain non-qualifying even if evidence is complete.
    store = JsonVoiceQualificationArtifactStore(tmp_path / "voice-report.json")
    report = VoiceQualificationReleaseRunner(store, latency_budgets_ms={"interruption": 50}).run(diagnostics)

    assert report["status"] == "not_qualified"
    assert any(item["kind"] == "latency_budget_exceeded" for item in report["release_gate"]["failures"])
