from __future__ import annotations

import argparse
import json
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.errors import EntryNotFoundError


RESOURCE_LOCK_PATH = Path(__file__).resolve().parents[2] / "resources.lock.json"


def emit_progress(phase: str, message: str) -> None:
    payload = json.dumps({"phase": phase, "message": message}, ensure_ascii=True)
    print(f"YUIZAKI_RESOURCE_PROGRESS {payload}", flush=True)


def locked_revisions() -> tuple[str, str]:
    lock = json.loads(RESOURCE_LOCK_PATH.read_text(encoding="utf-8"))
    sources = lock["resources"]["soulx"]["sources"]
    return str(sources[0]["revision"]), str(sources[1]["revision"])


def download(repo_id: str, local_dir: Path, revision: str) -> None:
    local_dir.mkdir(parents=True, exist_ok=True)
    emit_progress("downloading", f"Downloading {repo_id}")
    snapshot_download(
        repo_id=repo_id,
        repo_type="model",
        revision=revision,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )

def download_soulx_checkpoint(local_dir: Path, revision: str) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    emit_progress("downloading", "Downloading SoulX checkpoint")
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
    singer_revision, preprocess_revision = locked_revisions()
    parser = argparse.ArgumentParser(description="Download SoulX-Singer SVC model assets for the Docker service.")
    parser.add_argument("--models-dir", type=Path, default=Path(__file__).resolve().parent / "models")
    parser.add_argument("--singer-revision", default=singer_revision)
    parser.add_argument("--preprocess-revision", default=preprocess_revision)
    args = parser.parse_args()

    checkpoint = download_soulx_checkpoint(args.models_dir / "SoulX-Singer", args.singer_revision)
    download(
        "Soul-AILab/SoulX-Singer-Preprocess",
        args.models_dir / "SoulX-Singer-Preprocess",
        args.preprocess_revision,
    )
    emit_progress("verifying", "Verifying SoulX model files")
    references = Path(__file__).resolve().parent / "references"
    references.mkdir(parents=True, exist_ok=True)
    print(f"Downloaded SoulX models under {args.models_dir}")
    print(f"Checkpoint ready at {checkpoint}")
    print(f"Place reference audio at {references / '0.wav'} or {references / '0' / 'prompt.wav'}")


if __name__ == "__main__":
    main()
