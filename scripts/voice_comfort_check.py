"""Replay transcript-free voice comfort checks without devices or network.

This command exercises the same ``VoiceDiagnostics`` comfort gate used by the
runtime.  Values are deterministic synthetic fixtures: a passing report is
useful for regression and CI, but never qualifies a real microphone, speaker,
echo canceller, or VAD implementation.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modules.system.voice_diagnostics import VoiceDiagnostics

SCHEMA_VERSION = "yuizaki.voice-comfort-evaluation.v1"


def _case(name: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"name": name, "passed": True, "details": callback()}
    except Exception as exc:  # noqa: BLE001 - keep every bounded case visible.
        return {"name": name, "passed": False, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


def _healthy_run() -> dict[str, Any]:
    diagnostics = VoiceDiagnostics()
    run_id = diagnostics.begin_run("voice-comfort-staging")
    diagnostics.record_comfort_scenario(
        "deliberate_interrupt",
        run_id=run_id,
        stop_audio_latency_ms=180,
        interrupt_ack_latency_ms=120,
        false_interruption=False,
        continuous_turn_completed=True,
    )
    for scenario, first_audio in (
        ("hesitation", 220),
        ("backchannel", 240),
        ("background_speech", 260),
        ("empty_asr", 230),
    ):
        diagnostics.record_comfort_scenario(
            scenario,
            run_id=run_id,
            first_audio_latency_ms=first_audio,
            continuous_turn_completed=True,
        )
    for signal, source, confidence, duration in (
        ("hesitation", "local_vad", 0.8, 120),
        ("backchannel", "provider_vad", 0.7, 160),
        ("background_speech", "classifier", 0.6, 300),
    ):
        diagnostics.record_comfort_signal(
            signal,
            source,
            confidence,
            duration_ms=duration,
            run_id=run_id,
        )
    snapshot = diagnostics.comfort_snapshot()
    gate = snapshot["comfort_gate"]
    assert gate["status"] == "pass"
    assert snapshot["coverage_complete"] is True
    assert snapshot["comfort_signals"]["coverage_complete"] is True
    assert snapshot["claim"] == "synthetic_comfort_regression_only"
    return {
        "gate": gate,
        "scenarioCoverage": snapshot["scenario_counts"],
        "signalCoverage": snapshot["comfort_signals"]["signal_counts"],
        "falseInterruptionRate": snapshot["false_interruption_rate"],
        "continuousTurnCompletionRate": snapshot["continuous_turn_completion_rate"],
    }


def _missing_data_fails_closed() -> dict[str, Any]:
    diagnostics = VoiceDiagnostics()
    run_id = diagnostics.begin_run("voice-comfort-incomplete")
    diagnostics.record_comfort_scenario("first_audio", run_id=run_id, first_audio_latency_ms=240)
    gate = diagnostics.comfort_snapshot()["comfort_gate"]
    assert gate["status"] == "insufficient_data"
    assert "deliberate_interrupt" in diagnostics.comfort_snapshot()["missing_scenarios"]
    return {"status": gate["status"], "missingScenarioCount": len(diagnostics.comfort_snapshot()["missing_scenarios"])}


def _run_rotation_clears_previous_samples() -> dict[str, Any]:
    diagnostics = VoiceDiagnostics()
    first_run = diagnostics.begin_run("voice-comfort-a")
    diagnostics.record_comfort_scenario("empty_asr", run_id=first_run)
    second_run = diagnostics.begin_run("voice-comfort-b")
    snapshot = diagnostics.comfort_snapshot()
    assert second_run != first_run
    assert snapshot["sample_count"] == 0
    return {"previousRun": first_run, "currentRun": second_run, "sampleCount": snapshot["sample_count"]}


def run_checks() -> dict[str, Any]:
    scenarios = [
        _case("healthy_synthetic_run", _healthy_run),
        _case("missing_data_fails_closed", _missing_data_fails_closed),
        _case("run_rotation_clears_previous_samples", _run_rotation_clears_previous_samples),
    ]
    passed = sum(item["passed"] is True for item in scenarios)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "networkAccess": False,
        "realDevice": False,
        "claim": "synthetic_voice_comfort_regression_only",
        "summary": {"passed": passed, "total": len(scenarios)},
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = run_checks()
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(f"{args.output.suffix}.tmp")
        try:
            temporary.write_text(payload + "\n", encoding="utf-8")
            temporary.replace(args.output)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    print(payload)
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
