from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from threading import RLock
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
SKILL_CATALOG_SCHEMA_VERSION = "yuizaki.skill-catalog.v1"


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
        # Imported entries are a catalog projection until a trusted runtime
        # binding exists; they must not be presented as executable tools.
        "executionReady": False,
        "runtimeBinding": "catalog_only",
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
        "execution_ready": sum(1 for item in items if item.get("executionReady") is True),
        "catalog_only": sum(1 for item in items if item.get("runtimeBinding") == "catalog_only"),
        "planned": 0,
        "high_fit": sum(1 for item in items if item.get("fit") == "high"),
        "medium_fit": sum(1 for item in items if item.get("fit") == "medium"),
        "recommended": len(items),
        "categories": categories,
    }


class SkillCatalogStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_dir_from_env() / "imported_skills.json"
        self._lock = RLock()
        self.items: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
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
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("Failed to load imported skills: %s", exc)
                self.items = {}

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schemaVersion": SKILL_CATALOG_SCHEMA_VERSION,
                "items": self.list_items(),
            }
            temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)

    def list_items(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted((dict(item) for item in self.items.values()), key=lambda item: str(item.get("name") or "").lower())

    def get(self, skill_id: str) -> dict[str, Any] | None:
        """Return a defensive copy of one catalog item."""
        with self._lock:
            item = self.items.get(str(skill_id).strip())
            return dict(item) if item is not None else None

    def set_runtime_binding(
        self,
        skill_id: str,
        *,
        tool_name: str,
        scopes: list[str] | tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Attach an in-process binding after the runtime verified its target.

        Bindings are intentionally ephemeral: the catalog file remains an
        untrusted metadata source and is normalized back to ``catalog_only``
        on restart until a live runtime registers the tool again.
        """
        with self._lock:
            item = self.items.get(str(skill_id).strip())
            if item is None:
                raise KeyError(f"unknown skill: {skill_id}")
            item["executionReady"] = True
            item["runtimeBinding"] = "tool"
            item["runtimeTarget"] = str(tool_name).strip()[:160]
            item["runtimeScopes"] = [str(scope).strip()[:160] for scope in scopes if str(scope).strip()][:32]
            return dict(item)

    def clear_runtime_binding(self, skill_id: str) -> dict[str, Any] | None:
        """Remove an ephemeral runtime binding and return the catalog item."""
        with self._lock:
            item = self.items.get(str(skill_id).strip())
            if item is None:
                return None
            item["executionReady"] = False
            item["runtimeBinding"] = "catalog_only"
            item.pop("runtimeTarget", None)
            item.pop("runtimeScopes", None)
            return dict(item)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = self.list_items()
            return {
                "schemaVersion": SKILL_CATALOG_SCHEMA_VERSION,
                "items": items,
                "summary": _skill_summary(items),
            }

    def replace(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            normalized = [
                item
                for index, payload in enumerate(items)
                if (item := _normalize_skill_payload(payload, f"skill-{index + 1}")) is not None
            ]
            self.items = {item["id"]: item for item in normalized}
            self.save()
            return self.snapshot()

    def remove_many(self, skill_ids: list[str]) -> dict[str, Any]:
        with self._lock:
            remove_ids = {str(skill_id).strip() for skill_id in skill_ids if str(skill_id).strip()}
            before = len(self.items)
            for skill_id in remove_ids:
                self.items.pop(skill_id, None)
            removed = before - len(self.items)
            self.save()
            snapshot = self.snapshot()
            snapshot.update({"ok": True, "removed": removed})
            return snapshot
