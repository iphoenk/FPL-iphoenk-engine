from __future__ import annotations

from src.runtime_v6.health import build_source_health


def _source(source_id: str, *, critical: bool = False) -> dict:
    return {
        "id": source_id,
        "name": source_id,
        "category": "test",
        "critical": critical,
        "entity_scopes": [],
        "check_freshness_minutes": 90,
        "acquisition_kind": "rest_json",
    }


def _payload(source_id: str, *, availability: str = "AVAILABLE", status: str = "AVAILABLE") -> dict:
    return {
        "source_id": source_id,
        "checked_at": "2099-01-01T00:00:00+00:00",
        "health": "GREEN" if status == "AVAILABLE" else "AMBER",
        "availability": availability,
        "attempts": [
            {
                "status": status,
                "health": "GREEN" if status == "AVAILABLE" else "AMBER",
                "checked_at": "2099-01-01T00:00:00+00:00",
            }
        ],
        "coverage": {
            "expected_requests": 1,
            "usable_requests": 1 if status == "AVAILABLE" else 0,
            "truncated_attempts": 0,
        },
        "data": {
            "x": {
                "data_origin": "CURRENT_CYCLE",
                "checked_at": "2099-01-01T00:00:00+00:00",
                "sha256": "abc",
            }
        },
    }


def test_identity_unmapped_does_not_trigger_public_fallback():
    config = {"sources": [_source("secondary")]}
    health = build_source_health(config, {"secondary": _payload("secondary")}, identity_map={})
    row = health["sources"][0]

    assert row["readiness"]["operational"] == "GREEN"
    assert row["readiness"]["data"] == "GREEN"
    assert row["readiness"]["join"] == "NOT_APPLICABLE"
    assert row["fallback_recommended"] is False
    assert health["fallback_sources"] == []


def test_failed_optional_source_recommends_report_layer_refresh_without_red_public_core():
    config = {"sources": [_source("official", critical=True), _source("optional")]}
    results = {
        "official": _payload("official"),
        "optional": _payload("optional", availability="UNAVAILABLE", status="FAILED"),
    }
    health = build_source_health(config, results, identity_map={})
    optional = next(row for row in health["sources"] if row["source_id"] == "optional")

    assert health["public_core_status"] == "GREEN"
    assert health["consumer_readiness_overall"] in {"AMBER", "RED"}
    assert optional["fallback_recommended"] is True
    assert optional["fallback_reason"] == "TRANSPORT_UNAVAILABLE"
    assert health["fallback_sources"] == [
        {"source_id": "optional", "reason": "TRANSPORT_UNAVAILABLE"}
    ]


def test_failed_critical_public_source_blocks_public_core():
    config = {"sources": [_source("official", critical=True)]}
    health = build_source_health(
        config,
        {"official": _payload("official", availability="UNAVAILABLE", status="FAILED")},
        identity_map={},
    )

    assert health["public_core_status"] in {"AMBER", "RED"}
    assert health["fallback_recommended"] is True

    # Live Official source can contain immutable postmatch/historical caches
    # from weeks ago. They must not misclassify a fresh base acquisition.
    declared = _source("official", critical=True)
    declared["requests"] = [{"id": "bootstrap"}, {"id": "fixtures"}]
    current = _payload("official")
    current["data"] = {
        "bootstrap": {"status": "AVAILABLE", "data_origin": "CURRENT_CYCLE",
                      "checked_at": "2099-01-01T00:00:00+00:00", "sha256": "a" * 64},
        "fixtures": {"status": "AVAILABLE", "data_origin": "CURRENT_CYCLE",
                     "checked_at": "2099-01-01T00:00:00+00:00", "sha256": "b" * 64},
        "history_20260912": {"status": "AVAILABLE", "data_origin": "FINALIZED_HISTORY_CACHE",
                              "checked_at": "2026-09-12T00:00:00+00:00", "sha256": "c" * 64},
    }
    ready = build_source_health({"sources": [declared]}, {"official": current}, identity_map={})
    official_row = ready["sources"][0]
    assert ready["public_core_status"] == "GREEN"
    assert official_row["dimensions"]["freshness_health"] == "GREEN"
    assert official_row["freshness_scope"] == "DECLARED_LIVE_REQUESTS"
    assert official_row["max_effective_data_age_minutes"] > 90
    assert official_row["max_required_live_request_age_minutes"] == 0

    # Missing and genuinely stale declared live rows must remain RED.
    from copy import deepcopy
    missing = deepcopy(current)
    del missing["data"]["bootstrap"]
    missing_health = build_source_health(
        {"sources": [declared]}, {"official": missing}, identity_map={}
    )
    assert missing_health["public_core_status"] == "RED"
    assert missing_health["sources"][0]["max_required_live_request_age_minutes"] is None

    stale = deepcopy(current)
    stale["data"]["fixtures"]["checked_at"] = "2026-09-12T00:00:00+00:00"
    stale_health = build_source_health(
        {"sources": [declared]}, {"official": stale}, identity_map={}
    )
    assert stale_health["public_core_status"] == "RED"
    assert stale_health["sources"][0]["dimensions"]["freshness_health"] == "RED"

    # Provider 304 proof can be fresh even when original body SHA is old.
    revalidated = deepcopy(current)
    revalidated["data"]["fixtures"].update({
        "data_origin": "REVALIDATED_CACHE", "status": "NOT_MODIFIED",
        "checked_at": "2026-09-12T00:00:00+00:00",
        "revalidated_at": "2099-01-01T00:00:00+00:00",
    })
    cache_health = build_source_health(
        {"sources": [declared]}, {"official": revalidated}, identity_map={}
    )
    assert cache_health["public_core_status"] == "GREEN"
