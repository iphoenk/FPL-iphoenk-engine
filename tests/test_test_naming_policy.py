import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
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
