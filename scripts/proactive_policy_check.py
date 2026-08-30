"""Replay redacted proactive policy cases and emit a CI-friendly report."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

_PYTHON_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from modules.agent.proactive_evaluation import (
    SCHEMA_VERSION,
    evaluate_proactive_case,
    load_golden_cases,
    summarize_proactive_results,
)


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary_path.write_text(payload, encoding="utf-8")
        temporary_path.replace(path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _default_replay_now(cases: list[dict[str, Any]]) -> float:
    """Choose a deterministic clock from the fixture when none is supplied.

    Golden cases use a fixed frame timestamp so cooldown and budget decisions
    remain reproducible in CI. Falling back to ``time.time()`` would make the
    same fixture change meaning as the calendar advances.
    """
    timestamps: list[float] = []
    for case in cases:
        frame = case.get("frame")
        if not isinstance(frame, dict):
            continue
        value = frame.get("sourceCreatedAt", frame.get("source_created_at"))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            timestamps.append(numeric)
    if not timestamps:
        raise ValueError("cases must contain at least one finite frame sourceCreatedAt")
    return min(timestamps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay redacted Yuizaki proactive policy cases without external side effects."
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument(
        "--now",
        type=float,
        help="Replay clock in Unix seconds; defaults to the earliest fixture frame timestamp.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        cases = load_golden_cases(args.cases)
        evaluation_now = _default_replay_now(cases) if args.now is None else float(args.now)
        if not math.isfinite(evaluation_now):
            raise ValueError("now must be finite")
        results = [evaluate_proactive_case(case, now=evaluation_now) for case in cases]
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"cases rejected: {error}")
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "evaluatedAt": evaluation_now,
        "summary": summarize_proactive_results(results),
        "results": [result.to_dict() for result in results],
    }
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        _write_atomic(args.output, payload + "\n")
    print(payload)
    return 0 if report["summary"]["passed"] == report["summary"]["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
