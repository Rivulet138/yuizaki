from __future__ import annotations

from dataclasses import asdict
from typing import Any

from modules.agent.dsh_bridge import DshBridge
from modules.agent.tool_registry import ToolDefinition
from modules.agent.tool_result import ToolResultEnvelope

from .base import AgentPlugin

_DELEGATION_PROMPT = (
    "你可以使用 ask_dsh 将复杂编码任务交给本地 DSH 代理。"
    "仅当用户明确要求编写/运行代码、跑测试、修改文件或分析代码仓库时才使用；"
    "日常闲聊、陪伴和一般问答不要调用。任务必须自包含，DSH 看不到当前对话。"
    "该工具可能真实修改文件，需要用户授权；超时或失败也可能已产生写入，"
    "不得自动重试，应先向用户报告并核实文件状态。"
)


class DshDelegatePlugin(AgentPlugin):
    id = "dsh-delegate"
    name = "DSH 编码任务委托"

    async def _handle(self, args: dict[str, Any], ctx: Any, receipt: Any, permit: Any) -> ToolResultEnvelope:
        task = args.get("task")
        context = args.get("context", "")
        if not isinstance(task, str) or not isinstance(context, str):
            return ToolResultEnvelope(
                success=False, content="", source="plugin", tool_name="ask_dsh",
                error="dsh_invalid_task", retryable=False, permission_receipt=receipt,
            )
        # Validate the task itself before appending background; it must not be
        # possible to turn an empty task into a valid one using context alone.
        if not task.strip() or task.lstrip().startswith("--") or "\0" in task:
            return ToolResultEnvelope(
                success=False, content="", source="plugin", tool_name="ask_dsh",
                error="dsh_invalid_task", retryable=False, permission_receipt=receipt,
            )
        if context.strip():
            task += "\n\n必要背景：\n" + context
        try:
            bridge = DshBridge()
        except ValueError:
            return ToolResultEnvelope(
                success=False, content="", source="plugin", tool_name="ask_dsh",
                error="dsh_invalid_config", retryable=False, permission_receipt=receipt,
            )
        result = await bridge.run(task)
        unknown_effect = result.error in {
            "dsh_timeout", "dsh_nonzero_exit", "dsh_output_too_large", "dsh_io_error",
            "dsh_empty_output",
        }
        return ToolResultEnvelope(
            success=result.ok, content=result.output, source="plugin", tool_name="ask_dsh",
            data=asdict(result), error=result.error, permission_receipt=receipt,
            outcome="unknown_effect" if unknown_effect else None,
            retryable=False,
        )

    async def _without_context(self, args: dict[str, Any]) -> ToolResultEnvelope:
        # The context-free ABI must not become an alternate approval bypass.
        return ToolResultEnvelope(
            success=False, content="", source="plugin", tool_name="ask_dsh",
            error="dsh_execution_context_required", retryable=False,
        )

    def register_tools(self) -> list[ToolDefinition]:
        return [ToolDefinition(
            name="ask_dsh",
            description="把用户明确要求的复杂编码、跑测试、改文件或仓库分析任务交给 DSH。可能修改文件，失败勿自动重试。",
            source="plugin",
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "minLength": 1, "maxLength": 4000,
                             "description": "自包含的任务描述，DSH 看不到当前对话"},
                    "context": {"type": "string", "maxLength": 4000,
                                "description": "可选：必要背景与文件路径；合并后仍须不超过4000字符"},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            handler=self._without_context,
            context_handler=self._handle,
            require_confirm=True,
            effect_kind="write",
            risk_level="high",
            tags=["delegation", "dsh"],
            scopes=["dsh:delegate"],
        )]

    async def before_llm(self, ctx: Any) -> Any:
        message = {"role": "system", "content": _DELEGATION_PROMPT}
        if message not in ctx.messages:
            ctx.messages = [message, *ctx.messages]
        return ctx


PLUGIN = DshDelegatePlugin
