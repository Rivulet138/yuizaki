"""Print the fail-closed platform release readiness gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the standalone repository script work from either the repo root or
# another working directory without requiring an editable Python install.
_PYTHON_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from modules.system.release_readiness import build_release_readiness_snapshot


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return value if isinstance(value, dict) else None


def _write_atomic(path: Path, payload: str) -> None:
    """Publish a complete report without truncating an existing gate file."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Yuizaki platform release qualification evidence.")
    parser.add_argument("--platform-attestation", type=Path)
    parser.add_argument("--soak-report", type=Path)
    parser.add_argument("--target-platform")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_release_readiness_snapshot(
            platform_qualification=_read_json(args.platform_attestation),
            soak_report=_read_json(args.soak_report),
            target_platform=args.target_platform,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(f"evidence rejected: {error}")
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        _write_atomic(args.output, payload + "\n")
    print(payload)
    return 0 if report["status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
