from src.engines.official_fact_completeness import _snapshot_metadata
from src.engines.official_snapshot_service import _fallback_snapshot


def test_fallback_fact_provenance_uses_last_verified_snapshot_time_not_failed_pull_time():
    last_verified = "2026-08-31T05:30:00+00:00"
    failed_at = "2026-08-31T06:30:00+00:00"
    previous = {
        "generated_at": last_verified,
        "bootstrap": {"elements": [{"id": 1}]},
        "endpoint_health": {
            "bootstrap": {"status": "LIVE", "fetched_at": last_verified}
        },
        "official_freshness": {
            "state": "FRESH",
            "fallback": False,
            "snapshot_id": f"bootstrap-static@{last_verified}",
            "last_verified_at": last_verified,
            "age_seconds": 0,
            "confidence": "HIGH",
        },
    }
    fallback = _fallback_snapshot(
        previous,
        {"status": "FAILED", "fetched_at": failed_at, "error": "Timeout"},
    )
    assert fallback is not None

    meta = _snapshot_metadata(fallback)
    assert meta["freshness_state"] == "FALLBACK"
    assert meta["fetched_at"] == last_verified
    assert meta["last_verified_at"] == last_verified
    assert meta["fresh_pull_failed_at"] == failed_at
    assert meta["fetched_at"] != failed_at
