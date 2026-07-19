from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
IGNORED_SCHEMES = ("http://", "https://", "mailto:", "data:", "app://")
MAINTAINED_DOCS = {
    "API.md",
    "ARCHITECTURE.md",
    "DEPENDENCIES.md",
    "ENVIRONMENT_SETUP.md",
    "LINUX.md",
    "PRODUCT.md",
    "QUICKSTART.md",
    "README.md",
    "REPOSITORY_AUDIT.md",
    "RESOURCE_MANAGEMENT.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "python/tests/README.md",
    "services/soulx-svc/README.md",
}
FORBIDDEN_TEXT = {
    "qdrant/qdrant:latest": "Qdrant images must be pinned",
    "MEMORY_BACKEND=inmemory": "fresh installs must keep persistent memory",
    "WHISPER_LANG": "use ASR_LANGUAGE",
    "python/data/memory/memories.db": "the default database is python/data/memory.db",
    "E:/GPT-SoVITS": "do not commit machine-specific example paths",
}


def tracked_markdown() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return sorted({ROOT / line for line in result.stdout.splitlines() if line})


def local_link_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith("#") or target.lower().startswith(IGNORED_SCHEMES):
        return None
    path_part = unquote(target.split("#", 1)[0])
    return (document.parent / path_part).resolve()


def main() -> int:
    errors: list[str] = []
    tracked = tracked_markdown()
    tracked_names = {path.relative_to(ROOT).as_posix() for path in tracked}
    missing_docs = sorted(MAINTAINED_DOCS - tracked_names)
    errors.extend(f"missing maintained document: {name}" for name in missing_docs)

    for document in tracked:
        text = document.read_text(encoding="utf-8")
        relative = document.relative_to(ROOT).as_posix()
        if relative in MAINTAINED_DOCS:
            for forbidden, reason in FORBIDDEN_TEXT.items():
                if forbidden in text:
                    errors.append(f"{relative}: contains {forbidden!r} ({reason})")
        for match in MARKDOWN_LINK.finditer(text):
            target = local_link_target(document, match.group(1))
            if target is not None and not target.exists():
                errors.append(f"{relative}: broken local link {match.group(1)!r}")

    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Documentation validation passed ({len(tracked)} tracked Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
