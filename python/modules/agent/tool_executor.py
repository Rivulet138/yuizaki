from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable

from .policy_engine import PolicyEngine
from .context import get_runtime_bindings
from ..system.relationship_policy import summarize_relationship_events
from ..system.memory_write_pipeline import build_tool_success_event
from .tool_registry import ToolRegistry
from .tool_result import ToolResultEnvelope
from .models import RuntimeLoopRecord
from .permission_receipt import build_permission_receipt
from .route_policy import memory_reflector_route


PermissionRequestCallback = Any


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine | None = None,
        outcome_observer: Callable[[bool], None] | None = None,
    ) -> None:
        self.registry = registry
        self.policy_engine = policy_engine or PolicyEngine()
        self.outcome_observer = outcome_observer

    def _finish(self, outcome: ToolResultEnvelope) -> ToolResultEnvelope:
        self._observe(bool(outcome.success))
        return outcome

    def _observe(self, success: bool) -> None:
        if self.outcome_observer is None:
            return
        try:
            self.outcome_observer(success)
        except Exception:
            pass

    def _evaluate_policy(
        self,
        tool: Any,
        *,
        request_id: str | None,
        permission_scope: str | None,
        parameters: dict[str, Any],
        force_confirm: bool,
    ) -> Any:
        evaluator = self.policy_engine.evaluate_tool
        signature = inspect.signature(evaluator)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        candidates = {
            "request_id": request_id,
            "permission_scope": permission_scope,
            "parameters": parameters,
            "force_confirm": force_confirm,
        }
        kwargs = {
            key: value
            for key, value in candidates.items()
            if accepts_kwargs or key in signature.parameters
        }
        return evaluator(tool, **kwargs)

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any],
        permission_request_cb: PermissionRequestCallback | None = None,
        plugin_manager: Any = None,
        ctx: Any = None,
        force_confirmation: bool = False,
    ) -> ToolResultEnvelope:
        tool = self.registry.get(tool_name)
        if tool is None:
            return self._finish(ToolResultEnvelope(
                success=False,
                content="",
                source="builtin",
                tool_name=tool_name,
                error=f"Unknown tool: {tool_name}",
            ))

        if plugin_manager is not None:
            args = await plugin_manager.before_tool(tool.name, args, ctx)

        request_id = getattr(ctx, 'request_id', None) if ctx is not None else None
        permission_scope = getattr(ctx, 'permission_scope', None) if ctx is not None else None
        decision = await asyncio.to_thread(
            self._evaluate_policy,
            tool,
            request_id=request_id,
            permission_scope=permission_scope,
            parameters=args,
            force_confirm=force_confirmation,
        )
        allowed_by_policy = bool(getattr(decision, "allowed", False))
        require_confirm = bool(getattr(decision, "require_confirm", False))
        decision_request_id = getattr(decision, "request_id", None)
        decision_reason = str(getattr(decision, "reason", "permission_denied"))
        receipt = getattr(decision, "permission_receipt", None)
        if receipt is None:
            synthesized_decision = "required" if require_confirm else ("allowed" if allowed_by_policy else "denied")
            receipt = build_permission_receipt(
                agent_request_id=str(request_id or f"agent_{datetime.now().timestamp():.6f}"),
                permission_request_id=decision_request_id,
                decision=synthesized_decision,
                reason_code=(
                    "legacy_policy_permission_required" if require_confirm
                    else "legacy_policy_allowed" if allowed_by_policy
                    else "legacy_policy_denied"
                ),
                retryable=allowed_by_policy and not require_confirm,
                permission_scope=str(permission_scope or "default"),
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                risk_level=tool.risk_level,
                parameters=args,
            )
        if require_confirm and not decision_request_id:
            decision_request_id = receipt.permission_request_id
        if force_confirmation and not require_confirm and allowed_by_policy:
            require_confirm = True
            allowed_by_policy = False
            decision_request_id = receipt.permission_request_id
            decision_reason = "Untrusted MCP output cannot authorize a follow-up side effect"
            receipt = replace(
                receipt,
                decision="required",
                reason_code="untrusted_mcp_followup_requires_confirmation",
                retryable=False,
            )
        redacted_args = receipt.parameters if receipt is not None else args
        if require_confirm and decision_request_id:
            if permission_request_cb is None:
                discard_permission = getattr(self.policy_engine, "discard_permission", None)
                if callable(discard_permission):
                    discard_permission(decision_request_id)
                return self._finish(ToolResultEnvelope(
                    success=False,
                    content="",
                    source=tool.source,
                    tool_name=tool.name,
                    error=decision_reason,
                    permission_receipt=replace(
                        receipt,
                        reason_code=(
                            receipt.reason_code
                            if receipt.reason_code == "untrusted_mcp_followup_requires_confirmation"
                            else "interactive_permission_unavailable"
                        ),
                    ) if receipt is not None else None,
                ))

            future = self.policy_engine.register_pending(decision_request_id)
            await permission_request_cb(
                request_id=decision_request_id,
                tool_name=tool.name,
                capability_id=tool.name,
                capability_type="tool",
                capability_kind=f"{tool.source}-tool",
                permission_scope=permission_scope,
                risk_level=tool.risk_level,
                reason=decision_reason,
                args=redacted_args,
            )
            allowed = await future
            if not allowed:
                return self._finish(ToolResultEnvelope(
                    success=False,
                    content="",
                    source=tool.source,
                    tool_name=tool.name,
                    error=f"Tool '{tool.name}' was denied by user",
                    permission_receipt=replace(
                        receipt,
                        decision="denied",
                        reason_code="user_denied",
                        retryable=False,
                        decided_at=datetime.now().isoformat(),
                    ) if receipt is not None else None,
                ))
            receipt = replace(
                receipt,
                decision="allowed",
                reason_code="user_allowed",
                retryable=True,
                decided_at=datetime.now().isoformat(),
            ) if receipt is not None else None

        if not allowed_by_policy and not (require_confirm and receipt and receipt.decision == "allowed"):
            return self._finish(ToolResultEnvelope(
                success=False,
                content="",
                source=tool.source,
                tool_name=tool.name,
                error=decision_reason,
                permission_receipt=receipt,
            ))

        if ctx is not None and getattr(ctx, 'trace_store', None) is not None:
            ctx.trace_store.append(
                "runtime_loop",
                RuntimeLoopRecord(
                    timestamp=datetime.now().isoformat(),
                    session_id=getattr(ctx, 'session_id', ''),
                    request_id=getattr(ctx, 'request_id', None),
                    stage="ask_act",
                    status="ok",
                    summary=f"Executing capability '{tool.name}'.",
                    agent_id="yuizaki.task-router",
                    agent_role="router",
                    data={
                        "tool_name": tool.name,
                        "capability_id": tool.name,
                        "capability_type": "tool",
                        "capability_kind": f"{tool.source}-tool",
                        "risk_level": tool.risk_level,
                        "requires_approval": tool.require_confirm,
                        "source": tool.source,
                    },
                ).to_dict(),
            )

        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(args)
            else:
                result = await asyncio.to_thread(tool.handler, args)
                if inspect.isawaitable(result):
                    result = await result
            if plugin_manager is not None:
                result = await plugin_manager.after_tool(result, tool.name, args, ctx)
        except Exception:
            self._observe(False)
            raise
        result.permission_receipt = receipt
        bindings = get_runtime_bindings(ctx) if ctx is not None else None
        relationship_writer = bindings.relationship_event_writer if bindings is not None else None
        if relationship_writer is None and ctx is not None:
            relationship_writer = getattr(ctx, 'extra', {}).get('relationship_event_writer')
        if relationship_writer and getattr(result, 'success', False):
            try:
                relationship_history = bindings.relationship_history if bindings is not None else None
                if relationship_history is None and ctx is not None:
                    relationship_history = getattr(ctx, 'extra', {}).get('relationship_history')
                db_repo = bindings.db_repo if bindings is not None else None
                if db_repo is None and ctx is not None:
                    db_repo = getattr(ctx, 'extra', {}).get('db_repo')
                summary = summarize_relationship_events(relationship_history or []) if isinstance(relationship_history, list) else {}
                relationship_stage = str(summary.get('relationship_stage') or 'warming')
                milestone_salience = str(summary.get('milestone_salience') or 'low')
                proactive_budget = float(summary.get('proactive_budget') or 0.9)
                support_style = None
                if db_repo is not None and ctx is not None and getattr(ctx, 'workspace_id', None):
                    companion = await asyncio.to_thread(db_repo.get_workspace_companion, getattr(ctx, 'workspace_id'))
                    if companion:
                        support_style = companion.get('support_style')
                text = f"結崎通过工具 {tool.name} 成功完成了一次帮助。"
                importance = 0.88
                if relationship_stage == 'close':
                    text = f"結崎更主动地通过工具 {tool.name} 帮你完成了一次事情。"
                    importance = 0.93
                elif support_style == 'analytical':
                    text = f"結崎通过工具 {tool.name} 为你完成了一次结构化帮助。"
                elif support_style == 'cheerful':
                    text = f"結崎带着更积极的推进感，通过工具 {tool.name} 帮你完成了一次事情。"
                elif support_style == 'gentle':
                    text = f"結崎以更温和的方式，通过工具 {tool.name} 帮你完成了一次事情。"
                if milestone_salience == 'high':
                    text = f"这次工具协助很可能会成为你们关系中的一个关键节点。{text}"
                    importance = max(importance, 0.94)
                elif proactive_budget >= 1.2:
                    text = f"在当前更主动的关系节奏下，{text}"
                reflector_route = memory_reflector_route()
                await asyncio.to_thread(
                    relationship_writer,
                    build_tool_success_event(
                        tool_name=tool.name,
                        args=redacted_args,
                        text=text,
                        importance=importance,
                        owner_agent_id=reflector_route.owner_agent_id,
                        owner_agent_role=reflector_route.owner_agent_role,
                    ),
                )
                if ctx is not None and getattr(ctx, 'trace_store', None) is not None:
                    ctx.trace_store.append(
                        "runtime_loop",
                        RuntimeLoopRecord(
                            timestamp=datetime.now().isoformat(),
                            session_id=getattr(ctx, 'session_id', ''),
                            request_id=getattr(ctx, 'request_id', None),
                            stage="update_relationship",
                            status="ok",
                            summary=f"Updated relationship signal after capability '{tool.name}' succeeded.",
                            agent_id=reflector_route.owner_agent_id,
                            agent_role=reflector_route.owner_agent_role,
                            data={
                                "tool_name": tool.name,
                                "importance": importance,
                                "relationship_stage": relationship_stage,
                            },
                        ).to_dict(),
                    )
            except Exception:
                pass
        return self._finish(result)
