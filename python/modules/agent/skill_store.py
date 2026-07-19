from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from ..core.paths import data_dir_from_env
logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {
    "companion",
    "development",
    "frontend",
    "research",
    "automation",
    "document",
    "mcp",
    "governance",
    "media",
    "authoring",
    "general",
}
ALLOWED_FITS = {"high", "medium", "low"}


def _string_field(value: Any, *, max_length: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _normalize_skill_id(value: str) -> str:
    raw = value.strip() or "skill"
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", raw):
        return raw[:160]
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    stable_hash = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"imported.skill.{slug or stable_hash}"[:160]


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_tags = [str(item).strip() for item in value if str(item).strip()]
    elif isinstance(value, str):
        raw_tags = [item.strip() for item in re.split(r"[,\s]+", value) if item.strip()]
    else:
        raw_tags = []

    tags: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        clean_tag = tag[:48]
        key = clean_tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(clean_tag)
        if len(tags) >= 16:
            break
    return tags


def _normalize_category(category: str, name: str, description: str, tags: list[str]) -> str:
    if category in ALLOWED_CATEGORIES:
        return category
    haystack = f"{name} {description} {' '.join(tags)}".lower()
    if "mcp" in haystack:
        return "mcp"
    if re.search(r"ui|ux|frontend|visual|design|界面", haystack):
        return "frontend"
    if re.search(r"memory|dialogue|companion|voice|tts|asr|陪伴|语音|记忆", haystack):
        return "companion"
    if re.search(r"doc|pdf|sheet|ppt|document|文档|表格", haystack):
        return "document"
    if re.search(r"test|debug|review|code|ci|repo|测试|代码", haystack):
        return "development"
    if re.search(r"image|media|audio|video|图像|媒体", haystack):
        return "media"
    if re.search(r"research|search|docs|调研|搜索", haystack):
        return "research"
    if re.search(r"plan|quality|cleanup|治理", haystack):
        return "governance"
    if re.search(r"skill|author|prompt|编写", haystack):
        return "authoring"
    if re.search(r"task|file|automation|自动化|任务|文件", haystack):
        return "automation"
    return "general"


def _normalize_skill_payload(payload: Any, fallback_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    name = (
        _string_field(payload.get("name"), max_length=120)
        or _string_field(payload.get("title"), max_length=120)
        or _string_field(payload.get("id"), max_length=120)
        or fallback_id
    )
    description = (
        _string_field(payload.get("description"), max_length=1200)
        or _string_field(payload.get("desc"), max_length=1200)
        or _string_field(payload.get("summary"), max_length=1200)
        or "导入的本地 Skill"
    )
    tags = _normalize_tags(payload.get("tags"))
    category = _normalize_category(
        _string_field(payload.get("category"), max_length=64),
        name,
        description,
        tags,
    )
    fit = _string_field(payload.get("fit"), max_length=16)
    if fit not in ALLOWED_FITS:
        fit = "medium"

    return {
        "id": _normalize_skill_id(_string_field(payload.get("id"), max_length=160) or name or fallback_id),
        "name": name,
        "description": description,
        "category": category,
        "source": "imported",
        "status": "built-in",
        "fit": fit,
        "installed": True,
        "enabled_codex": True,
        "directory": _string_field(payload.get("directory"), max_length=500) or None,
        "repo": _string_field(payload.get("repo"), max_length=300) or None,
        "url": _string_field(payload.get("url"), max_length=500) or None,
        "tags": tags,
    }


def _skill_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    for item in items:
        category = str(item.get("category") or "general")
        categories[category] = categories.get(category, 0) + 1
    return {
        "total": len(items),
        "built_in": len(items),
        "ready": len(items),
        "planned": 0,
        "high_fit": sum(1 for item in items if item.get("fit") == "high"),
        "medium_fit": sum(1 for item in items if item.get("fit") == "medium"),
        "recommended": len(items),
        "categories": categories,
    }


class SkillCatalogStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "imported_skills.json"
        self.items: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        try:
            if not self.path.exists():
                self.items = {}
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            raw_items = data.get("items") if isinstance(data, dict) else data
            if not isinstance(raw_items, list):
                self.items = {}
                return
            normalized = [
                item
                for index, payload in enumerate(raw_items)
                if (item := _normalize_skill_payload(payload, f"stored-{index + 1}")) is not None
            ]
            self.items = {item["id"]: item for item in normalized}
        except Exception as exc:
            logger.warning("Failed to load imported skills: %s", exc)
            self.items = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"items": self.list_items()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_items(self) -> list[dict[str, Any]]:
        return sorted((dict(item) for item in self.items.values()), key=lambda item: str(item.get("name") or "").lower())

    def snapshot(self) -> dict[str, Any]:
        items = self.list_items()
        return {
            "items": items,
            "summary": _skill_summary(items),
        }

    def replace(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [
            item
            for index, payload in enumerate(items)
            if (item := _normalize_skill_payload(payload, f"skill-{index + 1}")) is not None
        ]
        self.items = {item["id"]: item for item in normalized}
        self.save()
        return self.snapshot()

    def remove_many(self, skill_ids: list[str]) -> dict[str, Any]:
        remove_ids = {str(skill_id).strip() for skill_id in skill_ids if str(skill_id).strip()}
        before = len(self.items)
        for skill_id in remove_ids:
            self.items.pop(skill_id, None)
        removed = before - len(self.items)
        self.save()
        snapshot = self.snapshot()
        snapshot.update({"ok": True, "removed": removed})
        return snapshot
