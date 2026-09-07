from src.platform.repository_test_naming_validate import validate_repository


def test_version_stamped_release_test_modules_are_fully_eliminated():
    failures = validate_repository()
    assert not [failure for failure in failures if "release-version test modules" in failure]


def test_no_accidental_placeholder_or_probe_files_are_committed():
    failures = validate_repository()
    assert not [failure for failure in failures if "placeholder/probe files" in failure]
