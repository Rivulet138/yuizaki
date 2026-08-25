"""Fail-closed release runner for real-device voice qualification evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .voice_diagnostics import (
    DEFAULT_VOICE_LATENCY_BUDGETS_MS,
    VoiceDiagnostics,
    VoiceMeasurementHandle,
)
from .voice_qualification_artifact import JsonVoiceQualificationArtifactStore


class VoiceQualificationReleaseRunner:
    """Build and persist one evidence artifact from a single diagnostic run.

    The runner never accepts a caller-provided snapshot. It evaluates the
    diagnostics instance directly, combines completeness with latency and
    recovery gates, and delegates qualified-artifact authorization to the
    injected external attestation verifier owned by the artifact store.
    """

    def __init__(
        self,
        artifact_store: JsonVoiceQualificationArtifactStore,
        *,
        latency_budgets_ms: Mapping[str, float] | None = None,
        min_recovery_success_rate: float = 0.01,
    ) -> None:
        self.artifact_store = artifact_store
        self.latency_budgets_ms = dict(latency_budgets_ms or DEFAULT_VOICE_LATENCY_BUDGETS_MS)
        self.min_recovery_success_rate = min_recovery_success_rate

    def run(
        self,
        diagnostics: VoiceDiagnostics,
        *,
        run_id: str | None = None,
        handle: VoiceMeasurementHandle | None = None,
    ) -> dict[str, Any]:
        qualification = diagnostics.qualification_snapshot(run_id=run_id, handle=handle)
        gate = diagnostics.release_gate(
            run_id=run_id,
            handle=handle,
            latency_budgets_ms=self.latency_budgets_ms,
            min_recovery_success_rate=self.min_recovery_success_rate,
        )
        passed = qualification["status"] == "qualified" and gate["status"] == "pass"
        report = dict(qualification)
        report["release_gate"] = gate
        report["status"] = "qualified" if passed else "not_qualified"
        report["claim"] = (
            "product_voice_release_gate_passed"
            if passed
            else "must_not_be_used_as_voice_release_qualification"
        )
        self.artifact_store.write(report)
        return report


def _not_qualified_report(reason: str) -> dict[str, Any]:
    """Create a safe CLI fallback without inventing a device measurement."""
    diagnostics = VoiceDiagnostics()
    qualification = diagnostics.qualification_snapshot()
    gate = diagnostics.release_gate()
    report = dict(qualification)
    report["release_gate"] = gate
    report["status"] = "not_qualified"
    report["claim"] = "must_not_be_used_as_voice_release_qualification"
    report["cli_reason"] = reason
    return report


def main(argv: list[str] | None = None) -> int:
    """Consume one external redacted artifact for release/CI inspection.

    This command is intentionally not a measurement harness. It cannot turn
    JSON into samples or supply the external attestation needed for a
    ``qualified`` report. A missing, corrupt, synthetic, or unattested input
    produces a persisted ``not_qualified`` report and a non-zero exit code.
    """
    parser = argparse.ArgumentParser(description="Inspect Yuizaki real-device voice qualification evidence.")
    parser.add_argument("--artifact", type=Path, help="Existing redacted artifact produced by a release runner.")
    parser.add_argument("--output", type=Path, help="Optional path for the resulting redacted report.")
    args = parser.parse_args(argv)

    reason = "artifact_missing"
    report: dict[str, Any]
    if args.artifact is None:
        report = _not_qualified_report(reason)
    else:
        try:
            report = JsonVoiceQualificationArtifactStore(args.artifact).read()
            if report.get("status") == "qualified":
                # The CLI has no publisher/hardware authority by design.
                report = _not_qualified_report("external_attestation_required")
            else:
                reason = "artifact_not_qualified"
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            report = _not_qualified_report("artifact_invalid")

    if args.output is not None:
        try:
            JsonVoiceQualificationArtifactStore(args.output).write(report)
        except (OSError, TypeError, ValueError) as error:
            parser.exit(3, f"voice qualification output rejected: {error}\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.get("status") == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["VoiceQualificationReleaseRunner", "main"]
