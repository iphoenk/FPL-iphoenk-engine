from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v6 import health
from src.runtime_v6.artifact_catalog import CATALOG_RELATIVE_PATH, write_artifact_catalog


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def test_source_health_exposes_independent_dimensions_and_cache_truth(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "player_identity_map.json").write_text(
        json.dumps(
            {
                "coverage": {
                    "example": {
                        "identity_health": "RED",
                        "mapped_status": "UNMAPPED",
                        "join_allowed": False,
                        "strategy": "NO_DETERMINISTIC_BRIDGE",
                        "coverage_ratio": 0.0,
                        "mapped_player_count": 0,
                        "unmapped_player_count": 10,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(health, "EVIDENCE", evidence)

    source = {
        "id": "example",
        "name": "Example",
        "category": "test",
        "critical": False,
        "adapter": "http",
        "acquisition_kind": "rest_json",
        "check_freshness_minutes": 90,
    }
    payload = {
        "source_id": "example",
        "health": "AMBER",
        "availability": "PARTIAL",
        "effective_state": "STALE_CACHE",
        "checked_at": _iso(),
        "duration_ms": 25.0,
        "attempts": [
            {
                "request_id": "one",
                "status": "UNAVAILABLE",
                "checked_at": _iso(),
                "attempt_count": 2,
                "latency_ms": 24.0,
            }
        ],
        "data": {
            "one": {
                "request_id": "one",
                "status": "AVAILABLE",
                "checked_at": _iso(30),
                "sha256": "abc",
                "data_origin": "LAST_GOOD_CACHE",
                "etag": "etag-1",
            }
        },
        "coverage": {
            "expected_requests": 1,
            "successful_checks_this_cycle": 0,
            "usable_requests": 1,
        },
        "polling": {"skipped": False, "reason": "DUE"},
        "governance": {"data_only": True},
    }

    report = health.build_source_health({"sources": [source]}, {"example": payload})
    row = report["sources"][0]

    assert report["schema_version"] == 4
    assert row["health"] == "AMBER"
    assert row["health_dimensions"] == {
        "transport_health": "AMBER",
        "freshness_health": "AMBER",
        "schema_health": "GREEN",
        "coverage_health": "GREEN",
        "identity_health": "RED",
        "provenance_health": "GREEN",
        "payload_integrity": "GREEN",
    }
    assert row["freshness"]["classification"] == "STALE_BUT_USABLE"
    assert row["freshness"]["source_specific_slo"] is True
    cache = row["cache_reuse_observability"]
    assert cache["network_fetch_performed"] is True
    assert cache["payload_effective_at"] is not None
    assert cache["cache_age_seconds"] is not None
    assert cache["current_run_duration_ms"] == 25.0
    assert cache["validators"]["one"]["etag"] == "etag-1"
    assert cache["zero_duration_is_never_network_fetch_claim"] is True


def test_scheduled_skip_is_not_reported_as_zero_latency_network_fetch(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "player_identity_map.json").write_text(json.dumps({"coverage": {}}), encoding="utf-8")
    monkeypatch.setattr(health, "EVIDENCE", evidence)

    source = {
        "id": "official_fpl",
        "name": "Official FPL",
        "category": "factual_authority",
        "critical": True,
        "adapter": "official_fpl",
        "acquisition_kind": "rest_json",
        "check_freshness_minutes": 90,
    }
    payload = {
        "source_id": "official_fpl",
        "health": "GREEN",
        "availability": "AVAILABLE",
        "effective_state": "SCHEDULED_CACHE",
        "checked_at": _iso(10),
        "duration_ms": 0.0,
        "attempts": [],
        "data": {
            "bootstrap": {
                "request_id": "bootstrap",
                "checked_at": _iso(10),
                "sha256": "abc",
                "data_origin": "CURRENT_CYCLE",
            }
        },
        "coverage": {"expected_requests": 1, "successful_checks_this_cycle": 1, "usable_requests": 1},
        "polling": {"skipped": True, "reason": "ALREADY_POLLED_THIS_SLOT"},
        "governance": {"data_only": True},
    }
    row = health.build_source_health({"sources": [source]}, {"official_fpl": payload})["sources"][0]
    cache = row["cache_reuse_observability"]
    assert cache["current_run_action"] == "SKIPPED_ALREADY_POLLED"
    assert cache["network_fetch_performed"] is False
    assert cache["current_run_duration_ms"] == 0.0
    assert cache["zero_duration_is_never_network_fetch_claim"] is True


def test_artifact_catalog_has_granular_lineage_and_checksum(tmp_path, monkeypatch):
    root = tmp_path / "data" / "v6"
    (root / "current").mkdir(parents=True)
    (root / "normalized").mkdir(parents=True)
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    (root / "manifest.json").write_text(
        json.dumps({"schema_version": 3, "generated_at": _iso(), "canonical": True}),
        encoding="utf-8",
    )
    (root / "current" / "example.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "source_id": "example",
                "checked_at": _iso(),
                "health": "GREEN",
                "data": {
                    "one": {
                        "request_id": "one",
                        "payload_digest": "payload-1",
                        "checked_at": _iso(),
                    }
                },
                "authority": "UPSTREAM_SOURCE",
                "normalization_version": "n1",
            }
        ),
        encoding="utf-8",
    )

    catalog = write_artifact_catalog(root)
    catalog_path = root / CATALOG_RELATIVE_PATH
    assert catalog_path.is_file()
    assert catalog["artifact_count"] == 2
    by_id = {row["artifact_id"]: row for row in catalog["artifacts"]}
    row = by_id["current/example.json"]
    assert row["path"] == "data/v6/current/example.json"
    assert row["producer_commit_sha"] == "abc123"
    assert row["source_snapshot_ids"] == ["payload-1"]
    assert row["primary_keys"] == ["request_id"]
    assert row["sha256"]
    assert row["bytes"] > 0
    assert row["authority"] == "UPSTREAM_SOURCE"
    assert row["normalization_version"] == "n1"
    assert row["freshness_class"] == "FRESH_OR_CURRENT"
    assert catalog["governance"]["catalog_does_not_create_analytical_authority"] is True
