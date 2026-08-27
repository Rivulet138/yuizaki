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


def test_memory_desktop_fixture_reports_usefulness_metrics_by_scenario() -> None:
    fixture = Path(__file__).parent / "fixtures" / "memory_desktop_scenarios.json"
    cases = load_golden_cases(fixture)
    assert {case["scenario"] for case in cases} == {
        "preference_change", "repeated_workflow", "last_failure",
        "unfinished_task", "missing_prerequisite",
    }

    def run(case: dict[str, Any]) -> dict[str, Any]:
        if case.get("abstention_expected"):
            return {
                "results": [],
                "missing_premises": case["missing_premises"],
                "trace": {
                    "latency_ms": 10,
                    "token_cost": 4,
                    "evidence_ids": case["required_evidence_ids"],
                },
            }
        return {
            "results": [{"doc": {"id": case["expected_ids"][0]}}],
            "trace": {
                "latency_ms": 10,
                "token_cost": 4,
                "evidence_ids": case["required_evidence_ids"],
            },
        }

    report = evaluate_memory_retrieval(cases, run)
    assert set(report["scenario_metrics"]) == {
        "preference_change", "repeated_workflow", "last_failure",
        "unfinished_task", "missing_prerequisite",
    }
    assert all(
        metrics["recall_at_k"] == 1.0
        and metrics["evidence_quality_pass_rate"] == 1.0
        and metrics["latency_ms"]["p95"] == 10.0
        for scenario, metrics in report["scenario_metrics"].items()
        if scenario != "missing_prerequisite"
    )
    assert report["abstention_mismatch_count"] == 0
    assert report["missing_premise_mismatch_count"] == 0
    missing_case = next(
        item for item in report["cases"] if item["scenario"] == "missing_prerequisite"
    )
    assert missing_case["abstention_expected"] is True
    assert missing_case["observed_abstention"] is True
    assert missing_case["expected_missing_premises"] == ["deployment-environment"]
    assert missing_case["missing_premise_mismatch"] is False


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


def test_retrieval_pipeline_expands_one_hop_evidence_and_rechecks_scope():
    anchor = Document(
        id="answer-record",
        text="the answer",
        metadata={
            "scope": "workspace", "workspace_id": "default", "layer": "semantic",
            "source_ids": ["evidence-a", "other-workspace"],
        },
    )
    evidence = Document(
        id="evidence-a",
        text="supporting event",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic"},
    )
    other_workspace = Document(
        id="other-workspace",
        text="private other workspace",
        metadata={"scope": "workspace", "workspace_id": "other", "layer": "episodic"},
    )

    class RelationStore:
        def search_with_rerank(self, query: str, **_kwargs: Any):
            assert query == "answer"
            return [(anchor, 0.9)]

        def list_documents(self):
            return [anchor, evidence, other_workspace]

    result = RetrievalPipeline(RelationStore()).recall(RetrievalRequest(
        query="answer", scope="workspace", workspace_id="default", top_k=2,
    ))
    assert [item["doc"]["id"] for item in result["results"]] == ["answer-record", "evidence-a"]
    trace = result["trace"]
    assert trace["anchor_ids"] == ["answer-record"]
    assert trace["expanded_ids"] == ["evidence-a"]
    assert trace["expansion_edges"] == [{"from": "answer-record", "to": "evidence-a", "relation": "source", "evidence_type": "source"}]
    assert trace["evidence_ids"] == ["evidence-a"]
    assert trace["relation_attempted"] == 2
    assert trace["relation_accepted"] == 1
    assert trace["evidence_coverage"] == 0.5
    assert trace["relation_token_estimate"] == 4
    assert trace["filter_reasons"]["relation_workspace"] == 1


def test_retrieval_pipeline_honors_relation_depth_and_node_limit():
    anchor = Document(
        id="anchor", text="answer",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic", "source_ids": ["hop-1"]},
    )
    hop_one = Document(
        id="hop-1", text="first evidence",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic", "source_ids": ["hop-2"]},
    )
    hop_two = Document(
        id="hop-2", text="second evidence",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic"},
    )

    class RelationStore:
        def search_with_rerank(self, query: str, **_kwargs: Any):
            return [(anchor, 1.0)]

        def list_documents(self):
            return [anchor, hop_one, hop_two]

    limited = RetrievalPipeline(RelationStore()).recall(RetrievalRequest(
        query="answer", scope="workspace", workspace_id="default", top_k=3,
        relation_depth=2, relation_limit=1,
    ))
    assert [item["doc"]["id"] for item in limited["results"]] == ["anchor", "hop-1"]
    assert limited["trace"]["expansion_depth"] == 1
    assert limited["trace"]["expansion_truncated"] is True

    expanded = RetrievalPipeline(RelationStore()).recall(RetrievalRequest(
        query="answer", scope="workspace", workspace_id="default", top_k=3,
        relation_depth=2, relation_limit=10,
    ))
    assert [item["doc"]["id"] for item in expanded["results"]] == ["anchor", "hop-1", "hop-2"]
    assert expanded["trace"]["expansion_depth"] == 2
    assert expanded["trace"]["relation_attempted"] == 2
    assert expanded["trace"]["evidence_coverage"] == 1.0


def test_retrieval_pipeline_caches_relation_projection_until_authority_revision_changes():
    anchor = Document(
        id="anchor", text="answer",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic", "source_ids": ["evidence"]},
    )
    evidence = Document(
        id="evidence", text="supporting evidence",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic"},
    )

    class RevisionStore:
        def __init__(self) -> None:
            self.revision = 1
            self.list_calls = 0

        def search_with_rerank(self, query: str, **_kwargs: Any):
            return [(anchor, 1.0)]

        def list_documents(self):
            self.list_calls += 1
            return [anchor, evidence]

        def get_authority_revision(self) -> int:
            return self.revision

    store = RevisionStore()
    pipeline = RetrievalPipeline(store)  # type: ignore[arg-type]
    request = RetrievalRequest(query="answer", scope="workspace", workspace_id="default", top_k=2)

    pipeline.recall(request)
    pipeline.recall(request)
    assert store.list_calls == 1

    store.revision = 2
    pipeline.recall(request)
    assert store.list_calls == 2


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


def test_memory_evaluation_reports_relation_coverage_latency_and_budget():
    report = evaluate_memory_retrieval(
        [{"id": "relation-case", "expected_ids": ["answer"]}],
        lambda _case: {
            "results": [{"doc": {"id": "answer"}}],
            "trace": {
                "latency_ms": 12,
                "relation_attempted": 4,
                "relation_accepted": 3,
                "evidence_coverage": 0.75,
                "relation_latency_ms": 2.5,
                "relation_token_estimate": 40,
            },
        },
    )
    assert report["relation"]["attempted"] == 4
    assert report["relation"]["accepted"] == 3
    assert report["relation"]["evidence_coverage_mean"] == 0.75
    assert report["relation"]["latency_ms"]["mean"] == 2.5
    assert report["relation"]["token_estimate"]["total"] == 40


def test_relation_golden_case_improves_evidence_recall_when_expansion_is_enabled():
    cases = load_golden_cases(Path(__file__).parent / "fixtures" / "memory_relation_golden_cases.json")
    answer = Document(
        id="launch-answer", text="launch is scheduled for Friday",
        metadata={
            "scope": "workspace", "workspace_id": "default", "layer": "semantic",
            "source_ids": ["launch-event", "launch-event-forgotten", "launch-event-other-workspace"],
        },
    )
    event = Document(
        id="launch-event", text="the release meeting confirmed Friday",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic"},
    )
    forgotten = Document(
        id="launch-event-forgotten", text="obsolete release note",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "episodic", "soft_forgotten": True},
    )
    other_workspace = Document(
        id="launch-event-other-workspace", text="other team's release meeting",
        metadata={"scope": "workspace", "workspace_id": "other", "layer": "episodic"},
    )
    region_old = Document(
        id="region-old", text="deployment region is west",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic", "review_status": "superseded"},
    )
    region_current = Document(
        id="region-current", text="deployment region is east",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "semantic"},
    )
    access_expired = Document(
        id="access-expired", text="temporary access code is 1234",
        metadata={"scope": "workspace", "workspace_id": "default", "layer": "working", "expires_at": "2000-01-01T00:00:00Z"},
    )
    results_by_query = {
        "What event supports the launch answer?": [(answer, 0.9)],
        "What is the current deployment region?": [(region_old, 0.99), (region_current, 0.9)],
        "Which temporary access code is still valid?": [(access_expired, 0.95)],
        "What is the user's undisclosed passport number?": [],
    }

    class BenchmarkStore:
        def search_with_rerank(self, query: str, **_kwargs: Any):
            return results_by_query[query]

        def list_documents(self):
            return [answer, event, forgotten, other_workspace, region_old, region_current, access_expired]

    def run(expand: bool):
        pipeline = RetrievalPipeline(BenchmarkStore())
        return evaluate_memory_retrieval(cases, lambda case: pipeline.recall(RetrievalRequest(
            query=str(case["query"]), scope="workspace", workspace_id="default", top_k=2,
            relation_expansion=expand,
        )))

    baseline = run(False)
    expanded = run(True)
    assert baseline["case_count"] == 4
    assert baseline["recall_at_k"] == 0.75
    assert baseline["evidence_quality_pass_rate"] == 0.0
    assert expanded["recall_at_k"] == 1.0
    assert expanded["evidence_quality_pass_rate"] == 1.0
    assert expanded["abstention_pass_rate"] == 1.0
    assert expanded["temporal_consistency_pass_rate"] == 1.0
    assert expanded["lifecycle_leakage_case_count"] == 0
    assert expanded["scope_leakage_case_count"] == 0
    assert expanded["relation"]["accepted"] == 1
    assert expanded["relation"]["attempted"] == 3
    assert expanded["relation"]["token_estimate"]["total"] > 0
