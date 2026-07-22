from evals.metrics import (
    character_error_rate,
    embedding_recall_at_k,
    real_time_factor,
    tool_success_rate,
    token_error_rate,
)
import pytest
from evals.suite import DEFAULT_FIXTURE, load_fixture, run_suite


def test_error_metrics_handle_chinese_and_spaced_text():
    assert token_error_rate("你好 世界", "你好 世界") == 0.0
    assert character_error_rate("你好世界", "你好世") == 0.25


def test_latency_and_retrieval_metrics_are_bounded():
    assert real_time_factor(250, 2.0) == 0.125
    assert tool_success_rate(["read_file", "open_url"], ["read_file"]) == 0.5
    assert embedding_recall_at_k(["a", "b"], ["b", "c", "a"], 2) == 0.5


def test_tool_success_rate_counts_repeated_expected_calls():
    assert tool_success_rate(["read_file", "read_file"], ["read_file"]) == 0.5


def test_default_smoke_fixture_passes_all_quality_gates():
    result = run_suite(load_fixture(DEFAULT_FIXTURE))
    assert result["passed"] is True
    assert result["metrics"]["asr"]["wer"] == 0.0
    assert result["metadata"]["source"] == "synthetic-ci-smoke"
    assert result["failures"] == []


def test_threshold_overrides_report_actionable_failures():
    fixture = load_fixture(DEFAULT_FIXTURE)
    result = run_suite(fixture, threshold_overrides={"tts_rtf_max": 0.01})
    assert result["passed"] is False
    assert result["failures"][0]["metric"] == "tts.rtf"
    assert result["failures"][0]["actual"] == pytest.approx(0.12)
    assert result["failures"][0]["threshold"] == 0.01


def test_fixture_requires_all_suites_and_provenance():
    fixture = load_fixture(DEFAULT_FIXTURE)
    fixture.pop("embedding")
    try:
        run_suite(fixture)
    except ValueError as exc:
        assert "embedding" in str(exc)
    else:
        raise AssertionError("missing suite should fail validation")
