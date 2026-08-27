from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from modules.system import provider_registry
from modules.system.provider_registry import build_provider_registry_snapshot
from routes.system_api import create_system_router

PROVIDER_FAILURE_MATRIX = json.loads(
    (Path(__file__).parent / "fixtures" / "provider_failure_matrix.json").read_text(encoding="utf-8")
)


def test_provider_registry_projects_config_runtime_and_redacts_messages() -> None:
    async def llm_health() -> tuple[bool, str]:
        return False, "upstream rejected api_key=secret-value"

    async def tts_health() -> tuple[bool, str]:
        return True, "TTS ready"

    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {
            "llm": {
                "provider": "openai",
                "model": "gpt-local",
                "base_url": "http://127.0.0.1:1234/v1",
                "vision_enabled": True,
                "vision_provider": "openai",
                "vision_model": "vision-local",
            },
            "tts": {"provider": "genie-tts", "model": "tts-1"},
            "asr": {"provider": "disabled"},
        },
        health_providers={"llm": llm_health, "tts": tts_health},
        client_providers={"llm": lambda: object(), "tts": lambda: object(), "vision": lambda: object(), "asr": lambda: None},
    ))

    by_id = {item["id"]: item for item in snapshot["providers"]}
    assert snapshot["schemaVersion"] == 1
    assert by_id["llm"]["configured"] is True
    assert by_id["llm"]["healthy"] is False
    assert by_id["llm"]["retryable"] is True
    assert "secret-value" not in by_id["llm"]["message"]
    assert by_id["vision"]["available"] is True
    assert by_id["asr"]["configured"] is False
    assert by_id["asr"]["retryable"] is False
    assert snapshot["summary"]["requiredHealthy"] is False


@pytest.mark.parametrize(
    "unsafe_message",
    [
        "Authorization: Bearer short-secret",
        "token=secret-value",
        'request failed: {"token": "quoted-secret"}',
        "upstream https://user:password@provider.example/v1 failed",
    ],
)
def test_provider_registry_redacts_sensitive_diagnostic_message_variants(unsafe_message: str) -> None:
    async def failed_health() -> tuple[bool, str]:
        return False, unsafe_message

    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {"llm": {"provider": "custom", "model": "chat"}},
        health_providers={"llm": failed_health},
        client_providers={"llm": lambda: object()},
    ))

    llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
    assert all(secret not in llm["message"] for secret in ("short-secret", "secret-value", "quoted-secret", "password"))
    assert "redacted" in llm["message"]


def test_provider_registry_surfaces_config_snapshot_exception_without_masking_runtime() -> None:
    def broken_config() -> dict[str, object]:
        raise RuntimeError("token=config-secret")

    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=broken_config,
        health_providers={"llm": lambda: asyncio.sleep(0, result=(True, "ok"))},
        client_providers={"llm": lambda: object()},
    ))

    llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
    assert llm["available"] is True
    assert llm["healthy"] is False
    assert llm["message"] == "Provider configuration status unavailable"
    assert llm["diagnosticError"].startswith("CONFIG_SNAPSHOT_FAILED: RuntimeError:")
    assert "config-secret" not in llm["diagnosticError"]
    assert snapshot["summary"]["requiredHealthy"] is False


def test_provider_registry_surfaces_client_provider_exception() -> None:
    def broken_client() -> object:
        raise RuntimeError('Authorization: Bearer client-secret')

    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {"llm": {"provider": "custom", "model": "chat"}},
        health_providers={"llm": lambda: asyncio.sleep(0, result=(True, "ok"))},
        client_providers={"llm": broken_client},
    ))

    llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
    assert llm["configured"] is True
    assert llm["available"] is False
    assert llm["healthy"] is False
    assert llm["message"] == "Provider runtime lookup failed"
    assert llm["diagnosticError"].startswith("CLIENT_PROVIDER_FAILED: RuntimeError:")
    assert "client-secret" not in llm["diagnosticError"]
    assert snapshot["summary"]["requiredHealthy"] is False


def test_provider_registry_handles_uninitialized_required_provider() -> None:
    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {"llm": {"provider": "custom", "model": "chat"}},
        health_providers={"llm": lambda: asyncio.sleep(0, result=(True, "ok"))},
        client_providers={"llm": lambda: None, "tts": lambda: None, "asr": lambda: None, "vision": lambda: None},
    ))

    llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
    assert llm["configured"] is True
    assert llm["available"] is False
    assert llm["healthy"] is False
    assert llm["message"] == "已配置但运行时未初始化"
    assert llm["retryable"] is True


def test_provider_registry_marks_configured_asr_without_runtime_unavailable() -> None:
    snapshot = asyncio.run(build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {"asr": {"provider": "whisper", "model": "base"}},
        health_providers={"asr": lambda: asyncio.sleep(0, result=(True, "optional"))},
        client_providers={"asr": lambda: None},
    ))
    asr = next(item for item in snapshot["providers"] if item["id"] == "asr")
    assert asr["configured"] is True
    assert asr["available"] is False
    assert asr["healthy"] is False
    assert asr["retryable"] is True


def test_provider_registry_times_out_a_stalled_health_probe(monkeypatch) -> None:
    monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.01)

    async def stalled_health() -> tuple[bool, str]:
        await asyncio.sleep(30)
        return True, "late success"

    snapshot = asyncio.run(provider_registry.build_provider_registry_snapshot(
        config_snapshot_provider=lambda: {"llm": {"provider": "custom", "model": "chat"}},
        health_providers={"llm": stalled_health},
        client_providers={"llm": lambda: object(), "tts": lambda: None, "asr": lambda: None, "vision": lambda: None},
    ))

    llm = next(item for item in snapshot["providers"] if item["id"] == "llm")
    assert llm["available"] is True
    assert llm["healthy"] is False
    assert llm["message"] == "Health probe timed out"


@pytest.mark.parametrize("case", PROVIDER_FAILURE_MATRIX, ids=lambda item: item["name"])
def test_provider_registry_failure_matrix(case: dict[str, object], monkeypatch) -> None:
    if "providers" in case:
        config = case["config"]
        provider_specs = case["providers"]
        assert isinstance(config, dict)
        assert isinstance(provider_specs, dict)
        probes = {}
        clients = {}
        for provider_id, raw_spec in provider_specs.items():
            assert isinstance(raw_spec, dict)
            probe_kind = str(raw_spec["probe"])
            probes[str(provider_id)] = _matrix_probe(probe_kind)
            clients[str(provider_id)] = (
                (lambda: object())
                if bool(raw_spec["client_available"])
                else (lambda: None)
            )
        snapshot = asyncio.run(build_provider_registry_snapshot(
            config_snapshot_provider=lambda: config,
            health_providers=probes,
            client_providers=clients,
        ))
        by_id = {item["id"]: item for item in snapshot["providers"]}
        expected_providers = case["expected_providers"]
        assert isinstance(expected_providers, dict)
        for provider_id, expected in expected_providers.items():
            assert isinstance(expected, dict)
            for key, value in expected.items():
                assert by_id[provider_id][key] == value
        expected_summary = case["expected_summary"]
        assert isinstance(expected_summary, dict)
        for key, value in expected_summary.items():
            assert snapshot["summary"][key] == value
        return

    target = str(case["target"])
    probe_sequence = case.get("probe_sequence")
    if isinstance(probe_sequence, list):
        sequence = [str(item) for item in probe_sequence]
        probe_calls = 0

        async def sequence_probe() -> tuple[bool, str]:
            nonlocal probe_calls
            probe_kind = sequence[min(probe_calls, len(sequence) - 1)]
            probe_calls += 1
            return await _matrix_probe(probe_kind)()

        config = case["config"]
        assert isinstance(config, dict)
        snapshots = [
            asyncio.run(build_provider_registry_snapshot(
                config_snapshot_provider=lambda: config,
                health_providers={target: sequence_probe},
                client_providers={target: lambda: object()},
            ))
            for _ in sequence
        ]
        expected_sequence = case["expected_sequence"]
        assert isinstance(expected_sequence, list)
        for snapshot, expected in zip(snapshots, expected_sequence, strict=True):
            actual = next(item for item in snapshot["providers"] if item["id"] == target)
            assert isinstance(expected, dict)
            for key, value in expected.items():
                assert actual[key] == value
        return

    probe_kind = str(case["probe"])
    if probe_kind == "timeout":
        monkeypatch.setattr(provider_registry, "HEALTH_PROBE_TIMEOUT_SECONDS", 0.01)

    config = case["config"]
    assert isinstance(config, dict)
    available = bool(case["client_available"])
    snapshot = asyncio.run(provider_registry.build_provider_registry_snapshot(
        config_snapshot_provider=lambda: config,
        health_providers={target: _matrix_probe(probe_kind)} if probe_kind != "none" else {},
        client_providers={target: (lambda: object()) if available else (lambda: None)},
    ))
    actual = next(item for item in snapshot["providers"] if item["id"] == target)
    expected = case["expected"]
    assert isinstance(expected, dict)
    for key, value in expected.items():
        assert actual[key] == value


def _matrix_probe(probe_kind: str):
    async def probe() -> tuple[bool, str]:
        if probe_kind == "timeout":
            await asyncio.sleep(30)
        if probe_kind == "failure":
            raise RuntimeError("provider unavailable")
        if probe_kind == "network_error":
            raise ConnectionRefusedError("provider offline")
        return (probe_kind == "healthy"), "ok"

    return probe


@pytest.mark.asyncio
async def test_provider_registry_recovers_after_real_local_connection_refusal() -> None:
    reserve = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserve.bind(("127.0.0.1", 0))
    port = reserve.getsockname()[1]

    async def tcp_health() -> tuple[bool, str]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        del reader
        writer.close()
        await writer.wait_closed()
        return True, "Local provider reachable"

    config = {"llm": {"provider": "local-http", "model": "chat"}}
    clients = {"llm": lambda: object()}
    try:
        offline = await build_provider_registry_snapshot(
            config_snapshot_provider=lambda: config,
            health_providers={"llm": tcp_health},
            client_providers=clients,
        )
    finally:
        reserve.close()

    async def handle_connection(_reader, writer) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_connection, "127.0.0.1", port)
    try:
        recovered = await build_provider_registry_snapshot(
            config_snapshot_provider=lambda: config,
            health_providers={"llm": tcp_health},
            client_providers=clients,
        )
    finally:
        server.close()
        await server.wait_closed()

    offline_llm = next(item for item in offline["providers"] if item["id"] == "llm")
    recovered_llm = next(item for item in recovered["providers"] if item["id"] == "llm")
    assert offline_llm["healthy"] is False
    assert offline_llm["retryable"] is True
    assert offline_llm["message"] == "Provider connection unavailable"
    assert recovered_llm["healthy"] is True
    assert recovered_llm["retryable"] is False
    assert recovered["summary"]["requiredHealthy"] is True


def test_provider_registry_route_is_read_only_and_exposed() -> None:
    app = FastAPI()
    app.include_router(create_system_router(
        health_handler=lambda: {"status": "healthy"},
        readiness_handler=lambda: {"ready": True},
        system_status_handler=lambda: {"status": "ok"},
        provider_registry_handler=lambda: {"schemaVersion": 1, "providers": [], "summary": {}},
    ))

    response = TestClient(app).get("/api/system/providers")
    assert response.status_code == 200
    assert response.json()["schemaVersion"] == 1
