from pathlib import Path

from i18n import I18nManager


def test_default_locale_directory_is_independent_of_current_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    manager = I18nManager()

    assert manager.locales_dir == Path(__file__).resolve().parents[1] / "locales"
    assert manager.get("common.save", "zh-CN")
    assert manager.get("common.save", "en-US")
    assert manager.get("common.save", "ja-JP")
