"""Import DSH / Codex ``SKILL.md`` directories into the Yuizaki skill catalog.

The catalog is metadata only. Every imported entry keeps
``runtimeBinding="catalog_only"`` and ``executionReady=False`` so a directory
listing can never be mistaken for an executable capability; see
``skill_store._normalize_skill_payload``, which enforces the same rule at write
time.

This module is pure parsing plus merge bookkeeping. File and HTTP side effects
live in ``scripts/import_dsh_skills.py`` so the parsers stay testable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .skill_store import _normalize_skill_id

SKILL_FILE_NAME = "SKILL.md"
MAX_SKILLS = 200
MAX_NAME = 120
MAX_DESCRIPTION = 1200
MAX_TAG = 48

# Deliberately conservative: a developer-oriented skill fits a companion app
# poorly even when it is well written.
_FIT_BY_CATEGORY = {
    "companion": "high",
    "automation": "medium",
    "document": "medium",
    "research": "medium",
    "media": "medium",
    "authoring": "medium",
    "general": "medium",
    "development": "low",
    "frontend": "low",
    "mcp": "low",
    "governance": "low",
}

# Order breaks score ties. Earlier categories win, so "code review" lands in
# development rather than governance, and "mcp-builder" stays mcp.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("companion", ("companion", "memory", "persona", "avatar", "voice", "chat", "桌面", "陪伴", "记忆")),
    ("mcp", ("mcp", "model context protocol", "server tool")),
    ("development", (
        "code", "coding", "refactor", "test", "bug", "build", "ci", "git", "api", "sdk",
        "repo", "debug", "python", "typescript", "javascript", "deploy", "migration",
    )),
    ("frontend", ("frontend", "front-end", "css", "figma", "ui", "ux", "component", "layout", "design", "visual")),
    ("research", ("research", "paper", "arxiv", "benchmark", "compare", "knowledge", "docs", "documentation search")),
    ("automation", ("automate", "automation", "workflow", "scrape", "crawl", "cron", "schedule", "pipeline", "ops")),
    ("document", (
        "document", "report", "wiki", "notion", "pdf", "slide", "presentation", "spreadsheet",
        "invoice", "resume", "email", "changelog", "meeting",
    )),
    ("media", ("image", "video", "audio", "gif", "music", "photo", "canvas", "poster", "art")),
    ("authoring", ("writing", "content", "blog", "article", "copy", "prompt", "story")),
    ("governance", ("security", "review", "audit", "policy", "permission", "triage", "safety", "安全", "审计")),
)


@dataclass
class MergeReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.updated) + len(self.unchanged)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": len(self.added),
            "updated": len(self.updated),
            "unchanged": len(self.unchanged),
            "skipped": len(self.skipped),
            "total": self.total,
            "added_ids": self.added,
            "updated_ids": self.updated,
            "skipped_detail": self.skipped,
        }


def _clean(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip()
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return ``(frontmatter, body)`` for a ``---``-delimited Markdown header.

    Only flat ``key: value`` pairs are supported. That is all the DSH and Codex
    skill frontmatter uses, and refusing to guess is safer than a partial YAML
    implementation.
    """
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---"):
        return {}, normalized
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, normalized
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return {}, normalized
    front: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if not key or key in front:
            continue
        front[key] = _clean(value)
    return front, "\n".join(lines[end + 1:])


def _first_heading(body: str) -> str:
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if text:
                return text
    return ""


def _first_paragraph(body: str) -> str:
    block: list[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped:
            if block:
                break
            continue
        if stripped.startswith("#") or stripped.startswith("```") or stripped.startswith("|"):
            if block:
                break
            continue
        block.append(stripped)
    return " ".join(block)


def classify_category(name: str, description: str) -> str:
    """Pick the best-matching category by keyword count, then declaration order.

    Scoring rather than "first match wins" keeps mixed titles honest: a
    "Code Review" skill is development even though "review" also appears in the
    governance list, while "Build UI from Figma" stays frontend.
    """
    haystack = f"{name} {description}".lower()
    best_category = "general"
    best_score = 0
    for category, keywords in _CATEGORY_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > best_score:
            best_category = category
            best_score = score
    return best_category


def derive_tags(name: str, description: str, category: str) -> list[str]:
    words: list[str] = []
    for raw in re.split(r"[^a-z0-9\u4e00-\u9fff]+", f"{name} {description}".lower()):
        token = raw.strip()
        if len(token) < 3 or token in words:
            continue
        words.append(token)
        if len(words) >= 6:
            break
    tags = [category, *words[:5]]
    deduped: list[str] = []
    for tag in tags:
        value = tag[:MAX_TAG]
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def skill_entry_from_markdown(markdown: str, *, directory: Path | None = None, fallback_id: str = "") -> dict[str, Any] | None:
    """Build one catalog entry from a SKILL.md payload, or ``None`` if unusable."""
    front, body = parse_frontmatter(markdown)
    name = (front.get("name") or _first_heading(body))[:MAX_NAME].strip()
    description = (front.get("description") or _first_paragraph(body))[:MAX_DESCRIPTION].strip()
    if not name and not description:
        return None
    if not name:
        name = fallback_id[:MAX_NAME] or "imported-skill"
    category = front.get("category") or classify_category(name, description)
    entry: dict[str, Any] = {
        "name": name,
        "description": description or "导入的本地 Skill",
        "category": category,
        "fit": _FIT_BY_CATEGORY.get(category, "medium"),
        "tags": derive_tags(name, description, category),
        "repo": front.get("repo") or None,
        "url": front.get("url") or None,
    }
    skill_id = (front.get("id") or name or fallback_id).strip()
    if skill_id:
        entry["id"] = skill_id[:160]
    if directory is not None:
        entry["directory"] = str(directory)
    return entry


def default_skill_roots(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return the skill roots to scan, honoring ``YUIZAKI_SKILL_SOURCES``.

    ``YUIZAKI_SKILL_SOURCES`` is an ``os.pathsep``-separated list of directories.
    When it is set, only those directories are scanned.
    """
    values = dict(os.environ if env is None else env)
    configured = str(values.get("YUIZAKI_SKILL_SOURCES", "") or "").strip()
    if configured:
        return [Path(item).expanduser() for item in configured.split(os.pathsep) if item.strip()]
    home = Path(values.get("USERPROFILE") or values.get("HOME") or Path.home())
    return [home / ".dsh" / "skills", home / ".codex" / "skills"]


def collect_skills(roots: Iterable[Path], *, limit: int = MAX_SKILLS) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Scan ``<root>/<skill>/SKILL.md`` and return ``(entries, skipped)``."""
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.is_dir():
                continue
            candidates = sorted(path for path in root.iterdir() if path.is_dir())
        except OSError as exc:
            skipped.append({"source": str(root), "reason": f"unreadable: {exc}"})
            continue
        for directory in candidates:
            if len(entries) >= limit:
                skipped.append({"source": str(directory), "reason": f"limit {limit} reached"})
                continue
            skill_file = directory / SKILL_FILE_NAME
            if not skill_file.is_file():
                continue
            try:
                markdown = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                skipped.append({"source": str(skill_file), "reason": f"unreadable: {exc}"})
                continue
            entry = skill_entry_from_markdown(markdown, directory=directory, fallback_id=directory.name)
            if entry is None:
                skipped.append({"source": str(skill_file), "reason": "no name or description"})
                continue
            key = str(entry.get("id") or entry["name"]).lower()
            if key in seen:
                skipped.append({"source": str(skill_file), "reason": "duplicate id"})
                continue
            seen.add(key)
            entries.append(entry)
    return entries, skipped


_COMPARED_FIELDS = ("name", "description", "category", "fit", "directory")


def merge_catalog(existing: Iterable[Mapping[str, Any]], incoming: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], MergeReport]:
    """Merge incoming entries over the existing catalog.

    Identity is the same normalized id the store uses, so re-running an import is
    idempotent even for display names containing spaces. Fields owned by the
    trust layer (``runtimeBinding``, ``executionReady``) are never taken from the
    incoming payload.
    """
    merged: dict[str, dict[str, Any]] = {}
    for item in existing:
        if not isinstance(item, Mapping):
            continue
        key = _normalize_skill_id(str(item.get("id") or item.get("name") or ""))
        if key:
            merged[key] = dict(item)
    report = MergeReport()
    for item in incoming:
        if not isinstance(item, Mapping):
            continue
        raw_key = str(item.get("id") or item.get("name") or "").strip()
        if not raw_key:
            report.skipped.append({"source": "<memory>", "reason": "missing id"})
            continue
        key = _normalize_skill_id(raw_key)
        previous = merged.get(key)
        if previous is None:
            entry = dict(item)
            entry["id"] = key
            merged[key] = entry
            report.added.append(key)
            continue
        updated = dict(previous)
        changed = False
        for compared in _COMPARED_FIELDS:
            if compared not in item:
                continue
            if previous.get(compared) != item.get(compared):
                updated[compared] = item.get(compared)
                changed = True
        for extra in ("tags", "repo", "url"):
            if extra in item and previous.get(extra) != item.get(extra):
                updated[extra] = item.get(extra)
                changed = True
        updated["id"] = previous.get("id") or key
        if changed:
            merged[key] = updated
            report.updated.append(key)
        else:
            report.unchanged.append(key)
    return list(merged.values()), report
