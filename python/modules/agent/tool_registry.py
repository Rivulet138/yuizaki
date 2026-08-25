from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .permission_receipt import PermissionReceipt
from .planner import canonical_json_bytes
from .tool_result import RiskLevel, ToolResultEnvelope, ToolSource

ToolHandler = Callable[[dict[str, Any]], ToolResultEnvelope | Awaitable[ToolResultEnvelope]]
ContextToolHandler = Callable[
    [dict[str, Any], Any, PermissionReceipt | None, Any],
    ToolResultEnvelope | Awaitable[ToolResultEnvelope],
]
ExecutionPermitClaims = Callable[[dict[str, Any], Any], str]
_EXECUTION_PERMIT_KEY = secrets.token_bytes(32)


@dataclass(frozen=True)
class _ToolExecutionPermit:
    payload: str
    seal: str
    nonce: str


def _canonical_parameters(parameters: dict[str, Any]) -> str:
    return canonical_json_bytes(parameters, path="tool parameters").decode("utf-8")


def _mint_execution_permit(  # pyright: ignore[reportUnusedFunction]
    *,
    tool_name: str,
    parameters: dict[str, Any],
    ctx: Any,
    receipt: PermissionReceipt,
    claims: str,
) -> _ToolExecutionPermit:
    if (
        receipt.decision != "allowed"
        or receipt.reason_code != "user_allowed"
        or receipt.decided_at is None
        or receipt.capability_id != tool_name
    ):
        raise RuntimeError("execution permit requires a fresh matching user decision")
    nonce = secrets.token_urlsafe(18)
    payload = _canonical_parameters({
        "tool_name": tool_name,
        "parameters_sha256": hashlib.sha256(_canonical_parameters(parameters).encode("utf-8")).hexdigest(),
        "context_id": id(ctx),
        "capability_call_id": receipt.capability_call_id,
        "claims": claims,
        "nonce": nonce,
    })
    seal = hmac.new(_EXECUTION_PERMIT_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return _ToolExecutionPermit(payload=payload, seal=seal, nonce=nonce)


def _verify_execution_permit(  # pyright: ignore[reportUnusedFunction]
    permit: object,
    *,
    tool_name: str,
    parameters: dict[str, Any],
    ctx: Any,
    receipt: PermissionReceipt | None,
    claims: str,
) -> str | None:
    if not isinstance(permit, _ToolExecutionPermit) or receipt is None:
        return None
    expected_seal = hmac.new(_EXECUTION_PERMIT_KEY, permit.payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_seal, permit.seal):
        return None
    expected_payload = _canonical_parameters({
        "tool_name": tool_name,
        "parameters_sha256": hashlib.sha256(_canonical_parameters(parameters).encode("utf-8")).hexdigest(),
        "context_id": id(ctx),
        "capability_call_id": receipt.capability_call_id,
        "claims": claims,
        "nonce": permit.nonce,
    })
    return permit.nonce if hmac.compare_digest(expected_payload, permit.payload) else None

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
    # High-consequence tools may require a fresh interactive decision for
    # every call instead of accepting a persisted tool/scope grant.
    allow_remembered_decision: bool = True
    context_handler: ContextToolHandler | None = None
    execution_permit_claims: ExecutionPermitClaims | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._revision = 0

    @property
    def revision(self) -> int:
        return self._revision

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.name] = definition
        self._revision += 1

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> None:
        if self._tools.pop(name, None) is not None:
            self._revision += 1

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
                "allowRememberedDecision": bool(tool.allow_remembered_decision),
                "tags": list(tool.tags or []),
                "scopes": list(tool.scopes or []),
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]
