from __future__ import annotations

import asyncio

import pytest
from modules.system import provider_registry
from modules.system.provider_registry import build_provider_registry_snapshot


class LocalProvider:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.delay = 0.0
        self.close_connection = False
        self.server: asyncio.Server | None = None
        self.host = "127.0.0.1"
        self.port: int | None = None

    async def start(self) -> str:
        self.server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return f"http://{self.host}:{self.port}"

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.close_connection:
                writer.close()
                await writer.wait_closed()
                return
            body = b'{"models": []}'
            writer.write(
                f"HTTP/1.1 {self.status} Test\r\nContent-Length: {len(body)}\r\n"
                "Content-Type: application/json\r\nConnection: close\r\n\r\n".encode() + body,
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def probe(self, timeout: float = 0.5) -> tuple[bool, str]:
        if self.port is None or self.server is None:
            raise ConnectionError("provider has not been started")
        writer: asyncio.StreamWriter | None = None
        try:
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout)
            except TimeoutError as exc:
                raise ConnectionError("connection refused") from exc
            writer.write(b"GET /models HTTP/1.1\r\nHost: local-provider\r\nConnection: close\r\n\r\n")
            await writer.drain()
            response = await asyncio.wait_for(reader.read(), timeout)
            if not response or not response.startswith(b"HTTP/1.1 "):
                return False, "Provider returned an invalid response"
            status = int(response.split(b" ", 2)[1])
            return status < 400, f"HTTP {status}"
        except (ConnectionError, OSError):
            raise ConnectionError("connection refused")
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_local_provider_http_failures_are_degraded(status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LocalProvider(status)
    url = await provider.start()
    monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.5)
    try:
        snapshot = await build_provider_registry_snapshot(
            config_snapshot_provider=lambda: {"llm": {"provider": "custom", "base_url": url, "model": "test"}},
            health_providers={"llm": provider.probe},
            client_providers={"llm": lambda: object()},
        )
        llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
        assert llm["healthy"] is False
        assert llm["retryable"] is True
        assert llm["message"] == f"HTTP {status}"
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_local_provider_timeout_and_socket_close_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LocalProvider()
    url = await provider.start()
    monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.05)
    try:
        provider.delay = 0.2
        timed_out = await provider_registry._probe_health(provider.probe, True)
        assert timed_out == (False, "Health probe timed out")
        provider.delay = 0.0
        provider.close_connection = True
        closed = await provider_registry._probe_health(provider.probe, True)
        assert closed[0] is False
        assert closed[1] == "Provider returned an invalid response"
        assert url.startswith("http://127.0.0.1:")
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_stale_failure_clears_after_local_provider_recovery_and_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LocalProvider(503)
    url = await provider.start()
    monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.5)
    def config() -> dict[str, object]:
        return {"llm": {"provider": "custom", "base_url": url, "model": "test"}}
    try:
        failed = await build_provider_registry_snapshot(
            config_snapshot_provider=config,
            health_providers={"llm": provider.probe},
            client_providers={"llm": lambda: object()},
        )
        assert failed["summary"]["requiredHealthy"] is False
        await provider.stop()
        refused = await provider_registry._probe_health(provider.probe, True)
        assert refused == (False, "Provider connection unavailable")
        provider = LocalProvider(200)
        url = await provider.start()
        recovered = await build_provider_registry_snapshot(
            config_snapshot_provider=lambda: {"llm": {"provider": "custom", "base_url": url, "model": "test"}},
            health_providers={"llm": provider.probe},
            client_providers={"llm": lambda: object()},
        )
        assert next(item for item in recovered["providers"] if item["id"] == "llm")["healthy"] is True
        assert recovered["summary"]["requiredHealthy"] is True
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_optional_provider_failure_does_not_block_text_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LocalProvider(200)
    url = await provider.start()
    monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.5)
    try:
        async def optional_failure() -> tuple[bool, str]:
            return False, "optional provider offline"

        snapshot = await build_provider_registry_snapshot(
            config_snapshot_provider=lambda: {
                "llm": {"provider": "custom", "base_url": url, "model": "test"},
                "tts": {"provider": "optional", "base_url": url, "model": "voice"},
            },
            health_providers={"llm": provider.probe, "tts": optional_failure},
            client_providers={"llm": lambda: object(), "tts": lambda: object()},
        )
        assert snapshot["summary"]["requiredHealthy"] is True
        assert next(item for item in snapshot["providers"] if item["id"] == "tts")["healthy"] is False
    finally:
        await provider.stop()
