from __future__ import annotations

import hashlib

from ..tools.local_tools import dispatch_tool, read_file, web_search
from .tool_registry import ToolDefinition, ToolRegistry
from .tool_result import ToolResultEnvelope


def _web_search_envelope(args: dict) -> ToolResultEnvelope:
    try:
        return ToolResultEnvelope(
            success=True,
            content=web_search(str(args.get("query", "")), int(args.get("limit", 5) or 5)),
            source="builtin",
            tool_name="web_search",
        )
    except Exception as exc:
        return ToolResultEnvelope(
            success=False,
            content="",
            source="builtin",
            tool_name="web_search",
            error=str(exc),
        )


def _verify_written_file(args: dict, *_context: object) -> dict[str, object]:
    expected = str(args.get("content", ""))
    actual = read_file(str(args.get("path", "")))
    matches = actual == expected
    digest = hashlib.sha256(actual.encode("utf-8")).hexdigest()[:12]
    return {
        "status": "verified" if matches else "unverified",
        "evidence": [f"file content {'matches' if matches else 'differs'} (sha256 {digest})"],
    }
def register_default_tools(registry: ToolRegistry) -> None:
    registry.register(ToolDefinition(
        name="open_app",
        description="按名称打开本机桌面应用。",
        source="builtin",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content=dispatch_tool("open_app", args),
            source="builtin",
            tool_name="open_app",
        ),
        effect_kind="write",
        risk_level="low",
        tags=["desktop", "launch"],
        scopes=["desktop:open_app"],
    ))

    registry.register(ToolDefinition(
        name="open_url",
        description="在默认浏览器中打开链接。",
        source="builtin",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content=dispatch_tool("open_url", args),
            source="builtin",
            tool_name="open_url",
        ),
        effect_kind="write",
        risk_level="low",
        tags=["browser", "external"],
        scopes=["browser:open_url"],
    ))

    registry.register(ToolDefinition(
        name="read_file",
        description="读取本地文本文件内容。",
        source="builtin",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content=dispatch_tool("read_file", args),
            source="builtin",
            tool_name="read_file",
        ),
        effect_kind="read",
        risk_level="low",
        tags=["filesystem", "read"],
        scopes=["fs:read"],
    ))

    registry.register(ToolDefinition(
        name="write_file",
        description="把文本内容写入本地文件。",
        source="builtin",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=lambda args: ToolResultEnvelope(
            success=True,
            content=dispatch_tool("write_file", args),
            source="builtin",
            tool_name="write_file",
        ),
        effect_kind="write",
        risk_level="high",
        require_confirm=True,
        tags=["filesystem", "write"],
        scopes=["fs:write"],
        postcondition_verifier=_verify_written_file,
        recheck_handler=lambda args, _ctx: _verify_written_file(args),
    ))

    registry.register(ToolDefinition(
        name="web_search",
        description="联网搜索公开信息，并返回简要结果和链接。",
        source="builtin",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query"],
        },
        handler=_web_search_envelope,
        effect_kind="read",
        risk_level="low",
        tags=["web", "search", "current"],
        scopes=["web:search"],
    ))
