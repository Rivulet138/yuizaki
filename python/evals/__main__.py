from __future__ import annotations

import argparse
import json
from pathlib import Path

from .suite import DEFAULT_FIXTURE, load_fixture, load_thresholds, run_suite


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Yuizaki model-quality evaluations.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--thresholds", type=Path, help="Optional JSON object overriding fixture quality gates.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    threshold_overrides = load_thresholds(args.thresholds) if args.thresholds else None
    result = run_suite(load_fixture(args.fixture), threshold_overrides=threshold_overrides, fixture_path=args.fixture)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
