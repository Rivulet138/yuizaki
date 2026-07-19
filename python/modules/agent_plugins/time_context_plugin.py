from __future__ import annotations

from datetime import datetime

from modules.agent.tool_registry import ToolDefinition
from modules.agent.tool_result import ToolResultEnvelope

from .base import AgentPlugin


class TimeContextPlugin(AgentPlugin):
    id = "time-context"
    name = "时间上下文插件"

    def default_config(self):
        return {
            "inject_system_time": True,
            "system_prompt_prefix": "当前本地时间",
        }

    def get_config_schema(self):
        return {
            "type": "object",
            "properties": {
                "inject_system_time": {
                    "type": "boolean",
                    "title": "注入系统时间",
                },
                "system_prompt_prefix": {
                    "type": "string",
                    "title": "系统提示前缀",
                },
            },
        }

    def register_tools(self):
        return [
            ToolDefinition(
                name="time.now",
                description="获取当前本地时间。",
                source="builtin",
                parameters={"type": "object", "properties": {}},
                handler=lambda args: ToolResultEnvelope(
                    success=True,
                    content=datetime.now().isoformat(),
                    source="builtin",
                    tool_name="time.now",
                ),
                risk_level="safe",
            )
        ]

    async def before_pipeline(self, ctx):
        if self.config.get("inject_system_time", True):
            ctx.extra["now"] = datetime.now().isoformat()
        return ctx

    async def before_llm(self, ctx):
        if not self.config.get("inject_system_time", True):
            return ctx
        now = ctx.extra.get("now")
        if now:
            ctx.messages = [{
                "role": "system",
                "content": f"{self.config.get('system_prompt_prefix', '当前本地时间')}: {now}",
            }] + ctx.messages
        return ctx


PLUGIN = TimeContextPlugin
