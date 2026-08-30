from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable
from typing import Any, cast

from ..llm.capabilities import infer_model_capability_support
from .failure_recovery import (
    ProviderRuntimeFailure,
    classify_provider_runtime_exception,
)
from .permission_receipt import serialize_permission_receipt
from .tool_executor import ToolExecutor
from .tool_registry import ToolDefinition, ToolRegistry, tool_may_change_state
from .tool_result import is_known_success

logger = logging.getLogger(__name__)


def _outcome_succeeded(outcome: Any) -> bool:
    """Use the shared explicit effect-outcome predicate as truth."""
    return is_known_success(outcome)


def _positive_budget(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(0, value)


def _completion_tokens(result: dict[str, Any]) -> int:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return 0
    for key in ("completion_tokens", "output_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return 0


def _loop_contract(
    *,
    max_iterations: int,
    max_output_tokens: int | None,
    retry_budget: int,
    tool_budget: int,
) -> tuple[dict[str, int | None], dict[str, int | str]]:
    return (
        {
            "max_iterations": max_iterations,
            "output_tokens": max_output_tokens,
            "retry_budget": retry_budget,
            "tool_budget": tool_budget,
        },
        {
            "iterations": 0,
            "output_tokens": 0,
            "retries": 0,
            "tool_calls": 0,
            "attempts": 0,
            "stop_reason": "not_started",
        },
    )


def _with_loop_contract(
    result: dict[str, Any],
    configured_budget: dict[str, int | None],
    consumed_usage: dict[str, int | str],
    stop_reason: str,
) -> dict[str, Any]:
    result["configured_budget"] = dict(configured_budget)
    result["consumed_usage"] = {**consumed_usage, "stop_reason": stop_reason}
    result.setdefault("stopped_reason", None if stop_reason == "completed" else stop_reason)
    return result


def _cancellation_requested(cancel_event: Any, generation: Any) -> bool:
    current_task = asyncio.current_task()
    task_cancelled = bool(
        current_task is not None and current_task.cancelling()
    )
    event_cancelled = bool(
        cancel_event is not None and cancel_event.is_set()
    )
    generation_cancelled = bool(
        generation is not None
        and (
            getattr(generation, "cancel", None) is not None
            and generation.cancel.is_set()
            or bool(getattr(generation, "invalidated", False))
        )
    )
    return task_cancelled or event_cancelled or generation_cancelled


async def _wait_for_cancellation(cancel_event: Any, generation: Any) -> None:
    while not _cancellation_requested(cancel_event, generation):
        await asyncio.sleep(0.02)


async def _await_with_cancellation(
    awaitable: Awaitable[Any],
    cancel_event: Any,
    generation: Any,
) -> tuple[Any, bool]:
    task = asyncio.ensure_future(awaitable)
    if cancel_event is None and generation is None:
        return await task, False
    if _cancellation_requested(cancel_event, generation):
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return None, True
    cancellation_task = asyncio.create_task(
        _wait_for_cancellation(cancel_event, generation)
    )
    try:
        done, _pending = await asyncio.wait(
            {task, cancellation_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation_task in done and _cancellation_requested(
            cancel_event, generation
        ):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None, True
        return await task, False
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    finally:
        cancellation_task.cancel()
        await asyncio.gather(cancellation_task, return_exceptions=True)


def _cancelled_loop_result(
    tool_calls: list[dict[str, Any]],
    configured_budget: dict[str, int | None],
    consumed_usage: dict[str, int | str],
) -> dict[str, Any]:
    return _with_loop_contract(
        {
            "reply": "",
            "tool_calls": tool_calls,
            "outcome": "cancelled",
            "retryable": False,
        },
        configured_budget,
        consumed_usage,
        "cancelled",
    )


async def run_streaming_tool_loop(
    llm_client: Any,
    messages: list[dict[str, Any]],
    *,
    tool_registry: ToolRegistry,
    tool_executor: ToolExecutor,
    max_iterations: int = 3,
    cancel_event: Any = None,
    generation: Any = None,
    emit: Any = None,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Run typed tool calls through an explicitly supported stream adapter.

    Providers must opt in with ``streaming_tool_calls_supported`` and expose
    ``stream_chat_with_tools``. Unsupported clients return ``None`` so callers
    retain the established text-stream path.
    """
    adapter = getattr(llm_client, "stream_chat_with_tools", None)
    if (
        not getattr(llm_client, "streaming_tool_calls_supported", False)
        or not callable(adapter)
    ):
        return None
    bounded_iterations = _positive_budget(max_iterations, 3)
    retry_budget = _positive_budget(kwargs.get("retry_budget"), 0)
    tool_budget = _positive_budget(
        kwargs.get("tool_budget"), max(1, bounded_iterations) * 8
    )
    max_output_tokens = kwargs.get("max_output_tokens")
    configured_budget, consumed_usage = _loop_contract(
        max_iterations=bounded_iterations,
        max_output_tokens=(
            max_output_tokens
            if isinstance(max_output_tokens, int) and not isinstance(max_output_tokens, bool)
            else None
        ),
        retry_budget=retry_budget,
        tool_budget=tool_budget,
    )
    working_messages = list(messages)
    tools, model_tool_name_map = _build_openai_tools(_filtered_tool_definitions(
        llm_client,
        tool_registry,
        allowed_tool_names=kwargs.get("allowed_tool_names"),
        allowed_mcp_server_names=kwargs.get("allowed_mcp_server_names"),
        preferred_tool_names=kwargs.get("preferred_tool_names"),
        include_mcp_tools=bool(kwargs.get("include_mcp_tools", True)),
        include_web_search_tools=bool(kwargs.get("include_web_search_tools", False)),
        model=kwargs.get("model"),
    ))
    untrusted_mcp_seen = False
    tool_calls_seen: list[dict[str, Any]] = []
    state_changing_tool_succeeded = False
    for _ in range(bounded_iterations):
        if _cancellation_requested(cancel_event, generation):
            return _cancelled_loop_result(
                tool_calls_seen, configured_budget, consumed_usage
            )
        try:
            result, provider_cancelled = await _await_with_cancellation(
                cast(Awaitable[Any], adapter(working_messages, tools=tools, **kwargs)),
                cancel_event,
                generation,
            )
            if provider_cancelled:
                return _cancelled_loop_result(
                    tool_calls_seen, configured_budget, consumed_usage
                )
        except asyncio.CancelledError:
            return _cancelled_loop_result(
                tool_calls_seen, configured_budget, consumed_usage
            )
        except Exception as exc:
            provider_failure = classify_provider_runtime_exception(exc)
            if provider_failure is None:
                raise
            return _provider_runtime_failure_result(
                provider_failure,
                tool_calls=tool_calls_seen,
                state_change_may_have_occurred=state_changing_tool_succeeded,
                configured_budget=configured_budget,
                consumed_usage=consumed_usage,
            )
        consumed_usage["iterations"] = int(consumed_usage["iterations"]) + 1
        if not isinstance(result, dict):
            return _with_loop_contract(
                {"reply": "", "tool_calls": tool_calls_seen}, configured_budget,
                consumed_usage, "invalid_stream_adapter_result",
            )
        consumed_usage["output_tokens"] = (
            int(consumed_usage["output_tokens"]) + _completion_tokens(result)
        )
        reply = str(result.get("reply") or "")
        if reply and callable(emit):
            await cast(Awaitable[Any], emit(reply))
        calls = [item for item in result.get("tool_calls") or [] if isinstance(item, dict)]
        if not calls:
            result["tool_calls"] = tool_calls_seen
            return _with_loop_contract(result, configured_budget, consumed_usage, "completed")
        working_messages.append({"role": "assistant", "content": reply, "tool_calls": calls})
        for call in calls:
            if _cancellation_requested(cancel_event, generation):
                return _cancelled_loop_result(
                    tool_calls_seen, configured_budget, consumed_usage
                )
            if int(consumed_usage["tool_calls"]) >= tool_budget:
                return _with_loop_contract(
                    {"reply": "", "tool_calls": tool_calls_seen}, configured_budget,
                    consumed_usage, "tool_budget_exhausted",
                )
            function = call.get("function") or {}
            model_name = str(function.get("name") or "")
            tool_name = model_tool_name_map.get(model_name)
            if tool_name is None:
                error = "tool_not_exposed"
                tool_calls_seen.append({"tool": model_name, "success": False, "error": error})
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps({
                        "source": "policy:tool_allowlist",
                        "trust": "untrusted",
                        "instruction_authority": "none",
                        "success": False,
                        "content": error,
                    }, ensure_ascii=False),
                })
                continue
            raw_args = function.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    raw_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    raw_args = {}
            args = raw_args if isinstance(raw_args, dict) else {}
            outcome = await tool_executor.execute(
                str(tool_name),
                args,
                permission_request_cb=kwargs.get("permission_request_cb"),
                plugin_manager=kwargs.get("plugin_manager"),
                ctx=kwargs.get("ctx"),
                force_confirmation=(
                    untrusted_mcp_seen
                    and (definition := tool_registry.get(str(tool_name))) is not None
                    and _requires_untrusted_followup_confirmation(definition)
                ),
                cancellation_signal=(
                    lambda: _cancellation_requested(cancel_event, generation)
                ),
            )
            if outcome.source == "mcp":
                untrusted_mcp_seen = True
            consumed_usage["tool_calls"] = int(consumed_usage["tool_calls"]) + 1
            consumed_usage["attempts"] = int(consumed_usage["attempts"]) + 1
            record = {
                "tool": tool_name,
                "success": _outcome_succeeded(outcome),
                "outcome": outcome.outcome,
                "retryable": bool(outcome.retryable),
                "error": outcome.error,
            }
            tool_calls_seen.append(record)
            definition = tool_registry.get(str(tool_name))
            if _outcome_succeeded(outcome) and definition is not None and tool_may_change_state(definition):
                state_changing_tool_succeeded = True
            working_messages.append({
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": json.dumps({
                    "source": f"{outcome.source}:{outcome.tool_name or tool_name}",
                    "trust": "untrusted",
                    "instruction_authority": "none",
                    "success": _outcome_succeeded(outcome),
                    "outcome": outcome.outcome,
                    "content": outcome.error or outcome.content,
                }, ensure_ascii=False),
            })
            if outcome.outcome == "unknown_effect":
                return _with_loop_contract(
                    {
                        "reply": "",
                        "tool_calls": tool_calls_seen,
                        "outcome": "unknown_effect",
                        "retryable": False,
                    },
                    configured_budget, consumed_usage, "unknown_effect",
                )
            if _cancellation_requested(cancel_event, generation):
                return _cancelled_loop_result(
                    tool_calls_seen, configured_budget, consumed_usage
                )
            receipt = outcome.permission_receipt
            if receipt is not None and receipt.retryable is False:
                return _with_loop_contract(
                    {
                        "reply": "",
                        "tool_calls": tool_calls_seen,
                        "permission_receipt": receipt,
                        "outcome": "known_failure",
                        "retryable": False,
                    },
                    configured_budget, consumed_usage,
                    f"permission_{receipt.decision}",
                )
    return _with_loop_contract(
        {"reply": "", "tool_calls": tool_calls_seen}, configured_budget,
        consumed_usage, "max_iterations",
    )


_OPENAI_TOOL_NAME_MAX_LENGTH = 64
def _provider_runtime_failure_result(
    failure: ProviderRuntimeFailure,
    *,
    tool_calls: list[dict[str, Any]],
    state_change_may_have_occurred: bool,
    configured_budget: dict[str, int | None],
    consumed_usage: dict[str, int | str],
) -> dict[str, Any]:
    if state_change_may_have_occurred:
        return _with_loop_contract(
            {
                "reply": "模型连接中断；工具可能已执行，请先查看结果后再决定是否重试。",
                "tool_calls": tool_calls,
                "outcome": "unknown_effect",
                "retryable": False,
                "failure": {
                    "kind": failure.kind,
                    "message": "provider_disconnected_after_state_change",
                    "status": "unknown_effect",
                    "retryable": False,
                },
                "recovery": {
                    "available": False,
                    "action": "review_tool_result",
                    "retryable": False,
                    "confirmation_required": False,
                    "reason": "provider_disconnected_after_state_change",
                },
                "persist_history": False,
            },
            configured_budget,
            consumed_usage,
            "provider_disconnected_after_state_change",
        )
    if failure.reason == "provider_timeout":
        reply = "模型响应超时，请稍后重试。"
    elif failure.reason == "provider_request_rejected":
        reply = "模型请求未被服务接受，请检查模型配置。"
    else:
        reply = "模型服务暂时不可用，请检查连接后重试。"
    recovery_available = bool(failure.retryable)
    recovery_action = "retry_turn" if recovery_available else "check_provider_settings"
    return _with_loop_contract(
        {
            "reply": reply,
            "tool_calls": tool_calls,
            "outcome": "failed",
            "retryable": failure.retryable,
            "failure": {
                "kind": failure.kind,
                "message": failure.reason,
                "status": "failed",
                "retryable": failure.retryable,
            },
            "recovery": {
                "available": recovery_available,
                "action": recovery_action,
                "retryable": failure.retryable,
                "confirmation_required": False,
                "reason": failure.reason,
            },
            "persist_history": False,
        },
        configured_budget,
        consumed_usage,
        failure.reason,
    )


def _requires_untrusted_followup_confirmation(tool: ToolDefinition) -> bool:
    if tool.source in {"mcp", "plugin"} and not tool.require_confirm:
        return False
    return tool_may_change_state(tool)


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


def _filtered_tool_definitions(
    llm_client: Any,
    tool_registry: ToolRegistry,
    *,
    allowed_tool_names: list[str] | None = None,
    allowed_mcp_server_names: list[str] | None = None,
    preferred_tool_names: list[str] | None = None,
    include_mcp_tools: bool = True,
    include_web_search_tools: bool = False,
    model: str | None = None,
) -> list[ToolDefinition]:
    """Apply the same capability/preset filtering to every tool-loop lane."""
    definitions = tool_registry.list()
    if infer_model_capability_support(
        getattr(llm_client, "provider", None),
        model or getattr(llm_client, "model", None),
        "tools",
    ) == "unsupported":
        return []
    if allowed_tool_names is not None:
        allowed = set(allowed_tool_names)
        definitions = [tool for tool in definitions if tool.name in allowed]
    if preferred_tool_names:
        preferred = {name: index for index, name in enumerate(preferred_tool_names)}
        original = {tool.name: index for index, tool in enumerate(definitions)}
        definitions.sort(key=lambda tool: (
            0 if tool.name in preferred else 1,
            preferred.get(tool.name, original[tool.name]),
            original[tool.name],
        ))
    if not include_mcp_tools:
        definitions = [tool for tool in definitions if tool.source != "mcp"]
    elif allowed_mcp_server_names is not None:
        allowed_servers = {name.strip().lower() for name in allowed_mcp_server_names if name.strip()}
        definitions = [
            tool for tool in definitions
            if tool.source != "mcp" or _mcp_server_name(tool) in allowed_servers
        ]
    if not include_web_search_tools:
        definitions = [tool for tool in definitions if tool.name != "web_search"]
    return definitions


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
    retry_budget: int = 0,
    tool_budget: int | None = None,
) -> dict[str, Any]:
    bounded_iterations = _positive_budget(max_iterations, 3)
    bounded_retry_budget = _positive_budget(retry_budget, 0)
    bounded_tool_budget = _positive_budget(
        tool_budget, max(1, bounded_iterations) * 8
    )
    configured_budget, consumed_usage = _loop_contract(
        max_iterations=bounded_iterations,
        max_output_tokens=max_output_tokens,
        retry_budget=bounded_retry_budget,
        tool_budget=bounded_tool_budget,
    )
    working_messages = list(messages)
    tool_definitions = _filtered_tool_definitions(
        llm_client,
        tool_registry,
        allowed_tool_names=allowed_tool_names,
        allowed_mcp_server_names=allowed_mcp_server_names,
        preferred_tool_names=preferred_tool_names,
        include_mcp_tools=include_mcp_tools,
        include_web_search_tools=include_web_search_tools,
        model=model,
    )
    tools, model_tool_name_map = _build_openai_tools(tool_definitions)
    untrusted_mcp_seen = False

    for _ in range(bounded_iterations):
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
        consumed_usage["iterations"] = int(consumed_usage["iterations"]) + 1
        consumed_usage["output_tokens"] = (
            int(consumed_usage["output_tokens"]) + _completion_tokens(result)
        )

        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            return _with_loop_contract(result, configured_budget, consumed_usage, "completed")

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
            if int(consumed_usage["tool_calls"]) >= bounded_tool_budget:
                return _with_loop_contract(
                    {"reply": "", "tool_calls": [], "pet_control": None},
                    configured_budget, consumed_usage, "tool_budget_exhausted",
                )
            function_call = tool_call.get("function") or {}
            model_tool_name = str(function_call.get("name") or "")
            tool_name = model_tool_name_map.get(model_tool_name)
            if tool_name is None:
                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": json.dumps({
                        "source": "policy:tool_allowlist",
                        "trust": "untrusted",
                        "instruction_authority": "none",
                        "success": False,
                        "content": "tool_not_exposed",
                    }, ensure_ascii=False),
                })
                continue
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
            consumed_usage["tool_calls"] = int(consumed_usage["tool_calls"]) + 1
            consumed_usage["attempts"] = int(consumed_usage["attempts"]) + 1
            tool_result_content = json.dumps({
                "source": f"{outcome.source}:{outcome.tool_name or tool_name}",
                "trust": "untrusted",
                "instruction_authority": "none",
                "success": _outcome_succeeded(outcome),
                "outcome": outcome.outcome,
                "content": outcome.error or outcome.content,
            }, ensure_ascii=False)
            working_messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": tool_result_content,
            })
            if outcome.outcome == "unknown_effect":
                return _with_loop_contract(
                    {
                        "reply": "",
                        "tool_calls": [{
                            "tool": outcome.tool_name,
                            "success": False,
                            "outcome": "unknown_effect",
                            "retryable": False,
                            "error": outcome.error,
                        }],
                        "pet_control": None,
                        "outcome": "unknown_effect",
                        "retryable": False,
                    },
                    configured_budget, consumed_usage, "unknown_effect",
                )
            receipt = outcome.permission_receipt
            if receipt is not None and receipt.retryable is False:
                return _with_loop_contract({
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
                    "outcome": "known_failure",
                    "retryable": False,
                }, configured_budget, consumed_usage, f"permission_{receipt.decision}")

    return _with_loop_contract({
        "reply": "工具循环达到最大迭代次数，已停止。",
        "tool_calls": [],
        "pet_control": None,
    }, configured_budget, consumed_usage, "max_iterations")
