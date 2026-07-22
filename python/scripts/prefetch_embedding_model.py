from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable


def emit_progress(phase: str, message: str) -> None:
    payload = json.dumps({"phase": phase, "message": message}, ensure_ascii=True)
    print(f"YUIZAKI_RESOURCE_PROGRESS {payload}", flush=True)


def fetch_embedding_snapshot(
    model_name: str,
    revision: str | None,
    cache_root: Path,
    max_workers: int,
    snapshot_download_fn: Callable[..., str],
) -> Path:
    local_model = Path(model_name).expanduser()
    if local_model.exists():
        return local_model.resolve()
    return Path(snapshot_download_fn(
        repo_id=model_name,
        revision=revision,
        cache_dir=str(cache_root),
        max_workers=max_workers,
    )).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch the configured embedding model into the local Hugging Face cache.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision")
    parser.add_argument("--max-workers", type=int, default=max(1, int(os.getenv("YUIZAKI_HF_MAX_WORKERS", "4"))))
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "huggingface",
    )
    args = parser.parse_args()

    cache_root = args.cache_root.resolve()
    cache_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(cache_root))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_root))
    os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "30")
    os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")

    emit_progress("downloading", "Downloading embedding model snapshot")
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    snapshot_path = fetch_embedding_snapshot(
        args.model,
        args.revision,
        cache_root,
        max(1, args.max_workers),
        snapshot_download,
    )
    model = SentenceTransformer(str(snapshot_path), cache_folder=str(cache_root))
    emit_progress("verifying", "Loading embedding model metadata")
    dimension = model.get_sentence_embedding_dimension()
    print(f"Embedding model ready: {args.model} (dimension={dimension})")


if __name__ == "__main__":
    main()
