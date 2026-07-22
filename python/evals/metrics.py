"""Small dependency-free metrics used by the offline evaluation suite."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence


_WORD_RE = re.compile(r"\S+")


def _edit_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_item in enumerate(hypothesis, start=1):
            substitution = previous[column - 1] + (reference_item != hypothesis_item)
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def _tokenize(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    if " " in normalized:
        return _WORD_RE.findall(normalized)
    return list(normalized)


def _error_rate(reference: Sequence[str], hypothesis: Sequence[str]) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _edit_distance(reference, hypothesis) / len(reference)


def token_error_rate(reference: str, hypothesis: str) -> float:
    """Return WER-like error rate using words when spaced, characters otherwise."""
    return _error_rate(_tokenize(reference), _tokenize(hypothesis))


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Return CER after removing whitespace."""
    reference_chars = list("".join(str(reference or "").split()))
    hypothesis_chars = list("".join(str(hypothesis or "").split()))
    return _error_rate(reference_chars, hypothesis_chars)


def real_time_factor(elapsed_ms: float, audio_duration_s: float) -> float:
    """Return synthesis/inference seconds divided by produced audio seconds."""
    if audio_duration_s <= 0:
        raise ValueError("audio_duration_s must be positive")
    if elapsed_ms < 0:
        raise ValueError("elapsed_ms must be non-negative")
    return (elapsed_ms / 1000.0) / audio_duration_s


def tool_success_rate(expected_tools: Iterable[str], actual_tools: Iterable[str]) -> float:
    """Return count-aware, case-insensitive success over expected tool calls."""
    expected = Counter(str(item).strip().lower() for item in expected_tools if str(item).strip())
    actual = Counter(str(item).strip().lower() for item in actual_tools if str(item).strip())
    if not expected:
        return 1.0
    matched = sum(min(count, actual[name]) for name, count in expected.items())
    return matched / sum(expected.values())


def embedding_recall_at_k(relevant_ids: Iterable[str], ranked_ids: Sequence[str], k: int) -> float:
    """Return recall@k for a query with one or more relevant document IDs."""
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = {str(item) for item in relevant_ids if str(item)}
    if not relevant:
        return 1.0
    retrieved = {str(item) for item in ranked_ids[:k]}
    return len(relevant & retrieved) / len(relevant)
