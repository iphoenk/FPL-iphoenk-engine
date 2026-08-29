import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
LEGACY_VERSION_STAMPED = {
    "test_v311_prediction_performance.py",
    "test_v312_lineup_governance.py",
    "test_v313_report_architecture.py",
    "test_v314_dss_watchlist.py",
    "test_v314_watchlist_sanitize.py",
    "test_v315_report_serving.py",
    "test_v317_dss_operationalization.py",
    "test_v318_architecture_governance.py",
    "test_v319_report_time_intelligence.py",
    "test_v3201_correctness.py",
    "test_v3202_artifact_contracts.py",
    "test_v321_weather_report_transparency.py",
    "test_v34_reliability.py",
    "test_v3_microservice_runtime.py",
}


def test_no_new_version_stamped_test_modules_are_added():
    version_pattern = re.compile(r"^test_v\d")
    actual = {path.name for path in TESTS.glob("test_v*.py") if version_pattern.match(path.name)}
    assert actual <= LEGACY_VERSION_STAMPED, (
        "New tests must use domain/capability names, not release-version names. "
        f"Unexpected: {sorted(actual - LEGACY_VERSION_STAMPED)}"
    )
    assert "test_v322_runtime_optimization.py" not in actual
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
