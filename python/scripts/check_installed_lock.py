"""Verify installed direct distributions match a platform lock exactly."""

from __future__ import annotations

import argparse
import importlib.metadata
from pathlib import Path

try:
    from .check_requirements_lock import _parse_requirements
except ImportError:  # pragma: no cover - direct script execution path
    from check_requirements_lock import _parse_requirements


ROOT = Path(__file__).resolve().parents[1]


def validate(lock: Path) -> list[str]:
    errors: list[str] = []
    for _normalized_name, (specifier, display_name) in _parse_requirements(lock).items():
        expected = specifier.removeprefix("==").strip()
        if not expected or expected == specifier:
            errors.append(f"{display_name}: lock entry is not an exact pin ({specifier})")
            continue
        try:
            installed = importlib.metadata.version(display_name)
        except importlib.metadata.PackageNotFoundError:
            errors.append(f"{display_name}: not installed (expected {expected})")
            continue
        if installed != expected:
            errors.append(f"{display_name}: installed {installed}, expected {expected}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check installed packages against an exact Yuizaki lock.")
    parser.add_argument("--lock", type=Path, required=True, help="Lock file relative to python/ or an absolute path.")
    args = parser.parse_args(argv)
    lock = args.lock if args.lock.is_absolute() else ROOT / args.lock
    if not lock.exists():
        parser.error(f"lock file does not exist: {lock}")
    errors = validate(lock)
    if errors:
        print("Installed dependency lock validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Installed dependency lock validation passed ({lock.name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
