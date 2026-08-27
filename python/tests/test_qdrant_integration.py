from __future__ import annotations

import hashlib
import json
import os
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from modules.memory.indexed_backend import IndexedMemoryBackend
from modules.memory.sqlite_store import SQLiteMemoryStore
from modules.memory.vector_client import QdrantVectorStore
from modules.memory.vector_store import Document


QDRANT_URL = os.getenv("YUIZAKI_QDRANT_INTEGRATION_URL", "").strip()
QDRANT_CONTAINER = os.getenv("YUIZAKI_QDRANT_INTEGRATION_CONTAINER", "").strip()
METRICS_PATH = os.getenv("YUIZAKI_QDRANT_METRICS_PATH", "").strip()

pytestmark = pytest.mark.skipif(
    not QDRANT_URL or not QDRANT_CONTAINER,
    reason="real Qdrant integration requires the explicit Docker runner",
)


class DeterministicEmbedding:
    dimension = 8
    _model_name = "yuizaki-qdrant-integration-v1"

    def embed(self, text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector = np.frombuffer(digest[: self.dimension * 2], dtype=np.uint16).astype(np.float32)
        vector = vector + 1.0
        return vector / np.linalg.norm(vector)


def _wait_for_qdrant(timeout_seconds: float = 45.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{QDRANT_URL}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError("Qdrant did not become healthy after restart") from last_error


def _restart_qdrant() -> float:
    started = time.perf_counter()
    subprocess.run(
        ["docker", "restart", QDRANT_CONTAINER],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    _wait_for_qdrant()
    return (time.perf_counter() - started) * 1000


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _new_backend(
    database_path: Path,
    collection_name: str,
    embedding: DeterministicEmbedding,
) -> IndexedMemoryBackend:
    authority = SQLiteMemoryStore(db_path=str(database_path), embedding_service=embedding)
    index = QdrantVectorStore(
        qdrant_url=QDRANT_URL,
        collection_name=collection_name,
        timeout=10,
        embedding_service=embedding,
    )
    return IndexedMemoryBackend(authority=authority, index=index)


def _rebuild(backend: IndexedMemoryBackend, generation: str) -> dict[str, object]:
    context = backend.get_rebuild_checkpoint_context()
    assert context is not None
    return backend.rebuild_index(
        snapshot_revision=int(context["snapshot_revision"]),
        index_generation=generation,
        embedding_config_revision=str(context["embedding_config_revision"]),
    )


def test_real_qdrant_restart_manifest_fallback_and_rebuild(tmp_path: Path) -> None:
    document_count = max(32, int(os.getenv("YUIZAKI_QDRANT_DOCUMENT_COUNT", "512")))
    sample_count = max(5, int(os.getenv("YUIZAKI_QDRANT_STARTUP_SAMPLES", "10")))
    database_path = tmp_path / "memory.db"
    collection_name = f"yuizaki_it_{uuid4().hex}"
    embedding = DeterministicEmbedding()
    backend = _new_backend(database_path, collection_name, embedding)
    try:
        for index in range(document_count):
            backend.authority.add_document(Document(
                id=f"memory-{index:05d}",
                text=f"desktop companion preference and workflow evidence {index}",
                metadata={
                    "scope": "workspace",
                    "workspace_id": "integration",
                    "layer": "semantic",
                    "type": "fact",
                },
            ))

        rebuild_started = time.perf_counter()
        first_generation = f"generation-{uuid4().hex}"
        rebuild_result = _rebuild(backend, first_generation)
        rebuild_ms = (time.perf_counter() - rebuild_started) * 1000
        assert rebuild_result["indexed_count"] == document_count
        assert backend.get_status().metadata["index_dirty"] is False

        restart_ms = _restart_qdrant()
        startup_samples: list[float] = []
        recovered: IndexedMemoryBackend | None = None
        for _ in range(sample_count):
            started = time.perf_counter()
            recovered = _new_backend(database_path, collection_name, embedding)
            startup_samples.append((time.perf_counter() - started) * 1000)
            assert recovered.get_status().metadata["index_dirty"] is False
        assert recovered is not None
        results = recovered.search_with_rerank("workflow evidence 42", top_k=3)
        assert results
        assert all(document.id.startswith("memory-") for document, _score in results)

        recovered.index.client.delete_collection(collection_name=collection_name)
        missing_collection = _new_backend(database_path, collection_name, embedding)
        missing_status = missing_collection.get_status()
        assert missing_status.healthy is True
        assert missing_status.metadata["index_dirty"] is True
        fallback = missing_collection.search_with_rerank("workflow evidence 42", top_k=3)
        assert fallback

        second_generation = f"generation-{uuid4().hex}"
        recovered_result = _rebuild(missing_collection, second_generation)
        assert recovered_result["indexed_count"] == document_count
        assert missing_collection.get_status().metadata["index_dirty"] is False

        metrics = {
            "qdrant_url": QDRANT_URL,
            "document_count": document_count,
            "startup_sample_count": sample_count,
            "rebuild_ms": round(rebuild_ms, 3),
            "container_restart_ms": round(restart_ms, 3),
            "startup_validation_ms": {
                "p50": round(statistics.median(startup_samples), 3),
                "p95": round(_percentile(startup_samples, 0.95), 3),
                "max": round(max(startup_samples), 3),
            },
            "persisted_generation": first_generation,
            "recovered_generation": second_generation,
            "collection_loss_fallback": "sqlite_authority",
        }
        print(f"YUIZAKI_QDRANT_INTEGRATION {json.dumps(metrics, sort_keys=True)}")
        if METRICS_PATH:
            Path(METRICS_PATH).write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    finally:
        try:
            if backend.index.client.collection_exists(collection_name=collection_name):
                backend.index.client.delete_collection(collection_name=collection_name)
        except Exception:
            pass
