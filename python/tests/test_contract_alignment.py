from __future__ import annotations

import base64
import io
import asyncio
import importlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

import pytest
from PIL import Image

from modules.ocr.recognizer import OCRClient


BuildSnapshot = Callable[..., dict[str, object]]

companion_runtime_module = importlib.import_module("modules.system.companion_runtime")

build_companion_runtime_snapshot = cast(
    BuildSnapshot,
    getattr(companion_runtime_module, "build_companion_runtime_snapshot"),
)


@dataclass
class EmptyMemoryState:
    store: "EmptyStore"


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
    def __call__(self, _image: Image.Image):
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
