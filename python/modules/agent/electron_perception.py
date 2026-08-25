"""Authenticated Electron-main perception transport."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .perception import PerceptionProviderError, PerceptionRequest


@dataclass
class ElectronPerceptionCollector:
    capability: str
    origin: str = ""
    backend_token: str = ""
    host_perception_token: str = ""
    timeout_seconds: float = 12.0
    transport: httpx.AsyncBaseTransport | None = None

    def __post_init__(self) -> None:
        if not self.origin:
            port = str(os.getenv("CONTROL_SERVER_PORT") or "38945").strip()
            self.origin = f"http://127.0.0.1:{port}"
        if not self.backend_token:
            self.backend_token = os.getenv("YUIZAKI_BACKEND_API_TOKEN", "").strip()
        if not self.host_perception_token:
            self.host_perception_token = os.getenv("YUIZAKI_HOST_PERCEPTION_TOKEN", "").strip()

    async def collect(self, request: PerceptionRequest) -> dict[str, Any]:
        if not self.backend_token or not self.host_perception_token:
            raise PerceptionProviderError("electron perception transport is not authenticated")
        route = self.capability.replace("_", "-")
        body = {
            "scope": {
                "workspaceId": request.workspace_id,
                "sessionId": request.session_id,
                "turnId": request.turn_id,
                "requestId": request.request_id,
                "generationId": request.generation_id,
                "interruptionEpoch": request.interruption_epoch,
            },
        }
        timeout = min(
            self.timeout_seconds,
            max(0.1, (request.expires_at or (request.issued_at + self.timeout_seconds)) - request.issued_at),
        )
        async with httpx.AsyncClient(timeout=timeout, transport=self.transport) as client:
            response = await client.post(
                f"{self.origin}/api/perception/collect-{route}",
                headers={
                    "Authorization": f"Bearer {self.backend_token}",
                    "x-yuizaki-host-perception-token": self.host_perception_token,
                },
                json=body,
            )
        payload = response.json() if response.content else {}
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise PerceptionProviderError("electron perception provider unavailable")
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            raise PerceptionProviderError("electron perception returned an invalid evidence envelope")
        return evidence
