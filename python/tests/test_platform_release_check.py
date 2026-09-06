from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_platform_release_check_is_fail_closed_without_evidence(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output_path = tmp_path / "release-readiness.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/platform_release_check.py",
            "--target-platform",
            "windows",
            "--output",
            str(output_path),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    stdout_report = json.loads(completed.stdout)
    file_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_report == file_report
    assert stdout_report["status"] == "not_qualified"
    assert stdout_report["claim"] == "must_not_be_used_as_release_qualification"
