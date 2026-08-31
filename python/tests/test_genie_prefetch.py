from __future__ import annotations

from pathlib import Path

from scripts.prefetch_genie_tts import (
    genie_assets_ready,
    normalize_genie_language,
    prefetch_genie_assets,
)


def test_auto_language_uses_japanese_character_model() -> None:
    assert normalize_genie_language("auto") == "Japanese"


def test_supported_genie_languages_are_normalized() -> None:
    assert normalize_genie_language("zh") == "Chinese"
    assert normalize_genie_language("en") == "English"
    assert normalize_genie_language("ja") == "Japanese"


def _write_local_genie_assets(root: Path, character: str = "feibi") -> tuple[Path, Path]:
    data_dir = root / ".cache" / "GenieData" / "GenieData"
    character_dir = root / "CharacterModels" / "v2ProPlus" / character
    for file_path in (
        data_dir / "speaker_encoder.onnx",
        data_dir / "chinese-hubert-base" / "model.onnx",
        data_dir / "G2P" / "ChineseG2P" / "dictionary.txt",
        character_dir / "prompt_wav.json",
        character_dir / "prompt_wav" / "normal.wav",
        character_dir / "tts_models" / "model.onnx",
        character_dir / "tts_models" / "weights.bin",
    ):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b"ready")
    return data_dir, character_dir


def test_repository_local_genie_assets_are_reused_without_download(tmp_path: Path) -> None:
    data_dir, character_dir = _write_local_genie_assets(tmp_path)

    assert genie_assets_ready(
        character="feibi",
        genie_data_dir=data_dir,
        workspace_root=tmp_path,
        include_predefined_character=True,
    )

    def fail_download(**_kwargs: object) -> str:
        raise AssertionError("complete local Genie assets must not be downloaded again")

    resolved_data, resolved_character = prefetch_genie_assets(
        character="feibi",
        revision="test",
        genie_data_dir=data_dir,
        workspace_root=tmp_path,
        include_predefined_character=True,
        max_workers=1,
        snapshot_download_fn=fail_download,
    )

    assert resolved_data == data_dir
    assert resolved_character == character_dir
