import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
DOMAIN_SUITES = {
    "test_prediction_and_correctness.py",
    "test_lineup_watchlist_and_governance.py",
    "test_reporting_and_sources.py",
    "test_architecture_and_runtime_contracts.py",
}


def test_version_stamped_release_test_modules_are_fully_eliminated():
    version_pattern = re.compile(r"^test_v\d")
    actual = {path.name for path in TESTS.glob("test_v*.py") if version_pattern.match(path.name)}
    assert actual == set(), (
        "Release-version test modules are forbidden; tests must be owned by stable domain/capability suites. "
        f"Unexpected: {sorted(actual)}"
    )
    assert all((TESTS / name).exists() for name in DOMAIN_SUITES)
    assert (TESTS / "test_runtime_optimization.py").exists()


def test_no_accidental_placeholder_or_probe_files_are_committed():
    forbidden_names = {
        "x",
        "noop",
        "noop.txt",
        "probe",
        "probe.txt",
        "accidental-noop",
        "accidental_noop",
    }
    forbidden_exact_contents = {
        "x",
        "noop",
        "probe",
        "accidental noop",
        "accidental noop/probe file",
    }
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name.lower() in forbidden_names:
            offenders.append(str(path.relative_to(ROOT)))
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gz", ".pyc"}:
            continue
        try:
            if path.stat().st_size <= 128:
                value = path.read_text(encoding="utf-8").strip().lower()
                if value in forbidden_exact_contents:
                    offenders.append(str(path.relative_to(ROOT)))
        except (UnicodeDecodeError, OSError):
            continue
    assert not offenders, f"Accidental placeholder/probe files must not be committed: {sorted(offenders)}"
