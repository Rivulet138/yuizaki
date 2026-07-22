"""Low-cost hybrid and optional learned reranking for memory retrieval."""

from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from typing import Protocol

import numpy as np


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff]")


def lexical_overlap_score(query: str, text: str) -> float:
    """Score exact phrases and multilingual token overlap in [0, 1]."""
    normalized_query = " ".join(str(query or "").lower().split())
    normalized_text = " ".join(str(text or "").lower().split())
    if not normalized_query or not normalized_text:
        return 0.0
    if normalized_query in normalized_text:
        return 1.0
    query_tokens = set(_TOKEN_RE.findall(normalized_query))
    text_tokens = set(_TOKEN_RE.findall(normalized_text))
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens) / len(query_tokens)
    return max(0.0, min(1.0, overlap))


class LearnedReranker(Protocol):
    @property
    def is_loaded(self) -> bool: ...

    def score(self, query: str, documents: Sequence[str]) -> np.ndarray: ...


class LazyCrossEncoderReranker:
    """Load a Sentence Transformers CrossEncoder only when explicitly enabled."""

    def __init__(self, model_name: str, *, enabled: bool = False, device: str = "cpu") -> None:
        self.model_name = model_name.strip()
        self.enabled = bool(enabled and self.model_name)
        self.device = device.strip() or "cpu"
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_model(self):
        if self._model is None:
            module = importlib.import_module("sentence_transformers")
            cross_encoder = getattr(module, "CrossEncoder")
            self._model = cross_encoder(self.model_name, device=self.device)
        return self._model

    def score(self, query: str, documents: Sequence[str]) -> np.ndarray:
        if not self.enabled or not documents:
            return np.zeros(len(documents), dtype=np.float32)
        model = self._ensure_model()
        pairs = [(query, document) for document in documents]
        values = model.predict(pairs, batch_size=min(16, max(1, len(pairs))), show_progress_bar=False)
        return np.asarray(values, dtype=np.float32).reshape(-1)


def normalize_scores(values: Sequence[float] | np.ndarray) -> np.ndarray:
    scores = np.asarray(values, dtype=np.float32).reshape(-1)
    if scores.size == 0:
        return scores
    low = float(np.min(scores))
    high = float(np.max(scores))
    if high - low < 1e-6:
        return np.full(scores.shape, 0.5, dtype=np.float32)
    return (scores - low) / (high - low)
