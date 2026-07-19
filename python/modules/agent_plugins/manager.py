from __future__ import annotations

import importlib
import json
import pkgutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agent.models import PluginSnapshot, PluginTraceRecord
from ..agent.tool_registry import ToolRegistry
from ..core.paths import data_dir_from_env

from .base import AgentPlugin


class PluginManager:
    def __init__(self, store_file: str | Path | None = None) -> None:
        self.plugins: dict[str, AgentPlugin] = {}
        self._plugin_tools: dict[str, list[str]] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._trace: list[dict[str, Any]] = []
        self._registry: ToolRegistry | None = None
        self._loaded = False
        self._store_file = Path(store_file) if store_file is not None else data_dir_from_env() / "agent_plugins.json"
        self._proactive_dispatch: Any | None = None
        self._load_store()

    def set_proactive_dispatch(self, dispatcher: Any) -> None:
        self._proactive_dispatch = dispatcher

    def _load_store(self) -> None:
        try:
            if not self._store_file.exists():
                return
            data = json.loads(self._store_file.read_text(encoding="utf-8"))
            states = data.get("states") or {}
            trace = data.get("trace") or []
            if isinstance(states, dict):
                self._states = states
            if isinstance(trace, list):
                self._trace = trace[-200:]
        except Exception:
            self._states = {}
            self._trace = []

    def _save_store(self) -> None:
        self._store_file.parent.mkdir(parents=True, exist_ok=True)
        self._store_file.write_text(
            json.dumps({"states": self._states, "trace": self._trace[-200:]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _append_trace(self, plugin_id: str, hook: str, status: str, detail: str = "") -> None:
        self._trace.append({
            "timestamp": datetime.now().isoformat(),
            "plugin_id": plugin_id,
            "hook": hook,
            "status": status,
            "detail": detail,
        })
        self._trace = self._trace[-200:]
        # 每 20 条批量写一次，避免每次 hook 都写磁盘
        if len(self._trace) % 20 == 0:
            self._save_store()

    async def discover_and_load(self, registry: ToolRegistry) -> None:
        self._registry = registry
        if self._loaded:
            return

        package = importlib.import_module("modules.agent_plugins")
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name in {"base", "manager"}:
                continue
            module = importlib.import_module(f"modules.agent_plugins.{module_info.name}")
            plugin_cls = getattr(module, "PLUGIN", None)
            if plugin_cls is None:
                continue

            plugin: AgentPlugin = plugin_cls()
            state = self._states.setdefault(plugin.id, {
                "id": plugin.id,
                "name": plugin.name,
                "version": plugin.version,
                "enabled": True,
                "loaded": False,
                "error": None,
                "config": plugin.default_config(),
            })
            state["version"] = str(getattr(plugin, "version", state.get("version") or "0.1.0"))

            try:
                merged_config = dict(plugin.default_config())
                if isinstance(state.get("config"), dict):
                    merged_config.update(state.get("config") or {})
                plugin.config = merged_config
                state["config"] = merged_config
                await plugin.initialize({
                    "tool_registry": registry,
                    "proactive_dispatch": self._proactive_dispatch,
                })
                state["loaded"] = True
                state["error"] = None
                self.plugins[plugin.id] = plugin

                if state.get("enabled", True):
                    tool_names: list[str] = []
                    for tool in plugin.register_tools():
                        registry.register(tool)
                        tool_names.append(tool.name)
                    self._plugin_tools[plugin.id] = tool_names

                self._append_trace(plugin.id, "initialize", "ok")
            except Exception as exc:
                state["loaded"] = False
                state["error"] = str(exc)
                self._append_trace(plugin.id, "initialize", "error", str(exc))

        self._loaded = True
        self._save_store()

    def snapshot(self) -> dict[str, Any]:
        contribution_summary = [
            {
                "category": "ui",
                "count": 0,
                "items": [],
            },
            {
                "category": "capability",
                "count": sum(len(names) for names in self._plugin_tools.values()),
                "items": [name for names in self._plugin_tools.values() for name in names],
            },
            {
                "category": "event",
                "count": sum(1 for item in self._trace if str(item.get("hook") or "") in {"before_pipeline", "before_llm", "after_llm", "before_tool", "after_tool", "before_dispatch", "proactive_dispatch"}),
                "items": sorted({str(item.get("hook") or "") for item in self._trace if item.get("hook")}),
            },
            {
                "category": "policy",
                "count": sum(1 for state in self._states.values() if bool(state.get("config_schema") or state.get("config"))),
                "items": [str(state.get("id") or "") for state in self._states.values() if state.get("id")],
            },
        ]
        return {
            "plugins": [
                PluginSnapshot(
                    id=str(state.get("id") or plugin_id),
                    name=str(state.get("name") or plugin_id),
                    version=str(state.get("version") or "0.1.0"),
                    enabled=bool(state.get("enabled", True)),
                    loaded=bool(state.get("loaded", False)),
                    error=state.get("error"),
                    config=state.get("config") if isinstance(state.get("config"), dict) else None,
                    config_schema=self.plugins[plugin_id].get_config_schema() if plugin_id in self.plugins else {"type": "object", "properties": {}},
                ).to_dict()
                for plugin_id, state in self._states.items()
            ],
            "trace": [
                PluginTraceRecord(
                    timestamp=str(item.get("timestamp") or ""),
                    plugin_id=str(item.get("plugin_id") or ""),
                    hook=str(item.get("hook") or ""),
                    status=str(item.get("status") or ""),
                    detail=str(item.get("detail") or ""),
                ).to_dict()
                for item in self._trace[-100:]
            ],
            "contributionSummary": contribution_summary,
        }

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any] | None:
        state = self._states.get(plugin_id)
        plugin = self.plugins.get(plugin_id)
        if state is None:
            return None
        state["enabled"] = enabled

        if self._registry is not None and plugin is not None:
            if enabled:
                tool_names: list[str] = []
                for tool in plugin.register_tools():
                    self._registry.register(tool)
                    tool_names.append(tool.name)
                self._plugin_tools[plugin_id] = tool_names
            else:
                for tool_name in self._plugin_tools.get(plugin_id, []):
                    self._registry.unregister(tool_name)
                self._plugin_tools[plugin_id] = []

        self._append_trace(plugin_id, "toggle", "enabled" if enabled else "disabled")
        return state

    async def update_config(self, plugin_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
        state = self._states.get(plugin_id)
        plugin = self.plugins.get(plugin_id)
        if state is None:
            return None

        if plugin is not None:
            maybe_config = await plugin.on_config_updated(config)
            state["config"] = maybe_config if isinstance(maybe_config, dict) else config
        else:
            state["config"] = config

        self._append_trace(plugin_id, "config_update", "ok")
        return state

    async def before_pipeline(self, ctx: Any) -> Any:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            ctx = await plugin.before_pipeline(ctx)
            self._append_trace(plugin_id, "before_pipeline", "ok")
        return ctx

    async def before_llm(self, ctx: Any) -> Any:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            ctx = await plugin.before_llm(ctx)
            self._append_trace(plugin_id, "before_llm", "ok")
        return ctx

    async def after_llm(self, result: Any, ctx: Any) -> Any:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            result = await plugin.after_llm(result, ctx)
            self._append_trace(plugin_id, "after_llm", "ok")
        return result

    async def before_tool(self, tool_name: str, args: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            args = await plugin.before_tool(tool_name, args, ctx)
            self._append_trace(plugin_id, "before_tool", "ok", tool_name)
        return args

    async def after_tool(self, result: Any, tool_name: str, args: dict[str, Any], ctx: Any = None) -> Any:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            result = await plugin.after_tool(result, tool_name, args, ctx)
            self._append_trace(plugin_id, "after_tool", "ok", tool_name)
        return result

    async def before_dispatch(self, result: Any, ctx: Any) -> Any:
        for plugin_id, plugin in self.plugins.items():
            if not self._states.get(plugin_id, {}).get("enabled", True):
                continue
            result = await plugin.before_dispatch(result, ctx)
            self._append_trace(plugin_id, "before_dispatch", "ok")
        return result

    async def dispatch_proactive_message(
        self,
        *,
        plugin_id: str,
        message: str,
        session_id: str = "plugin-proactive",
        sid: str | None = None,
        pet_control_context: dict[str, Any] | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            raise RuntimeError(f"plugin not loaded: {plugin_id}")
        if not self._states.get(plugin_id, {}).get("enabled", True):
            raise RuntimeError(f"plugin disabled: {plugin_id}")
        if not self._proactive_dispatch:
            raise RuntimeError("proactive dispatcher not configured")
        result = await self._proactive_dispatch(
            plugin_id=plugin_id,
            message=message,
            session_id=session_id,
            sid=sid,
            pet_control_context=pet_control_context,
            source=source,
            metadata=metadata,
        )
        self._append_trace(plugin_id, "proactive_dispatch", "ok", str(source or "plugin"))
        return result
