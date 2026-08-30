"""Workspace, memory and prompt enrichment stage for AgentPipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..llm.context_window import message_content_to_text
from ..memory.pipeline import RetrievalPipeline
from ..memory.schema import RetrievalRequest
from .context import AgentRequestContext, bind_runtime_bindings, get_runtime_bindings
from .interpret import interpret_user_text
from .planning_stage import apply_visual_context_decision
from .prompt_assembly import PromptBlock, build_prompt_assembly

RuntimeLoopAppender = Callable[..., None]
TakeRetrievalPrefetch = Callable[..., Awaitable[dict[str, Any] | None]]

_DEFAULT_MEMORY_LAYERS = [
    "profile", "working", "episodic", "relationship", "reflective", "semantic",
]
_DEFAULT_MEMORY_CONTEXT_BUDGET_TOKENS = 1200
_MIN_MEMORY_CONTEXT_BUDGET_TOKENS = 128
_MAX_MEMORY_CONTEXT_BUDGET_TOKENS = 32000


class ContextStage:
    """Resolve workspace presets, memory evidence and final prompt messages."""

    async def run(
        self,
        ctx: AgentRequestContext,
        *,
        retrieval_pipeline: RetrievalPipeline | None,
        take_retrieval_prefetch: TakeRetrievalPrefetch,
        append_runtime_loop: RuntimeLoopAppender,
        logger: logging.Logger | None = None,
    ) -> AgentRequestContext:
        log = logger or logging.getLogger(__name__)
        await self._load_workspace_presets(ctx, log)
        user_text = self._user_text(ctx)
        if not user_text.strip():
            return ctx

        ctx.extra["interpret_result"] = interpret_user_text(user_text)
        visual_decision = apply_visual_context_decision(ctx, user_text)
        ctx.extra["intent_envelope"] = ctx.extra["interpret_result"].to_envelope(
            evidence_ids=["user_text"],
            confirmation_required=visual_decision.confirmation_required,
        )
        if retrieval_pipeline is not None:
            await self._recall(
                ctx,
                user_text=user_text,
                retrieval_pipeline=retrieval_pipeline,
                take_retrieval_prefetch=take_retrieval_prefetch,
                append_runtime_loop=append_runtime_loop,
            )
        await self._assemble_prompt(ctx, append_runtime_loop)
        return ctx

    @staticmethod
    async def _load_workspace_presets(ctx: AgentRequestContext, log: logging.Logger) -> None:
        if not ctx.workspace_id or not ctx.tool_registry:
            return
        bindings = get_runtime_bindings(ctx)
        db_repo = bindings.db_repo or ctx.extra.get("db_repo")
        if not db_repo:
            return
        try:
            workspaces = await asyncio.to_thread(db_repo.list_workspaces)
            workspace = next((item for item in workspaces if item.get("id") == ctx.workspace_id), None)
            if not workspace:
                return
            raw_tool_preset = workspace.get("tool_preset")
            if isinstance(raw_tool_preset, str) and raw_tool_preset.strip():
                try:
                    allowed_tools = json.loads(raw_tool_preset)
                    if isinstance(allowed_tools, list):
                        ctx.extra["workspace_tool_preset"] = sorted({
                            str(tool) for tool in allowed_tools if isinstance(tool, str)
                        })
                except json.JSONDecodeError:
                    pass
            raw_mcp_preset = workspace.get("mcp_preset_id")
            if isinstance(raw_mcp_preset, str) and raw_mcp_preset.strip():
                ctx.extra["workspace_mcp_preset"] = [raw_mcp_preset.strip()]
        except Exception as exc:  # noqa: BLE001 - optional preset degrades locally
            log.warning("[pipeline] workspace tool_preset parse failed: %s", exc)

    @staticmethod
    def _user_text(ctx: AgentRequestContext) -> str:
        for message in reversed(ctx.messages):
            if message.get("role") == "user":
                return message_content_to_text(message.get("content", ""))
        return ""

    async def _recall(
        self,
        ctx: AgentRequestContext,
        *,
        user_text: str,
        retrieval_pipeline: RetrievalPipeline,
        take_retrieval_prefetch: TakeRetrievalPrefetch,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> None:
        try:
            context_budget_tokens = self._context_budget_tokens(ctx)
            try:
                data = await take_retrieval_prefetch(
                    cache_key=ctx.sid,
                    final_query=user_text,
                    workspace_id=ctx.workspace_id,
                    context_budget_tokens=context_budget_tokens,
                )
            except TypeError as exc:
                # Keep custom runtime integrations written against the old
                # callback shape working while they migrate to budgets.
                if "context_budget_tokens" not in str(exc):
                    raise
                data = await take_retrieval_prefetch(
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
                    layers=list(_DEFAULT_MEMORY_LAYERS),
                    context_budget_tokens=context_budget_tokens,
                )
                data = await asyncio.to_thread(retrieval_pipeline.recall, request)
            ctx.extra["retrieval_prefetch_hit"] = prefetch_hit
            retrieval_trace = data.get("trace") if isinstance(data, dict) else None
            if isinstance(retrieval_trace, dict) and retrieval_trace.get("revision_stable") is False:
                # Do not place a result assembled across a memory mutation in
                # the prompt. The next turn can retry against the new revision.
                ctx.extra["rag_error"] = "memory_revision_changed_during_recall"
                append_runtime_loop(
                    ctx,
                    stage="recall",
                    summary="Memory changed during recall; skipped retrieved context.",
                    status="stale",
                    agent_id="yuizaki.companion-orchestrator",
                    agent_role="orchestrator",
                    data={"error": ctx.extra["rag_error"], "retrieval_trace": retrieval_trace},
                )
                return
            self._apply_recall_results(
                ctx,
                data.get("results", []),
                user_text,
                append_runtime_loop,
                retrieval_trace=data.get("trace"),
            )
        except Exception as exc:  # noqa: BLE001 - recall failure preserves text path
            ctx.extra["rag_error"] = str(exc)
            append_runtime_loop(
                ctx,
                stage="recall",
                summary="Recall failed; continuing without retrieved chunks.",
                status="error",
                agent_id="yuizaki.companion-orchestrator",
                agent_role="orchestrator",
                data={"error": str(exc)},
            )

    @staticmethod
    def _context_budget_tokens(ctx: AgentRequestContext) -> int:
        raw = ctx.extra.get("memory_context_budget_tokens")
        try:
            value = int(raw) if raw is not None else _DEFAULT_MEMORY_CONTEXT_BUDGET_TOKENS
        except (TypeError, ValueError):
            value = _DEFAULT_MEMORY_CONTEXT_BUDGET_TOKENS
        return max(_MIN_MEMORY_CONTEXT_BUDGET_TOKENS, min(_MAX_MEMORY_CONTEXT_BUDGET_TOKENS, value))

    @staticmethod
    def _apply_recall_results(
        ctx: AgentRequestContext,
        raw_results: object,
        user_text: str,
        append_runtime_loop: RuntimeLoopAppender,
        retrieval_trace: object = None,
    ) -> None:
        results = raw_results if isinstance(raw_results, list) else []
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
            source_kind = str(doc.get("source_kind") or metadata.get("source_kind") or "").strip()
            source_id = str(doc.get("source_id") or metadata.get("source_id") or "").strip()
            turn_id = str(doc.get("turn_id") or metadata.get("turn_id") or "").strip()
            evidence = metadata.get("evidence")
            evidence_ids: list[str] = []
            if isinstance(evidence, dict):
                raw_ids = evidence.get("ids") or evidence.get("id")
                if isinstance(raw_ids, (list, tuple, set)):
                    evidence_ids = [str(value)[:160] for value in raw_ids if str(value).strip()][:8]
                elif raw_ids is not None and str(raw_ids).strip():
                    evidence_ids = [str(raw_ids)[:160]]
            elif isinstance(evidence, (list, tuple, set)):
                evidence_ids = [str(value)[:160] for value in evidence if str(value).strip()][:8]
            elif isinstance(evidence, str) and evidence.strip():
                evidence_ids = [evidence.strip()[:160]]
            score = item.get("score")
            memory_sources.append({
                "id": doc_id,
                "text": f"{clean_text[:317]}..." if len(clean_text) > 320 else clean_text,
                **({"layer": layer} if layer else {}),
                **({"source": source} if source else {}),
                **({"source_kind": source_kind} if source_kind else {}),
                **({"source_id": source_id} if source_id else {}),
                **({"turn_id": turn_id} if turn_id else {}),
                **({"evidence_ids": evidence_ids} if evidence_ids else {}),
                **({"score": float(score)} if isinstance(score, (int, float)) else {}),
            })
        if not chunks:
            return

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
        if isinstance(retrieval_trace, dict):
            ctx.extra["memory_retrieval_trace"] = dict(retrieval_trace)
        recent_signal_docs: list[dict[str, str]] = []
        for item in results[:5]:
            doc_payload = item.get("doc") if isinstance(item, dict) else {}
            metadata = doc_payload.get("metadata") if isinstance(doc_payload, dict) else {}
            metadata_payload = metadata if isinstance(metadata, dict) else {}
            relationship_event = metadata_payload.get("relationship_event") or {}
            relationship_payload = relationship_event if isinstance(relationship_event, dict) else {}
            kind = relationship_payload.get("kind") or metadata_payload.get("type") or ""
            recent_signal_docs.append({"kind": str(kind)})
        ctx.extra["recent_signal_docs"] = recent_signal_docs
        append_runtime_loop(
            ctx,
            stage="recall",
            summary="Retrieved memory and context chunks for prompt assembly.",
            agent_id="yuizaki.companion-orchestrator",
            agent_role="orchestrator",
            data={
                "retrieved_chunk_count": len(chunks[:5]),
                "query": user_text,
                "recent_signal_kinds": [item.get("kind") for item in recent_signal_docs],
                "memory_sources": memory_sources,
                "retrieval_trace": retrieval_trace if isinstance(retrieval_trace, dict) else None,
            },
        )

    @staticmethod
    async def _assemble_prompt(
        ctx: AgentRequestContext,
        append_runtime_loop: RuntimeLoopAppender,
    ) -> None:
        bindings = get_runtime_bindings(ctx)
        db_repo = bindings.db_repo or ctx.extra.get("db_repo")
        relationship_history = bindings.relationship_history or ctx.extra.get("relationship_history")
        retrieved_chunks = bindings.retrieved_chunks or ctx.extra.get("retrieved_chunks")
        interpret_result = ctx.extra.get("interpret_result")
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
                block
                for block in (ctx.extra.get("additional_prompt_blocks") or [])
                if isinstance(block, PromptBlock)
            ],
        )
        append_runtime_loop(
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


__all__ = ["ContextStage"]
