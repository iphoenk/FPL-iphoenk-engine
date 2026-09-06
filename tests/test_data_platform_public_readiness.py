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
