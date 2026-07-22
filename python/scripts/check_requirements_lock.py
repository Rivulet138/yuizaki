"""Validate the checked-in platform dependency lock matrix.

The project intentionally keeps source manifests (ranges) separate from
platform lock files (exact direct pins). This check makes drift visible in CI:
every declared direct package must be pinned once, and no undeclared direct
package may be added to a lock.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_MATRIX = {
    "requirements-core-lock-windows.txt": "requirements-core.txt",
    "requirements-core-lock-linux.txt": "requirements-core.txt",
    "requirements-lock-windows.txt": "requirements.txt",
    "requirements-lock-linux.txt": "requirements.txt",
    "requirements-dev-lock-windows.txt": "requirements-dev.txt",
    "requirements-dev-lock-linux.txt": "requirements-dev.txt",
}
LOCKS = tuple(ROOT / name for name in LOCK_MATRIX)
_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(.*)$")
_PIN_RE = re.compile(r"^==\s*([^;\s]+)")


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-")


def _merge(target: dict[str, tuple[str, str]], incoming: dict[str, tuple[str, str]], source: Path) -> None:
    for name, requirement in incoming.items():
        if name in target and target[name] != requirement:
            raise ValueError(f"{source.name}: conflicting requirement for {name}")
        target[name] = requirement


def _parse_requirements(path: Path, _seen: set[Path] | None = None) -> dict[str, tuple[str, str]]:
    """Parse a manifest or lock, resolving local ``-r`` includes."""

    seen = set() if _seen is None else _seen
    resolved = path.resolve()
    if resolved in seen:
        return {}
    seen.add(resolved)
    values: dict[str, tuple[str, str]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            included = (path.parent / line[3:].strip()).resolve()
            if not included.exists():
                raise ValueError(f"{path.name}: included file does not exist: {included.name}")
            _merge(values, _parse_requirements(included, seen), path)
            continue
        if line.startswith("-"):
            raise ValueError(f"{path.name}: unsupported requirement option: {raw_line}")
        match = _NAME_RE.match(line)
        if match is None or not match.group(2):
            raise ValueError(f"{path.name}: invalid requirement: {raw_line}")
        name, specifier = match.groups()
        normalized = _normalize(name)
        item = (specifier.strip(), name)
        if normalized in values:
            raise ValueError(f"{path.name}: duplicate requirement: {name}")
        values[normalized] = item
    return values


def _requirements(path: Path, _seen: set[Path] | None = None) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
    """Backward-compatible view returning only the pinned version string."""

    parsed = _parse_requirements(path, _seen)
    return {name: specifier.removeprefix("==").strip() for name, (specifier, _) in parsed.items()}


def _validate_lock(lock: Path, manifest: Path) -> None:
    declared = _parse_requirements(manifest)
    locked = _parse_requirements(lock)
    missing = sorted(set(declared) - set(locked))
    extra = sorted(set(locked) - set(declared))
    if missing:
        raise ValueError(f"{lock.name}: missing direct pins: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{lock.name}: undeclared direct pins: {', '.join(extra)}")

    for name, (specifier, display_name) in declared.items():
        lock_specifier, _ = locked[name]
        pin = _PIN_RE.fullmatch(lock_specifier)
        if pin is None:
            raise ValueError(f"{lock.name}: {display_name} is not exact-pinned: {lock_specifier}")
        if specifier.startswith("==") and specifier != lock_specifier:
            raise ValueError(
                f"{lock.name}: pinned version drift for {display_name}: "
                f"manifest {specifier}, lock {lock_specifier}"
            )


def main() -> int:
    for lock_name, manifest_name in LOCK_MATRIX.items():
        lock = ROOT / lock_name
        manifest = ROOT / manifest_name
        if not manifest.exists():
            raise SystemExit(f"missing source manifest: {manifest}")
        if not lock.exists():
            raise SystemExit(f"missing lock file: {lock}")
        try:
            _validate_lock(lock, manifest)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    print(f"Dependency lock validation passed ({len(LOCK_MATRIX)} files; direct pins match manifests).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
