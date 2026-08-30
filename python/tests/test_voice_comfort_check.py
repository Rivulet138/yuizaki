from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.voice_comfort_check import run_checks


def test_voice_comfort_replay_is_synthetic_and_fail_closed() -> None:
    report = run_checks()

    assert report["schemaVersion"] == "yuizaki.voice-comfort-evaluation.v1"
    assert report["networkAccess"] is False
    assert report["realDevice"] is False
    assert report["claim"] == "synthetic_voice_comfort_regression_only"
    assert report["summary"] == {"passed": 3, "total": 3}
    assert all(item["passed"] is True for item in report["scenarios"])
