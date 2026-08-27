from __future__ import annotations

import pytest
from modules.system.health_providers import build_app_runtime_health_providers


class _FakeLlm:
    def __init__(self, outcomes: list[bool]) -> None:
        self.outcomes = outcomes
        self.last_ok: bool | None = None

    async def preconnect(self, *, force: bool = False) -> bool:
        del force
        self.last_ok = self.outcomes.pop(0)
        return self.last_ok

    def status_snapshot(self) -> dict[str, object]:
        return {"last_preconnect_ok": self.last_ok}


@pytest.mark.asyncio
async def test_llm_health_requires_upstream_probe_and_recovers() -> None:
    client = _FakeLlm([False, True])
    providers = build_app_runtime_health_providers(
        llm_client_provider=lambda: client,
        tts_client_provider=lambda: None,
        asr_manager_provider=lambda: None,
        ocr_client_provider=lambda: None,
        database_repository_provider=lambda: None,
        memory_state_provider=lambda: None,
    )

    assert await providers.llm() == (False, "LLM provider unavailable")
    assert await providers.llm() == (True, "LLM service healthy")
