from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "python" / "evals" / "fixtures" / "proactive_policy.json"
SCRIPT = ROOT / "scripts" / "proactive_policy_check.py"


def test_cli_uses_deterministic_fixture_clock_by_default() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--cases", str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["evaluatedAt"] == 1_800_000_000.0
    assert report["summary"]["passed"] == report["summary"]["total"] == 11

