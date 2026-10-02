import json
from pathlib import Path

from modules.system.service_discovery import discover_genie_tts_characters


MODEL_FILES = (
    "t2s_encoder_fp32.onnx",
    "t2s_first_stage_decoder_fp32.onnx",
    "t2s_stage_decoder_fp32.onnx",
    "vits_fp32.onnx",
    "prompt_encoder_fp32.onnx",
)


def test_genie_character_discovery_returns_ready_local_bundle(tmp_path: Path) -> None:
    root = tmp_path / "CharacterModels" / "v2ProPlus"
    character = root / "local-role"
    model_dir = character / "tts_models"
    prompt_dir = character / "prompt_wav"
    model_dir.mkdir(parents=True)
    prompt_dir.mkdir()
    for name in MODEL_FILES:
        (model_dir / name).write_bytes(b"model")
    (prompt_dir / "normal.wav").write_bytes(b"RIFF")
    (character / "prompt_wav.json").write_text(
        json.dumps({"Normal": {"wav": "normal.wav", "text": "reference"}}),
        encoding="utf-8",
    )
    genie_data = tmp_path / "GenieData"
    (genie_data / "chinese-hubert-base").mkdir(parents=True)
    (genie_data / "G2P").mkdir()
    (genie_data / "speaker_encoder.onnx").write_bytes(b"model")

    result = discover_genie_tts_characters(character_root=root, genie_data_dir=genie_data)

    assert result == [{
        "id": "local-role",
        "label": "local-role",
        "language": "auto",
        "model_dir": str(model_dir.resolve()),
        "ref_audio": str((prompt_dir / "normal.wav").resolve()),
        "ref_text": "reference",
        "ready": True,
        "details": [],
    }]


def test_genie_character_discovery_reports_missing_assets(tmp_path: Path) -> None:
    root = tmp_path / "CharacterModels" / "v2ProPlus"
    (root / "incomplete").mkdir(parents=True)

    result = discover_genie_tts_characters(character_root=root, genie_data_dir=tmp_path / "missing")

    assert result[0]["ready"] is False
    assert "speaker_encoder.onnx" in result[0]["details"]
    assert "t2s_encoder_fp32.onnx" in result[0]["details"]
    assert "prompt_wav/*.wav" in result[0]["details"]
