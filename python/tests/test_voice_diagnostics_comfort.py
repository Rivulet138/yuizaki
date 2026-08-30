from __future__ import annotations

import math

import pytest

from modules.system.runtime_endpoints import (
    build_voice_diagnostics_begin_endpoint,
    build_voice_diagnostics_comfort_endpoint,
    build_voice_diagnostics_comfort_signal_endpoint,
    build_voice_diagnostics_endpoint,
)
from modules.system.voice_diagnostics import VoiceDiagnostics
from routes.system_api import create_system_router


def _endpoint() -> tuple[VoiceDiagnostics, object]:
    diagnostics = VoiceDiagnostics()
    endpoint = build_voice_diagnostics_comfort_endpoint(
        diagnostics_provider=lambda: diagnostics,
    )
    return diagnostics, endpoint


def test_comfort_endpoint_records_bounded_transcript_free_sample() -> None:
    diagnostics, endpoint = _endpoint()

    result = endpoint({
        "scenario": "first_audio",
        "first_audio_latency_ms": 240.5,
        "run_id": diagnostics.run_id,
    })

    assert result["sample_count"] == 1
    assert result["first_audio_latency"]["count"] == 1
    assert result["first_audio_latency"]["p95_ms"] == 240.5
    assert diagnostics.comfort_snapshot()["claim"] == "synthetic_comfort_regression_only"


def test_begin_endpoint_rotates_run_and_rejects_stale_samples() -> None:
    diagnostics = VoiceDiagnostics()
    diagnostics.record("first_audio", 120)
    previous_run_id = diagnostics.run_id
    endpoint = build_voice_diagnostics_begin_endpoint(
        diagnostics_provider=lambda: diagnostics,
    )

    result = endpoint({"run_id": "voice-ui-next"})

    assert result == {
        "ok": True,
        "run_id": "voice-ui-next",
        "sample_count": 0,
        "schemaVersion": "yuizaki.voice-diagnostics-run.v1",
    }
    assert diagnostics.run_id == "voice-ui-next"
    with pytest.raises(ValueError, match="stale"):
        diagnostics.record("first_audio", 100, run_id=previous_run_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"run_id": "token=secret"},
        {"run_id": ""},
        {"run_id": 123},
        {"unexpected": True},
    ],
)
def test_begin_endpoint_rejects_unsafe_run_payload(payload: dict[str, object]) -> None:
    diagnostics = VoiceDiagnostics()
    endpoint = build_voice_diagnostics_begin_endpoint(
        diagnostics_provider=lambda: diagnostics,
    )
    previous_run_id = diagnostics.run_id

    with pytest.raises((TypeError, ValueError)):
        endpoint(payload)

    assert diagnostics.run_id == previous_run_id


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "empty_asr", "transcript": "secret"},
        {"scenario": "empty_asr", "audio": "base64"},
        {"scenario": "empty_asr", "run_id": "token=leaked"},
        {"scenario": "empty_asr", "first_audio_latency_ms": math.nan},
    ],
)
def test_comfort_endpoint_rejects_content_and_non_finite_values(payload: dict[str, object]) -> None:
    _diagnostics, endpoint = _endpoint()

    with pytest.raises((TypeError, ValueError)):
        endpoint(payload)


def test_comfort_endpoint_does_not_persist_rejected_sample() -> None:
    diagnostics, endpoint = _endpoint()

    with pytest.raises(ValueError):
        endpoint({"scenario": "empty_asr", "unexpected": True})

    assert diagnostics.comfort_snapshot()["sample_count"] == 0


def test_voice_diagnostics_run_route_is_exposed_only_when_handler_is_bound() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        voice_diagnostics_begin_handler=lambda _payload: {"ok": True},
    )
    paths = {route.path for route in router.routes}
    assert "/api/system/voice-diagnostics/run" in paths


def test_comfort_signal_endpoint_records_explicit_signal_only() -> None:
    diagnostics = VoiceDiagnostics()
    endpoint = build_voice_diagnostics_comfort_signal_endpoint(
        diagnostics_provider=lambda: diagnostics,
    )

    result = endpoint({
        "signal": "hesitation",
        "source": "local_vad",
        "confidence": 0.875,
        "duration_ms": 420,
    })

    assert result["ok"] is True
    assert result["accepted"] is True
    assert result["sample_count"] == 1
    assert result["signal_counts"] == {
        "hesitation": 1,
        "backchannel": 0,
        "background_speech": 0,
    }
    assert result["source_counts"]["local_vad"] == 1
    assert diagnostics.comfort_snapshot()["comfort_signals"]["claim"] == "comfort_signal_regression_only"


@pytest.mark.parametrize(
    "payload",
    [
        {"signal": "hesitation", "source": "local_vad", "confidence": math.nan},
        {"signal": "hesitation", "source": "local_vad", "confidence": 1.01},
        {"signal": "unknown", "source": "local_vad", "confidence": 0.5},
        {"signal": "hesitation", "source": "unknown", "confidence": 0.5},
        {"signal": "hesitation", "source": "local_vad", "confidence": 0.5, "transcript": "secret"},
        {"signal": "hesitation", "source": "local_vad", "confidence": 0.5, "audio": "base64"},
        {"signal": "hesitation", "source": "local_vad", "confidence": 0.5, "run_id": "token=leaked"},
    ],
)
def test_comfort_signal_endpoint_rejects_ambiguous_or_sensitive_payloads(
    payload: dict[str, object],
) -> None:
    diagnostics = VoiceDiagnostics()
    endpoint = build_voice_diagnostics_comfort_signal_endpoint(
        diagnostics_provider=lambda: diagnostics,
    )

    with pytest.raises((TypeError, ValueError)):
        endpoint(payload)

    assert diagnostics.comfort_signal_snapshot()["sample_count"] == 0


def test_comfort_signal_samples_survive_reload(tmp_path) -> None:
    path = tmp_path / "voice-diagnostics.json"
    first = VoiceDiagnostics(persistence_path=path)
    endpoint = build_voice_diagnostics_comfort_signal_endpoint(
        diagnostics_provider=lambda: first,
    )
    endpoint({
        "signal": "background_speech",
        "source": "provider_vad",
        "confidence": 0.6,
        "duration_ms": 180,
    })

    second = VoiceDiagnostics(persistence_path=path)
    snapshot = second.comfort_signal_snapshot()
    assert snapshot["sample_count"] == 1
    assert snapshot["signal_counts"]["background_speech"] == 1
    assert snapshot["source_counts"]["provider_vad"] == 1


def test_comfort_signal_route_is_exposed_only_when_handler_is_bound() -> None:
    router = create_system_router(
        health_handler=dict,
        readiness_handler=dict,
        system_status_handler=dict,
        voice_diagnostics_comfort_signal_handler=lambda _payload: {"ok": True},
    )
    paths = {route.path for route in router.routes}
    assert "/api/system/voice-diagnostics/comfort-signal" in paths


def test_voice_diagnostics_endpoint_projects_redacted_release_gates() -> None:
    diagnostics = VoiceDiagnostics()
    endpoint = build_voice_diagnostics_endpoint(diagnostics_provider=lambda: diagnostics)

    result = endpoint()

    assert result["qualification"]["status"] == "not_qualified"
    assert result["release_gate"]["status"] == "fail"
    assert result["qualification"]["sample_count"] == 0
    assert "provenance" not in result["qualification"]
    assert not {"machine", "input_device", "output_device"}.intersection(result["qualification"])
