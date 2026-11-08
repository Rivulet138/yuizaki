from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

SERVER_PATH = Path(__file__).resolve().parents[2] / "services" / "soulx-svc" / "server.py"
SPEC = importlib.util.spec_from_file_location("soulx_service_server", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
soulx_server = importlib.util.module_from_spec(SPEC)
sys.modules["soulx_service_server"] = soulx_server
SPEC.loader.exec_module(soulx_server)


@pytest.mark.parametrize("use_fp16", [False, True])
def test_lifecycle_initializes_runtime_once_before_serving(monkeypatch, tmp_path: Path, use_fp16: bool) -> None:
    work_dir = tmp_path / "nested" / "work"
    fake_runtime = SimpleNamespace(device="cpu", use_fp16=use_fp16)

    def create_runtime():
        assert work_dir.is_dir()
        return fake_runtime

    runtime_factory = Mock(side_effect=create_runtime)
    monkeypatch.setattr(soulx_server, "WORK_DIR", work_dir)
    monkeypatch.setattr(soulx_server, "SoulXSvcRuntime", runtime_factory)
    monkeypatch.setattr(soulx_server, "runtime", None)

    assert soulx_server.health() == {
        "ok": False,
        "provider": "soulx-service",
        "device": None,
        "fp16": None,
    }
    runtime_factory.assert_not_called()
    assert not work_dir.exists()

    for expected_calls in (1, 2):
        with TestClient(soulx_server.app) as client:
            assert soulx_server.runtime is fake_runtime
            for _ in range(2):
                response = client.get("/health")
                assert response.status_code == 200
                assert response.json() == {
                    "ok": True,
                    "provider": "soulx-service",
                    "device": "cpu",
                    "fp16": use_fp16,
                }
            assert runtime_factory.call_count == expected_calls
        assert soulx_server.runtime is fake_runtime
        assert work_dir.is_dir()


def test_lifecycle_propagates_runtime_initialization_failure(monkeypatch, tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    runtime_factory = Mock(side_effect=RuntimeError("runtime initialization failed"))
    monkeypatch.setattr(soulx_server, "WORK_DIR", work_dir)
    monkeypatch.setattr(soulx_server, "SoulXSvcRuntime", runtime_factory)
    monkeypatch.setattr(soulx_server, "runtime", None)

    with pytest.raises(RuntimeError, match="runtime initialization failed"):
        with TestClient(soulx_server.app):
            pytest.fail("startup must fail before serving requests")

    runtime_factory.assert_called_once_with()
    assert work_dir.is_dir()
    assert soulx_server.runtime is None
    assert soulx_server.health()["ok"] is False


@pytest.mark.parametrize("filename", ["voice.WAV", "voice.mp3", None])
def test_audio_suffix_is_normalized(filename: str | None) -> None:
    assert soulx_server._validated_audio_suffix(filename) in {".wav", ".mp3"}


@pytest.mark.parametrize("filename", ["voice.$", "voice.é", "voice." + "a" * 16])
def test_audio_suffix_rejects_ambiguous_filename(filename: str) -> None:
    with pytest.raises(HTTPException, match="invalid audio filename"):
        soulx_server._validated_audio_suffix(filename)
