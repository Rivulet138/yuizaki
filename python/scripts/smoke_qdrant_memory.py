from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from modules.memory.vector_client import QdrantVectorStore  # noqa: E402
from modules.memory.vector_store import Document  # noqa: E402


class SmokeEmbeddingService:
    dimension = 4

    def _vector(self, text: str) -> np.ndarray:
        normalized = text.lower()
        return np.array(
            [
                1.0 if "qdrant" in normalized else 0.0,
                1.0 if "memory" in normalized or "记忆" in normalized else 0.0,
                1.0 if "live2d" in normalized else 0.0,
                1.0 if "tts" in normalized else 0.0,
            ],
            dtype=np.float32,
        )

    def embed_document(self, text: str) -> np.ndarray:
        return self._vector(text)

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)

    def embed(self, text: str) -> np.ndarray:
        return self._vector(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test Yuizaki's Qdrant memory backend.")
    parser.add_argument("--url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    parser.add_argument("--api-key", default=os.getenv("QDRANT_API_KEY", ""))
    parser.add_argument("--collection", default=f"yuizaki_smoke_{uuid.uuid4().hex[:10]}")
    parser.add_argument("--keep", action="store_true", help="Keep the smoke-test collection after success.")
    args = parser.parse_args()

    store = QdrantVectorStore(
        args.url,
        qdrant_api_key=args.api_key,
        collection_name=args.collection,
        embedding_service=SmokeEmbeddingService(),
    )

    docs = [
        Document(
            id="doc-1",
            text="Yuizaki Qdrant memory backend smoke test",
            metadata={"scope": "workspace", "workspace_id": "smoke", "layer": "semantic", "state": "active"},
        ),
        Document(
            id="doc-2",
            text="Live2D emotion and motion linkage smoke test",
            metadata={"scope": "workspace", "workspace_id": "smoke", "layer": "relationship", "state": "active"},
        ),
        Document(
            id="doc-deleted",
            text="Deleted Qdrant memory should be skipped during rebuild",
            metadata={"scope": "workspace", "workspace_id": "smoke", "layer": "semantic", "state": "deleted"},
        ),
    ]

    try:
        for doc in docs:
            store.add_document(doc)

        before = store.search("qdrant memory", top_k=3)
        if not before or before[0][0].id != "doc-1":
            raise RuntimeError(f"unexpected search result before rebuild: {[doc.id for doc, _score in before]}")

        rebuild = store.rebuild_index()
        if rebuild.get("indexed_count") != 2 or rebuild.get("skipped_count") != 1:
            raise RuntimeError(f"unexpected rebuild result: {rebuild}")

        after = store.search("qdrant memory", top_k=3)
        if not after or after[0][0].id != "doc-1":
            raise RuntimeError(f"unexpected search result after rebuild: {[doc.id for doc, _score in after]}")

        status = store.get_status()
        if not status.healthy or status.document_count != 2:
            raise RuntimeError(f"unexpected status: {status}")

        print(
            "qdrant_smoke_ok "
            f"url={args.url} collection={args.collection} "
            f"indexed={rebuild.get('indexed_count')} skipped={rebuild.get('skipped_count')} "
            f"top={after[0][0].id}"
        )
    finally:
        if not args.keep:
            try:
                store._delete_collection_if_exists()
            except Exception:
                pass


if __name__ == "__main__":
    main()
