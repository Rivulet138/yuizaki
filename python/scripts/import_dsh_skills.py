#!/usr/bin/env python
"""Import DSH / Codex ``SKILL.md`` directories into the Yuizaki skill catalog.

The catalog is metadata only: every entry stays ``catalog_only`` and
``executionReady=False``. Nothing is executed, imported, or trusted here.

Usage (from the repository root):

    python python/scripts/import_dsh_skills.py --dry-run
    python python/scripts/import_dsh_skills.py
    python python/scripts/import_dsh_skills.py --offline --json

By default the script talks to a running backend (``PUT /api/system/skills/imported``)
and falls back to writing the catalog file directly when the backend is down.
Both paths keep a timestamped backup of ``data/imported_skills.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from modules.agent.skill_import import (  # noqa: E402
    collect_skills,
    default_skill_roots,
    merge_catalog,
)
from modules.agent.skill_store import SkillCatalogStore  # noqa: E402
from modules.core.paths import data_dir_from_env  # noqa: E402


def _catalog_path() -> Path:
    return data_dir_from_env() / "imported_skills.json"


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    shutil.copy2(path, backup)
    return backup


def _existing_items(catalog_path: Path) -> list[dict]:
    return SkillCatalogStore(catalog_path).list_items()


def _push_to_api(base_url: str, items: list[dict], timeout_s: float = 10.0) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/api/system/skills/imported"
    payload = json.dumps({"items": items}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="PUT",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - loopback only
            body = response.read().decode("utf-8", "replace")
            return True, body[:400]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, str(exc)


def _emit(report: dict, *, as_json: bool, extra: dict | None = None) -> None:
    payload = {"report": report}
    if extra:
        payload.update(extra)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(
        "skills: added={added} updated={updated} unchanged={unchanged} skipped={skipped} total={total}".format(**report)
    )
    for item in report.get("added_ids", []):
        print(f"  + {item}")
    for item in report.get("updated_ids", []):
        print(f"  ~ {item}")
    for item in report.get("skipped_detail", []):
        print(f"  ! {item.get('source')}: {item.get('reason')}")
    if extra:
        for key, value in extra.items():
            print(f"{key}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import DSH/Codex SKILL.md directories into Yuizaki.")
    parser.add_argument("--dry-run", action="store_true", help="report the diff without writing anything")
    parser.add_argument("--offline", action="store_true", help="write the catalog file instead of calling the backend")
    parser.add_argument("--source", action="append", default=None, help="skill root to scan (repeatable)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="Yuizaki backend base URL")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    roots = [Path(item).expanduser() for item in args.source] if args.source else default_skill_roots()
    incoming, skipped = collect_skills(roots)
    catalog_path = _catalog_path()
    existing = _existing_items(catalog_path)
    merged, report = merge_catalog(existing, incoming)
    report.skipped.extend(skipped)

    payload = report.as_dict()
    extra = {
        "catalog": str(catalog_path),
        "sources": ", ".join(str(root) for root in roots if root.is_dir()) or "(none found)",
    }

    if args.dry_run:
        _emit(payload, as_json=args.json, extra={**extra, "mode": "dry-run"})
        return 0

    if not incoming:
        _emit(payload, as_json=args.json, extra={**extra, "mode": "skipped", "detail": "no skill sources found"})
        return 0

    if args.offline:
        backup = _backup(catalog_path)
        snapshot = SkillCatalogStore(catalog_path).replace(merged)
        summary = snapshot.get("summary") or {}
        _emit(
            payload,
            as_json=args.json,
            extra={
                **extra,
                "mode": "offline",
                "backup": str(backup) if backup else "(none)",
                "catalog_total": summary.get("total"),
                "catalog_only": summary.get("catalog_only"),
            },
        )
        return 0

    ok, detail = _push_to_api(args.base_url, merged)
    if not ok:
        backup = _backup(catalog_path)
        snapshot = SkillCatalogStore(catalog_path).replace(merged)
        summary = snapshot.get("summary") or {}
        _emit(
            payload,
            as_json=args.json,
            extra={
                **extra,
                "mode": "offline-fallback",
                "api_error": detail,
                "backup": str(backup) if backup else "(none)",
                "catalog_total": summary.get("total"),
                "catalog_only": summary.get("catalog_only"),
            },
        )
        return 0

    _emit(payload, as_json=args.json, extra={**extra, "mode": "api", "api_response": detail})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
