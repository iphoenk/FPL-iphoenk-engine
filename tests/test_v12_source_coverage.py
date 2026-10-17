from src.engines.v12_source_coverage import (
    validate_independent_counterpart_coverage,
    validate_news_source_coverage,
)


def test_missing_news_coverage_fails_closed():
    result = validate_news_source_coverage(None)
    assert result["status"] == "FAIL"
    assert "ALL_20_CLUBS_IDENTITY_COVERAGE_INVALID" in result["failures"]


def test_missing_counterpart_fails_closed():
    result = validate_independent_counterpart_coverage(None)
    assert result["status"] == "FAIL"
    assert "COUNTERPART_DOMAIN_MISSING:CAPTAIN_VICE" in result["failures"]
