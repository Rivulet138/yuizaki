"""Run the offline memory retrieval contract replay.

The replay uses the real RetrievalPipeline and VectorStore, with a tiny
deterministic embedding provider so CI never downloads a model or calls an LLM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modules.memory.evaluation import (
    SCHEMA_VERSION,
    evaluate_memory_retrieval,
    load_golden_cases,
)
from modules.memory.pipeline import RetrievalPipeline
from modules.memory.schema import RetrievalRequest
from modules.memory.vector_store import Document, VectorStore


class DeterministicEmbedding:
    dimension = 64

    def embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in re.findall(r"[\w]+|[\u4e00-\u9fff]", text.lower()):
            # Python's built-in hash is process-randomized, which makes the
            # offline replay produce different rankings in CI and locally.
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self.dimension] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector


def _load_documents(cases: list[dict[str, Any]]) -> list[Document]:
    documents: dict[str, Document] = {}
    for case in cases:
        for raw in case.get("documents", []):
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                raise TypeError("memory fixture documents must have string ids")
            documents[raw["id"]] = Document(
                id=raw["id"],
                text=str(raw.get("text") or ""),
                metadata=dict(raw.get("metadata") or {}),
            )
    return list(documents.values())


def run_fixture(path: Path) -> dict[str, Any]:
    cases = load_golden_cases(path)

    def run_query(case: dict[str, Any]) -> dict[str, Any]:
        # Rebuild a tiny store per case so fixtures cannot accidentally share
        # memories across workspace/session boundaries.
        store = VectorStore(embedding_service=DeterministicEmbedding())
        for document in _load_documents([case]):
            store.add_document(document)
        pipeline = RetrievalPipeline(store)
        request = RetrievalRequest(
            query=str(case.get("query") or ""),
            scope=case.get("scope"),
            session_id=case.get("session_id"),
            workspace_id=case.get("workspace_id"),
            top_k=int(case.get("top_k", 5)),
            memory_role=case.get("memory_role"),
            relation_expansion=bool(case.get("relation_expansion", True)),
            relation_limit=int(case.get("relation_limit", 20)),
        )
        response = pipeline.recall(request)
        response["missing_premises"] = list(case.get("missing_premises", []))
        return response

    report = evaluate_memory_retrieval(cases, run_query)
    return {"schema_version": SCHEMA_VERSION, **report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "python" / "evals" / "fixtures" / "memory_retrieval.json",
    )
    args = parser.parse_args()
    report = run_fixture(args.fixture)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] == report["case_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
