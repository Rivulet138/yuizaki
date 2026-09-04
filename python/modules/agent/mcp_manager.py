from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any
import uuid

import httpx

from ..core.paths import data_dir_from_env
from ..tools.mcp_bridge import MCPToolError, call_http_mcp_tool

from .models import MCPHistoryEntry, MCPInventoryItem, MCPServerConfigSnapshot, MCPServerStatusSnapshot, MCPSnapshot
from .tool_registry import ToolDefinition, ToolRegistry
from .tool_result import ToolResultEnvelope

logger = logging.getLogger(__name__)

SSE_READY_TIMEOUT_SECONDS = 10.0
SSE_TOOL_TIMEOUT_SECONDS = 60.0
MCP_STATUS_REFRESH_TIMEOUT_SECONDS = 3.0
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_BUILTIN_PRESET_STORE_VERSION = 1
LEGACY_BROWSER_MCP_DEFAULT_URLS = {"http://127.0.0.1:7777", "http://localhost:7777"}
MCP_STDIO_INHERITED_ENV_KEYS = frozenset({
    "APPDATA", "COMSPEC", "HOME", "LANG", "LC_ALL", "LOCALAPPDATA",
    "NODE_PATH", "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT",
    "TEMP", "TMP", "USERPROFILE", "WINDIR",
})


def _log_task_exception(task: asyncio.Task[object]) -> None:
    if not task.cancelled() and task.exception():
        logger.warning("Background MCP task %s failed: %s", task.get_name(), task.exception())


@dataclass
class MCPServerConfig:
    name: str
    base_url: str
    transport: str = "http"
    enabled: bool = True
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None


@dataclass
class MCPServerPreset:
    id: str
    name: str
    description: str
    category: str
    transport: str
    base_url: str = ""
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "transport": self.transport,
            "base_url": self.base_url,
            "command": self.command,
            "args": list(self.args or []),
            "env_keys": sorted((self.env or {}).keys()),
            "header_keys": sorted((self.headers or {}).keys()),
            "enabled": self.enabled,
        }

    def to_server_config(self) -> MCPServerConfig:
        return MCPServerConfig(
            name=self.id,
            base_url=self.base_url,
            transport=self.transport,
            enabled=self.enabled,
            command=self.command,
            args=list(self.args or []),
            env=dict(self.env or {}),
            headers=dict(self.headers or {}),
        )


class MCPManager:
    def __init__(self, store_file: str | Path | None = None) -> None:
        self._store_file = Path(store_file) if store_file is not None else data_dir_from_env() / "mcp_servers.json"
        self.servers: dict[str, MCPServerConfig] = {}
        self.status: dict[str, dict[str, Any]] = {}
        self._stdio_sessions: dict[str, dict[str, Any]] = {}
        self._sse_sessions: dict[str, dict[str, Any]] = {}
        self._streamable_http_sessions: dict[str, dict[str, Any]] = {}
        self._telemetry: dict[str, dict[str, Any]] = {}
        self._registry: ToolRegistry | None = None
        self._registered_dynamic_tools_by_server: dict[str, set[str]] = {}
        self._store_metadata: dict[str, Any] = {}
        self._load_store()

    def _python_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _npx_command(self) -> str:
        return "npx.cmd" if os.name == "nt" else "npx"

    def _npm_global_command(self, command_name: str) -> str:
        suffix = ".cmd" if os.name == "nt" else ""
        candidate = Path.home() / "AppData" / "Roaming" / "npm" / f"{command_name}{suffix}"
        if os.name == "nt" and candidate.exists():
            return candidate.as_posix()
        return f"{command_name}{suffix}"

    def _command_from_env(self, env_key: str, default_command: str) -> str:
        return os.getenv(env_key, "").strip() or default_command

    def _url_from_env(self, env_key: str, default_url: str = "") -> str:
        return (os.getenv(env_key, "").strip() or default_url).rstrip("/")

    def _browser_mcp_url_from_env(self) -> str:
        return (
            os.getenv("YUIZAKI_BROWSER_MCP_URL", "").strip()
            or os.getenv("YUIZAKI_MCP_PLAYWRIGHT_URL", "").strip()
        ).rstrip("/")

    def _resolve_template_value(self, value: str) -> tuple[str, list[str]]:
        missing: list[str] = []

        def replace_env(match: re.Match[str]) -> str:
            key = match.group(1)
            fallback = match.group(2) or ""
            env_value = os.getenv(key, "") or fallback
            if not env_value:
                missing.append(key)
            return env_value

        resolved = re.sub(r"\{env:([A-Za-z_][A-Za-z0-9_]*)(?:\|([^}]*))?\}", replace_env, value)
        return resolved, missing

    def _resolved_mapping(self, mapping: dict[str, str] | None) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for raw_key, raw_value in (mapping or {}).items():
            key = str(raw_key).strip()
            value, missing = self._resolve_template_value(str(raw_value))
            if not key or missing or not value.strip():
                continue
            resolved[key] = value
        return resolved

    def _stdio_process_env(self, server: MCPServerConfig) -> dict[str, str]:
        inherited = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in MCP_STDIO_INHERITED_ENV_KEYS
        }
        inherited.update(self._resolved_mapping(server.env))
        return inherited

    def _request_headers(self, server: MCPServerConfig, base_headers: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(base_headers or {})
        headers.update(self._resolved_mapping(server.headers))
        return headers

    def _server_public_payload(self, server: MCPServerConfig) -> dict[str, Any]:
        data = dict(server.__dict__)
        data.pop("env", None)
        data.pop("headers", None)
        data["env_keys"] = sorted((server.env or {}).keys())
        data["header_keys"] = sorted((server.headers or {}).keys())
        return data

    def _custom_stdio_enabled(self) -> bool:
        return os.getenv("YUIZAKI_ALLOW_CUSTOM_MCP_STDIO", "").strip().lower() in {"1", "true", "yes", "on"}

    def _matches_stdio_preset(self, server: MCPServerConfig) -> bool:
        for preset in self._preset_definitions():
            preset_server = preset.to_server_config()
            if (
                preset_server.transport == "stdio"
                and preset_server.name == server.name
                and preset_server.command == server.command
                and list(preset_server.args or []) == list(server.args or [])
                and dict(preset_server.env or {}) == dict(server.env or {})
            ):
                return True
        return False

    def _stdio_launch_allowed(self, server: MCPServerConfig) -> bool:
        return self._custom_stdio_enabled() or self._matches_stdio_preset(server)

    def _preset_definitions(self) -> list[MCPServerPreset]:
        data_dir = self._python_root() / "data"
        chat_db = data_dir / "chat.db"
        return [
            MCPServerPreset(
                id="memory_graph",
                name="长期桌宠记忆",
                description="官方知识图谱记忆 MCP，适合记录用户偏好、桌宠关系、长期目标与桌宠设定。",
                category="companion",
                transport="stdio",
                command=self._npx_command(),
                args=["-y", "@modelcontextprotocol/server-memory"],
                env={"MEMORY_FILE_PATH": str(data_dir / "mcp_memory_graph.jsonl")},
                enabled=False,
            ),
            MCPServerPreset(
                id="simple_memory",
                name="日常任务记忆",
                description="SQLite 轻量记忆 MCP，适合保存日程片段、会话摘要、待办与项目决策。",
                category="daily",
                transport="stdio",
                command=self._npx_command(),
                args=["-y", "mcp-simple-memory", "serve"],
                env={"MCP_MEMORY_DIR": str(data_dir / "mcp_simple_memory")},
                enabled=False,
            ),
            MCPServerPreset(
                id="notion_remote",
                name="Notion 知识库",
                description="远程 Streamable HTTP MCP，用于读写 Notion 页面、资料库与桌宠日志；需要后续完成账户授权。",
                category="daily",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_NOTION_URL", "https://mcp.notion.com/mcp"),
                enabled=False,
            ),
            MCPServerPreset(
                id="todoist_remote",
                name="Todoist 日常任务",
                description="远程 Streamable HTTP MCP，用于创建、整理和回顾小型日常任务；需要后续完成账户授权。",
                category="daily",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_TODOIST_URL", "https://ai.todoist.net/mcp"),
                enabled=False,
            ),
            MCPServerPreset(
                id="yuizaki_sqlite_ro",
                name="Yuizaki 数据库只读检查",
                description="只读连接本项目 chat.db，用于排查会话、工作区和桌宠记忆数据，不允许写入。",
                category="diagnostics",
                transport="stdio",
                command=self._npx_command(),
                args=["-y", "@berthojoris/mcp-sqlite-server", f"sqlite:///{chat_db.as_posix()}", "list,read"],
                enabled=False,
            ),
            MCPServerPreset(
                id="chrome_devtools",
                name="Chrome DevTools",
                description="连接 Chrome DevTools，用于检查本地页面、控制台日志、网络请求和交互状态。",
                category="browser",
                transport="stdio",
                command=self._command_from_env("YUIZAKI_MCP_CHROME_DEVTOOLS_COMMAND", self._npm_global_command("chrome-devtools-mcp")),
                args=["--headless"],
                enabled=False,
            ),
            MCPServerPreset(
                id="edge_devtools",
                name="Edge DevTools",
                description="连接本机 Edge 调试端口，用于浏览器页面调试和前端问题定位。",
                category="browser",
                transport="stdio",
                command=self._command_from_env("YUIZAKI_MCP_EDGE_DEVTOOLS_COMMAND", self._npm_global_command("edge-devtools-mcp")),
                env={"EDGE_DEBUG_PORT": "{env:EDGE_DEBUG_PORT|9222}", "EDGE_DEBUG_HOST": "{env:EDGE_DEBUG_HOST|localhost}", "EDGE_HEADLESS": "{env:EDGE_HEADLESS|false}"},
                enabled=False,
            ),
            MCPServerPreset(
                id="playwright_mcp",
                name="Playwright MCP",
                description="提供 Playwright 浏览器自动化能力，可作为 Yuizaki 内置浏览器桥的备用入口。",
                category="browser",
                transport="stdio",
                command=self._command_from_env("YUIZAKI_MCP_PLAYWRIGHT_COMMAND", self._npm_global_command("playwright-mcp")),
                args=["--headless"],
                enabled=False,
            ),
            MCPServerPreset(
                id="deepwiki",
                name="DeepWiki",
                description="面向代码库和文档的问答检索入口，适合分析依赖、模块关系和实现背景。",
                category="research",
                transport="stdio",
                command=self._command_from_env("YUIZAKI_MCP_DEEPWIKI_COMMAND", self._npm_global_command("mcp-instruct")),
                enabled=False,
            ),
            MCPServerPreset(
                id="firecrawl",
                name="Firecrawl",
                description="抓取网页正文与结构化页面内容，适合资料整理和长网页提取；需要 FIRECRAWL_API_KEY。",
                category="web",
                transport="stdio",
                command=self._command_from_env("YUIZAKI_MCP_FIRECRAWL_COMMAND", self._npm_global_command("firecrawl-mcp")),
                env={"FIRECRAWL_API_KEY": "{env:FIRECRAWL_API_KEY}"},
                enabled=False,
            ),
            MCPServerPreset(
                id="context7",
                name="Context7",
                description="查询当前版本的库、框架和 SDK 文档，适合实现前确认 API 用法；需要授权时填写 CONTEXT7_API_KEY。",
                category="docs",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_CONTEXT7_URL", "https://mcp.context7.com/mcp"),
                headers={"Authorization": "Bearer {env:CONTEXT7_API_KEY}"},
                enabled=False,
            ),
            MCPServerPreset(
                id="github",
                name="GitHub Copilot MCP",
                description="连接 GitHub 相关仓库、Issue 和代码上下文；启用前需要配置 GITHUB_PERSONAL_ACCESS_TOKEN。",
                category="code",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_GITHUB_URL", "https://api.githubcopilot.com/mcp/"),
                headers={"Authorization": "Bearer {env:GITHUB_PERSONAL_ACCESS_TOKEN}"},
                enabled=False,
            ),
            MCPServerPreset(
                id="grep_app",
                name="grep.app",
                description="搜索公开代码片段和仓库实现，适合查找相似用法、错误模式和开源参考。",
                category="code",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_GREP_APP_URL", "https://mcp.grep.app"),
                enabled=False,
            ),
            MCPServerPreset(
                id="websearch",
                name="Exa Web Search",
                description="提供网页搜索能力，适合查找近期资料、工具说明和公开信息来源。",
                category="web",
                transport="streamable_http",
                base_url=self._url_from_env("YUIZAKI_MCP_WEBSEARCH_URL", "https://mcp.exa.ai/mcp?tools=web_search_exa"),
                enabled=False,
            ),
        ]

    def presets_snapshot(self) -> list[dict[str, Any]]:
        installed = set(self.servers.keys())
        payload: list[dict[str, Any]] = []
        for preset in self._preset_definitions():
            item = preset.to_dict()
            item["installed"] = preset.id in installed
            payload.append(item)
        return payload

    def _ensure_telemetry(self, name: str) -> dict[str, Any]:
        if name not in self._telemetry:
            self._telemetry[name] = {
                "total_calls": 0,
                "total_failures": 0,
                "reconnect_count": 0,
                "last_error": None,
                "session_id": None,
                "history": [],
            }
        return self._telemetry[name]

    def _pending_request_count(self, name: str) -> int | None:
        session = self._sse_sessions.get(name)
        pending = session.get("pending") if session else None
        if isinstance(pending, dict):
            return len(pending)
        return None

    def _coerce_optional_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    def _empty_inventory(self, inventory_error: str | None = None) -> dict[str, Any]:
        return {
            "tools_count": 0,
            "resources_count": 0,
            "prompts_count": 0,
            "tools": [],
            "resources": [],
            "prompts": [],
            "inventory_error": inventory_error,
        }

    def _coerce_inventory_items(self, value: Any) -> list[MCPInventoryItem]:
        if not isinstance(value, list):
            return []
        items: list[MCPInventoryItem] = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    items.append(MCPInventoryItem(name=item.strip()))
                continue
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("id")
            if not isinstance(name, str) or not name.strip():
                continue
            description = item.get("description") or item.get("desc") or ""
            raw_schema = item.get("input_schema") or item.get("inputSchema") or item.get("schema")
            items.append(MCPInventoryItem(
                name=name.strip(),
                description=description if isinstance(description, str) else "",
                input_schema=raw_schema if isinstance(raw_schema, dict) else None,
            ))
        return items

    def _inventory_from_manifest(self, payload: Any, inventory_error: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return self._empty_inventory(inventory_error or "manifest payload is not an object")
        tools = self._coerce_inventory_items(payload.get("tools"))
        resources = self._coerce_inventory_items(payload.get("resources"))
        prompts = self._coerce_inventory_items(payload.get("prompts"))
        return {
            "tools_count": len(tools),
            "resources_count": len(resources),
            "prompts_count": len(prompts),
            "tools": [item.to_dict() for item in tools],
            "resources": [item.to_dict() for item in resources],
            "prompts": [item.to_dict() for item in prompts],
            "inventory_error": inventory_error,
        }

    async def _fetch_http_inventory(self, server: MCPServerConfig, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            headers = self._request_headers(server)
            if headers:
                resp = await client.get(f"{server.base_url.rstrip('/')}/manifest", headers=headers)
            else:
                resp = await client.get(f"{server.base_url.rstrip('/')}/manifest")
            resp.raise_for_status()
            return self._inventory_from_manifest(resp.json())
        except Exception as exc:
            return self._empty_inventory(str(exc))

    def _capability_contribution_items(self) -> list[str]:
        items: list[str] = []
        for server_name, status in self.status.items():
            raw_tools = status.get("tools")
            if isinstance(raw_tools, list) and raw_tools:
                for tool in raw_tools:
                    if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                        items.append(f"{server_name}:{tool['name']}")
                continue
            if server_name in self.servers:
                items.append(server_name)
        if items:
            return sorted(set(items))
        return sorted(self.servers.keys())

    def _append_history(
        self,
        name: str,
        event: str,
        detail: str = "",
        *,
        status: str = "info",
        transport: str | None = None,
        tool: str | None = None,
        request_id: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        session_id: str | None = None,
        pending_requests: int | None = None,
        args_keys: list[str] | None = None,
        output_chars: int | None = None,
    ) -> None:
        telemetry = self._ensure_telemetry(name)
        history = telemetry.setdefault("history", [])
        server = self.servers.get(name)
        entry = MCPHistoryEntry(
            timestamp=datetime.now().isoformat(),
            event=event,
            status=status,
            detail=detail,
            transport=transport or (server.transport if server else None),
            tool=tool,
            request_id=request_id,
            duration_ms=duration_ms,
            error=error,
            session_id=session_id or telemetry.get("session_id"),
            pending_requests=pending_requests if pending_requests is not None else self._pending_request_count(name),
            total_calls=int(telemetry.get("total_calls") or 0),
            total_failures=int(telemetry.get("total_failures") or 0),
            args_keys=args_keys,
            output_chars=output_chars,
        )
        history.append(entry.to_dict())
        telemetry["history"] = history[-10:]

    def _history_entries_for_status(self, status: dict[str, Any]) -> list[MCPHistoryEntry]:
        raw_history = status.get("history")
        if not isinstance(raw_history, list):
            return []
        entries: list[MCPHistoryEntry] = []
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            args_keys = item.get("args_keys")
            entries.append(MCPHistoryEntry(
                timestamp=str(item.get("timestamp") or ""),
                event=str(item.get("event") or "unknown"),
                status=str(item.get("status") or "info"),
                detail=str(item.get("detail") or ""),
                transport=item.get("transport") if item.get("transport") is None else str(item.get("transport")),
                tool=item.get("tool") if item.get("tool") is None else str(item.get("tool")),
                request_id=item.get("request_id") if item.get("request_id") is None else str(item.get("request_id")),
                duration_ms=self._coerce_optional_int(item.get("duration_ms")),
                error=item.get("error") if item.get("error") is None else str(item.get("error")),
                session_id=item.get("session_id") if item.get("session_id") is None else str(item.get("session_id")),
                pending_requests=self._coerce_optional_int(item.get("pending_requests")),
                total_calls=self._coerce_optional_int(item.get("total_calls")),
                total_failures=self._coerce_optional_int(item.get("total_failures")),
                args_keys=[str(value) for value in args_keys] if isinstance(args_keys, list) else None,
                output_chars=self._coerce_optional_int(item.get("output_chars")),
            ))
        return entries

    def _default_server_configs(self) -> dict[str, MCPServerConfig]:
        browser_mcp_url = self._browser_mcp_url_from_env()
        return {
            "playwright": MCPServerConfig(
                name="playwright",
                base_url=browser_mcp_url,
                transport="http",
                enabled=bool(browser_mcp_url),
                command="node",
                args=["server.mjs", "--stdio"],
            )
        }

    def _builtin_server_configs(self) -> dict[str, MCPServerConfig]:
        servers = self._default_server_configs()
        for preset in self._preset_definitions():
            servers.setdefault(preset.id, preset.to_server_config())
        return servers

    def _coerce_server_config(self, name: str, payload: Any) -> MCPServerConfig | None:
        if not isinstance(payload, dict):
            return None
        allowed_fields = MCPServerConfig.__dataclass_fields__.keys()
        cleaned = {field: payload[field] for field in allowed_fields if field in payload}
        cleaned["name"] = str(cleaned.get("name") or name)
        try:
            return MCPServerConfig(**cleaned)
        except TypeError:
            return None

    def _merge_builtin_server_configs(self) -> bool:
        changed = False
        for name, server in self._builtin_server_configs().items():
            if name not in self.servers:
                self.servers[name] = server
                changed = True
        return changed

    def _migrate_legacy_browser_mcp_default(self) -> bool:
        server = self.servers.get("playwright")
        if server is None:
            return False
        if server.base_url.rstrip("/") not in LEGACY_BROWSER_MCP_DEFAULT_URLS:
            return False
        if server.transport != "http" or server.command != "node" or (server.args or []) != ["server.mjs", "--stdio"]:
            return False
        browser_mcp_url = self._browser_mcp_url_from_env()
        server.base_url = browser_mcp_url
        server.enabled = bool(browser_mcp_url)
        return True

    def _load_store(self) -> None:
        default_servers = self._builtin_server_configs()
        try:
            if not self._store_file.exists():
                self.servers = default_servers
                self._store_metadata["builtin_preset_version"] = MCP_BUILTIN_PRESET_STORE_VERSION
                self._save_store()
                return
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._store_metadata = {key: value for key, value in data.items() if key != "servers"}
            servers = data.get("servers") or {}
            if isinstance(servers, dict):
                self.servers = {
                    name: server
                    for name, payload in servers.items()
                    if (server := self._coerce_server_config(name, payload)) is not None
                }
            else:
                self.servers = default_servers
            store_changed = self._migrate_legacy_browser_mcp_default()
            try:
                stored_builtin_version = int(self._store_metadata.get("builtin_preset_version") or 0)
            except (TypeError, ValueError):
                stored_builtin_version = 0
            if stored_builtin_version < MCP_BUILTIN_PRESET_STORE_VERSION:
                changed = self._merge_builtin_server_configs()
                self._store_metadata["builtin_preset_version"] = MCP_BUILTIN_PRESET_STORE_VERSION
                store_changed = store_changed or changed or stored_builtin_version != MCP_BUILTIN_PRESET_STORE_VERSION
            if store_changed:
                self._save_store()
        except Exception:
            self.servers = default_servers
            self._store_metadata["builtin_preset_version"] = MCP_BUILTIN_PRESET_STORE_VERSION

    def _save_store(self) -> None:
        self._store_file.parent.mkdir(parents=True, exist_ok=True)
        self._store_file.write_text(
            json.dumps(
                {
                    **self._store_metadata,
                    "servers": {name: server.__dict__ for name, server in self.servers.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _disabled_status(self, server: MCPServerConfig) -> dict[str, Any]:
        telemetry = self._ensure_telemetry(server.name)
        return {"enabled": False, "ok": False, "message": "disabled", "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}

    def _unsupported_status(self, server: MCPServerConfig) -> dict[str, Any]:
        telemetry = self._ensure_telemetry(server.name)
        return {"enabled": True, "ok": False, "message": f"unsupported transport: {server.transport}", "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}

    def _timeout_status(self, server: MCPServerConfig, timeout_seconds: float) -> dict[str, Any]:
        telemetry = self._ensure_telemetry(server.name)
        message = f"status refresh timed out after {timeout_seconds:.1f}s"
        telemetry["last_error"] = message
        return {"enabled": True, "ok": False, "message": message, "transport": server.transport, "connected": False, **self._empty_inventory(message), **telemetry}

    async def _refresh_server_status(self, name: str, server: MCPServerConfig, timeout_seconds: float | None = None) -> tuple[str, dict[str, Any]]:
        if not server.enabled:
            return name, self._disabled_status(server)
        if server.transport not in {"http", "stdio", "sse", "streamable_http"}:
            return name, self._unsupported_status(server)
        try:
            if timeout_seconds is None:
                return name, await self._check_server_status(server)
            return name, await asyncio.wait_for(self._check_server_status(server), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return name, self._timeout_status(server, timeout_seconds or MCP_STATUS_REFRESH_TIMEOUT_SECONDS)

    async def refresh_status(self, timeout_seconds: float | None = None) -> None:
        results = await asyncio.gather(*[
            self._refresh_server_status(name, server, timeout_seconds)
            for name, server in self.servers.items()
        ])
        for name, status in results:
            self.status[name] = status
            self._sync_server_tools(name)

    def snapshot(self) -> dict[str, Any]:
        capability_items = self._capability_contribution_items()
        contribution_summary = [
            {
                "category": "ui",
                "count": 0,
                "items": [],
            },
            {
                "category": "capability",
                "count": len(capability_items),
                "items": capability_items,
            },
            {
                "category": "event",
                "count": sum(len((self._telemetry.get(name, {}) or {}).get("history", [])) for name in self.servers.keys()),
                "items": [f"history:{name}" for name in self.servers.keys()],
            },
            {
                "category": "policy",
                "count": sum(1 for server in self.servers.values() if server.enabled),
                "items": [server.name for server in self.servers.values() if server.enabled],
            },
        ]
        snapshot = MCPSnapshot(
            servers={
                name: MCPServerConfigSnapshot(
                    name=server.name,
                    base_url=server.base_url,
                    transport=server.transport,
                    enabled=server.enabled,
                    command=server.command,
                    args=list(server.args or []),
                    env_keys=sorted((server.env or {}).keys()),
                    header_keys=sorted((server.headers or {}).keys()),
                )
                for name, server in self.servers.items()
            },
            status={
                name: MCPServerStatusSnapshot(
                    enabled=bool(status.get("enabled", False)),
                    ok=bool(status.get("ok", False)),
                    status_code=status.get("status_code"),
                    message=status.get("message"),
                    transport=status.get("transport"),
                    connected=status.get("connected"),
                    pending_requests=status.get("pending_requests"),
                    total_calls=status.get("total_calls"),
                    total_failures=status.get("total_failures"),
                    reconnect_count=status.get("reconnect_count"),
                    last_error=status.get("last_error"),
                    session_id=status.get("session_id"),
                    history=self._history_entries_for_status(status),
                    tools_count=self._coerce_optional_int(status.get("tools_count")),
                    resources_count=self._coerce_optional_int(status.get("resources_count")),
                    prompts_count=self._coerce_optional_int(status.get("prompts_count")),
                    tools=self._coerce_inventory_items(status.get("tools")),
                    resources=self._coerce_inventory_items(status.get("resources")),
                    prompts=self._coerce_inventory_items(status.get("prompts")),
                    inventory_error=status.get("inventory_error") if status.get("inventory_error") is None else str(status.get("inventory_error")),
                )
                for name, status in self.status.items()
            },
        )
        payload = snapshot.to_dict()
        payload["contributionSummary"] = contribution_summary
        payload["presets"] = self.presets_snapshot()
        return payload

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        server = self.servers.get(name)
        if server is None:
            return None
        server.enabled = enabled
        if not enabled:
            self._unregister_dynamic_tools(name)
            session = self._stdio_sessions.pop(name, None)
            if session is not None:
                asyncio.create_task(self._close_stdio_session(session), name=f"mcp-stdio-close-{name}").add_done_callback(_log_task_exception)
            sse_session = self._sse_sessions.pop(name, None)
            if sse_session is not None:
                asyncio.create_task(self._close_sse_session(sse_session), name=f"mcp-sse-close-{name}").add_done_callback(_log_task_exception)
            self._streamable_http_sessions.pop(name, None)
            telemetry = self._ensure_telemetry(name)
            telemetry["session_id"] = None
            self._append_history(name, "disabled", "server disabled", status="disabled")
        else:
            self._append_history(name, "enabled", "server enabled", status="enabled")
        self._save_store()
        return self._server_public_payload(server)

    def add_server(
        self,
        name: str,
        base_url: str,
        transport: str = "http",
        enabled: bool = True,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        server = MCPServerConfig(name=name, base_url=base_url, transport=transport, enabled=enabled, command=command, args=args, env=env, headers=headers)
        if server.transport == "stdio" and not self._stdio_launch_allowed(server):
            raise MCPToolError("Custom stdio MCP registration is disabled; install a preset or set YUIZAKI_ALLOW_CUSTOM_MCP_STDIO=true")
        self.servers[name] = server
        self._append_history(name, "added", "server registered", status="ok", transport=transport)
        self._save_store()
        return self._server_public_payload(server)

    def install_preset(self, preset_id: str) -> dict[str, Any] | None:
        preset = next((item for item in self._preset_definitions() if item.id == preset_id), None)
        if preset is None:
            return None
        server = preset.to_server_config()
        self.servers[server.name] = server
        self._append_history(server.name, "preset_installed", preset.name, status="ok", transport=server.transport)
        self._save_store()
        return self._server_public_payload(server)

    def remove_server(self, name: str) -> bool:
        if name not in self.servers:
            return False
        session = self._stdio_sessions.pop(name, None)
        if session is not None:
            asyncio.create_task(self._close_stdio_session(session), name=f"mcp-stdio-remove-{name}").add_done_callback(_log_task_exception)
        sse_session = self._sse_sessions.pop(name, None)
        if sse_session is not None:
            asyncio.create_task(self._close_sse_session(sse_session), name=f"mcp-sse-remove-{name}").add_done_callback(_log_task_exception)
        self._append_history(name, "removed", "server removed", status="removed")
        self._unregister_dynamic_tools(name)
        self.servers.pop(name, None)
        self.status.pop(name, None)
        self._save_store()
        return True

    async def shutdown(self) -> None:
        sessions = list(self._stdio_sessions.values())
        self._stdio_sessions.clear()
        for session in sessions:
            await self._close_stdio_session(session)
        sse_sessions = list(self._sse_sessions.values())
        self._sse_sessions.clear()
        for session in sse_sessions:
            await self._close_sse_session(session)
        self._streamable_http_sessions.clear()

    async def refresh_one(self, name: str, timeout_seconds: float | None = None) -> dict[str, Any] | None:
        server = self.servers.get(name)
        if server is None:
            return None
        _, status = await self._refresh_server_status(name, server, timeout_seconds)
        self.status[name] = status
        self._sync_server_tools(name)
        return self.status[name]

    async def call_tool(self, server_name: str, tool_name: str, args: dict[str, Any]) -> str:
        server = self.servers.get(server_name)
        if server is None:
            raise MCPToolError(f"Unknown MCP server: {server_name}")
        if not server.enabled:
            raise MCPToolError(f"MCP server '{server_name}' is disabled")
        telemetry = self._ensure_telemetry(server_name)
        telemetry["total_calls"] += 1
        request_id = f"mcp_call_{uuid.uuid4().hex[:10]}"
        started_at = perf_counter()
        args_keys = sorted(str(key) for key in args.keys())
        self._append_history(
            server_name,
            "tool_call_started",
            f"{tool_name} via {server.transport}",
            status="started",
            tool=tool_name,
            request_id=request_id,
            args_keys=args_keys,
        )
        if server.transport == "http":
            try:
                headers = self._request_headers(server)
                if headers:
                    output = await call_http_mcp_tool(server.base_url, tool_name, args, headers=headers)
                else:
                    output = await call_http_mcp_tool(server.base_url, tool_name, args)
                self._append_history(
                    server_name,
                    "tool_call_succeeded",
                    f"{tool_name} completed",
                    status="ok",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    args_keys=args_keys,
                    output_chars=len(output),
                )
                return output
            except Exception as exc:
                telemetry["total_failures"] += 1
                telemetry["last_error"] = str(exc)
                self._append_history(
                    server_name,
                    "tool_call_failed",
                    f"{tool_name} failed",
                    status="error",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    error=str(exc),
                    args_keys=args_keys,
                )
                raise
        if server.transport == "stdio":
            try:
                output = await self._call_stdio_tool(server, tool_name, args)
                self._append_history(
                    server_name,
                    "tool_call_succeeded",
                    f"{tool_name} completed",
                    status="ok",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    args_keys=args_keys,
                    output_chars=len(output),
                )
                return output
            except Exception as exc:
                telemetry["total_failures"] += 1
                telemetry["last_error"] = str(exc)
                self._append_history(
                    server_name,
                    "tool_call_failed",
                    f"{tool_name} failed",
                    status="error",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    error=str(exc),
                    args_keys=args_keys,
                )
                raise
        if server.transport == "sse":
            try:
                output = await self._call_sse_tool(server, tool_name, args, request_id, args_keys)
                self._append_history(
                    server_name,
                    "tool_call_succeeded",
                    f"{tool_name} completed",
                    status="ok",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    args_keys=args_keys,
                    output_chars=len(output),
                )
                return output
            except Exception as exc:
                telemetry["total_failures"] += 1
                telemetry["last_error"] = str(exc)
                self._append_history(
                    server_name,
                    "tool_call_failed",
                    f"{tool_name} failed",
                    status="error",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    error=str(exc),
                    args_keys=args_keys,
                )
                raise
        if server.transport == "streamable_http":
            try:
                result = await self._streamable_http_request(server, "tools/call", {"name": tool_name, "arguments": args}, timeout=SSE_TOOL_TIMEOUT_SECONDS)
                output = self._format_stdio_tool_result(result)
                self._append_history(
                    server_name,
                    "tool_call_succeeded",
                    f"{tool_name} completed",
                    status="ok",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    args_keys=args_keys,
                    output_chars=len(output),
                )
                return output
            except Exception as exc:
                telemetry["total_failures"] += 1
                telemetry["last_error"] = str(exc)
                self._append_history(
                    server_name,
                    "tool_call_failed",
                    f"{tool_name} failed",
                    status="error",
                    tool=tool_name,
                    request_id=request_id,
                    duration_ms=int((perf_counter() - started_at) * 1000),
                    error=str(exc),
                    args_keys=args_keys,
                )
                raise
        raise MCPToolError(f"Unsupported MCP transport: {server.transport}")

    async def _check_server_status(self, server: MCPServerConfig) -> dict[str, Any]:
        telemetry = self._ensure_telemetry(server.name)
        if server.transport == "http":
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = self._request_headers(server)
                    if headers:
                        resp = await client.get(f"{server.base_url}/health", headers=headers)
                    else:
                        resp = await client.get(f"{server.base_url}/health")
                    inventory = await self._fetch_http_inventory(server, client) if resp.is_success else self._empty_inventory()
                return {"enabled": True, "ok": resp.is_success, "status_code": resp.status_code, "transport": server.transport, "connected": resp.is_success, **inventory, **telemetry}
            except Exception as exc:
                telemetry["last_error"] = str(exc)
                return {"enabled": True, "ok": False, "message": str(exc), "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}

        if server.transport == "stdio":
            if not server.command:
                return {"enabled": True, "ok": False, "message": "missing stdio command", "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}
            try:
                inventory = await self._fetch_stdio_inventory(server)
                existing = self._stdio_sessions.get(server.name)
                running = bool(existing and existing.get("process") and existing["process"].returncode is None)
                protocol = str((existing or {}).get("protocol") or "legacy")
                return {
                    "enabled": True,
                    "ok": True,
                    "message": f"stdio {protocol} connected" if running else "stdio configured",
                    "transport": server.transport,
                    "connected": running,
                    **inventory,
                    **telemetry,
                }
            except Exception as exc:
                telemetry["last_error"] = str(exc)
                return {"enabled": True, "ok": False, "message": str(exc), "transport": server.transport, "connected": False, **self._empty_inventory(str(exc)), **telemetry}

        if server.transport == "sse":
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = self._request_headers(server)
                    if headers:
                        resp = await client.get(f"{server.base_url}/health", headers=headers)
                    else:
                        resp = await client.get(f"{server.base_url}/health")
                    inventory = await self._fetch_http_inventory(server, client) if resp.is_success else self._empty_inventory()
                existing = self._sse_sessions.get(server.name)
                connected = bool(existing and existing.get("task") and not existing["task"].done())
                pending_requests = len(existing.get("pending", {})) if existing else 0
                return {"enabled": True, "ok": resp.is_success, "status_code": resp.status_code, "transport": server.transport, "message": "sse connected" if connected else None, "connected": connected, "pending_requests": pending_requests, **inventory, **telemetry}
            except Exception as exc:
                telemetry["last_error"] = str(exc)
                return {"enabled": True, "ok": False, "message": str(exc), "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}

        if server.transport == "streamable_http":
            try:
                await self._ensure_streamable_http_session(server)
                inventory = await self._fetch_streamable_http_inventory(server)
                session = self._streamable_http_sessions.get(server.name) or {}
                telemetry["session_id"] = session.get("session_id")
                return {
                    "enabled": True,
                    "ok": True,
                    "message": "streamable http connected",
                    "transport": server.transport,
                    "connected": True,
                    **inventory,
                    **telemetry,
                }
            except Exception as exc:
                telemetry["last_error"] = str(exc)
                return {"enabled": True, "ok": False, "message": str(exc), "transport": server.transport, "connected": False, **self._empty_inventory(str(exc)), **telemetry}

        return {"enabled": True, "ok": False, "message": f"unsupported transport: {server.transport}", "transport": server.transport, "connected": False, **self._empty_inventory(), **telemetry}

    async def _ensure_streamable_http_session(self, server: MCPServerConfig) -> dict[str, Any]:
        session = self._streamable_http_sessions.get(server.name)
        if session is not None:
            return session
        result, session_id = await self._streamable_http_raw_request(
            server,
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "clientInfo": {
                    "name": "yuizaki",
                    "version": "0.1.0",
                },
            },
            session_id=None,
            timeout=12.0,
        )
        session = {
            "session_id": session_id or f"http_{uuid.uuid4().hex[:8]}",
            "protocol": "streamable_http",
            "server_info": result.get("serverInfo") if isinstance(result, dict) else None,
            "mcp_session_id": session_id,
        }
        self._streamable_http_sessions[server.name] = session
        await self._streamable_http_notification(server, "notifications/initialized", {}, session_id=session_id)
        self._append_history(
            server.name,
            "streamable_http_connected",
            str(session["session_id"]),
            status="ok",
            transport="streamable_http",
            session_id=str(session["session_id"]),
        )
        return session

    async def _fetch_streamable_http_inventory(self, server: MCPServerConfig) -> dict[str, Any]:
        tools_result = await self._streamable_http_request(server, "tools/list", {}, timeout=8.0)
        resources_result = await self._streamable_http_optional_list(server, "resources/list")
        prompts_result = await self._streamable_http_optional_list(server, "prompts/list")
        return self._inventory_from_manifest({
            "tools": tools_result.get("tools") if isinstance(tools_result, dict) else [],
            "resources": resources_result.get("resources") if isinstance(resources_result, dict) else [],
            "prompts": prompts_result.get("prompts") if isinstance(prompts_result, dict) else [],
        })

    async def _streamable_http_optional_list(self, server: MCPServerConfig, method: str) -> dict[str, Any]:
        try:
            result = await self._streamable_http_request(server, method, {}, timeout=5.0)
            return result if isinstance(result, dict) else {}
        except MCPToolError:
            return {}

    async def _streamable_http_request(
        self,
        server: MCPServerConfig,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        session = await self._ensure_streamable_http_session(server)
        result, session_id = await self._streamable_http_raw_request(
            server,
            method,
            params or {},
            session_id=session.get("mcp_session_id"),
            timeout=timeout,
        )
        if session_id:
            session["mcp_session_id"] = session_id
        return result

    async def _streamable_http_raw_request(
        self,
        server: MCPServerConfig,
        method: str,
        params: dict[str, Any] | None,
        *,
        session_id: str | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str | None]:
        request_id = f"yuizaki_{uuid.uuid4().hex[:10]}"
        headers = self._request_headers(server, {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        })
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(server.base_url, json=payload, headers=headers)
        response.raise_for_status()
        next_session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or session_id
        data = self._parse_streamable_http_response(response, request_id)
        if data.get("error"):
            error = data["error"]
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or error
            else:
                message = error
            raise MCPToolError(str(message))
        result = data.get("result")
        return (result if isinstance(result, dict) else {"value": result}), next_session_id

    async def _streamable_http_notification(
        self,
        server: MCPServerConfig,
        method: str,
        params: dict[str, Any] | None,
        *,
        session_id: str | None,
    ) -> None:
        headers = self._request_headers(server, {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        })
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(server.base_url, json=payload, headers=headers)
        if response.status_code not in {200, 202, 204}:
            response.raise_for_status()

    def _parse_streamable_http_response(self, response: httpx.Response, request_id: str) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            for raw_line in response.text.splitlines():
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line.split(":", 1)[1].strip()
                if not payload:
                    continue
                data = json.loads(payload)
                if str(data.get("id") or "") == request_id:
                    return data
            raise MCPToolError("streamable HTTP MCP response did not include the matching JSON-RPC id")
        data = response.json()
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and str(item.get("id") or "") == request_id:
                    return item
            raise MCPToolError("streamable HTTP MCP batch response did not include the matching JSON-RPC id")
        if not isinstance(data, dict):
            raise MCPToolError("streamable HTTP MCP response is not a JSON object")
        return data

    async def _fetch_stdio_inventory(self, server: MCPServerConfig) -> dict[str, Any]:
        session = await self._get_or_create_stdio_session(server)
        if session.get("protocol") != "mcp-jsonrpc":
            raise MCPToolError(
                "legacy stdio protocol is unsupported; migrate the server to MCP JSON-RPC stdio"
            )

        async with session["lock"]:
            tools_result = await self._stdio_jsonrpc_request_locked(session, "tools/list", {}, timeout=8.0)
            resources_result = await self._stdio_optional_list_locked(session, "resources/list")
            prompts_result = await self._stdio_optional_list_locked(session, "prompts/list")

        return self._inventory_from_manifest({
            "tools": tools_result.get("tools") if isinstance(tools_result, dict) else [],
            "resources": resources_result.get("resources") if isinstance(resources_result, dict) else [],
            "prompts": prompts_result.get("prompts") if isinstance(prompts_result, dict) else [],
        })

    async def _stdio_optional_list_locked(self, session: dict[str, Any], method: str) -> dict[str, Any]:
        try:
            result = await self._stdio_jsonrpc_request_locked(session, method, {}, timeout=5.0)
            return result if isinstance(result, dict) else {}
        except MCPToolError:
            return {}

    async def _stdio_jsonrpc_request_locked(
        self,
        session: dict[str, Any],
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        request_id = f"yuizaki_{uuid.uuid4().hex[:10]}"
        process = session["process"]
        stdin = process.stdin
        stdout = process.stdout
        if stdin is None or stdout is None:
            raise MCPToolError("stdio MCP pipes are unavailable")

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await stdin.drain()

        while True:
            line = await self._stdio_readline(process, timeout=timeout)
            try:
                data = json.loads(line.decode("utf-8", errors="ignore").strip() or "{}")
            except Exception as exc:
                raise MCPToolError(f"Invalid JSON from stdio MCP server: {line[:200]!r}") from exc

            if not isinstance(data, dict):
                continue
            if "ok" in data and "jsonrpc" not in data:
                raise MCPToolError("legacy stdio MCP protocol detected")
            if str(data.get("id") or "") != request_id:
                continue
            if data.get("error"):
                error = data["error"]
                if isinstance(error, dict):
                    message = error.get("message") or error.get("code") or error
                else:
                    message = error
                raise MCPToolError(str(message))
            result = data.get("result")
            return result if isinstance(result, dict) else {"value": result}

    async def _stdio_notification_locked(self, session: dict[str, Any], method: str, params: dict[str, Any] | None = None) -> None:
        process = session["process"]
        stdin = process.stdin
        if stdin is None:
            raise MCPToolError("stdio MCP stdin is unavailable")
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await stdin.drain()

    async def _stdio_readline(self, process: Any, *, timeout: float) -> bytes:
        stdout = process.stdout
        if stdout is None:
            raise MCPToolError("stdio MCP stdout is unavailable")
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise MCPToolError("stdio MCP response timed out") from exc
        if line:
            return line
        stderr = process.stderr
        detail = "stdio MCP process closed stdout"
        if stderr is not None:
            try:
                more = await asyncio.wait_for(stderr.read(), timeout=0.2)
                detail = (more.decode("utf-8", errors="ignore") or detail).strip()
            except Exception:
                pass
        raise MCPToolError(detail)

    def _format_stdio_tool_result(self, result: dict[str, Any]) -> str:
        structured = result.get("structuredContent")
        content = result.get("content")
        parts: list[str] = []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    parts.append(str(item))
                    continue
                if item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
                elif item.get("type") == "resource":
                    parts.append(json.dumps(item.get("resource"), ensure_ascii=False))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        if structured is not None:
            parts.append(json.dumps(structured, ensure_ascii=False))
        output = "\n".join(part for part in parts if part)
        if result.get("isError"):
            raise MCPToolError(output or "MCP tool returned an error")
        return output or json.dumps(result, ensure_ascii=False)

    async def _call_stdio_tool(self, server: MCPServerConfig, tool_name: str, args: dict[str, Any]) -> str:
        if not server.command:
            raise MCPToolError("MCP stdio transport missing command")
        session = await self._get_or_create_stdio_session(server)
        process = session["process"]
        if session.get("protocol") == "mcp-jsonrpc":
            async with session["lock"]:
                result = await self._stdio_jsonrpc_request_locked(
                    session,
                    "tools/call",
                    {"name": tool_name, "arguments": args},
                    timeout=SSE_TOOL_TIMEOUT_SECONDS,
                )
            return self._format_stdio_tool_result(result)

        payload = json.dumps({"name": tool_name, "args": args}, ensure_ascii=False) + "\n"
        async with session["lock"]:
            stdin = process.stdin
            stdout = process.stdout
            if stdin is None or stdout is None:
                raise MCPToolError("stdio MCP pipes are unavailable")
            stdin.write(payload.encode("utf-8"))
            await stdin.drain()
            try:
                line = await self._stdio_readline(process, timeout=SSE_TOOL_TIMEOUT_SECONDS)
            except MCPToolError:
                self._stdio_sessions.pop(server.name, None)
                await self._close_stdio_session(session)
                raise
        if process.returncode not in {None}:
            stderr = process.stderr
            detail = "stdio MCP process exited"
            if stderr is not None:
                more = await stderr.read()
                detail = (more.decode("utf-8", errors="ignore") or detail).strip()
            self._stdio_sessions.pop(server.name, None)
            raise MCPToolError(detail)
        try:
            data = json.loads(line.decode("utf-8", errors="ignore").strip() or "{}")
        except Exception as exc:
            raise MCPToolError(f"Invalid JSON from stdio MCP server: {line[:200]!r}") from exc
        if not data.get("ok", False):
            raise MCPToolError(str(data.get("error", "Unknown stdio MCP error")))
        return str(data.get("output", ""))

    async def _get_or_create_stdio_session(self, server: MCPServerConfig) -> dict[str, Any]:
        existing_session = self._stdio_sessions.get(server.name)
        process = existing_session.get("process") if existing_session else None
        if existing_session and process is not None and process.returncode is None:
            return existing_session

        if not server.command:
            raise MCPToolError(f"stdio MCP command missing for server {server.name}")
        if not self._stdio_launch_allowed(server):
            raise MCPToolError("Custom stdio MCP launch is disabled; install a preset or set YUIZAKI_ALLOW_CUSTOM_MCP_STDIO=true")

        cwd = str(Path(__file__).resolve().parents[3] / "node-mcp") if server.command == "node" else None
        process_env = self._stdio_process_env(server)
        process = await asyncio.create_subprocess_exec(
            server.command,
            *(server.args or []),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=process_env,
        )
        session: dict[str, Any] = {
            "session_id": f"stdio_{uuid.uuid4().hex[:8]}",
            "server_name": server.name,
            "process": process,
            "lock": asyncio.Lock(),
            "protocol": "legacy",
        }
        try:
            async with session["lock"]:
                initialize_result = await self._stdio_jsonrpc_request_locked(
                    session,
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {},
                            "resources": {},
                            "prompts": {},
                        },
                        "clientInfo": {
                            "name": "yuizaki",
                            "version": "0.1.0",
                        },
                    },
                    timeout=8.0,
                )
                await self._stdio_notification_locked(session, "notifications/initialized", {})
            session["protocol"] = "mcp-jsonrpc"
            session["server_info"] = initialize_result.get("serverInfo") if isinstance(initialize_result, dict) else None
        except Exception as exc:
            session["protocol"] = "legacy"
            session["initialization_error"] = str(exc)
        self._stdio_sessions[server.name] = session
        telemetry = self._ensure_telemetry(server.name)
        telemetry["session_id"] = session["session_id"]
        self._append_history(
            server.name,
            "stdio_connected",
            f"{session['session_id']} ({session['protocol']})",
            status="ok",
            transport="stdio",
            session_id=str(session["session_id"]),
        )
        return session

    async def _close_stdio_session(self, session: dict[str, Any]) -> None:
        process = session.get("process")
        if process is None or process.returncode is not None:
            return
        self._append_history(
            str(session.get("server_name") or "unknown"),
            "stdio_closing",
            str(session.get("session_id") or ""),
            status="closing",
            transport="stdio",
            session_id=str(session.get("session_id") or ""),
        )
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3.0)
        except Exception:
            process.kill()
            try:
                await process.wait()
            except Exception:
                pass

    async def _call_sse_tool(self, server: MCPServerConfig, tool_name: str, args: dict[str, Any], request_id: str, args_keys: list[str]) -> str:
        session = await self._get_or_create_sse_session(server)
        future = asyncio.get_running_loop().create_future()
        session["pending"][request_id] = {
            "future": future,
            "created_at": asyncio.get_running_loop().time(),
        }
        self._append_history(
            server.name,
            "sse_request_queued",
            f"{tool_name} queued for SSE result",
            status="pending",
            transport="sse",
            tool=tool_name,
            request_id=request_id,
            pending_requests=len(session["pending"]),
            args_keys=args_keys,
        )
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                headers = self._request_headers(server)
                if headers:
                    resp = await client.post(
                        f"{server.base_url.rstrip('/')}/tools",
                        json={"name": tool_name, "args": args, "requestId": request_id},
                        headers=headers,
                    )
                else:
                    resp = await client.post(
                        f"{server.base_url.rstrip('/')}/tools",
                        json={"name": tool_name, "args": args, "requestId": request_id},
                    )
            resp.raise_for_status()
        except Exception as exc:
            session["pending"].pop(request_id, None)
            self._append_history(
                server.name,
                "sse_request_dispatch_failed",
                f"{tool_name} dispatch failed",
                status="error",
                transport="sse",
                tool=tool_name,
                request_id=request_id,
                error=str(exc),
                pending_requests=len(session["pending"]),
                args_keys=args_keys,
            )
            raise MCPToolError(f"MCP SSE transport request failed: {exc}") from exc
        try:
            data = await asyncio.wait_for(asyncio.shield(future), timeout=SSE_TOOL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            reason = "MCP SSE request timed out waiting for event"
            self._fail_pending(session, reason, only_stale=False)
            if future.done():
                try:
                    future.result()
                except Exception:
                    pass
            raise MCPToolError(reason) from exc
        finally:
            session["pending"].pop(request_id, None)
        if not data.get("ok", False):
            raise MCPToolError(str(data.get("error", "Unknown SSE MCP error")))
        return str(data.get("output", ""))

    async def _wait_for_sse_ready(self, server_name: str, session: dict[str, Any], timeout_seconds: float = SSE_READY_TIMEOUT_SECONDS) -> None:
        ready = session.get("ready")
        if not isinstance(ready, asyncio.Event) or ready.is_set():
            return
        try:
            await asyncio.wait_for(ready.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise MCPToolError(f"MCP SSE session did not become ready for server {server_name}") from exc

    async def _get_or_create_sse_session(self, server: MCPServerConfig) -> dict[str, Any]:
        existing_session = self._sse_sessions.get(server.name)
        task = existing_session.get("task") if existing_session else None
        if existing_session and task is not None and not task.done():
            await self._wait_for_sse_ready(server.name, existing_session)
            return existing_session

        session: dict[str, Any] = {
            "session_id": f"sse_{uuid.uuid4().hex[:8]}",
            "pending": {},
            "stop": asyncio.Event(),
            "ready": asyncio.Event(),
            "backoff_seconds": 1.0,
        }
        task = asyncio.create_task(self._run_sse_listener(server, session), name=f"mcp-sse-listener-{server.name}")
        task.add_done_callback(_log_task_exception)
        session["task"] = task
        session["server_name"] = server.name
        self._sse_sessions[server.name] = session
        telemetry = self._ensure_telemetry(server.name)
        telemetry["session_id"] = session["session_id"]
        await self._wait_for_sse_ready(server.name, session)
        return session

    async def _run_sse_listener(self, server: MCPServerConfig, session: dict[str, Any]) -> None:
        server_name = server.name
        url = f"{server.base_url.rstrip('/')}/events"
        telemetry = self._ensure_telemetry(server_name)
        try:
            while not session["stop"].is_set():
                try:
                    async with httpx.AsyncClient(timeout=None) as client:
                        async with client.stream("GET", url, headers=self._request_headers(server, {"Accept": "text/event-stream"})) as response:
                            response.raise_for_status()
                            session["backoff_seconds"] = 1.0
                            event_name = "message"
                            data_lines: list[str] = []
                            async for raw_line in response.aiter_lines():
                                if session["stop"].is_set():
                                    break
                                self._cleanup_stale_pending(session)
                                line = raw_line.strip()
                                if not line:
                                    if data_lines:
                                        payload = "\n".join(data_lines)
                                        if event_name == "ready":
                                            ready = session.get("ready")
                                            if isinstance(ready, asyncio.Event) and not ready.is_set():
                                                ready.set()
                                                self._append_history(
                                                    server_name,
                                                    "sse_connected",
                                                    str(session.get("session_id") or ""),
                                                    status="ok",
                                                    transport="sse",
                                                    session_id=str(session.get("session_id") or ""),
                                                    pending_requests=len(session["pending"]),
                                                )
                                        elif event_name == "tool-result":
                                            try:
                                                parsed = json.loads(payload)
                                                request_id = str(parsed.get("requestId") or "")
                                                pending = session["pending"].get(request_id)
                                                future = pending.get("future") if pending else None
                                                if future and not future.done():
                                                    future.set_result(parsed)
                                            except Exception as exc:
                                                self._append_history(server_name, "sse_event_parse_failed", "invalid tool-result payload", status="error", transport="sse", error=str(exc))
                                    event_name = "message"
                                    data_lines = []
                                    continue
                                if line.startswith("event:"):
                                    event_name = line.split(":", 1)[1].strip() or "message"
                                elif line.startswith("data:"):
                                    data_lines.append(line.split(":", 1)[1].lstrip())
                except Exception as exc:
                    telemetry["last_error"] = str(exc)
                    telemetry["reconnect_count"] += 1
                    self._append_history(server_name, "sse_reconnect", str(exc), status="error", transport="sse", error=str(exc), pending_requests=len(session["pending"]))
                    self._fail_pending(session, f"MCP SSE listener error: {exc}", only_stale=False)
                    await asyncio.sleep(session["backoff_seconds"])
                    session["backoff_seconds"] = min(session["backoff_seconds"] * 2, 15.0)
        finally:
            telemetry["session_id"] = None
            self._append_history(server_name, "sse_closed", "session closed", status="closed", transport="sse", pending_requests=len(session["pending"]))
            self._fail_pending(session, "MCP SSE session closed", only_stale=False)
            self._sse_sessions.pop(server_name, None)

    def _cleanup_stale_pending(self, session: dict[str, Any], *, ttl_seconds: float = 65.0) -> None:
        self._fail_pending(session, "MCP SSE request timed out waiting for event", only_stale=True, ttl_seconds=ttl_seconds)

    def _fail_pending(self, session: dict[str, Any], reason: str, *, only_stale: bool, ttl_seconds: float = 65.0) -> None:
        now = asyncio.get_running_loop().time()
        for request_id, pending in list(session["pending"].items()):
            created_at = pending.get("created_at", now)
            if only_stale and (now - created_at) < ttl_seconds:
                continue
            future = pending.get("future")
            if future and not future.done():
                future.set_exception(MCPToolError(reason))
            server_name = session.get("server_name")
            session["pending"].pop(request_id, None)
            if server_name:
                self._append_history(
                    server_name,
                    "pending_failed",
                    reason,
                    status="error",
                    transport="sse",
                    request_id=str(request_id),
                    error=reason,
                    pending_requests=len(session["pending"]),
                )

    async def _close_sse_session(self, session: dict[str, Any]) -> None:
        session["stop"].set()
        task = session.get("task")
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    def _safe_tool_segment(self, value: str) -> str:
        segment = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
        return segment or "tool"

    def _registered_mcp_tool_name(self, server_name: str, remote_tool_name: str) -> str:
        return f"mcp_{self._safe_tool_segment(server_name)}_{self._safe_tool_segment(remote_tool_name)}"

    def _unregister_dynamic_tools(self, server_name: str) -> None:
        registry = self._registry
        if registry is None:
            return
        for tool_name in self._registered_dynamic_tools_by_server.pop(server_name, set()):
            registry.unregister(tool_name)

    def _sync_server_tools(self, server_name: str) -> None:
        registry = self._registry
        if registry is None:
            return
        self._unregister_dynamic_tools(server_name)
        server = self.servers.get(server_name)
        status = self.status.get(server_name)
        if server is None or status is None or not server.enabled or not status.get("ok"):
            return

        registered: set[str] = set()
        for item in self._coerce_inventory_items(status.get("tools")):
            remote_tool_name = item.name
            registered_name = self._registered_mcp_tool_name(server_name, remote_tool_name)

            async def _mcp_tool_handler(args: dict[str, Any], *, _server_name: str = server_name, _remote_tool_name: str = remote_tool_name, _registered_name: str = registered_name) -> ToolResultEnvelope:
                output = await self.call_tool(_server_name, _remote_tool_name, args)
                return ToolResultEnvelope(
                    success=True,
                    content=output,
                    source="mcp",
                    tool_name=_registered_name,
                    data={
                        "server": _server_name,
                        "remote_tool": _remote_tool_name,
                    },
                )

            registry.register(ToolDefinition(
                name=registered_name,
                description=f"{item.description or remote_tool_name} (MCP: {server_name}/{remote_tool_name})",
                source="mcp",
                parameters=item.input_schema or {"type": "object", "properties": {}},
                handler=_mcp_tool_handler,
                effect_kind="unknown",
                risk_level="medium",
                require_confirm=False,
                tags=["mcp", f"mcp-server:{server_name}", f"mcp-tool:{remote_tool_name}", "contrib:capability"],
                scopes=[f"mcp:{server_name}", f"mcp:{server_name}:{remote_tool_name}"],
            ))
            registered.add(registered_name)
        if registered:
            self._registered_dynamic_tools_by_server[server_name] = registered

    def register_tools(self, registry: ToolRegistry) -> None:
        self._registry = registry

        async def _browser_open_page(args: dict[str, Any]) -> ToolResultEnvelope:
            output = await self.call_tool("playwright", "browser.open_page", args)
            return ToolResultEnvelope(
                success=True,
                content=output,
                source="mcp",
                tool_name="browser.open_page",
            )

        registry.register(ToolDefinition(
            name="browser.open_page",
            description="通过 Playwright MCP 服务打开浏览器页面。",
            source="mcp",
            parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            handler=_browser_open_page,
            effect_kind="write",
            risk_level="medium",
            require_confirm=False,
            tags=["mcp", "browser", "playwright"],
            scopes=["mcp:playwright", "browser:open_page"],
        ))
        for server_name in list(self.status.keys()):
            self._sync_server_tools(server_name)
