from __future__ import annotations

import json
import hashlib
import logging
import re
from typing import Any

from .tool_executor import ToolExecutor
from .tool_registry import ToolDefinition, ToolRegistry
from .permission_receipt import serialize_permission_receipt
from ..llm.capabilities import infer_model_capability_support

logger = logging.getLogger(__name__)


_OPENAI_TOOL_NAME_MAX_LENGTH = 64
_SIDE_EFFECT_TOOL_MARKERS = (
    "create", "delete", "execute", "install", "launch", "open", "post", "remove",
    "run", "send", "set", "update", "upload", "write",
)


def _requires_untrusted_followup_confirmation(tool: ToolDefinition) -> bool:
    normalized_name = re.sub(r"[^a-z0-9]+", "_", tool.name.lower())
    return bool(
        tool.risk_level != "safe"
        or tool.require_confirm
        or any(marker in normalized_name.split("_") for marker in _SIDE_EFFECT_TOOL_MARKERS)
    )


def _openai_safe_tool_name(name: str, used_names: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "")).strip("_-")
    if not base:
        base = "tool"
    if len(base) > _OPENAI_TOOL_NAME_MAX_LENGTH:
        base = base[:_OPENAI_TOOL_NAME_MAX_LENGTH].rstrip("_-") or "tool"

    candidate = base
    if candidate not in used_names:
        return candidate

    digest = hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:8]
    prefix_len = _OPENAI_TOOL_NAME_MAX_LENGTH - len(digest) - 1
    prefix = base[:prefix_len].rstrip("_-") or "tool"
    candidate = f"{prefix}_{digest}"
    counter = 2
    while candidate in used_names:
        suffix = f"_{counter}"
        prefix_len = _OPENAI_TOOL_NAME_MAX_LENGTH - len(digest) - len(suffix) - 1
        prefix = base[:prefix_len].rstrip("_-") or "tool"
        candidate = f"{prefix}_{digest}{suffix}"
        counter += 1
    return candidate


def _build_openai_tools(tool_definitions: list[ToolDefinition]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    used_names: set[str] = set()
    model_to_registry_name: dict[str, str] = {}
    tools: list[dict[str, Any]] = []
    for tool in tool_definitions:
        model_name = _openai_safe_tool_name(tool.name, used_names)
        used_names.add(model_name)
        model_to_registry_name[model_name] = tool.name
        tools.append({
            "type": "function",
            "function": {
                "name": model_name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        })
    return tools, model_to_registry_name


def _mcp_server_name(tool: ToolDefinition) -> str | None:
    for tag in tool.tags or []:
        if tag.startswith("mcp-server:"):
            return tag.split(":", 1)[1].strip().lower() or None
    for scope in tool.scopes or []:
        if scope.startswith("mcp:"):
            return scope.split(":", 2)[1].strip().lower() or None
    return None


async def run_tool_loop(
    llm_client: Any,
    messages: list[dict[str, Any]],
    *,
    tool_registry: ToolRegistry,
    tool_executor: ToolExecutor,
    pet_control_context: dict[str, Any] | None = None,
    max_iterations: int = 3,
    max_output_tokens: int | None = None,
    permission_request_cb: Any = None,
    plugin_manager: Any = None,
    ctx: Any = None,
    allowed_tool_names: list[str] | None = None,
    allowed_mcp_server_names: list[str] | None = None,
    preferred_tool_names: list[str] | None = None,
    include_mcp_tools: bool = True,
    include_web_search_tools: bool = False,
    model: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    min_p: float | None = None,
    frequency_penalty: float | None = None,
    presence_penalty: float | None = None,
    repetition_penalty: float | None = None,
    reasoning_effort: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    working_messages = list(messages)
    tool_definitions = tool_registry.list()
    tool_support = infer_model_capability_support(
        getattr(llm_client, "provider", None),
        model or getattr(llm_client, "model", None),
        "tools",
    )
    if tool_support == "unsupported":
        tool_definitions = []
    if allowed_tool_names is not None:
        allowed_set = set(allowed_tool_names)
        tool_definitions = [tool for tool in tool_definitions if tool.name in allowed_set]
    if preferred_tool_names:
        preferred_order = {name: index for index, name in enumerate(preferred_tool_names)}
        original_order = {tool.name: index for index, tool in enumerate(tool_definitions)}
        tool_definitions.sort(key=lambda tool: (
            0 if tool.name in preferred_order else 1,
            preferred_order.get(tool.name, original_order[tool.name]),
            original_order[tool.name],
        ))
    if not include_mcp_tools:
        tool_definitions = [tool for tool in tool_definitions if tool.source != "mcp"]
    elif allowed_mcp_server_names is not None:
        allowed_mcp_servers = {name.strip().lower() for name in allowed_mcp_server_names if name.strip()}
        tool_definitions = [
            tool
            for tool in tool_definitions
            if tool.source != "mcp" or _mcp_server_name(tool) in allowed_mcp_servers
        ]
    if not include_web_search_tools:
        tool_definitions = [tool for tool in tool_definitions if tool.name != "web_search"]
    tools, model_tool_name_map = _build_openai_tools(tool_definitions)
    untrusted_mcp_seen = False

    for _ in range(max_iterations):
        result = await llm_client.complete_chat(
            working_messages,
            max_output_tokens=max_output_tokens,
            pet_control_context=pet_control_context,
            tools=tools,
            model=model,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            min_p=min_p,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            repetition_penalty=repetition_penalty,
            reasoning_effort=reasoning_effort,
            thinking=thinking,
        )

        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            return result

        assistant_message = {
            "role": "assistant",
            "content": result.get("reply") or "",
            "tool_calls": tool_calls,
        }
        reasoning_content = result.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            assistant_message["reasoning_content"] = reasoning_content
        working_messages.append(assistant_message)

        for tool_call in tool_calls:
            function_call = tool_call.get("function") or {}
            model_tool_name = str(function_call.get("name") or "")
            tool_name = model_tool_name_map.get(model_tool_name, model_tool_name)
            raw_arguments = function_call.get("arguments") or "{}"
            try:
                args = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                logger.warning("[tool_loop] failed to parse args for %s: %s", tool_name, exc)
                args = {}

            outcome = await tool_executor.execute(
                str(tool_name),
                args,
                permission_request_cb=permission_request_cb,
                plugin_manager=plugin_manager,
                ctx=ctx,
                force_confirmation=(
                    untrusted_mcp_seen
                    and (definition := tool_registry.get(str(tool_name))) is not None
                    and _requires_untrusted_followup_confirmation(definition)
                ),
            )
            if outcome.source == "mcp":
                untrusted_mcp_seen = True
            tool_result_content = json.dumps({
                "source": f"{outcome.source}:{outcome.tool_name or tool_name}",
                "trust": "untrusted",
                "instruction_authority": "none",
                "success": bool(outcome.success),
                "content": outcome.error or outcome.content,
            }, ensure_ascii=False)
            working_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": tool_result_content,
            })
            receipt = outcome.permission_receipt
            if receipt is not None and receipt.retryable is False:
                return {
                    "reply": "",
                    "tool_calls": [{
                        "tool": outcome.tool_name,
                        "success": False,
                        "error": outcome.error,
                        "permission_receipt": serialize_permission_receipt(receipt),
                    }],
                    "pet_control": None,
                    "permission_receipt": receipt,
                    "stopped_reason": f"permission_{receipt.decision}",
                }

    return {
        "reply": "工具循环达到最大迭代次数，已停止。",
        "tool_calls": [],
        "pet_control": None,
    }
