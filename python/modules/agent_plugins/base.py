from __future__ import annotations

from typing import Any


class AgentPlugin:
    id = "base"
    name = "Base Agent Plugin"
    version = "0.1.0"

    def __init__(self) -> None:
        self.config: dict[str, Any] = self.default_config()
        self._proactive_dispatcher: Any | None = None

    async def initialize(self, ctx: dict[str, Any]) -> None:
        self._proactive_dispatcher = ctx.get("proactive_dispatch")
        return None

    async def terminate(self) -> None:
        return None

    def register_tools(self) -> list[Any]:
        return []

    async def before_pipeline(self, ctx: Any) -> Any:
        return ctx

    async def before_llm(self, ctx: Any) -> Any:
        return ctx

    async def after_llm(self, result: Any, ctx: Any) -> Any:
        return result

    async def before_tool(self, tool_name: str, args: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
        return args

    async def after_tool(self, result: Any, tool_name: str, args: dict[str, Any], ctx: Any = None) -> Any:
        return result

    async def before_dispatch(self, result: Any, ctx: Any) -> Any:
        return result

    def default_config(self) -> dict[str, Any]:
        return {}

    def get_config_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def on_config_updated(self, config: dict[str, Any]) -> dict[str, Any] | None:
        self.config = config
        return self.config

    async def dispatch_proactive_message(
        self,
        *,
        message: str,
        session_id: str = "plugin-proactive",
        sid: str | None = None,
        pet_control_context: dict[str, Any] | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if not self._proactive_dispatcher:
            raise RuntimeError("proactive dispatcher not initialized")
        return await self._proactive_dispatcher(
            plugin_id=self.id,
            message=message,
            session_id=session_id,
            sid=sid,
            pet_control_context=pet_control_context,
            source=source,
            metadata=metadata,
        )
