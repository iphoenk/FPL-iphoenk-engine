from src.v5.sources.fusion import _aggregate_status


def test_active_enabled_source_makes_fusion_active():
    summaries = {
        "api_football": {"status": "ACTIVE", "fail_neutral": True},
        "understat": {"status": "DISABLED", "fail_neutral": True},
    }
    assert _aggregate_status(summaries, ["api_football"]) == "ACTIVE"


def test_fail_neutral_unavailable_provider_keeps_provider_truth_but_degrades_aggregate():
    summaries = {
        "api_football": {
            "status": "UNAVAILABLE",
            "availability_class": "PLAN_RESTRICTED",
            "fail_neutral": True,
        },
        "understat": {"status": "DISABLED", "fail_neutral": True},
    }
    assert summaries["api_football"]["status"] == "UNAVAILABLE"
    assert _aggregate_status(summaries, ["api_football"]) == "DEGRADED"


def test_unexpected_unavailable_provider_fails_aggregate_health():
    summaries = {
        "api_football": {
            "status": "UNAVAILABLE",
            "availability_class": "NETWORK_ERROR",
            "fail_neutral": False,
        }
    }
    assert _aggregate_status(summaries, ["api_football"]) == "UNAVAILABLE"


def test_no_enabled_sources_is_unavailable_not_fake_degraded():
    summaries = {"understat": {"status": "DISABLED", "fail_neutral": True}}
    assert _aggregate_status(summaries, []) == "UNAVAILABLE"
