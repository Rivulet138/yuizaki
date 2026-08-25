from __future__ import annotations

import time
from dataclasses import replace
from types import MethodType
from unittest.mock import AsyncMock

import pytest
from modules.agent.perception import PerceptionEvidence, PerceptionRequest
from socket_server import DesktopPetSocketServer


def _request(capability: str, **metadata: object) -> PerceptionRequest:
    return PerceptionRequest(
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        request_id="request-1",
        generation_id="generation-1",
        interruption_epoch=4,
        capability=capability,
        metadata={"sid": "socket-1", **metadata},
    )


def _screenshot_evidence() -> PerceptionEvidence:
    captured_at = time.time()
    return PerceptionEvidence(
        evidence_id="frame-current",
        provider="desktop-screenshot",
        capability="screenshot",
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        request_id="request-1",
        generation_id="generation-1",
        interruption_epoch=4,
        payload={"image": "aW1hZ2U="},
        captured_at=captured_at,
        expires_at=captured_at + 10,
        redacted=False,
        provenance={"trust": "untrusted", "authority": "evidence"},
    )


@pytest.mark.asyncio
async def test_authorized_screenshot_rejects_an_unrelated_latest_frame() -> None:
    server = object.__new__(DesktopPetSocketServer)
    server._request_visual_capture = AsyncMock(return_value="frame-current")
    server._latest_visual_frame_for_sid = MethodType(
        lambda _self, _sid: {
            "frame_id": "frame-stale",
            "job_id": "vision:other-request",
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "request_id": "other-request",
            "interruption_epoch": 4,
        },
        server,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await server._collect_authorized_screenshot(_request("screenshot"))


@pytest.mark.asyncio
async def test_authorized_ocr_reads_only_the_supplied_screenshot_evidence() -> None:
    server = object.__new__(DesktopPetSocketServer)
    recognize = AsyncMock(return_value={"text": "recognized", "blocks": []})
    server.ocr_client = type("OcrClient", (), {"recognize": recognize})()
    source = _screenshot_evidence()

    result = await server._collect_authorized_ocr(
        _request("ocr", source_evidence=source),
    )

    recognize.assert_awaited_once_with("aW1hZ2U=")
    assert result["evidence_id"] == "ocr:frame-current"
    assert result["request_id"] == "request-1"


@pytest.mark.asyncio
async def test_authorized_ocr_rejects_cross_request_screenshot_evidence() -> None:
    server = object.__new__(DesktopPetSocketServer)
    recognize = AsyncMock(return_value={"text": "must not run"})
    server.ocr_client = type("OcrClient", (), {"recognize": recognize})()
    source = replace(_screenshot_evidence(), request_id="other-request")

    with pytest.raises(RuntimeError, match="scope mismatch"):
        await server._collect_authorized_ocr(
            _request("ocr", source_evidence=source),
        )
    recognize.assert_not_awaited()
