from __future__ import annotations

import asyncio
import inspect
import re
import time
import uuid
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
from .companion_events import CompanionJobEventLog, CompanionJobCapacityError


PermissionRequestCallback = Any
_RESULT_SUMMARY_LIMIT = 360


def _bounded_result_summary(content: Any) -> str:
    """Keep the user-visible job result useful without copying tool output into the event log."""
    text = str(content or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= _RESULT_SUMMARY_LIMIT:
        return text
    return f"{text[:_RESULT_SUMMARY_LIMIT - 3].rstrip()}..."


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine | None = None,
        outcome_observer: Callable[[bool], None] | None = None,
        job_event_log: CompanionJobEventLog | None = None,
    ) -> None:
        self.registry = registry
        self.policy_engine = policy_engine or PolicyEngine()
        self.outcome_observer = outcome_observer
        self.job_event_log = job_event_log

    @staticmethod
    def _cancelled(signal: Any) -> bool:
        if signal is None:
            return False
        try:
            return bool(signal.is_set()) if hasattr(signal, "is_set") else bool(signal()) if callable(signal) else bool(signal)
        except Exception:
            # A broken cancellation signal must fail closed.
            return True

    def _job_event(
        self,
        *,
        ctx: Any,
        status: str,
        job_id: str,
        run_id: str,
        request_id: str,
        source: str,
        tool_name: str,
        progress: float | None = None,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> bool:
        log = self.job_event_log
        if log is None and ctx is not None:
            log = getattr(ctx, "extra", {}).get("job_event_log")
        if log is None:
            return True
        event_data: dict[str, Any] = {"toolName": tool_name, **(data or {})}
        if progress is not None:
            event_data["progress"] = max(0.0, min(1.0, float(progress)))
        if error:
            event_data["error"] = error
        try:
            log.append(
                workspace_id=str(getattr(ctx, "workspace_id", None) or getattr(ctx, "extra", {}).get("active_workspace_id", "default")),
                session_id=str(getattr(ctx, "session_id", None) or "tool"),
                turn_id=str(getattr(ctx, "extra", {}).get("turn_id") or f"turn:{request_id}"),
                job_id=job_id, run_id=run_id, request_id=request_id,
                interruption_epoch=int(getattr(ctx, "extra", {}).get("interruption_epoch", 0) or 0),
                source=source, timestamp=time.time(), status=status, data=event_data,
            )
        except CompanionJobCapacityError:
            return False
        return True

    @classmethod
    async def _wait_for_cancellation(cls, signal: Any) -> None:
        if isinstance(signal, asyncio.Event):
            await signal.wait()
            return
        while not cls._cancelled(signal):
            await asyncio.sleep(0.02)

    @classmethod
    async def _await_with_cancellation(cls, awaitable: Any, signal: Any) -> tuple[Any, bool]:
        task = asyncio.ensure_future(awaitable)
        if signal is None:
            return await task, False
        if cls._cancelled(signal):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None, True

        cancellation_task = asyncio.create_task(cls._wait_for_cancellation(signal))
        try:
            done, _ = await asyncio.wait(
                {task, cancellation_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task in done and cls._cancelled(signal):
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
        request_id: str | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        source: str | None = None,
        cancellation_signal: Any = None,
        retry: bool = False,
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

        request_id = str(
            request_id
            or (getattr(ctx, 'request_id', None) if ctx is not None else None)
            or f"req:{uuid.uuid4().hex}"
        )
        extra = getattr(ctx, "extra", {}) if ctx is not None else {}
        cancellation_signal = cancellation_signal or extra.get("cancellation_signal") or extra.get("cancel_event")
        if cancellation_signal is None and ctx is not None:
            generation_mgr = getattr(ctx, "generation_mgr", None)
            get_generation = getattr(generation_mgr, "get", None)
            generation = get_generation(getattr(ctx, "session_id", "")) if callable(get_generation) else None
            cancellation_signal = getattr(generation, "cancel", None)
        retry_of_run_id = str(run_id or extra.get("run_id") or "") or None
        retry_of_job_id = str(job_id or extra.get("job_id") or "") or None
        run_id = retry_of_run_id or f"run:{uuid.uuid4().hex}"
        job_id = retry_of_job_id or f"job:{uuid.uuid4().hex}"
        if retry:
            run_id = f"{run_id}:retry:{uuid.uuid4().hex[:8]}"
            job_id = f"job:{uuid.uuid4().hex}"
        permission_scope = getattr(ctx, 'permission_scope', None) if ctx is not None else None
        event_source = str(getattr(tool, "source", None) or "builtin")
        job_data: dict[str, Any] = {"toolSource": event_source}
        if source:
            job_data["invocationSource"] = source
        if retry:
            job_data["retry"] = True
            if retry_of_job_id:
                job_data["retryOfJobId"] = retry_of_job_id
            if retry_of_run_id:
                job_data["retryOfRunId"] = retry_of_run_id
        if not self._job_event(
            ctx=ctx,
            status="created",
            job_id=job_id,
            run_id=run_id,
            request_id=request_id,
            source=event_source,
            tool_name=tool_name,
            data=job_data,
        ):
            return self._finish(ToolResultEnvelope(
                success=False,
                content="",
                source=tool.source,
                tool_name=tool_name,
                error="Tool execution rejected: companion job capacity exceeded",
                data={"code": "TOOL_JOB_CAPACITY_EXCEEDED"},
            ))
        if self._cancelled(cancellation_signal):
            self._job_event(
                ctx=ctx,
                status="cancelled",
                job_id=job_id,
                run_id=run_id,
                request_id=request_id,
                source=event_source,
                tool_name=tool_name,
                error="cancelled",
                data=job_data,
            )
            return self._finish(ToolResultEnvelope(
                success=False,
                content="",
                source=tool.source,
                tool_name=tool_name,
                error="Tool execution cancelled",
            ))

        try:
            if plugin_manager is not None:
                args = await plugin_manager.before_tool(tool.name, args, ctx)
            decision = await asyncio.to_thread(
                self._evaluate_policy,
                tool,
                request_id=request_id,
                permission_scope=permission_scope,
                parameters=args,
                force_confirm=force_confirmation,
            )
        except asyncio.CancelledError:
            self._job_event(
                ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                error="cancelled", data=job_data,
            )
            self._observe(False)
            raise
        except Exception as exc:
            self._job_event(
                ctx=ctx, status="failed", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                error=str(exc), data=job_data,
            )
            self._observe(False)
            raise
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
                self._job_event(
                    ctx=ctx, status="failed", job_id=job_id, run_id=run_id,
                    request_id=request_id, source=event_source, tool_name=tool_name,
                    error=decision_reason, data={**job_data, "args": redacted_args, "retryable": False},
                )
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
            try:
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
            except asyncio.CancelledError:
                self.policy_engine.resolve_pending(
                    decision_request_id, False, False, tool.name, permission_scope,
                )
                self._job_event(
                    ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                    request_id=request_id, source=event_source, tool_name=tool_name,
                    error="cancelled", data={**job_data, "args": redacted_args, "retryable": True},
                )
                self._observe(False)
                raise
            except Exception as exc:
                self.policy_engine.resolve_pending(
                    decision_request_id, False, False, tool.name, permission_scope,
                )
                self._job_event(
                    ctx=ctx, status="failed", job_id=job_id, run_id=run_id,
                    request_id=request_id, source=event_source, tool_name=tool_name,
                    error=str(exc), data={**job_data, "args": redacted_args, "retryable": True},
                )
                self._observe(False)
                raise
            allowed, cancelled = await self._await_with_cancellation(future, cancellation_signal)
            if cancelled:
                self.policy_engine.resolve_pending(
                    decision_request_id,
                    False,
                    False,
                    tool.name,
                    permission_scope,
                )
                self._job_event(
                    ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                    request_id=request_id, source=event_source, tool_name=tool_name,
                    error="cancelled", data={**job_data, "args": redacted_args, "retryable": True},
                )
                return self._finish(ToolResultEnvelope(
                    success=False,
                    content="",
                    source=tool.source,
                    tool_name=tool.name,
                    error="Tool execution cancelled",
                    permission_receipt=receipt,
                ))
            if not allowed:
                self._job_event(
                    ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                    request_id=request_id, source=event_source, tool_name=tool_name,
                    error="permission_denied", data={**job_data, "args": redacted_args, "retryable": False},
                )
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
            self._job_event(
                ctx=ctx, status="failed", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                error=decision_reason, data={**job_data, "args": redacted_args, "retryable": False},
            )
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

        terminal_data = {
            **job_data,
            "args": redacted_args,
            "retryable": not bool(getattr(receipt, "redacted_paths", [])),
        }
        started_at = time.perf_counter()
        self._job_event(
            ctx=ctx,
            status="running",
            job_id=job_id,
            run_id=run_id,
            request_id=request_id,
            source=event_source,
            tool_name=tool_name,
            data=job_data,
        )

        async def _run_tool() -> Any:
            if inspect.iscoroutinefunction(tool.handler):
                tool_result = await tool.handler(args)
            else:
                tool_result = await asyncio.to_thread(tool.handler, args)
                if inspect.isawaitable(tool_result):
                    tool_result = await tool_result
            if plugin_manager is not None:
                tool_result = await plugin_manager.after_tool(tool_result, tool.name, args, ctx)
            return tool_result

        try:
            # asyncio cannot stop a synchronous function already running in a
            # worker thread. Await it to a real terminal state before reporting
            # cancellation, so the job never claims a side effect stopped while
            # it is still executing.
            if not inspect.iscoroutinefunction(tool.handler):
                result = await _run_tool()
                cancelled = self._cancelled(cancellation_signal)
            else:
                result, cancelled = await self._await_with_cancellation(_run_tool(), cancellation_signal)
        except asyncio.CancelledError:
            terminal_data = {**terminal_data, "durationMs": round((time.perf_counter() - started_at) * 1000)}
            self._job_event(
                ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                error="cancelled", data=terminal_data,
            )
            self._observe(False)
            raise
        except Exception as exc:
            terminal_data = {**terminal_data, "durationMs": round((time.perf_counter() - started_at) * 1000)}
            self._job_event(
                ctx=ctx, status="failed", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                error=str(exc), data=terminal_data,
            )
            self._observe(False)
            raise
        if cancelled:
            terminal_data = {**terminal_data, "durationMs": round((time.perf_counter() - started_at) * 1000), "cancellationReason": "cancelled"}
            self._job_event(
                ctx=ctx, status="cancelled", job_id=job_id, run_id=run_id,
                request_id=request_id, source=event_source, tool_name=tool_name,
                progress=1.0, error="cancelled", data=terminal_data,
            )
            return self._finish(ToolResultEnvelope(
                success=False,
                content="",
                source=tool.source,
                tool_name=tool_name,
                error="Tool execution cancelled",
                permission_receipt=receipt,
            ))
        result_summary = _bounded_result_summary(getattr(result, "content", ""))
        terminal_data = {
            **terminal_data,
            "durationMs": round((time.perf_counter() - started_at) * 1000),
            "artifactCount": len(getattr(result, "artifacts", []) or []),
            **({"resultSummary": result_summary} if result_summary else {}),
        }
        self._job_event(
            ctx=ctx,
            status="completed" if result.success else "failed",
            job_id=job_id,
            run_id=run_id,
            request_id=request_id,
            source=event_source,
            tool_name=tool_name,
            progress=1.0,
            error=str(result.error) if not result.success else None,
            data=terminal_data,
        )
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
