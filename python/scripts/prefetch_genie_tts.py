from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch Genie TTS data for the configured character.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--model-dir", default="")
    parser.add_argument(
        "--genie-data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "GenieData" / "GenieData",
    )
    args = parser.parse_args()

    genie_data_dir = args.genie_data_dir.resolve()
    genie_data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("GENIE_DATA_DIR", str(genie_data_dir))

    import genie_tts

    if args.model_dir.strip():
        genie_tts.load_character(
            character_name=args.character,
            onnx_model_dir=args.model_dir.strip(),
            language=args.language,
        )
    else:
        genie_tts.load_predefined_character(args.character)

    print(f"Genie TTS assets ready for {args.character} under {genie_data_dir}")


if __name__ == "__main__":
    main()
