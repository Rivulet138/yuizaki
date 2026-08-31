from __future__ import annotations

from scripts.prefetch_genie_tts import normalize_genie_language


def test_auto_language_uses_japanese_character_model() -> None:
    assert normalize_genie_language("auto") == "Japanese"


def test_supported_genie_languages_are_normalized() -> None:
    assert normalize_genie_language("zh") == "Chinese"
    assert normalize_genie_language("en") == "English"
    assert normalize_genie_language("ja") == "Japanese"
