from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from statistics import fmean
from typing import Any

GoldenCase = Mapping[str, Any]
QueryRunner = Callable[[GoldenCase], Mapping[str, Any]]
_REQUIRED_SCORE_COMPONENTS = frozenset({
    "semantic", "lexical", "learned", "recency", "quality", "final",
})


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_golden_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise TypeError("memory golden cases must be a JSON array")
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def evaluate_memory_retrieval(
    cases: Iterable[GoldenCase],
    run_query: QueryRunner,
) -> dict[str, Any]:
    """Evaluate deterministic retrieval cases without requiring a judge model."""
    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        case_id = str(case.get("id") or f"case-{index + 1}")
        expected_ids = [str(item) for item in case.get("expected_ids", [])]
        lifecycle_forbidden_ids = {
            str(item) for item in case.get("lifecycle_forbidden_ids", [])
        }
        scope_forbidden_ids = {str(item) for item in case.get("scope_forbidden_ids", [])}
        forbidden_ids = (
            {str(item) for item in case.get("forbidden_ids", [])}
            | lifecycle_forbidden_ids
            | scope_forbidden_ids
        )
        response = run_query(case)
        retrieved_ids = [
            str(item.get("doc", {}).get("id"))
            for item in response.get("results", [])
            if isinstance(item, Mapping) and isinstance(item.get("doc"), Mapping)
        ]
        expected_set = set(expected_ids)
        hits = expected_set.intersection(retrieved_ids)
        recall_at_k = len(hits) / len(expected_set) if expected_set else None
        recall_at = {
            str(k): len(expected_set.intersection(retrieved_ids[:k])) / len(expected_set)
            if expected_set
            else None
            for k in (1, 3, 5)
        }
        first_rank = next(
            (rank for rank, doc_id in enumerate(retrieved_ids, start=1) if doc_id in expected_set),
            None,
        )
        reciprocal_rank = (
            1.0 / first_rank
            if first_rank is not None
            else (0.0 if expected_set else None)
        )
        leaked_ids = sorted(forbidden_ids.intersection(retrieved_ids))
        lifecycle_leaked_ids = sorted(lifecycle_forbidden_ids.intersection(retrieved_ids))
        scope_leaked_ids = sorted(scope_forbidden_ids.intersection(retrieved_ids))
        raw_trace = response.get("trace")
        trace: Mapping[str, Any] = raw_trace if isinstance(raw_trace, Mapping) else {}
        required_evidence_ids = {
            str(item) for item in case.get("required_evidence_ids", [])
        }
        raw_evidence_ids = trace.get("evidence_ids", response.get("evidence_ids", []))
        observed_evidence_ids = {
            str(item) for item in raw_evidence_ids
        } if isinstance(raw_evidence_ids, (list, tuple, set, frozenset)) else set()
        evidence_quality_passed: bool | None = (
            required_evidence_ids.issubset(observed_evidence_ids)
            if required_evidence_ids
            else None
        )
        response_results = response.get("results", [])
        score_component_count = sum(
            1
            for item in response_results
            if isinstance(item, Mapping)
            and isinstance(item.get("score_components"), Mapping)
            and _REQUIRED_SCORE_COMPONENTS.issubset(item["score_components"])
        )
        security_phase = str(case.get("security_phase") or "")
        security_passed: bool | None = None
        if security_phase:
            security_passed = not leaked_ids and (
                bool(expected_set) and expected_set.issubset(hits)
                or not expected_set and not retrieved_ids
            )
        results.append({
            "id": case_id,
            "retrieved_ids": retrieved_ids,
            "recall_at_k": recall_at_k,
            "recall_at": recall_at,
            "reciprocal_rank": reciprocal_rank,
            "abstention_passed": not expected_set and not retrieved_ids,
            "leaked_ids": leaked_ids,
            "lifecycle_leaked_ids": lifecycle_leaked_ids,
            "scope_leaked_ids": scope_leaked_ids,
            "latency_ms": float(trace.get("latency_ms") or 0.0),
            "retrieval_latency_ms": float(
                trace.get("retrieval_latency_ms", trace.get("latency_ms")) or 0.0
            ),
            "token_cost": float(trace.get("token_cost") or 0.0),
            "input_tokens": int(trace.get("input_tokens") or 0),
            "output_tokens": int(trace.get("output_tokens") or 0),
            "candidate_count": int(trace.get("candidate_count") or 0),
            "filtered_out_count": int(trace.get("filtered_out_count") or 0),
            "score_component_completeness": (
                score_component_count / len(retrieved_ids) if retrieved_ids else 1.0
            ),
            "llm_service_calls": int(trace.get("llm_service_calls") or 0),
            "temporal_consistency_passed": not bool(
                {str(item) for item in case.get("consistency_forbidden_ids", [])}
                .intersection(retrieved_ids)
            ),
            "security_phase": security_phase,
            "security_passed": security_passed,
            "required_evidence_ids": sorted(required_evidence_ids),
            "observed_evidence_ids": sorted(observed_evidence_ids),
            "evidence_quality_passed": evidence_quality_passed,
        })

    count = len(results)
    latencies = [item["latency_ms"] for item in results]
    retrieval_latencies = [item["retrieval_latency_ms"] for item in results]
    token_costs = [item["token_cost"] for item in results]
    candidate_counts = [float(item["candidate_count"]) for item in results]
    filtered_counts = [float(item["filtered_out_count"]) for item in results]
    positive_results = [item for item in results if item["recall_at_k"] is not None]
    reciprocal_ranks = [
        item["reciprocal_rank"]
        for item in positive_results
        if item["reciprocal_rank"] is not None
    ]
    abstention_results = [item for item in results if item["recall_at_k"] is None]
    security_results = [item for item in results if item["security_phase"]]
    evidence_results = [item for item in results if item["evidence_quality_passed"] is not None]
    return {
        "case_count": count,
        "recall_at_k": (
            fmean(item["recall_at_k"] for item in positive_results)
            if positive_results
            else 0.0
        ),
        "recall_at": {
            str(k): fmean(item["recall_at"][str(k)] for item in positive_results)
            if positive_results
            else 0.0
            for k in (1, 3, 5)
        },
        "mrr": fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "abstention_pass_rate": (
            fmean(1.0 if item["abstention_passed"] else 0.0 for item in abstention_results)
            if abstention_results
            else 1.0
        ),
        "leakage_case_count": sum(1 for item in results if item["leaked_ids"]),
        "lifecycle_leakage_case_count": sum(
            1 for item in results if item["lifecycle_leaked_ids"]
        ),
            "scope_leakage_case_count": sum(1 for item in results if item["scope_leaked_ids"]),
        "latency_ms": {
            "mean": fmean(latencies) if latencies else 0.0,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": max(latencies, default=0.0),
        },
        "retrieval_latency_ms": {
            "mean": fmean(retrieval_latencies) if retrieval_latencies else 0.0,
            "p50": _percentile(retrieval_latencies, 0.50),
            "p95": _percentile(retrieval_latencies, 0.95),
            "max": max(retrieval_latencies, default=0.0),
        },
        "token_cost": {
            "total": sum(token_costs),
            "mean": fmean(token_costs) if token_costs else 0.0,
            "p95": _percentile(token_costs, 0.95),
        },
        "score_component_completeness": (
            fmean(item["score_component_completeness"] for item in results) if count else 1.0
        ),
        "llm_service_calls": sum(item["llm_service_calls"] for item in results),
        "mean_candidate_count": (
            fmean(item["candidate_count"] for item in results) if count else 0.0
        ),
        "mean_filtered_out_count": (
            fmean(item["filtered_out_count"] for item in results) if count else 0.0
        ),
        "candidate_count": {
            "mean": fmean(candidate_counts) if candidate_counts else 0.0,
            "p95": _percentile(candidate_counts, 0.95),
            "max": max(candidate_counts, default=0.0),
        },
        "filtered_out_count": {
            "mean": fmean(filtered_counts) if filtered_counts else 0.0,
            "p95": _percentile(filtered_counts, 0.95),
            "max": max(filtered_counts, default=0.0),
        },
        "temporal_consistency_pass_rate": (
            fmean(1.0 if item["temporal_consistency_passed"] else 0.0 for item in results)
            if results else 1.0
        ),
        "security_sequence": {
            phase: sum(1 for item in results if item["security_phase"] == phase)
            for phase in ("write", "execute", "forget", "repair")
        },
        "security_phase_pass_rate": {
            phase: (
                fmean(
                    1.0 if item["security_passed"] else 0.0
                    for item in security_results
                    if item["security_phase"] == phase
                )
                if any(item["security_phase"] == phase for item in security_results)
                else None
            )
            for phase in ("write", "execute", "forget", "repair")
        },
        "evidence_quality_pass_rate": (
            fmean(1.0 if item["evidence_quality_passed"] else 0.0 for item in evidence_results)
            if evidence_results else 1.0
        ),
        "cases": results,
    }
