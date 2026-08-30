from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.connector_staging_check import run_staging_checks


def test_local_connector_staging_replay_covers_signature_and_idempotency() -> None:
    report = asyncio.run(run_staging_checks())

    assert report["schemaVersion"] == "yuizaki.connector-staging-evaluation.v1"
    assert report["networkAccess"] is False
    assert report["realProviders"] is False
    assert report["claim"] == "local_connector_contract_replay_only"
    assert report["summary"] == {"passed": 4, "total": 4}
    assert all(item["passed"] is True for item in report["scenarios"])
