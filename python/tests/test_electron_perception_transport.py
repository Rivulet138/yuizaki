from __future__ import annotations

import json

import httpx
import pytest
from modules.agent.electron_perception import ElectronPerceptionCollector
from modules.agent.perception import PerceptionProviderError, PerceptionRequest


def _request() -> PerceptionRequest:
    return PerceptionRequest(
        workspace_id="workspace-1",
        session_id="session-1",
        turn_id="turn-1",
        request_id="request-1",
        generation_id="generation-1",
        interruption_epoch=4,
        capability="clipboard",
    )


@pytest.mark.asyncio
async def test_electron_transport_sends_authenticated_exact_scope_and_returns_host_envelope() -> None:
    request = _request()

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/api/perception/collect-clipboard"
        assert http_request.headers["Authorization"] == "Bearer backend-secret"
        assert http_request.headers["x-yuizaki-host-perception-token"] == "host-secret"
        body = json.loads(http_request.content)
        assert body == {
            "scope": {
                "workspaceId": request.workspace_id,
                "sessionId": request.session_id,
                "turnId": request.turn_id,
                "requestId": request.request_id,
                "generationId": request.generation_id,
                "interruptionEpoch": request.interruption_epoch,
            },
        }
        return httpx.Response(200, json={
            "ok": True,
            "evidence": {
                "provider": "electron-clipboard",
                "capability": "clipboard",
                "workspace_id": request.workspace_id,
                "session_id": request.session_id,
                "turn_id": request.turn_id,
                "request_id": request.request_id,
                "generation_id": request.generation_id,
                "interruption_epoch": request.interruption_epoch,
                "captured_at": request.issued_at,
                "expires_at": request.issued_at + 5,
                "payload": {"text": "hello"},
            },
        })

    collector = ElectronPerceptionCollector(
        "clipboard",
        origin="http://127.0.0.1:38945",
        backend_token="backend-secret",
        host_perception_token="host-secret",
        transport=httpx.MockTransport(handler),
    )
    evidence = await collector.collect(request)
    assert evidence["request_id"] == request.request_id


@pytest.mark.asyncio
async def test_electron_transport_fails_closed_without_auth_or_valid_evidence() -> None:
    with pytest.raises(PerceptionProviderError, match="not authenticated"):
        await ElectronPerceptionCollector("clipboard", origin="http://host", backend_token="").collect(_request())

    collector = ElectronPerceptionCollector(
        "clipboard",
        origin="http://host",
        backend_token="token",
        host_perception_token="host-token",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True})),
    )
    with pytest.raises(PerceptionProviderError, match="invalid evidence"):
        await collector.collect(_request())
