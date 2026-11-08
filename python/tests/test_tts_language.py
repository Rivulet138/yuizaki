from pathlib import Path
from types import SimpleNamespace

from modules.tts.synthesizer import _generate_wav, _resolve_utterance_language


def test_fixed_japanese_tts_does_not_follow_chinese_llm_text() -> None:
    assert _resolve_utterance_language("你好，今天过得怎么样？", "ja", "Japanese") == "Japanese"


def test_auto_tts_language_detection_remains_opt_in() -> None:
    assert _resolve_utterance_language("你好", "auto", "Japanese") == "Chinese"


def test_genie_receives_full_translation_and_owns_sentence_splitting(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def tts(**kwargs: object) -> None:
        calls.append(kwargs)
        Path(str(kwargs["save_path"])).write_bytes(b"wav")

    genie = SimpleNamespace(tts=tts, wait_for_playback_done=lambda: None)
    path = tmp_path / "speech.wav"

    _generate_wav(
        genie,
        "japanese-character",
        "こんにちは。今日はお元気ですか？",
        str(path),
        split_sentence=True,
        language="Japanese",
    )

    assert calls[0]["text"] == "こんにちは。今日はお元気ですか？"
    assert calls[0]["split_sentence"] is True
    assert calls[0]["language"] == "Japanese"
