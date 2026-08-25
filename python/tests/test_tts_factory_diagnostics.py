from __future__ import annotations

from pathlib import Path

from modules.system.voice_diagnostics import VoiceDiagnostics
from modules.tts.factory import create_tts_client


def test_factory_preserves_shared_diagnostics_for_genie_and_openai():
    diagnostics = VoiceDiagnostics()
    common = {
        "base_url": "http://localhost:8000/v1",
        "api_key": "",
        "model": "tts-1",
        "voice": "alloy",
        "timeout": 10.0,
        "genie_character": "feibi",
        "genie_model_dir": None,
        "ref_audio": "",
        "ref_text": "",
        "language": "ja",
        "device": "cpu",
        "quality": "标准",
        "split": "自动",
        "mode": "串行推理",
        "save_mode": "禁用自动保存",
        "audio_cache_dir": Path("."),
        "diagnostics": diagnostics,
    }

    genie = create_tts_client(provider="genie-tts", **common)
    openai = create_tts_client(provider="openai-compatible", **common)

    assert genie.diagnostics is diagnostics
    assert openai.diagnostics is diagnostics
    assert genie.status_snapshot()["voice_diagnostics"]["evidence_claim"] == "synthetic_regression_only"
    assert openai.status_snapshot()["voice_diagnostics"]["evidence_claim"] == "synthetic_regression_only"
