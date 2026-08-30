from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.stream_staging_check import run_staging_checks


def test_local_stream_staging_replay_covers_success_and_recovery_boundaries() -> None:
    report = run_staging_checks()

    assert report["schemaVersion"] == "yuizaki.stream-staging-evaluation.v1"
    assert report["networkAccess"] is False
    assert report["realProviders"] is False
    assert report["claim"] == "local_stream_contract_replay_only"
    assert report["summary"] == {"passed": 6, "total": 6}
    assert all(item["passed"] is True for item in report["scenarios"])
