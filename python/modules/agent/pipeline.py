from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import logging
import re
import time
from datetime import datetime
from typing import Any

from .action_compiler import compile_action_envelope
from .context import AgentPipelineResult, AgentRequestContext, get_runtime_bindings, bind_runtime_bindings
from .interpret import interpret_user_text
from .models import PlannerStepRecord, PlannerTrace, RuntimeLoopRecord, StepConditionRecord
from .planner import Planner, StepCondition
from .prompt_assembly import PromptBlock, build_prompt_assembly
from .route_policy import resolve_route_from_intent
from ..core.state import Generation
from ..llm.context_window import message_content_to_text
from ..memory.pipeline import RetrievalPipeline
from ..memory.schema import RetrievalRequest
from ..pet_control import filter_pet_control_payload

logger = logging.getLogger(__name__)

_SPECULATIVE_CONTEXT_TTL_SECONDS = 8.0
_SPECULATIVE_CONTEXT_MAX_ENTRIES = 32
_VISUAL_QUERY_PHRASES = (
    "你看到",
    "看一下这个",
    "看看这个",
    "what do you see",
    "look at this",
)
_CHINESE_VISUAL_REQUEST = re.compile(
    r"(?:(?:请|帮我|你能)?(?:看|看看|看一下|查看|检查|识别|读取|分析|描述)"
    r".{0,12}(?:屏幕|画面|窗口|桌面|显示器|截图|这个页面))|"
    r"(?:(?:屏幕|画面|窗口|桌面|显示器|截图|页面)(?:上|里|中|现在)"
    r".{0,10}(?:有什么|是什么|显示什么|怎么了))"
)
_ENGLISH_VISUAL_REQUEST = re.compile(
    r"\b(?:(?:look at|check|inspect|read|analy[sz]e|describe)"
    r".{0,48}(?:screen|desktop|window|screenshot|page)|"
    r"(?:can|could) you see.{0,32}(?:screen|desktop|window|screenshot|page)|"
    r"what changed.{0,24}(?:screen|desktop|window|screenshot|page)|"
    r"(?:what(?:'s| is)|tell me what(?:'s| is))\s+(?:currently\s+)?on\s+"
    r"(?:my|the|this)\s+(?:screen|desktop|window|screenshot|page))\b"
)


def _normalize_query(value: str) -> str:
    return " ".join((value or "").lower().split())


def _query_matches_partial(
    partial_query: str,
    final_query: str,
    *,
    min_coverage: float = 0.55,
) -> bool:
    partial = _normalize_query(partial_query)
    final = _normalize_query(final_query)
    if not partial or not final:
        return False
    coverage = len(partial) / max(1, len(final))
    similarity = SequenceMatcher(None, partial, final).ratio()
    return coverage >= min_coverage and (final.startswith(partial) or similarity >= 0.82)


def _visual_context_requested(query: str) -> bool:
    normalized = _normalize_query(query)
    return bool(
        any(phrase in normalized for phrase in _VISUAL_QUERY_PHRASES)
        or _CHINESE_VISUAL_REQUEST.search(normalized)
        or _ENGLISH_VISUAL_REQUEST.search(normalized)
    )


def visual_context_requested(query: str) -> bool:
    return _visual_context_requested(query)


def _coerce_pet_control(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _coerce_tool_calls(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _coerce_step_results(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _coerce_execution_summary(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _planner_condition_record(condition: StepCondition | None) -> StepConditionRecord | None:
    if condition is None:
        return None
    return StepConditionRecord(
        source_step_id=condition.source_step_id,
        mode=condition.mode,
        status_in=list(condition.status_in),
        status_not_in=list(condition.status_not_in),
        content_contains=list(condition.content_contains),
        error_contains=list(condition.error_contains),
        all_of=[record for item in condition.all_of if (record := _planner_condition_record(item)) is not None],
        any_of=[record for item in condition.any_of if (record := _planner_condition_record(item)) is not None],
        none_of=[record for item in condition.none_of if (record := _planner_condition_record(item)) is not None],
    )


def _execution_did_not_complete(summary: dict[str, Any] | None, step_results: list[dict[str, Any]]) -> bool:
    if summary is not None:
        return str(summary.get("status") or "") in {"partial", "failed"}
    return any(
        item.get("status") == "error"
        or (item.get("status") == "skipped" and item.get("error") != "condition_not_met")
        for item in step_results
    )


def _execution_trace_payload(
    step_results: list[dict[str, Any]],
    execution_summary: dict[str, Any] | None,
    execution_policy: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not step_results and execution_summary is None and not extra:
        return []
    payload: dict[str, Any] = dict(extra or {})
    payload["step_results"] = step_results
    if execution_summary is not None:
        payload["execution_summary"] = execution_summary
    payload["execution_policy"] = execution_policy
    return [payload]


def _requires_structured_immediate_execution(steps: list[Any]) -> bool:
    return any(
        getattr(step, "kind", "") in {"tool", "join"} or getattr(step, "condition", None) is not None
        for step in steps
    ) or len(steps) > 1


def _force_agent_tool_loop(ctx: AgentRequestContext, plan: Any) -> None:
    if not ctx.web_search_enabled:
        return
    if not getattr(plan, "immediate_steps", None):
        return
    for step in plan.immediate_steps:
        if getattr(step, "kind", "") == "agent":
            ctx.extra["force_tool_loop"] = True
            return


class AgentPipeline:

    @staticmethod
    def _silent_result(ctx: AgentRequestContext) -> AgentPipelineResult:
        execution_summary = {
            "status": "stopped",
            "total_steps": 0,
            "completed_steps": 0,
            "failed_steps": 0,
            "skipped_steps": 0,
            "pending_steps": [],
            "stopped_reason": "silent_autonomy_mode",
        }
        return AgentPipelineResult(
            reply="",
            pet_control=None,
            tool_calls=[],
            action_envelope=compile_action_envelope(
                reply="",
                pet_control=None,
                tool_calls=_execution_trace_payload(
                    [], execution_summary, {"stop_on_failure": True, "tool_retry_limit": 0}
                ),
                source="agent",
                request_id=ctx.request_id,
            ),
        )
    def __init__(self, retrieval_pipeline: RetrievalPipeline | None = None) -> None:
        self.planner = Planner()
        self.retrieval_pipeline = retrieval_pipeline
        self._retrieval_prefetch_tasks: dict[str, asyncio.Task[None]] = {}
        self._retrieval_prefetch_cache: dict[str, dict[str, Any]] = {}
        self._speculative_context_cache: dict[str, dict[str, Any]] = {}

    def bind_retrieval_pipeline(self, retrieval_pipeline: RetrievalPipeline) -> None:
        self.retrieval_pipeline = retrieval_pipeline

    @staticmethod
    def _rank_tool_names(tool_registry: Any, query: str) -> list[str]:
        rank_candidates = getattr(tool_registry, "rank_candidates", None)
        if not callable(rank_candidates):
            return []
        try:
            ranked = rank_candidates(query, limit=8)
            if not isinstance(ranked, list):
                return []
            return [str(tool.name) for tool in ranked if getattr(tool, "name", None)]
        except Exception as exc:
            logger.debug("Tool candidate prefetch failed: %s", exc)
            return []

    def schedule_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        query: str,
        workspace_id: str | None,
        tool_registry: Any,
        visual_frame_id: str | None,
    ) -> bool:
        clean_query = " ".join((query or "").split())
        if not cache_key or len(clean_query) < 2:
            return False
        self._speculative_context_cache[cache_key] = {
            "partial_query": clean_query,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "tool_candidates": self._rank_tool_names(tool_registry, clean_query),
            "visual_requested": _visual_context_requested(clean_query),
            "visual_frame_id": visual_frame_id,
            "confirmed": False,
        }
        while len(self._speculative_context_cache) > _SPECULATIVE_CONTEXT_MAX_ENTRIES:
            self._speculative_context_cache.pop(next(iter(self._speculative_context_cache)))
        return True

    def confirm_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
        tool_registry: Any,
    ) -> bool:
        clean_final = " ".join((final_query or "").split())
        if not cache_key or not clean_final:
            self._speculative_context_cache.pop(cache_key, None)
            return False

        cached = self._speculative_context_cache.get(cache_key)
        cached_is_fresh = bool(
            cached
            and cached.get("workspace_id") == workspace_id
            and time.monotonic() - float(cached.get("recorded_at") or 0) <= _SPECULATIVE_CONTEXT_TTL_SECONDS
        )
        partial_matches = bool(
            cached_is_fresh
            and cached
            and _query_matches_partial(
                str(cached.get("partial_query") or ""),
                clean_final,
                min_coverage=0.3,
            )
        )
        prefetched_candidates = list(cached.get("tool_candidates") or []) if partial_matches and cached else []
        final_candidates = self._rank_tool_names(tool_registry, clean_final)
        merged_candidates = [name for name in prefetched_candidates if name in final_candidates]
        merged_candidates.extend(name for name in final_candidates if name not in merged_candidates)
        self._speculative_context_cache[cache_key] = {
            "partial_query": str(cached.get("partial_query") or "") if cached else "",
            "final_query": clean_final,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "tool_candidates": merged_candidates[:8],
            "visual_requested": _visual_context_requested(clean_final),
            "visual_frame_id": cached.get("visual_frame_id") if partial_matches and cached else None,
            "partial_match": partial_matches,
            "confirmed": True,
            "voice": True,
        }
        return True

    def take_speculative_context_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
    ) -> dict[str, Any] | None:
        cached = self._speculative_context_cache.pop(cache_key, None)
        if not cached or cached.get("workspace_id") != workspace_id or cached.get("confirmed") is not True:
            return None
        if time.monotonic() - float(cached.get("recorded_at") or 0) > _SPECULATIVE_CONTEXT_TTL_SECONDS:
            return None
        if _normalize_query(str(cached.get("final_query") or "")) != _normalize_query(final_query):
            return None
        return dict(cached)

    def cancel_speculative_context_prefetch(self, cache_key: str) -> None:
        self._speculative_context_cache.pop(cache_key, None)

    def speculative_visual_requested(self, cache_key: str) -> bool:
        cached = self._speculative_context_cache.get(cache_key)
        if not cached or cached.get("visual_requested") is not True:
            return False
        if time.monotonic() - float(cached.get("recorded_at") or 0) > _SPECULATIVE_CONTEXT_TTL_SECONDS:
            self._speculative_context_cache.pop(cache_key, None)
            return False
        return True

    def schedule_retrieval_prefetch(
        self,
        *,
        cache_key: str,
        query: str,
        session_id: str | None,
        workspace_id: str | None,
    ) -> bool:
        clean_query = " ".join(query.split())
        if self.retrieval_pipeline is None or not cache_key or len(clean_query) < 4:
            return False
        self.cancel_retrieval_prefetch(cache_key, clear_cache=False)
        task = asyncio.create_task(
            self._run_retrieval_prefetch(cache_key, clean_query, session_id, workspace_id),
            name=f"retrieval-prefetch-{cache_key}",
        )
        self._retrieval_prefetch_tasks[cache_key] = task
        task.add_done_callback(lambda completed, key=cache_key: self._prefetch_done(key, completed))
        return True

    def cancel_retrieval_prefetch(self, cache_key: str, *, clear_cache: bool = True) -> None:
        task = self._retrieval_prefetch_tasks.pop(cache_key, None)
        if task is not None and not task.done():
            task.cancel()
        if clear_cache:
            self._retrieval_prefetch_cache.pop(cache_key, None)

    async def _run_retrieval_prefetch(
        self,
        cache_key: str,
        query: str,
        session_id: str | None,
        workspace_id: str | None,
    ) -> None:
        pipeline = self.retrieval_pipeline
        if pipeline is None:
            return
        request = RetrievalRequest(
            query=query,
            scope="workspace" if workspace_id else ("session" if session_id else None),
            session_id=session_id,
            workspace_id=workspace_id,
            top_k=5,
            layers=['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'],
        )
        data = await asyncio.to_thread(pipeline.recall, request)
        if not isinstance(data, dict) or not data.get("results"):
            return
        self._retrieval_prefetch_cache[cache_key] = {
            "query": query,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "data": data,
        }
        while len(self._retrieval_prefetch_cache) > 32:
            self._retrieval_prefetch_cache.pop(next(iter(self._retrieval_prefetch_cache)))

    def _prefetch_done(self, cache_key: str, task: asyncio.Task[None]) -> None:
        if self._retrieval_prefetch_tasks.get(cache_key) is task:
            self._retrieval_prefetch_tasks.pop(cache_key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.debug("Retrieval prefetch failed for %s: %s", cache_key, error)

    async def _take_retrieval_prefetch(
        self,
        *,
        cache_key: str,
        final_query: str,
        workspace_id: str | None,
    ) -> dict[str, Any] | None:
        task = self._retrieval_prefetch_tasks.get(cache_key)
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.12)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        cached = self._retrieval_prefetch_cache.pop(cache_key, None)
        if not cached or cached.get("workspace_id") != workspace_id:
            return None
        if time.monotonic() - float(cached.get("recorded_at") or 0) > 8:
            return None
        if not _query_matches_partial(str(cached.get("query") or ""), final_query):
            return None
        data = cached.get("data")
        return data if isinstance(data, dict) else None

    def _extract_user_text(self, ctx: AgentRequestContext) -> str:
        for message in reversed(ctx.messages):
            if message.get("role") == "user":
                return str(message.get("content", ""))
        return ""

    def _append_runtime_loop(
        self,
        ctx: AgentRequestContext,
        *,
        stage: str,
        summary: str,
        status: str = "ok",
        agent_id: str | None = None,
        agent_role: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if ctx.trace_store is None:
            return
        ctx.trace_store.append(
            "runtime_loop",
            RuntimeLoopRecord(
                timestamp=datetime.now().isoformat(),
                session_id=ctx.session_id,
                request_id=ctx.request_id,
                stage=stage,
                status=status,
                summary=summary,
                agent_id=agent_id,
                agent_role=agent_role,
                data=data,
            ).to_dict(),
        )

    async def prepare_context(self, ctx: AgentRequestContext):
        ctx = await self.normalize_input(ctx)
        self._append_runtime_loop(
            ctx,
            stage="observe",
            summary="Collected input state from request/session/workspace/runtime bindings.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "message_count": len(ctx.messages),
                "workspace_id": ctx.workspace_id,
                "session_id": ctx.session_id,
                "has_pet_control_context": bool(ctx.pet_control_context),
            },
        )
        if ctx.plugin_manager:
            ctx = await ctx.plugin_manager.before_pipeline(ctx)
        ctx = await self.enrich_context(ctx)

        if ctx.plugin_manager:
            ctx = await ctx.plugin_manager.before_llm(ctx)

        user_text = self._extract_user_text(ctx)
        interpret_result = interpret_user_text(user_text)
        ctx.extra["interpret_result"] = interpret_result
        bindings = get_runtime_bindings(ctx)
        relationship_summary = bindings.relationship_summary or {}
        relationship_stage = str(relationship_summary.get("relationship_stage") or "warming")
        autonomy_mode = getattr(ctx, "autonomy_mode", "companion")
        recent_signal_kinds = [str(item.get("kind") or "") for item in (ctx.extra.get("recent_signal_docs") or []) if isinstance(item, dict)]
        has_workspace_tool_preset = bool(ctx.extra.get("workspace_tool_preset"))
        top_route = resolve_route_from_intent(
            interpret_result,
            relationship_stage,
            autonomy_mode,
            recent_signal_kinds=recent_signal_kinds,
            has_workspace_tool_preset=has_workspace_tool_preset,
        )
        ctx.extra["top_route"] = top_route
        plan = self.planner.plan(user_text, interpret_result=interpret_result)
        _force_agent_tool_loop(ctx, plan)
        self._append_runtime_loop(
            ctx,
            stage="interpret",
            summary=f"Intent={interpret_result.intent}, urgency={interpret_result.urgency}, route={top_route.owner_agent_role}",
            agent_id=top_route.owner_agent_id,
            agent_role=top_route.owner_agent_role,
            data={
                "goal": plan.goal,
                "mode": plan.mode,
                "step_count": len(plan.steps),
                "intent": interpret_result.intent,
                "urgency": interpret_result.urgency,
                "emotional_signal": interpret_result.emotional_signal,
                "tool_hint": interpret_result.tool_hint,
                "web_search_enabled": ctx.web_search_enabled is True,
                "force_tool_loop": ctx.extra.get("force_tool_loop") is True,
                "autonomy_mode": autonomy_mode,
                "relationship_stage": relationship_stage,
                "top_route_reason": top_route.route_reason,
                "has_workspace_tool_preset": has_workspace_tool_preset,
            },
        )
        if ctx.trace_store:
            trace = PlannerTrace(
                timestamp=datetime.now().isoformat(),
                session_id=ctx.session_id,
                goal=plan.goal,
                mode=plan.mode,
            steps=[
                PlannerStepRecord(
                    id=step.id,
                    title=step.title,
                    kind=step.kind,
                    description=step.description,
                    depends_on=list(step.depends_on),
                    condition=_planner_condition_record(step.condition),
                )
                for step in plan.steps
            ],
                request_id=ctx.request_id,
            )
            ctx.trace_store.append("planner", trace.to_dict())
        return ctx, plan

    async def finalize_result(self, ctx: AgentRequestContext, result_obj: AgentPipelineResult) -> AgentPipelineResult:
        original_envelope = dict(result_obj.action_envelope or {})
        original_tool_calls = list(result_obj.tool_calls or [])
        if ctx.plugin_manager:
            result_obj = await ctx.plugin_manager.after_llm(result_obj, ctx)
            result_obj = await ctx.plugin_manager.before_dispatch(result_obj, ctx)

        trace_suffix: list[dict[str, Any]] = []
        original_actions = original_envelope.get("actions")
        if isinstance(original_actions, list):
            tool_trace = next(
                (
                    action for action in original_actions
                    if isinstance(action, dict) and action.get("type") == "tool_trace"
                ),
                None,
            )
            payload = tool_trace.get("payload") if isinstance(tool_trace, dict) else None
            if (
                isinstance(payload, list)
                and payload[:len(original_tool_calls)] == original_tool_calls
            ):
                trace_suffix = [
                    item for item in payload[len(original_tool_calls):]
                    if isinstance(item, dict)
                ]

        result_obj.pet_control = filter_pet_control_payload(
            result_obj.pet_control,
            ctx.pet_control_context,
        )
        result_obj.tool_calls = _coerce_tool_calls(result_obj.tool_calls)
        result_obj.action_envelope = compile_action_envelope(
            reply=str(result_obj.reply or ""),
            pet_control=result_obj.pet_control,
            tool_calls=[*result_obj.tool_calls, *trace_suffix],
            memory_sources=[
                source for source in (ctx.extra.get("memory_sources") or [])
                if isinstance(source, dict)
            ],
            source=str(original_envelope.get("source") or "agent"),
            request_id=str(original_envelope.get("request_id") or ctx.request_id or "") or None,
        )
        self._append_runtime_loop(
            ctx,
            stage="ask_act",
            summary="Prepared reply and actions for dispatch.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "reply_length": len(result_obj.reply or ""),
                "tool_call_count": len(result_obj.tool_calls or []),
                "has_pet_control": bool(result_obj.pet_control),
            },
        )
        bindings = get_runtime_bindings(ctx)
        relationship_summary = bindings.relationship_summary or {}
        self._append_runtime_loop(
            ctx,
            stage="reflect",
            summary="Recorded execution outcome for future policy and memory adjustment.",
            agent_id="yuizaki.memory-reflector",
            agent_role="reflector",
            data={
                "relationship_stage": relationship_summary.get("relationship_stage"),
                "proactive_budget": relationship_summary.get("proactive_budget"),
            },
        )
        self._append_runtime_loop(
            ctx,
            stage="update_relationship",
            summary="Prepared relationship update signals from current execution.",
            agent_id="yuizaki.memory-reflector",
            agent_role="reflector",
            data={
                "relationship_history_count": len(bindings.relationship_history or []),
                "retrieved_chunk_count": len(bindings.retrieved_chunks or []),
            },
        )
        return result_obj

    async def normalize_input(self, ctx: AgentRequestContext) -> AgentRequestContext:
        ctx.messages = list(ctx.messages or [])
        ctx.session_id = ctx.session_id or ctx.sid
        return ctx

    async def enrich_context(self, ctx: AgentRequestContext) -> AgentRequestContext:
        # Apply workspace tool and MCP preset filtering.
        if ctx.workspace_id and ctx.tool_registry:
            bindings = get_runtime_bindings(ctx)
            db_repo = bindings.db_repo or ctx.extra.get("db_repo")
            if db_repo:
                try:
                    workspaces = await asyncio.to_thread(db_repo.list_workspaces)
                    workspace = next((w for w in workspaces if w.get("id") == ctx.workspace_id), None)
                    if workspace:
                        import json as _json
                        raw_tool_preset = workspace.get("tool_preset")
                        if isinstance(raw_tool_preset, str) and raw_tool_preset.strip():
                            try:
                                allowed_tools = _json.loads(raw_tool_preset)
                                if isinstance(allowed_tools, list):
                                    allowed_set = {str(t) for t in allowed_tools if isinstance(t, str)}
                                    ctx.extra["workspace_tool_preset"] = sorted(allowed_set)
                            except _json.JSONDecodeError:
                                pass
                        raw_mcp_preset = workspace.get("mcp_preset_id")
                        if isinstance(raw_mcp_preset, str) and raw_mcp_preset.strip():
                            ctx.extra["workspace_mcp_preset"] = [raw_mcp_preset.strip()]
                except Exception as exc:
                    logger.warning("[pipeline] workspace tool_preset parse failed: %s", exc)

        user_text = ""
        for message in reversed(ctx.messages):
            if message.get("role") == "user":
                user_text = message_content_to_text(message.get("content", ""))
                break

        if not user_text.strip():
            return ctx

        if self.retrieval_pipeline is not None:
            try:
                data = await self._take_retrieval_prefetch(
                    cache_key=ctx.sid,
                    final_query=user_text,
                    workspace_id=ctx.workspace_id,
                )
                prefetch_hit = data is not None
                if data is None:
                    request = RetrievalRequest(
                        query=user_text,
                        scope="workspace" if ctx.workspace_id else ("session" if ctx.session_id else None),
                        session_id=ctx.session_id,
                        workspace_id=ctx.workspace_id,
                        top_k=5,
                        layers=['profile', 'working', 'episodic', 'relationship', 'reflective', 'semantic'],
                    )
                    data = await asyncio.to_thread(self.retrieval_pipeline.recall, request)
                ctx.extra["retrieval_prefetch_hit"] = prefetch_hit
                results = data.get("results", [])
                chunks: list[str] = []
                memory_sources: list[dict[str, Any]] = []
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    doc = item.get("doc") or {}
                    if not isinstance(doc, dict):
                        continue
                    text = str(doc.get("text", ""))
                    if text:
                        chunks.append(text)
                    doc_id = str(doc.get("id") or item.get("id") or "").strip()
                    clean_text = " ".join(text.split())
                    if not doc_id or not clean_text or len(memory_sources) >= 5:
                        continue
                    raw_metadata = doc.get("metadata")
                    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                    layer = str(doc.get("layer") or metadata.get("layer") or "").strip()
                    source = str(doc.get("source") or metadata.get("source") or "").strip()
                    score = item.get("score")
                    memory_sources.append({
                        "id": doc_id,
                        "text": f"{clean_text[:317]}..." if len(clean_text) > 320 else clean_text,
                        **({"layer": layer} if layer else {}),
                        **({"source": source} if source else {}),
                        **({"score": float(score)} if isinstance(score, (int, float)) else {}),
                    })
                if chunks:
                    bindings = get_runtime_bindings(ctx)
                    bindings.retrieved_chunks = chunks[:5]
                    bind_runtime_bindings(
                        ctx,
                        db_repo=bindings.db_repo,
                        relationship_event_writer=bindings.relationship_event_writer,
                        relationship_history=bindings.relationship_history,
                        relationship_summary=bindings.relationship_summary,
                        retrieved_chunks=bindings.retrieved_chunks,
                    )
                    ctx.extra["retrieved_chunks"] = chunks[:5]
                    ctx.extra["memory_sources"] = memory_sources
                    recent_signal_docs: list[dict[str, str]] = []
                    for item in results[:5]:
                        doc_payload = item.get("doc") or {}
                        metadata = doc_payload.get("metadata") if isinstance(doc_payload, dict) else {}
                        metadata_payload = metadata if isinstance(metadata, dict) else {}
                        relationship_event = metadata_payload.get("relationship_event") or {}
                        relationship_payload = relationship_event if isinstance(relationship_event, dict) else {}
                        kind = relationship_payload.get("kind") or metadata_payload.get("type") or ""
                        recent_signal_docs.append({"kind": str(kind)})
                    ctx.extra["recent_signal_docs"] = recent_signal_docs
                    self._append_runtime_loop(
                        ctx,
                        stage="recall",
                        summary="Retrieved memory and context chunks for prompt assembly.",
                        agent_id="yuizaki.companion-orchestrator",
                        agent_role="orchestrator",
                        data={
                            "retrieved_chunk_count": len(chunks[:5]),
                            "query": user_text,
                            "recent_signal_kinds": [item.get("kind") for item in ctx.extra.get("recent_signal_docs", []) if isinstance(item, dict)],
                        },
                    )
            except Exception as exc:
                ctx.extra["rag_error"] = str(exc)
                self._append_runtime_loop(
                    ctx,
                    stage="recall",
                    summary="Recall failed; continuing without retrieved chunks.",
                    status="error",
                    agent_id="yuizaki.companion-orchestrator",
                    agent_role="orchestrator",
                    data={"error": str(exc)},
                )

        bindings = get_runtime_bindings(ctx)
        db_repo = bindings.db_repo or ctx.extra.get("db_repo")
        relationship_history = bindings.relationship_history or ctx.extra.get("relationship_history")
        retrieved_chunks = bindings.retrieved_chunks or ctx.extra.get("retrieved_chunks")
        interpret_result = ctx.extra.get("interpret_result") if hasattr(ctx, "extra") else None
        ctx.messages = await asyncio.to_thread(
            build_prompt_assembly,
            db_repo=db_repo,
            generation_mgr=ctx.generation_mgr,
            workspace_id=ctx.workspace_id,
            session_id=ctx.session_id,
            messages=ctx.messages,
            interpret_result=interpret_result,
            retrieved_chunks=retrieved_chunks,
            relationship_history=relationship_history,
            pet_control_context=ctx.pet_control_context,
            prompt_profile=ctx.prompt_profile,
            response_mode=ctx.response_mode,
            additional_blocks=[
                block for block in (ctx.extra.get("additional_prompt_blocks") or [])
                if isinstance(block, PromptBlock)
            ],
        )

        self._append_runtime_loop(
            ctx,
            stage="decide",
            summary="Prepared prompt context and selected execution path.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "has_db_repo": bool(db_repo),
                "relationship_history_count": len(relationship_history or []),
                "retrieved_chunk_count": len(retrieved_chunks or []),
                "autonomy_mode": getattr(ctx, "autonomy_mode", "companion"),
                "interpret_intent": getattr(interpret_result, "intent", None),
            },
        )

        return ctx

    async def run(self, ctx: AgentRequestContext) -> AgentPipelineResult:
        if ctx.autonomy_mode == "silent":
            return self._silent_result(ctx)
        ctx, plan = await self.prepare_context(ctx)
        autonomy_mode = getattr(ctx, "autonomy_mode", "companion")

        if autonomy_mode == "assistant" and plan.mode in {"scheduled_once", "scheduled_interval", "mixed"} and plan.scheduled_steps:
            plan.scheduled_steps = []
            plan.steps = [step for step in plan.steps if step.kind != "schedule"]
            if plan.immediate_steps:
                plan.mode = "immediate"

        if autonomy_mode == "reflector" and plan.immediate_steps:
            for step in plan.immediate_steps:
                if step.kind == "tool":
                    step.kind = "agent"

        if plan.scheduled_steps and ctx.scheduler:
            created_tasks = await ctx.step_executor.execute_schedule_steps(ctx, plan.scheduled_steps) if ctx.step_executor else []

            if plan.mode == "scheduled_once":
                reply = f"已为你创建一次性任务，将在 {plan.delay_seconds} 秒后执行。"
            elif plan.mode == "scheduled_interval":
                reply = f"已为你创建循环任务，将每隔 {plan.interval_seconds} 秒执行一次。"
            else:
                reply = "已为你创建计划任务，并将继续执行即时部分。"

            if plan.immediate_steps:
                result = await ctx.step_executor.execute_immediate_steps(ctx, plan.immediate_steps) if ctx.step_executor else {"reply": "", "tool_calls": [], "pet_control": None}
                immediate_reply = str(result.get("reply") or "")
                pet_control = _coerce_pet_control(result.get("pet_control"))
                tool_calls = _coerce_tool_calls(result.get("tool_calls"))
                step_results = _coerce_step_results(result.get("step_results"))
                execution_summary = _coerce_execution_summary(result.get("execution_summary"))
                failed = _execution_did_not_complete(execution_summary, step_results)
                rollback_results: list[dict[str, Any]] = []
                created_task_results = [item.to_dict() for item in created_tasks]
                if failed and ctx.step_executor:
                    rollback_records = await ctx.step_executor.rollback_schedule_results(ctx, created_tasks)
                    rollback_results = [item.to_dict() for item in rollback_records]
                    reply = "计划任务的即时执行部分失败，已回滚已创建的调度任务。"
                combined_reply = f"{reply}\n\n{immediate_reply}" if immediate_reply else reply
                result_obj = AgentPipelineResult(
                    reply=combined_reply,
                    pet_control=pet_control,
                    tool_calls=tool_calls,
                    action_envelope=compile_action_envelope(
                        reply=combined_reply,
                        pet_control=pet_control,
                        tool_calls=tool_calls + _execution_trace_payload(
                            [*created_task_results, *step_results, *rollback_results],
                            execution_summary,
                            {
                                "stop_on_failure": True,
                                "tool_retry_limit": getattr(ctx.step_executor, 'max_tool_retries', 0) if ctx.step_executor else 0,
                                "schedule_rollback_on_immediate_failure": True,
                            },
                            {
                                "scheduled_tasks": [task.task_id for task in created_tasks if task.task_id],
                                "mode": plan.mode,
                                "plan_steps": [step.title for step in plan.steps],
                            },
                        ),
                        source="planner",
                        request_id=ctx.request_id,
                    ),
                )
                return await self.finalize_result(ctx, result_obj)

            result_obj = AgentPipelineResult(
                reply=reply,
                pet_control=None,
                tool_calls=[],
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=None,
                    tool_calls=[{
                        "scheduled_tasks": [task.task_id for task in created_tasks if task.task_id],
                        "mode": plan.mode,
                        "plan_steps": [step.title for step in plan.steps],
                        "step_results": [item.to_dict() for item in created_tasks],
                        "execution_policy": {
                            "stop_on_failure": True,
                            "tool_retry_limit": getattr(ctx.step_executor, 'max_tool_retries', 0) if ctx.step_executor else 0,
                            "schedule_rollback_on_immediate_failure": True,
                        },
                    }],
                    source="planner",
                    request_id=ctx.request_id,
                ),
            )
            return await self.finalize_result(ctx, result_obj)

        result = await ctx.step_executor.execute_immediate_steps(ctx, plan.immediate_steps) if ctx.step_executor else {"reply": "", "tool_calls": [], "pet_control": None}

        reply = str(result.get("reply") or "")
        pet_control = _coerce_pet_control(result.get("pet_control"))
        tool_calls = _coerce_tool_calls(result.get("tool_calls"))
        step_results = _coerce_step_results(result.get("step_results"))
        execution_summary = _coerce_execution_summary(result.get("execution_summary"))

        result_obj = AgentPipelineResult(
            reply=reply,
            pet_control=pet_control,
            tool_calls=tool_calls,
            action_envelope=compile_action_envelope(
                reply=reply,
                pet_control=pet_control,
                tool_calls=tool_calls + _execution_trace_payload(
                    step_results,
                    execution_summary,
                    {
                        "stop_on_failure": True,
                        "tool_retry_limit": getattr(ctx.step_executor, 'max_tool_retries', 0) if ctx.step_executor else 0,
                    },
                ),
                source="agent",
                request_id=ctx.request_id,
            ),
        )
        return await self.finalize_result(ctx, result_obj)

    async def run_streaming(self, ctx: AgentRequestContext, ws_adapter: Any, generation: Generation) -> AgentPipelineResult:
        if ctx.autonomy_mode == "silent":
            generation.tokens = []
            return self._silent_result(ctx)
        ctx, plan = await self.prepare_context(ctx)

        if plan.scheduled_steps and ctx.scheduler and ctx.step_executor:
            await ctx.step_executor.execute_schedule_steps(ctx, plan.scheduled_steps)

        if ctx.step_executor and plan.immediate_steps and (ctx.extra.get("force_tool_loop") is True or _requires_structured_immediate_execution(plan.immediate_steps)):
            result = await ctx.step_executor.execute_immediate_steps(ctx, plan.immediate_steps)
            reply = str(result.get("reply") or "")
            pet_control = _coerce_pet_control(result.get("pet_control"))
            tool_calls = _coerce_tool_calls(result.get("tool_calls"))
            step_results = _coerce_step_results(result.get("step_results"))
            execution_summary = _coerce_execution_summary(result.get("execution_summary"))

            generation.tokens = [reply] if reply else []
            if reply and ctx.generation_mgr:
                ctx.generation_mgr.append_history(ctx.session_id, "assistant", reply)
            if pet_control:
                setattr(generation, "pet_control", pet_control)

            if ws_adapter is not None:
                if reply:
                    await ws_adapter.send_json({
                        "type": "token",
                        "session_id": generation.session_id,
                        "generation_id": generation.generation_id,
                        "content": reply,
                    })
                if pet_control:
                    await ws_adapter.send_json({
                        "type": "pet_control",
                        "session_id": generation.session_id,
                        "generation_id": generation.generation_id,
                        "pet_control": pet_control,
                    })
                await ws_adapter.send_json({
                    "type": "done",
                    "session_id": generation.session_id,
                    "generation_id": generation.generation_id,
                    "content": reply,
                })

            result_obj = AgentPipelineResult(
                reply=reply,
                pet_control=pet_control,
                tool_calls=tool_calls,
                action_envelope=compile_action_envelope(
                    reply=reply,
                    pet_control=pet_control,
                    tool_calls=tool_calls + _execution_trace_payload(
                        step_results,
                        execution_summary,
                        {
                            "stop_on_failure": True,
                            "tool_retry_limit": getattr(ctx.step_executor, 'max_tool_retries', 0),
                        },
                    ),
                    source="agent",
                    request_id=ctx.request_id,
                ),
            )
            return await self.finalize_result(ctx, result_obj)

        if not ctx.llm_client or not ctx.generation_mgr:
            raise RuntimeError("LLM client or generation manager not available")

        await ctx.llm_client.stream_chat(
            ws_adapter,
            generation,
            ctx.generation_mgr,
            ctx.messages,
            max_output_tokens=ctx.max_tokens,
            pet_control_context=ctx.pet_control_context,
            model=ctx.model,
            temperature=ctx.temperature,
            top_p=ctx.top_p,
            top_k=ctx.top_k,
            min_p=ctx.min_p,
            frequency_penalty=ctx.frequency_penalty,
            presence_penalty=ctx.presence_penalty,
            repetition_penalty=ctx.repetition_penalty,
            reasoning_effort=ctx.reasoning_effort,
            thinking=ctx.thinking_mode,
        )

        result_obj = AgentPipelineResult(
            reply=generation.full_text,
            pet_control=getattr(generation, 'pet_control', None),
            tool_calls=[],
            action_envelope=compile_action_envelope(
                reply=generation.full_text,
                pet_control=getattr(generation, 'pet_control', None),
                tool_calls=[{"mode": plan.mode, "plan_steps": [step.title for step in plan.steps]}],
                source="agent",
                request_id=ctx.request_id or f"act_{generation.generation_id}",
            ),
        )
        return await self.finalize_result(ctx, result_obj)
