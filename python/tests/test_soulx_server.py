from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


SERVER_PATH = Path(__file__).resolve().parents[2] / "services" / "soulx-svc" / "server.py"
SPEC = importlib.util.spec_from_file_location("soulx_service_server", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
soulx_server = importlib.util.module_from_spec(SPEC)
sys.modules["soulx_service_server"] = soulx_server
SPEC.loader.exec_module(soulx_server)


@pytest.mark.parametrize("filename", ["voice.WAV", "voice.mp3", None])
def test_audio_suffix_is_normalized(filename: str | None) -> None:
    assert soulx_server._validated_audio_suffix(filename) in {".wav", ".mp3"}


@pytest.mark.parametrize("filename", ["voice.$", "voice.é", "voice." + "a" * 16])
def test_audio_suffix_rejects_ambiguous_filename(filename: str) -> None:
    with pytest.raises(HTTPException, match="invalid audio filename"):
        soulx_server._validated_audio_suffix(filename)
