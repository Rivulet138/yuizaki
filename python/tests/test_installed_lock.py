from scripts.check_installed_lock import validate


def test_installed_lock_validator_rejects_non_exact_entries(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("example-package>=1\n", encoding="utf-8")

    errors = validate(lock)

    assert errors == ["example-package: lock entry is not an exact pin (>=1)"]


def test_installed_lock_validator_reports_missing_distribution(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("package-that-is-not-installed==1.0.0\n", encoding="utf-8")

    errors = validate(lock)

    assert errors == ["package-that-is-not-installed: not installed (expected 1.0.0)"]
