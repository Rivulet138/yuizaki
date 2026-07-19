from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch the configured embedding model into the local Hugging Face cache.")
    parser.add_argument("--model", required=True)
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

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(args.model, cache_folder=str(cache_root))
    dimension = model.get_sentence_embedding_dimension()
    print(f"Embedding model ready: {args.model} (dimension={dimension})")


if __name__ == "__main__":
    main()
