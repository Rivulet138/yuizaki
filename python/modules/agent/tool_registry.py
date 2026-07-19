from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Awaitable, Callable

from .tool_result import RiskLevel, ToolSource, ToolResultEnvelope


ToolHandler = Callable[[dict[str, Any]], ToolResultEnvelope | Awaitable[ToolResultEnvelope]]

_QUERY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "浏览器": ("browser", "web", "open"),
    "网页": ("browser", "web", "page"),
    "网址": ("url", "browser", "open"),
    "链接": ("url", "link", "open"),
    "文件": ("file", "read", "write"),
    "搜索": ("search", "web", "find"),
    "查找": ("search", "find"),
    "音乐": ("music", "audio", "play"),
    "播放": ("play", "media"),
    "日程": ("calendar", "schedule"),
    "提醒": ("reminder", "schedule"),
    "屏幕": ("screen", "screenshot", "display"),
    "窗口": ("window", "screen"),
}


def _query_terms(query: str) -> set[str]:
    normalized = " ".join((query or "").lower().split())
    terms = set(re.findall(r"[a-z0-9_./:-]{2,}", normalized))
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(run) <= 4:
            terms.add(run)
        terms.update(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    for marker, synonyms in _QUERY_SYNONYMS.items():
        if marker in normalized:
            terms.update(synonyms)
    return terms


@dataclass
class ToolDefinition:
    name: str
    description: str
    source: ToolSource
    parameters: dict[str, Any]
    handler: ToolHandler
    require_confirm: bool = False
    risk_level: RiskLevel = "safe"
    tags: list[str] | None = None
    scopes: list[str] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def rank_candidates(self, query: str, *, limit: int = 8) -> list[ToolDefinition]:
        """Rank tool metadata locally without invoking handlers or remote services."""
        clean_query = " ".join((query or "").lower().split())
        if not clean_query or limit <= 0:
            return []
        terms = _query_terms(clean_query)
        ranked: list[tuple[int, int, ToolDefinition]] = []
        for index, tool in enumerate(self._tools.values()):
            name = tool.name.lower()
            description = tool.description.lower()
            tags = " ".join(tool.tags or []).lower()
            scopes = " ".join(tool.scopes or []).lower()
            score = 0
            if name in clean_query or clean_query in name:
                score += 20
            for term in terms:
                if term in name:
                    score += 6
                if term in tags:
                    score += 4
                if term in description:
                    score += 2
                if term in scopes:
                    score += 1
            if score > 0:
                ranked.append((score, index, tool))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in ranked[:limit]]

    def list_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def list_capabilities(self) -> list[dict[str, Any]]:
        kind_map = {
            "builtin": "builtin-tool",
            "plugin": "plugin-tool",
            "mcp": "mcp-tool",
        }
        return [
            {
                "id": tool.name,
                "name": tool.name,
                "description": tool.description,
                "kind": kind_map.get(tool.source, "builtin-tool"),
                "source": tool.source,
                "riskLevel": tool.risk_level,
                "requiresApproval": bool(tool.require_confirm),
                "tags": list(tool.tags or []),
                "scopes": list(tool.scopes or []),
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]
