from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ..memory.pipeline import RetrievalPipeline
from ..memory.schema import RetrievalRequest
from .visual_intent import classify_visual_context_request
from .visual_intent import normalize_query as _normalize_query
from .visual_intent import query_matches_partial as _query_matches_partial

logger = logging.getLogger(__name__)

SPECULATIVE_CONTEXT_TTL_SECONDS = 8.0
SPECULATIVE_CONTEXT_MAX_ENTRIES = 32
RETRIEVAL_PREFETCH_MAX_ENTRIES = 32
RETRIEVAL_PREFETCH_WAIT_SECONDS = 0.12


class ContextPrefetchCoordinator:
    """Best-effort context warming for voice turns.

    This coordinator owns only ephemeral caches and asyncio tasks.  It never
    changes the authoritative retrieval store, and callers can safely fall
    back to a normal retrieval when a cache is stale or mismatched.
    """

    def __init__(self, retrieval_pipeline: RetrievalPipeline | None = None) -> None:
        self.retrieval_pipeline = retrieval_pipeline
        self.retrieval_prefetch_tasks: dict[str, asyncio.Task[None]] = {}
        self.retrieval_prefetch_cache: dict[str, dict[str, Any]] = {}
        self.speculative_context_cache: dict[str, dict[str, Any]] = {}

    def bind_retrieval_pipeline(self, retrieval_pipeline: RetrievalPipeline) -> None:
        self.retrieval_pipeline = retrieval_pipeline

    @staticmethod
    def rank_tool_names(tool_registry: Any, query: str) -> list[str]:
        rank_candidates = getattr(tool_registry, "rank_candidates", None)
        if not callable(rank_candidates):
            return []
        try:
            ranked = rank_candidates(query, limit=8)
            if not isinstance(ranked, list):
                return []
            return [str(tool.name) for tool in ranked if getattr(tool, "name", None)]
        except Exception as exc:  # noqa: BLE001 - candidate prefetch is best-effort
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
        visual_decision = classify_visual_context_request(clean_query)
        self.speculative_context_cache[cache_key] = {
            "partial_query": clean_query,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "tool_candidates": self.rank_tool_names(tool_registry, clean_query),
            "visual_requested": visual_decision.requested,
            "visual_confidence": visual_decision.confidence,
            "visual_reason": visual_decision.reason,
            "visual_confirmation_required": visual_decision.confirmation_required,
            "visual_frame_id": visual_frame_id,
            "confirmed": False,
        }
        while len(self.speculative_context_cache) > SPECULATIVE_CONTEXT_MAX_ENTRIES:
            self.speculative_context_cache.pop(next(iter(self.speculative_context_cache)))
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
            self.speculative_context_cache.pop(cache_key, None)
            return False
        cached = self.speculative_context_cache.get(cache_key)
        cached_is_fresh = bool(
            cached
            and cached.get("workspace_id") == workspace_id
            and time.monotonic() - float(cached.get("recorded_at") or 0)
            <= SPECULATIVE_CONTEXT_TTL_SECONDS
        )
        partial_matches = bool(
            cached_is_fresh
            and cached
            and _query_matches_partial(
                str(cached.get("partial_query") or ""), clean_final, min_coverage=0.3
            )
        )
        prefetched_candidates = list(cached.get("tool_candidates") or []) if partial_matches and cached else []
        final_candidates = self.rank_tool_names(tool_registry, clean_final)
        merged_candidates = [name for name in prefetched_candidates if name in final_candidates]
        merged_candidates.extend(name for name in final_candidates if name not in merged_candidates)
        visual_decision = classify_visual_context_request(clean_final)
        self.speculative_context_cache[cache_key] = {
            "partial_query": str(cached.get("partial_query") or "") if cached else "",
            "final_query": clean_final,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "tool_candidates": merged_candidates[:8],
            "visual_requested": visual_decision.requested,
            "visual_confidence": visual_decision.confidence,
            "visual_reason": visual_decision.reason,
            "visual_confirmation_required": visual_decision.confirmation_required,
            "visual_frame_id": cached.get("visual_frame_id") if partial_matches and cached else None,
            "partial_match": partial_matches,
            "confirmed": True,
            "voice": True,
        }
        return True

    def take_speculative_context_prefetch(
        self, *, cache_key: str, final_query: str, workspace_id: str | None
    ) -> dict[str, Any] | None:
        cached = self.speculative_context_cache.pop(cache_key, None)
        if not cached or cached.get("workspace_id") != workspace_id or cached.get("confirmed") is not True:
            return None
        if time.monotonic() - float(cached.get("recorded_at") or 0) > SPECULATIVE_CONTEXT_TTL_SECONDS:
            return None
        if _normalize_query(str(cached.get("final_query") or "")) != _normalize_query(final_query):
            return None
        return dict(cached)

    def cancel_speculative_context_prefetch(self, cache_key: str) -> None:
        self.speculative_context_cache.pop(cache_key, None)

    def speculative_visual_requested(self, cache_key: str) -> bool:
        cached = self.speculative_context_cache.get(cache_key)
        if not cached or cached.get("visual_requested") is not True:
            return False
        if time.monotonic() - float(cached.get("recorded_at") or 0) > SPECULATIVE_CONTEXT_TTL_SECONDS:
            self.speculative_context_cache.pop(cache_key, None)
            return False
        return True

    def schedule_retrieval_prefetch(
        self, *, cache_key: str, query: str, session_id: str | None, workspace_id: str | None
    ) -> bool:
        clean_query = " ".join(query.split())
        if self.retrieval_pipeline is None or not cache_key or len(clean_query) < 4:
            return False
        self.cancel_retrieval_prefetch(cache_key, clear_cache=False)
        task = asyncio.create_task(
            self._run_retrieval_prefetch(cache_key, clean_query, session_id, workspace_id),
            name=f"retrieval-prefetch-{cache_key}",
        )
        self.retrieval_prefetch_tasks[cache_key] = task
        task.add_done_callback(lambda completed, key=cache_key: self._prefetch_done(key, completed))
        return True

    def cancel_retrieval_prefetch(self, cache_key: str, *, clear_cache: bool = True) -> None:
        task = self.retrieval_prefetch_tasks.pop(cache_key, None)
        if task is not None and not task.done():
            task.cancel()
        if clear_cache:
            self.retrieval_prefetch_cache.pop(cache_key, None)

    async def _run_retrieval_prefetch(
        self, cache_key: str, query: str, session_id: str | None, workspace_id: str | None
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
            layers=["profile", "working", "episodic", "relationship", "reflective", "semantic"],
        )
        data = await asyncio.to_thread(pipeline.recall, request)
        if not isinstance(data, dict) or not data.get("results"):
            return
        self.retrieval_prefetch_cache[cache_key] = {
            "query": query,
            "workspace_id": workspace_id,
            "recorded_at": time.monotonic(),
            "data": data,
        }
        while len(self.retrieval_prefetch_cache) > RETRIEVAL_PREFETCH_MAX_ENTRIES:
            self.retrieval_prefetch_cache.pop(next(iter(self.retrieval_prefetch_cache)))

    def _prefetch_done(self, cache_key: str, task: asyncio.Task[None]) -> None:
        if self.retrieval_prefetch_tasks.get(cache_key) is task:
            self.retrieval_prefetch_tasks.pop(cache_key, None)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.debug("Retrieval prefetch failed for %s: %s", cache_key, error)

    async def take_retrieval_prefetch(
        self, *, cache_key: str, final_query: str, workspace_id: str | None
    ) -> dict[str, Any] | None:
        task = self.retrieval_prefetch_tasks.get(cache_key)
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=RETRIEVAL_PREFETCH_WAIT_SECONDS)
            except asyncio.TimeoutError:
                pass
        cached = self.retrieval_prefetch_cache.pop(cache_key, None)
        if not cached or cached.get("workspace_id") != workspace_id:
            return None
        if time.monotonic() - float(cached.get("recorded_at") or 0) > SPECULATIVE_CONTEXT_TTL_SECONDS:
            return None
        if not _query_matches_partial(str(cached.get("query") or ""), final_query):
            return None
        data = cached.get("data")
        return data if isinstance(data, dict) else None
