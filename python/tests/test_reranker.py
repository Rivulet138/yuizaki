from __future__ import annotations

import numpy as np

from modules.memory.reranker import LazyCrossEncoderReranker, lexical_overlap_score, normalize_scores


def test_lexical_overlap_prefers_exact_multilingual_phrase():
    assert lexical_overlap_score("打开浏览器", "请打开浏览器并等待") == 1.0
    assert lexical_overlap_score("browser", "open the browser") > 0.0
    assert lexical_overlap_score("不存在", "天气晴朗") == 0.0


def test_disabled_cross_encoder_is_lazy_and_returns_zeroes():
    reranker = LazyCrossEncoderReranker("BAAI/bge-reranker-v2-m3", enabled=False)

    scores = reranker.score("query", ["document"])

    assert np.array_equal(scores, np.zeros(1, dtype=np.float32))
    assert reranker.is_loaded is False


def test_score_normalization_is_bounded():
    scores = normalize_scores([2.0, 4.0, 6.0])

    assert np.allclose(scores, [0.0, 0.5, 1.0])
