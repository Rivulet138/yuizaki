from __future__ import annotations

import asyncio
import base64
import copy
import importlib
import io
import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

import pytest
from modules.ocr.recognizer import OCRClient
from PIL import Image

BuildSnapshot = Callable[..., dict[str, object]]

companion_runtime_module = importlib.import_module("modules.system.companion_runtime")

build_companion_runtime_snapshot = cast(
    BuildSnapshot,
    vars(companion_runtime_module)["build_companion_runtime_snapshot"],
)


@dataclass
class EmptyMemoryState:
    store: EmptyStore


class EmptyStore:
    def list_documents(self) -> list[object]:
        return []


@dataclass
class RuntimeDoc:
    id: str
    text: str
    metadata: dict[str, object]


class RuntimeStore:
    def __init__(self, docs: list[RuntimeDoc]):
        self._docs = docs

    def list_documents(self) -> list[RuntimeDoc]:
        return list(self._docs)


@dataclass
class RuntimeMemoryState:
    store: RuntimeStore


class EmptyRepo:
    def get_workspace_companion(self, _workspace_id: str) -> None:
        return None


class CompanionStateRepo:
    def get_workspace_companion(self, workspace_id: str) -> dict[str, object]:
        return {
            "id": f"companion-{workspace_id}",
            "emotion_state": "focused",
            "energy_state": 0.42,
            "trust_state": 0.81,
            "intimacy_state": 0.63,
            "interruptibility_state": 0.27,
            "fatigue_state": 0.36,
            "support_style": "gentle",
        }


class RuntimeJobEventSource:
    def __init__(self, events: list[dict[str, object]]):
        self.events = events

    def snapshot(self) -> list[dict[str, object]]:
        return self.events

    def snapshot_job_events(self) -> list[dict[str, object]]:
        return self.events

    def active_job_ids(self) -> list[str]:
        return ["job-1"]


def _empty_relationship_summary(events: Sequence[object]) -> dict[str, object]:
    return {
        "event_count": len(events),
        "high_importance_count": 0,
        "global_count": 0,
        "workspace_count": 0,
        "milestone_count": 0,
        "recent_trust_shift_count": 0,
        "recent_gratitude_count": 0,
        "relationship_stage": "warming",
        "proactive_budget": 1,
        "relationship_trend": "stable",
    }


def _is_relationship_milestone(_kind: str, _importance: object) -> bool:
    return False


def test_companion_runtime_empty_snapshot_matches_frontend_memory_contract():
    snapshot = build_companion_runtime_snapshot(
        active_workspace_id="workspace-1",
        db_repo=EmptyRepo(),
        heartbeat_scheduler=None,
        memory_state=EmptyMemoryState(store=EmptyStore()),
        summarize_relationship_events=_empty_relationship_summary,
        is_relationship_milestone=_is_relationship_milestone,
        limit=4,
    )

    assert snapshot["active_workspace_id"] == "workspace-1"
    assert snapshot["active_companion"] is None
    assert snapshot["jobs"] == {"events": [], "active_job_ids": []}
    assert snapshot["memory_state"] == {
        "profile_count": 0,
        "semantic_count": 0,
        "episodic_count": 0,
        "relationship_count": 0,
        "working_count": 0,
        "reflective_count": 0,
        "recent_signals": [],
        "signal_summary": {},
    }


@pytest.mark.parametrize("source_kind", ["job_event_log", "scheduler"])
def test_companion_runtime_projects_bounded_redacted_job_events_without_mutating_source(source_kind: str):
    event = {
        "version": 1,
        "type": "companion.job.failed",
        "workspaceId": "workspace-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "jobId": "job-1",
        "requestId": "request-1",
        "revision": 7,
        "interruptionEpoch": 2,
        "source": "tool",
        "timestamp": 1234.0,
        "status": "failed",
        "data": {
            "args": {
                "path": "notes.txt",
                "api_key": "args-secret",
                "nested": {
                    "Authorization": "Bearer nested-secret-token",
                    "detail": "token=inline-secret-token",
                },
            },
            "toolName": "write_file",
            "retryable": True,
            "replayArgsAvailable": True,
            "recheckAvailable": True,
            "effectOutcome": "unknown_effect",
            "verification": {
                "status": "error",
                "evidence": [f"evidence-{index}" for index in range(40)],
            },
            "recovery": {
                "available": True,
                "action": "resume_failed_step",
                "retryable": True,
                "handle": "rh_recovery_handle",
            },
            "failure": {
                "category": "provider_timeout",
                "failedStep": "write-output",
                "message": "Authorization: Bearer failure-secret-token",
            },
            "longText": "x" * 2000,
            "longList": list(range(100)),
            "longDict": {f"key-{index}": index for index in range(100)},
        },
    }
    source = RuntimeJobEventSource([event])
    before = copy.deepcopy(source.events)
    source_argument = {source_kind: source}

    snapshot = build_companion_runtime_snapshot(
        active_workspace_id="workspace-1",
        db_repo=EmptyRepo(),
        heartbeat_scheduler=None,
        memory_state=EmptyMemoryState(store=EmptyStore()),
        summarize_relationship_events=_empty_relationship_summary,
        is_relationship_milestone=_is_relationship_milestone,
        limit=4,
        **source_argument,
    )

    jobs = cast(dict[str, object], snapshot["jobs"])
    projected = cast(list[dict[str, object]], jobs["events"])[0]
    for key in (
        "version", "type", "workspaceId", "sessionId", "turnId", "jobId",
        "requestId", "revision", "interruptionEpoch", "source", "timestamp", "status",
    ):
        assert projected[key] == event[key]
    data = cast(dict[str, object], projected["data"])
    for key in (
        "args", "toolName", "retryable", "replayArgsAvailable", "recheckAvailable",
        "effectOutcome", "verification", "recovery", "failure",
    ):
        assert key in data
    assert data["toolName"] == "write_file"
    assert data["retryable"] is True
    assert data["replayArgsAvailable"] is True
    assert data["recheckAvailable"] is True
    assert data["effectOutcome"] == "unknown_effect"
    assert len(cast(str, data["longText"])) <= 512
    assert len(cast(list[object], data["longList"])) <= 16
    assert len(cast(dict[str, object], data["longDict"])) <= 32
    verification = cast(dict[str, object], data["verification"])
    assert verification["status"] == "error"
    assert len(cast(list[object], verification["evidence"])) <= 16
    recovery = cast(dict[str, object], data["recovery"])
    assert recovery["handle"] == "rh_recovery_handle"
    failure = cast(dict[str, object], data["failure"])
    assert failure["category"] == "provider_timeout"
    args = cast(dict[str, object], data["args"])
    assert args["path"] == "notes.txt"
    assert args["api_key"] == "[REDACTED]"
    serialized = json.dumps(projected)
    assert "args-secret" not in serialized
    assert "nested-secret-token" not in serialized
    assert "inline-secret-token" not in serialized
    assert "failure-secret-token" not in serialized
    assert source.events == before


def test_companion_runtime_uses_persisted_companion_state_fields():
    snapshot = build_companion_runtime_snapshot(
        active_workspace_id="workspace-1",
        db_repo=CompanionStateRepo(),
        heartbeat_scheduler=None,
        memory_state=EmptyMemoryState(store=EmptyStore()),
        summarize_relationship_events=_empty_relationship_summary,
        is_relationship_milestone=_is_relationship_milestone,
        limit=4,
    )

    assert snapshot["companion_state"] == {
        "mood": "focused",
        "energy": 0.42,
        "trust": 0.81,
        "intimacy": 0.63,
        "interruptibility": 0.27,
        "fatigue": 0.36,
        "stage": "warming",
        "proactive_state": None,
        "behavior_profile": None,
    }


def test_companion_runtime_isolates_memory_by_active_workspace():
    snapshot = build_companion_runtime_snapshot(
        active_workspace_id="workspace-1",
        db_repo=CompanionStateRepo(),
        heartbeat_scheduler=None,
        memory_state=RuntimeMemoryState(
            store=RuntimeStore(
                [
                    RuntimeDoc(
                        id="other-profile",
                        text="other preference",
                        metadata={
                            "layer": "profile",
                            "type": "preference",
                            "scope": "workspace",
                            "workspace_id": "workspace-2",
                        },
                    ),
                    RuntimeDoc(
                        id="workspace-profile",
                        text="workspace preference",
                        metadata={
                            "layer": "profile",
                            "type": "preference",
                            "scope": "workspace",
                            "workspace_id": "workspace-1",
                        },
                    ),
                    RuntimeDoc(
                        id="other-relationship",
                        text="other relationship",
                        metadata={
                            "layer": "relationship",
                            "scope": "workspace",
                            "workspace_id": "workspace-2",
                            "companion_id": "companion-workspace-1",
                            "event_type": "relationship_state",
                            "relationship_event": {"kind": "support_request"},
                        },
                    ),
                ]
            )
        ),
        summarize_relationship_events=_empty_relationship_summary,
        is_relationship_milestone=_is_relationship_milestone,
        limit=4,
    )

    memory_state = cast(dict[str, object], snapshot["memory_state"])
    assert memory_state["profile_count"] == 1
    assert memory_state["relationship_count"] == 0
    assert memory_state["signal_summary"] == {"preference": 1}
    relationship = cast(dict[str, object], snapshot["relationship"])
    assert relationship["events"] == []


class _FakeOcrEngine:
    def __call__(self, image: bytes):
        assert isinstance(image, bytes)
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        return (
            [
                (
                    [[1, 2], [5, 2], [5, 8], [1, 8]],
                    "screen text",
                    0.93,
                )
            ],
            None,
        )


def _tiny_png_data_url() -> str:
    image = Image.new("RGB", (2, 2), color=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}"


@pytest.mark.asyncio
async def test_ocr_client_accepts_data_url_payload_and_normalizes_blocks():
    client = OCRClient()
    client._ocr = _FakeOcrEngine()
    client._available = True

    result = await client.recognize(_tiny_png_data_url())

    assert result == {
        "status": "ok",
        "text": "screen text",
        "blocks": [
            {
                "text": "screen text",
                "bbox": [1.0, 2.0, 4.0, 6.0],
                "confidence": 0.93,
            }
        ],
    }


@pytest.mark.asyncio
async def test_ocr_client_initializes_once_on_demand_without_blocking_event_loop(monkeypatch: pytest.MonkeyPatch):
    client = OCRClient()
    initialization_calls = 0

    def create_engine():
        nonlocal initialization_calls
        initialization_calls += 1
        time.sleep(0.08)
        return _FakeOcrEngine()

    monkeypatch.setattr(client, "_create_engine", create_engine)
    assert client.initialization_state == "idle"

    started = time.perf_counter()
    requests = asyncio.gather(
        client.recognize(_tiny_png_data_url()),
        client.recognize(_tiny_png_data_url()),
    )
    await asyncio.sleep(0.01)
    event_loop_delay_ms = (time.perf_counter() - started) * 1000
    results = await requests

    assert event_loop_delay_ms < 50
    assert initialization_calls == 1
    assert client.initialization_state == "ready"
    assert [result["status"] for result in results] == ["ok", "ok"]


@pytest.mark.asyncio
async def test_ocr_client_offloads_recognition_and_serializes_engine_calls():
    client = OCRClient()
    active_calls = 0
    max_active_calls = 0
    counter_lock = threading.Lock()

    class SlowOcrEngine:
        def __call__(self, image: bytes):
            nonlocal active_calls, max_active_calls
            assert isinstance(image, bytes)
            with counter_lock:
                active_calls += 1
                max_active_calls = max(max_active_calls, active_calls)
            time.sleep(0.08)
            with counter_lock:
                active_calls -= 1
            return ([], None)

    client._ocr = SlowOcrEngine()
    client._available = True

    started = time.perf_counter()
    requests = asyncio.gather(
        client.recognize(_tiny_png_data_url()),
        client.recognize(_tiny_png_data_url()),
    )
    await asyncio.sleep(0.01)
    event_loop_delay_ms = (time.perf_counter() - started) * 1000
    results = await requests

    assert event_loop_delay_ms < 50
    assert max_active_calls == 1
    assert [result["status"] for result in results] == ["ok", "ok"]


@pytest.mark.asyncio
async def test_ocr_disconnect_waits_for_active_recognition():
    client = OCRClient()
    recognition_started = threading.Event()
    allow_recognition_to_finish = threading.Event()

    class BlockingOcrEngine:
        def __call__(self, image: bytes):
            assert isinstance(image, bytes)
            recognition_started.set()
            assert allow_recognition_to_finish.wait(timeout=2)
            return ([], None)

    client._ocr = BlockingOcrEngine()
    client._available = True
    recognition = asyncio.create_task(client.recognize(_tiny_png_data_url()))
    assert await asyncio.to_thread(recognition_started.wait, 1)

    disconnect = asyncio.create_task(client.disconnect())
    await asyncio.sleep(0)
    assert not disconnect.done()

    allow_recognition_to_finish.set()
    assert (await recognition)["status"] == "ok"
    await disconnect
    assert client.initialization_state == "idle"


@pytest.mark.asyncio
async def test_ocr_client_preserves_engine_error_status():
    client = OCRClient()

    class FailingOcrEngine:
        def __call__(self, image: bytes):
            assert isinstance(image, bytes)
            raise ValueError("invalid OCR input")

    client._ocr = FailingOcrEngine()
    client._available = True

    result = await client.recognize(_tiny_png_data_url())

    assert result == {
        "status": "error",
        "error": "invalid OCR input",
        "text": "",
        "blocks": [],
    }
