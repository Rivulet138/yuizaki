from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable


GENIE_REPO_ID = "High-Logic/Genie"


def emit_progress(phase: str, message: str) -> None:
    payload = json.dumps({"phase": phase, "message": message}, ensure_ascii=True)
    print(f"YUIZAKI_RESOURCE_PROGRESS {payload}", flush=True)


def validate_character_name(character: str) -> str:
    normalized = character.strip()
    if not normalized or normalized in {".", ".."} or any(char in normalized for char in ("/", "\\", "\0")):
        raise ValueError("Character name contains unsupported path characters")
    return normalized


def normalize_genie_language(language: str) -> str:
    normalized = language.strip().lower()
    return {
        "auto": "Japanese",
        "ja": "Japanese",
        "japanese": "Japanese",
        "zh": "Chinese",
        "cn": "Chinese",
        "chinese": "Chinese",
        "en": "English",
        "english": "English",
    }.get(normalized, language.strip() or "Japanese")


def prefetch_genie_assets(
    *,
    character: str,
    revision: str,
    genie_data_dir: Path,
    workspace_root: Path,
    include_predefined_character: bool,
    max_workers: int,
    snapshot_download_fn: Callable[..., str],
) -> tuple[Path, Path | None]:
    character = validate_character_name(character)
    shared_root = genie_data_dir.parent
    shared_root.mkdir(parents=True, exist_ok=True)
    workspace_root.mkdir(parents=True, exist_ok=True)

    snapshot_download_fn(
        repo_id=GENIE_REPO_ID,
        revision=revision,
        allow_patterns="GenieData/*",
        local_dir=str(shared_root),
        max_workers=max_workers,
    )

    character_dir: Path | None = None
    if include_predefined_character:
        snapshot_download_fn(
            repo_id=GENIE_REPO_ID,
            revision=revision,
            allow_patterns=f"CharacterModels/v2ProPlus/{character}/*",
            local_dir=str(workspace_root),
            max_workers=max_workers,
        )
        character_dir = workspace_root / "CharacterModels" / "v2ProPlus" / character
    return genie_data_dir, character_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch Genie TTS data for the configured character.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-workers", type=int, default=max(1, int(os.getenv("YUIZAKI_HF_MAX_WORKERS", "4"))))
    parser.add_argument(
        "--genie-data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "GenieData" / "GenieData",
    )
    args = parser.parse_args()

    character = validate_character_name(args.character)
    language = normalize_genie_language(args.language)
    genie_data_dir = args.genie_data_dir.resolve()
    workspace_root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("GENIE_DATA_DIR", str(genie_data_dir))
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")

    emit_progress("downloading", "Downloading Genie shared assets")
    from huggingface_hub import snapshot_download

    prefetch_genie_assets(
        character=character,
        revision=args.revision,
        genie_data_dir=genie_data_dir,
        workspace_root=workspace_root,
        include_predefined_character=not args.model_dir.strip(),
        max_workers=max(1, args.max_workers),
        snapshot_download_fn=snapshot_download,
    )

    emit_progress("verifying", "Loading Genie TTS assets")
    import genie_tts

    if args.model_dir.strip():
        genie_tts.load_character(
            character_name=character,
            onnx_model_dir=args.model_dir.strip(),
            language=language,
        )
    else:
        genie_tts.load_predefined_character(character)

    print(f"Genie TTS assets ready for {character} under {genie_data_dir}")


if __name__ == "__main__":
    main()
