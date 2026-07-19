from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .orchestration_registry import OrchestrationRegistry
from .tool_registry import ToolDefinition, ToolRegistry


@dataclass
class CapabilityRegistry:
    tool_registry: ToolRegistry
    orchestration_registry: OrchestrationRegistry | None = None

    def _tool_display_name(self, tool: ToolDefinition) -> str:
        names = {
            "open_app": "打开应用",
            "open_url": "打开链接",
            "read_file": "读取文件",
            "write_file": "写入文件",
            "web_search": "联网搜索",
            "time.now": "当前时间",
        }
        return names.get(tool.name, tool.name)

    def _tool_description(self, tool: ToolDefinition) -> str:
        descriptions = {
            "open_app": "按名称打开本机桌面应用。",
            "open_url": "在默认浏览器中打开链接。",
            "read_file": "读取本地文本文件内容。",
            "write_file": "把文本内容写入本地文件。",
            "web_search": "联网搜索公开信息，并返回简要结果和链接。",
            "time.now": "获取当前本地时间。",
            "browser.open_page": "通过 Playwright MCP 服务打开浏览器页面。",
            "mcp_playwright_browser_open_page": "在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。",
            "mcp_playwright_browser_click": "打开 URL 后点击指定 CSS 选择器。",
        }
        if tool.name in descriptions:
            return descriptions[tool.name]

        raw_description = " ".join(str(tool.description or "").strip().lower().split())
        raw_descriptions = {
            "launch a desktop application by name": "按名称打开本机桌面应用。",
            "open a url in the default browser": "在默认浏览器中打开链接。",
            "read a local text file": "读取本地文本文件内容。",
            "write text content to a local file": "把文本内容写入本地文件。",
            "search the web for current public information and return concise results with urls": "联网搜索公开信息，并返回简要结果和链接。",
            "open a browser page via playwright mcp server": "通过 Playwright MCP 服务打开浏览器页面。",
            "get the current local time": "获取当前本地时间。",
            "open a url in a playwright browser context and wait for network idle. (mcp: playwright/browser.open_page)": "在 Playwright 浏览器上下文中打开 URL，并等待网络空闲。",
            "open a url and click a css selector with playwright. (mcp: playwright/browser.click)": "打开 URL 后点击指定 CSS 选择器。",
        }
        return raw_descriptions.get(raw_description, tool.description)

    def _tool_owner(self, tool: ToolDefinition) -> str:
        if tool.source == "plugin":
            parts = tool.name.split(".")
            if len(parts) >= 3 and parts[0] == "plugin":
                return f"plugin:{parts[1]}"
            return "plugin-runtime"
        if tool.source == "mcp":
            parts = tool.name.split(".")
            if len(parts) >= 2:
                return f"mcp:{parts[0]}"
            return "mcp-runtime"
        return "yuizaki.builtin-tools"

    def _tool_capability(self, tool: ToolDefinition) -> dict[str, object]:
        kind_map = {
            "builtin": "builtin-tool",
            "plugin": "plugin-tool",
            "mcp": "mcp-tool",
        }
        contribution_categories = [str(tag).split(":", 1)[1] for tag in (tool.tags or []) if str(tag).startswith("contrib:")]
        return {
            "id": tool.name,
            "name": self._tool_display_name(tool),
            "description": self._tool_description(tool),
            "type": "tool",
            "kind": kind_map.get(tool.source, "builtin-tool"),
            "source": tool.source,
            "riskLevel": tool.risk_level,
            "requiresApproval": bool(tool.require_confirm),
            "owner": self._tool_owner(tool),
            "tags": list(tool.tags or []),
            "contributionCategories": contribution_categories,
            "scopes": list(tool.scopes or []),
            "inputSchema": tool.parameters,
            "outputSchema": {},
            "timeoutMs": None,
            "memoryHooks": [],
            "observability": {
                "trace": True,
                "audit": True,
            },
            "parameters": tool.parameters,
        }

    def _skill_owner(self, item: dict[str, object]) -> str:
        skill_id = str(item.get("id") or "")
        stage = str(item.get("stage") or "")
        if "capability-routing" in skill_id or stage == "decide-act":
            return "yuizaki.task-router"
        return "yuizaki.companion-orchestrator"

    def _skill_capabilities(self) -> list[dict[str, object]]:
        registry = self.orchestration_registry or OrchestrationRegistry()
        snapshot = registry.snapshot()
        skills_raw = snapshot.get("skills", [])
        if not isinstance(skills_raw, list):
            return []
        skills: list[dict[str, object]] = []
        for raw_item in cast(list[object], skills_raw):
            if not isinstance(raw_item, dict):
                continue
            raw_dict = cast(dict[object, object], raw_item)
            item: dict[str, object] = {str(key): value for key, value in raw_dict.items()}
            skills.append(item)

        capabilities: list[dict[str, object]] = []
        for item in skills:
            stage = str(item.get("stage") or "")
            tags = ["skill"]
            if stage:
                tags.append(stage)
            raw_tags = item.get("tags")
            if isinstance(raw_tags, list):
                tags.extend(str(tag) for tag in raw_tags if str(tag) not in tags)
            capabilities.append({
                "id": str(item.get("id") or "skill"),
                "name": str(item.get("name") or item.get("id") or "Skill"),
                "description": str(item.get("description") or ""),
                "type": "skill",
                "kind": "skill",
                "source": "orchestration",
                "riskLevel": "low",
                "requiresApproval": False,
                "owner": self._skill_owner(item),
                "tags": tags,
                "contributionCategories": ["capability"],
                "scopes": [],
                "inputSchema": {},
                "outputSchema": {},
                "timeoutMs": None,
                "memoryHooks": ["reflective"],
                "observability": {
                    "trace": True,
                    "audit": False,
                    "stage": stage or None,
                },
                "parameters": {},
            })
        return capabilities

    def _command_owner(self, item: dict[str, object]) -> str:
        target = str(item.get("target") or "")
        if "/api/system/schedules/" in target:
            return "yuizaki.task-router"
        return "yuizaki.companion-orchestrator"

    def _command_capabilities(self) -> list[dict[str, object]]:
        registry = self.orchestration_registry or OrchestrationRegistry()
        snapshot = registry.snapshot()
        commands_raw = snapshot.get("commands", [])
        if not isinstance(commands_raw, list):
            return []
        commands: list[dict[str, object]] = []
        for raw_item in cast(list[object], commands_raw):
            if not isinstance(raw_item, dict):
                continue
            raw_dict = cast(dict[object, object], raw_item)
            item: dict[str, object] = {str(key): value for key, value in raw_dict.items()}
            commands.append(item)

        capabilities: list[dict[str, object]] = []
        for item in commands:
            target = str(item.get("target") or "")
            capabilities.append({
                "id": str(item.get("id") or "command"),
                "name": str(item.get("name") or item.get("id") or "Command"),
                "description": str(item.get("description") or ""),
                "type": "command",
                "kind": "command",
                "source": "orchestration",
                "riskLevel": "low",
                "requiresApproval": False,
                "owner": self._command_owner(item),
                "tags": ["command", "task-entry"],
                "contributionCategories": ["capability"],
                "scopes": [],
                "inputSchema": {},
                "outputSchema": {},
                "timeoutMs": None,
                "memoryHooks": ["reflective"],
                "observability": {
                    "trace": True,
                    "audit": False,
                    "stage": "task-entry",
                },
                "parameters": {
                    "target": target,
                },
            })
        return capabilities

    def snapshot(self) -> dict[str, object]:
        capabilities: list[dict[str, object]] = [
            *(self._tool_capability(tool) for tool in self.tool_registry.list()),
            *self._skill_capabilities(),
            *self._command_capabilities(),
        ]
        return {
            "capabilities": capabilities,
            "summary": {
                "total": len(capabilities),
                "builtin": sum(1 for item in capabilities if item.get("kind") == "builtin-tool"),
                "plugin": sum(1 for item in capabilities if item.get("kind") == "plugin-tool"),
                "mcp": sum(1 for item in capabilities if item.get("kind") == "mcp-tool"),
                "skill": sum(1 for item in capabilities if item.get("kind") == "skill"),
                "command": sum(1 for item in capabilities if item.get("kind") == "command"),
                "approval_required": sum(1 for item in capabilities if bool(item.get("requiresApproval"))),
            },
        }
