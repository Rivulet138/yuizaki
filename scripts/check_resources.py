from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "resources.lock.json"
RESOURCE_IDS = {"soulx", "sherpa", "sherpa_online", "embedding", "tts"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    errors: list[str] = []
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if lock.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    resources = lock.get("resources", {})
    if set(resources) != RESOURCE_IDS:
        errors.append(f"resource ids must be {sorted(RESOURCE_IDS)}")

    for resource_id, resource in resources.items():
        for field in ("label", "version", "kind", "license", "licenseUrl", "downloadBytes", "sources"):
            if not resource.get(field):
                errors.append(f"{resource_id}: missing {field}")
        if not isinstance(resource.get("downloadBytes"), int) or resource.get("downloadBytes", 0) <= 0:
            errors.append(f"{resource_id}: downloadBytes must be a positive integer")
        for index, source in enumerate(resource.get("sources", [])):
            prefix = f"{resource_id}.sources[{index}]"
            if "url" in source and source.get("sha256") is not None and not SHA256.fullmatch(source["sha256"]):
                errors.append(f"{prefix}: invalid sha256")
            if "repo" in source and not REVISION.fullmatch(source.get("revision", "")):
                errors.append(f"{prefix}: Hugging Face revision must be a 40-character commit")

    for resource_id in ("sherpa", "sherpa_online"):
        source = resources.get(resource_id, {}).get("sources", [{}])[0]
        if not SHA256.fullmatch(source.get("sha256", "")):
            errors.append(f"{resource_id}: archive must have SHA256 integrity")

    if errors:
        print("Resource lock validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Resource lock validation passed ({len(resources)} resources).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
