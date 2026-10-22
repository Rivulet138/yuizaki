from __future__ import annotations

import json
import os
from pathlib import Path

from modules.agent.skill_import import (
    MergeReport,
    classify_category,
    collect_skills,
    derive_tags,
    default_skill_roots,
    merge_catalog,
    parse_frontmatter,
    skill_entry_from_markdown,
)
from modules.agent.skill_store import SkillCatalogStore


def _write_skill(root: Path, name: str, body: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(body, encoding="utf-8")
    return directory


def test_parse_frontmatter_handles_quotes_and_crlf() -> None:
    front, body = parse_frontmatter(
        '---\r\nname: "agent-deep-links"\r\ndescription: \'Build deep links\'\r\n---\r\n# Title\r\n'
    )
    assert front == {"name": "agent-deep-links", "description": "Build deep links"}
    assert body.strip() == "# Title"


def test_parse_frontmatter_ignores_unterminated_and_plain_documents() -> None:
    assert parse_frontmatter("---\nname: x\n") == ({}, "---\nname: x\n")
    assert parse_frontmatter("# Just a heading\n\nText") == ({}, "# Just a heading\n\nText")


def test_entry_falls_back_to_heading_and_paragraph() -> None:
    entry = skill_entry_from_markdown(
        "# Memory tidy-up\n\nKeeps companion memories clean and short.\n\n## Workflow\n1. Read.\n",
        fallback_id="memory-tidy",
    )
    assert entry is not None
    assert entry["name"] == "Memory tidy-up"
    assert entry["description"].startswith("Keeps companion memories")
    assert entry["category"] == "companion"
    assert entry["fit"] == "high"
    assert "id" in entry


def test_entry_requires_some_identity() -> None:
    assert skill_entry_from_markdown("", fallback_id="") is None


def test_category_and_fit_are_conservative_for_developer_skills() -> None:
    assert classify_category("Code Review", "Review a pull request diff") == "development"
    assert classify_category("Figma Implement", "Build UI from Figma nodes") == "frontend"
    assert classify_category("Memory Keeper", "陪伴与长期记忆整理") == "companion"
    assert classify_category("Something Else", "unrelated words") == "general"
    entry = skill_entry_from_markdown("---\nname: Repo Audit\ndescription: audit a git repository\n---\n")
    assert entry is not None
    assert entry["category"] == "development"
    assert entry["fit"] == "low", "developer skills must not claim a high companion fit"


def test_derive_tags_is_bounded_and_deduplicated() -> None:
    tags = derive_tags("Skill", "one one two three four five six seven eight", "general")
    assert tags[0] == "general"
    assert len(tags) <= 6
    assert len(set(tags)) == len(tags)
    assert all(len(tag) <= 48 for tag in tags)


def test_collect_skills_scans_directories_and_reports_skips(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "alpha", "---\nname: Alpha\ndescription: first skill\n---\n")
    _write_skill(root, "beta", "---\nname: Alpha\ndescription: duplicate id\n---\n")
    _write_skill(root, "gamma", "")
    (root / "empty-dir").mkdir()
    entries, skipped = collect_skills([root, tmp_path / "missing"])
    assert [entry["name"] for entry in entries] == ["Alpha"]
    reasons = {item["reason"] for item in skipped}
    assert "duplicate id" in reasons
    assert "no name or description" in reasons
    assert all(item["source"] for item in skipped)


def test_collect_skills_enforces_a_limit(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    for index in range(3):
        _write_skill(root, f"skill-{index}", f"---\nname: Skill {index}\ndescription: d\n---\n")
    entries, skipped = collect_skills([root], limit=2)
    assert len(entries) == 2
    assert any("limit" in item["reason"] for item in skipped)


def test_default_roots_honour_override() -> None:
    roots = default_skill_roots({"YUIZAKI_SKILL_SOURCES": f"C:/a{os.pathsep}C:/b"})
    assert [root.name for root in roots] == ["a", "b"]


def test_merge_is_idempotent_and_keeps_trust_fields() -> None:
    existing = [{
        "id": "Alpha",
        "name": "Alpha",
        "description": "old",
        "runtimeBinding": "catalog_only",
        "executionReady": False,
        "enabled_codex": True,
    }]
    incoming = [{
        "id": "Alpha",
        "name": "Alpha",
        "description": "new",
        "category": "development",
        "fit": "low",
        "tags": ["development"],
        "runtimeBinding": "tool",
        "executionReady": True,
    }]
    merged, report = merge_catalog(existing, incoming)
    assert isinstance(report, MergeReport)
    assert report.updated == ["Alpha"]
    item = merged[0]
    assert item["description"] == "new"
    assert item["runtimeBinding"] == "catalog_only", "incoming trust fields must be ignored"
    assert item["executionReady"] is False
    assert item["enabled_codex"] is True, "unmanaged fields survive the merge"

    merged_again, report_again = merge_catalog(merged, incoming)
    assert report_again.added == []
    assert report_again.updated == []
    assert report_again.unchanged == ["Alpha"]


def test_merge_adds_unknown_ids_and_skips_unusable(tmp_path: Path) -> None:
    merged, report = merge_catalog([], [{"name": "Brand New", "description": "d"}, {"description": "no id"}])
    assert report.added == ["imported.skill.brand-new"]
    assert merged[0]["id"] == "imported.skill.brand-new"
    assert report.skipped and report.skipped[0]["reason"] == "missing id"


def test_catalog_store_round_trip_stays_catalog_only(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "alpha", "---\nname: Alpha\ndescription: first skill\n---\n")
    entries, _ = collect_skills([root])
    catalog_path = tmp_path / "imported_skills.json"
    snapshot = SkillCatalogStore(catalog_path).replace(entries)
    assert snapshot["summary"]["total"] == 1
    assert snapshot["summary"]["catalog_only"] == 1
    persisted = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert persisted["schemaVersion"] == "yuizaki.skill-catalog.v1"
    assert persisted["items"][0]["executionReady"] is False
    assert persisted["items"][0]["runtimeBinding"] == "catalog_only"
