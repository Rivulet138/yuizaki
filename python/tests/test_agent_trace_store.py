from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from modules.agent.agent_trace_store import AgentTraceStore


def _step(index: int, **extra: object) -> dict[str, object]:
    return {
        "timestamp": str(index),
        "kind": "tool",
        "status": "completed",
        "step_id": f"step-{index}",
        "tool": "demo",
        "success": True,
        **extra,
    }


def test_trace_append_and_snapshot_redact_and_bound_nested_values(tmp_path) -> None:
    store = AgentTraceStore(tmp_path / "trace.json", max_entries=10)
    store.append("steps", _step(1, args={"api_key": "secret", "nested": {"value": "x" * 600}}, prompt="p" * 700))

    snapshot = store.snapshot()
    record = snapshot["steps"][0]
    assert record["args"]["api_key"] == "[REDACTED]"
    assert record["args"]["nested"]["value"].endswith("...")
    assert len(record["prompt"]) == 512
    assert "secret" not in json.dumps(snapshot)


def test_trace_load_sanitizes_legacy_persisted_payload(tmp_path) -> None:
    path = tmp_path / "trace.json"
    path.write_text(json.dumps({"steps": [_step(1, args={"password": "legacy-secret", "items": list(range(100))})]}), encoding="utf-8")
    store = AgentTraceStore(path, max_entries=10)
    record = store.snapshot()["steps"][0]
    assert record["args"]["password"] == "[REDACTED]"
    assert len(record["args"]["items"]) == 17
    assert "legacy-secret" not in path.read_text(encoding="utf-8")


def test_trace_append_is_concurrency_safe(tmp_path) -> None:
    store = AgentTraceStore(tmp_path / "trace.json", max_entries=100)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: store.append("steps", _step(index)), range(80)))

    records = store.snapshot()["steps"]
    assert len(records) == 80
    assert {record["step_id"] for record in records} == {f"step-{index}" for index in range(80)}


def test_trace_append_once_sanitizes_before_durable_write(tmp_path) -> None:
    path = tmp_path / "trace.json"
    store = AgentTraceStore(path, max_entries=10)

    assert store.append_once(
        "steps",
        _step(1, args={"authorization": "Bearer leaked-token", "nested": "z" * 700}),
        projection_key="projection-1",
    ) is True

    persisted = path.read_text(encoding="utf-8")
    assert "leaked-token" not in persisted
    assert "Bearer" not in persisted
    record = store.snapshot()["steps"][0]
    assert record["args"]["authorization"] == "[REDACTED]"
    assert record["args"]["nested"].endswith("...")


def test_trace_sanitizes_token_bearing_text_values(tmp_path) -> None:
    store = AgentTraceStore(tmp_path / "trace.json", max_entries=10)
    store.append_once(
        "steps",
        _step(1, error="GET https://example.test/?token=secret-value failed: Bearer another-secret"),
        projection_key="text-projection",
    )

    persisted = (tmp_path / "trace.json").read_text(encoding="utf-8")
    assert "secret-value" not in persisted
    assert "another-secret" not in persisted
