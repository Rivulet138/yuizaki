from scripts.check_requirements_lock import main


def test_platform_lock_matrix_matches_source_manifests():
    assert main() == 0
