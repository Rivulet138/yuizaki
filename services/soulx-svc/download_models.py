from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.errors import EntryNotFoundError


def download(repo_id: str, local_dir: Path, revision: str | None) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo_id,
        repo_type="model",
        revision=revision,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )

def download_soulx_checkpoint(local_dir: Path, revision: str | None) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("model-svc.pt", "model.pt"):
        try:
            downloaded_path = hf_hub_download(
                repo_id="Soul-AILab/SoulX-Singer",
                filename=filename,
                repo_type="model",
                revision=revision,
                local_dir=str(local_dir),
                local_dir_use_symlinks=False,
            )
            return Path(downloaded_path)
        except EntryNotFoundError:
            continue
    raise FileNotFoundError("Neither model-svc.pt nor model.pt could be downloaded from Soul-AILab/SoulX-Singer")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download SoulX-Singer SVC model assets for the Docker service.")
    parser.add_argument("--models-dir", type=Path, default=Path(__file__).resolve().parent / "models")
    parser.add_argument("--revision", default=None, help="Optional Hugging Face revision for both model repos.")
    args = parser.parse_args()

    checkpoint = download_soulx_checkpoint(args.models_dir / "SoulX-Singer", args.revision)
    download("Soul-AILab/SoulX-Singer-Preprocess", args.models_dir / "SoulX-Singer-Preprocess", args.revision)
    references = Path(__file__).resolve().parent / "references"
    references.mkdir(parents=True, exist_ok=True)
    print(f"Downloaded SoulX models under {args.models_dir}")
    print(f"Checkpoint ready at {checkpoint}")
    print(f"Place reference audio at {references / '0.wav'} or {references / '0' / 'prompt.wav'}")


if __name__ == "__main__":
    main()
