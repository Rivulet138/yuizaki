from modules.system.experience_metrics import ExperienceMetricsStore


def test_renderer_timing_stages_are_bounded_and_reported() -> None:
    metrics = ExperienceMetricsStore(max_entries=10)

    for elapsed_ms in range(10, 110, 10):
        assert metrics.record_client_timing("renderer_lcp", elapsed_ms)
    assert metrics.record_client_timing("socket_connected", 421.2)
    assert not metrics.record_client_timing("renderer_lcp", float("nan"))

    latency = metrics.snapshot()["latency"]
    assert latency["renderer_lcp"] == {
        "samples": 10,
        "latest_ms": 100.0,
        "p50_ms": 55.0,
        "p95_ms": 95.5,
        "p99_ms": 99.1,
    }
    assert latency["socket_connected"]["p50_ms"] == 421.2
    assert latency["socket_connected"]["p99_ms"] == 421.2
