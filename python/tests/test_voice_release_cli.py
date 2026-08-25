from __future__ import annotations

import json

from modules.system.voice_diagnostics import VoiceDiagnostics
from modules.system.voice_qualification_artifact import (
    JsonVoiceQualificationArtifactStore,
)
from modules.system.voice_release_runner import VoiceQualificationReleaseRunner, main


def test_voice_release_cli_without_artifact_is_fail_closed(tmp_path, capsys) -> None:
    output = tmp_path / "voice-report.json"

    status = main(["--output", str(output)])

    assert status == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "not_qualified"
    assert report["cli_reason"] == "artifact_missing"
    assert JsonVoiceQualificationArtifactStore(output).read()["status"] == "not_qualified"


def test_voice_release_cli_rejects_corrupt_or_synthetic_artifacts(tmp_path, capsys) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")
    assert main(["--artifact", str(corrupt)]) == 2
    assert json.loads(capsys.readouterr().out)["cli_reason"] == "artifact_invalid"

    synthetic = tmp_path / "synthetic.json"
    synthetic.write_text(json.dumps({"status": "qualified", "evidence_kind": "synthetic"}), encoding="utf-8")
    assert main(["--artifact", str(synthetic)]) == 2
    assert json.loads(capsys.readouterr().out)["cli_reason"] == "artifact_invalid"


def test_voice_release_cli_does_not_promote_unattested_qualified_artifact(tmp_path, capsys) -> None:
    qualified_path = tmp_path / "qualified.json"
    diagnostics = VoiceDiagnostics()
    # An empty run cannot qualify, so this is only a shape test for the CLI's
    # no-authority boundary: write a valid non-qualified artifact first.
    VoiceQualificationReleaseRunner(JsonVoiceQualificationArtifactStore(qualified_path)).run(diagnostics)
    report = json.loads(qualified_path.read_text(encoding="utf-8"))
    report["status"] = "qualified"
    report["claim"] = "product_voice_release_gate_passed"
    qualified_path.write_text(json.dumps(report), encoding="utf-8")

    assert main(["--artifact", str(qualified_path)]) == 2
    fallback = json.loads(capsys.readouterr().out)
    assert fallback["status"] == "not_qualified"
    assert fallback["cli_reason"] == "artifact_invalid"


def test_voice_release_cli_round_trips_valid_not_qualified_artifact(tmp_path, capsys) -> None:
    source = tmp_path / "source.json"
    target = tmp_path / "target.json"
    VoiceQualificationReleaseRunner(JsonVoiceQualificationArtifactStore(source)).run(VoiceDiagnostics())

    assert main(["--artifact", str(source), "--output", str(target)]) == 2
    rendered = json.loads(capsys.readouterr().out)
    persisted = JsonVoiceQualificationArtifactStore(target).read()
    assert rendered["status"] == persisted["status"] == "not_qualified"
    assert rendered["run_id"] == persisted["run_id"]
