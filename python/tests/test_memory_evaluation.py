from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from modules.memory.evaluation import evaluate_memory_retrieval, load_golden_cases
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest
from modules.memory.vector_store import Document


def test_memory_golden_evaluation_reports_quality_cost_and_leakage() -> None:
    fixture = Path(__file__).parent / "fixtures" / "memory_golden_cases.json"
    cases = load_golden_cases(fixture)[:3]
    responses: dict[str, dict[str, Any]] = {
        "preference-update": {
            "results": [{
                "doc": {"id": "preference-current"},
                "score": 0.9,
                "score_components": {
                    "semantic": 0.9, "lexical": 0.5, "learned": 0.0,
                    "recency": 0.8, "quality": 0.9, "final": 0.9,
                },
            }],
            "trace": {"latency_ms": 4.0, "candidate_count": 4, "filtered_out_count": 1},
        },
        "workspace-boundary": {
            "results": [{
                "doc": {"id": "workspace-current"},
                "score": 0.8,
                "score_components": {
                    "semantic": 0.8, "lexical": 0.4, "learned": 0.0,
                    "recency": 0.7, "quality": 0.8, "final": 0.8,
                },
            }],
            "trace": {"latency_ms": 6.0, "candidate_count": 5, "filtered_out_count": 2},
        },
        "forgotten-memory": {
            "results": [],
            "trace": {"latency_ms": 2.0, "candidate_count": 1, "filtered_out_count": 1},
        },
    }

    report = evaluate_memory_retrieval(cases, lambda case: responses[str(case["id"])])

    assert report["case_count"] == 3
    assert report["recall_at_k"] == 1.0
    assert report["recall_at"] == {"1": 1.0, "3": 1.0, "5": 1.0}
    assert report["mrr"] == 1.0
    assert report["abstention_pass_rate"] == 1.0
    assert report["leakage_case_count"] == 0
    assert report["lifecycle_leakage_case_count"] == 0
    assert report["scope_leakage_case_count"] == 0
    assert report["latency_ms"]["mean"] == 4.0
    assert report["latency_ms"]["p50"] == 4.0
    assert report["latency_ms"]["max"] == 6.0
    assert report["score_component_completeness"] == 1.0
    assert report["mean_candidate_count"] == 10 / 3
    assert report["mean_filtered_out_count"] == 4 / 3


def test_memory_golden_evaluation_detects_forbidden_recall() -> None:
    report = evaluate_memory_retrieval(
        [{"id": "leak", "expected_ids": [], "lifecycle_forbidden_ids": ["forgotten"]}],
        lambda _case: {
            "results": [{"doc": {"id": "forgotten"}, "score": 1.0}],
            "trace": {},
        },
    )

    assert report["leakage_case_count"] == 1
    assert report["lifecycle_leakage_case_count"] == 1
    assert report["scope_leakage_case_count"] == 0
    assert report["cases"][0]["leaked_ids"] == ["forgotten"]


def test_memory_golden_cases_execute_through_retrieval_pipeline() -> None:
    fixture = Path(__file__).parent / "fixtures" / "memory_golden_cases.json"
    cases = load_golden_cases(fixture)[:3]
    results_by_query = {
        "Which drink does the user prefer now?": [
            (Document(
                id="preference-superseded",
                text="prefers coffee",
                metadata={
                    "scope": "workspace", "workspace_id": "default",
                    "layer": "profile", "review_status": "superseded",
                },
            ), 0.99),
            (Document(
                id="preference-current",
                text="prefers tea",
                metadata={"scope": "workspace", "workspace_id": "default", "layer": "profile"},
            ), 0.9),
        ],
        "What is the private project codename?": [
            (Document(
                id="workspace-other",
                text="other secret",
                metadata={"scope": "workspace", "workspace_id": "other", "layer": "semantic"},
            ), 0.95),
            (Document(
                id="workspace-current",
                text="current secret",
                metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic"},
            ), 0.85),
        ],
        "What should no longer be recalled?": [
            (Document(
                id="soft-forgotten",
                text="hidden",
                metadata={
                    "scope": "workspace", "workspace_id": "default",
                    "layer": "semantic", "soft_forgotten": True,
                },
            ), 1.0),
        ],
    }

    class GoldenStore:
        backend_name = "golden"

        def search_with_rerank(self, query: str, **_kwargs: Any):
            return results_by_query[query]

    pipeline = RetrievalPipeline(GoldenStore())  # type: ignore[arg-type]

    def run(case: dict[str, Any]):
        return pipeline.recall(RetrievalRequest(
            query=str(case["query"]),
            scope="workspace",
            workspace_id="default",
            top_k=5,
        ))

    report = evaluate_memory_retrieval(cases, run)

    assert report["recall_at_k"] == 1.0
    assert report["mrr"] == 1.0
    assert report["abstention_pass_rate"] == 1.0
    assert report["lifecycle_leakage_case_count"] == 0
    assert report["scope_leakage_case_count"] == 0


def test_memory_evaluation_covers_temporal_abstention_security_and_cost_metrics() -> None:
    cases = load_golden_cases(
        Path(__file__).parent / "fixtures" / "memory_golden_cases.json"
    )[3:]
    responses = {
        "cross-session-preference": {
            "results": [{"doc": {"id": "session-2-editor"}, "score_components": {
                "semantic": 1, "lexical": 1, "learned": 0, "recency": 1,
                "quality": 1, "final": 1,
            }}],
            "trace": {"latency_ms": 8, "retrieval_latency_ms": 7, "token_cost": 3.5,
                      "candidate_count": 6, "filtered_out_count": 2},
        },
        "temporal-contradiction": {
            "results": [{"doc": {"id": "launch-date-current"}, "score_components": {
                "semantic": 1, "lexical": 1, "learned": 0, "recency": 1,
                "quality": 1, "final": 1,
            }}],
            "trace": {"latency_ms": 10, "retrieval_latency_ms": 9, "token_cost": 4.5,
                      "candidate_count": 8, "filtered_out_count": 3},
        },
        "no-evidence-abstention": {
            "results": [],
            "trace": {"latency_ms": 2, "retrieval_latency_ms": 2, "token_cost": 1,
                      "candidate_count": 1, "filtered_out_count": 1},
        },
        "memory-security-write": {
            "results": [{"doc": {"id": "candidate-untrusted"}}],
            "trace": {"latency_ms": 3, "token_cost": 2, "candidate_count": 2},
        },
        "memory-security-execute": {
            "results": [],
            "trace": {"latency_ms": 3, "retrieval_latency_ms": 3, "token_cost": 1.5,
                      "candidate_count": 2, "filtered_out_count": 2},
        },
        "memory-security-forget": {
            "results": [],
            "trace": {"latency_ms": 2, "retrieval_latency_ms": 2, "token_cost": 1,
                      "candidate_count": 2, "filtered_out_count": 2},
        },
        "memory-security-execute-forget-repair": {
            "results": [{"doc": {"id": "repair-record"}}],
            "trace": {"latency_ms": 4, "retrieval_latency_ms": 3, "token_cost": 2.5,
                      "candidate_count": 4, "filtered_out_count": 2},
        },
    }
    report = evaluate_memory_retrieval(cases, lambda case: responses[str(case["id"])])

    assert report["case_count"] == 7
    assert report["recall_at_k"] == 1.0
    assert report["abstention_pass_rate"] == 1.0
    assert report["temporal_consistency_pass_rate"] == 1.0
    assert report["token_cost"]["total"] == 16.0
    assert report["token_cost"]["mean"] == pytest.approx(16 / 7)
    assert report["token_cost"]["p95"] == pytest.approx(4.2)
    assert report["retrieval_latency_ms"]["p95"] == pytest.approx(8.4)
    assert report["candidate_count"]["mean"] == pytest.approx(25 / 7)
    assert report["candidate_count"]["p95"] == pytest.approx(7.4)
    assert report["candidate_count"]["max"] == 8.0
    assert report["security_sequence"] == {"write": 1, "execute": 1, "forget": 1, "repair": 1}
    assert report["security_phase_pass_rate"] == {"write": 1.0, "execute": 1.0, "forget": 1.0, "repair": 1.0}


def test_memory_evaluation_marks_security_phase_failure_when_forbidden_memory_is_recalled() -> None:
    report = evaluate_memory_retrieval(
        [{
            "id": "execute-leak",
            "expected_ids": [],
            "lifecycle_forbidden_ids": ["executed-untrusted"],
            "security_phase": "execute",
        }],
        lambda _case: {"results": [{"doc": {"id": "executed-untrusted"}}], "trace": {}},
    )

    assert report["security_phase_pass_rate"] == {"write": None, "execute": 0.0, "forget": None, "repair": None}
    assert report["cases"][0]["security_passed"] is False


def test_memory_evaluation_reports_evidence_coverage_separately_from_recall() -> None:
    cases = [{
        "id": "multi-hop-evidence",
        "expected_ids": ["answer-record"],
        "required_evidence_ids": ["event-a", "event-b"],
    }]

    complete = evaluate_memory_retrieval(
        cases,
        lambda _case: {
            "results": [{"doc": {"id": "answer-record"}}],
            "trace": {"evidence_ids": ["event-a", "event-b"]},
        },
    )
    assert complete["recall_at_k"] == 1.0
    assert complete["evidence_quality_pass_rate"] == 1.0
    assert complete["cases"][0]["evidence_quality_passed"] is True

    incomplete = evaluate_memory_retrieval(
        cases,
        lambda _case: {
            "results": [{"doc": {"id": "answer-record"}}],
            "trace": {"evidence_ids": ["event-a"]},
        },
    )
    assert incomplete["recall_at_k"] == 1.0
    assert incomplete["evidence_quality_pass_rate"] == 0.0
    assert incomplete["cases"][0]["observed_evidence_ids"] == ["event-a"]
