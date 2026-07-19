from modules.tts.visemes import normalize_viseme_cues


def test_normalize_viseme_cues_sorts_bounds_and_drops_invalid_entries() -> None:
    cues = normalize_viseme_cues([
        {"viseme": "IH", "offset_ms": 70, "weight": 1.5},
        {"viseme": "aa", "offset_ms": 0, "duration_ms": 25},
        {"viseme": "unknown", "offset_ms": 10},
        {"viseme": "oh", "offset_ms": -1},
        {"viseme": "sil", "offset_ms": "120", "weight": -2},
        {"viseme": "ee", "offset_ms": float("nan")},
    ])

    assert cues == [
        {"viseme": "aa", "offset_ms": 0.0, "duration_ms": 25.0},
        {"viseme": "ih", "offset_ms": 70.0, "weight": 1.0},
        {"viseme": "sil", "offset_ms": 120.0, "weight": 0.0},
    ]


def test_normalize_viseme_cues_rejects_non_lists() -> None:
    assert normalize_viseme_cues({"viseme": "aa", "offset_ms": 0}) == []
