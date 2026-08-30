from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from modules.memory.evaluation import load_golden_cases

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "python" / "evals" / "fixtures" / "memory_retrieval.json"
SCRIPT = ROOT / "scripts" / "memory_retrieval_check.py"


def test_memory_fixture_is_bounded_and_unique() -> None:
    cases = load_golden_cases(FIXTURE)
    assert len(cases) == 6
    assert len({case["id"] for case in cases}) == len(cases)


def test_memory_retrieval_replay_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == "yuizaki.memory-evaluation.v1"
    assert report["passed"] == report["case_count"] == 6
    assert report["llm_service_calls"] == 0


def test_memory_fixture_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps([{"id": "same"}, {"id": "same"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_golden_cases(duplicate)
