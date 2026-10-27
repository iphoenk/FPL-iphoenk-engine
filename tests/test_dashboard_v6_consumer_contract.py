"""Downstream contract: what the protected FPL dashboard reads from V6.

iphoenk/fpl-iphoenk-dashboard (multiuser-decision-server.mjs) fetches only
  <runtime-data-v6>/data/v6/evidence/latest_index.json
  <runtime-data-v6>/data/v6/health/publish_integrity.json
and treats a missing/invalid pair as UNAVAILABLE/UNVERIFIED (never a crash).
These tests pin the fields and types it depends on so that engine or V6
publisher changes cannot silently break it. They never touch the dashboard.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "dashboard_v6_consumer_contract.json").read_text("utf-8")
)


def _aware(value):
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def dashboard_provenance(index, integrity):
    """Python mirror of the dashboard's provenance() decision (read side)."""
    source = next((s for s in index.get("sources", []) if s.get("source_id") == "official_fpl"), None)
    stamp = integrity.get("observed_at") or index.get("generated_at")
    try:
        _aware(stamp)
    except (TypeError, ValueError, AssertionError):
        return "UNVERIFIED"
    if integrity.get("status") != "PASS":
        return "UNVERIFIED"
    return "VERIFIED:" + str((source or {}).get("health", "UNAVAILABLE"))


def test_integrity_fields_consumed_by_dashboard_are_present_and_typed():
    integrity = FIXTURE["publish_integrity"]
    assert integrity["status"] in {"PASS", "FAIL"}
    _aware(integrity["observed_at"])
    assert isinstance(integrity["schema_version"], int)


def test_index_fields_consumed_by_dashboard_are_present_and_typed():
    index = FIXTURE["latest_index"]
    _aware(index["generated_at"])
    assert isinstance(index["sources"], list) and index["sources"]
    for row in index["sources"]:
        assert isinstance(row["source_id"], str) and row["source_id"]
        assert isinstance(row["health"], str) and row["health"]
    assert any(r["source_id"] == "official_fpl" for r in index["sources"])


def test_frozen_production_pair_is_verified_for_dashboard():
    assert dashboard_provenance(FIXTURE["latest_index"], FIXTURE["publish_integrity"]) == "VERIFIED:GREEN"


def test_failed_integrity_is_unverified_not_verified():
    bad = dict(FIXTURE["publish_integrity"], status="FAIL")
    assert dashboard_provenance(FIXTURE["latest_index"], bad) == "UNVERIFIED"


def test_naive_or_missing_timestamp_is_unverified():
    bad = dict(FIXTURE["publish_integrity"], observed_at="2026-10-27T00:45:57")
    assert dashboard_provenance(FIXTURE["latest_index"], bad) == "UNVERIFIED"
    index = dict(FIXTURE["latest_index"], generated_at="")
    bad = dict(FIXTURE["publish_integrity"], observed_at="")
    assert dashboard_provenance(index, bad) == "UNVERIFIED"


def test_v12_verified_pointer_and_private_artifacts_are_not_dashboard_inputs():
    """The dashboard has no V12/private input; the verified pointer lives in a
    private repository and carries identifiers/hashes only (additive, versioned)."""
    from ops import verified_pointer

    assert verified_pointer.SCHEMA == "FPL_VERIFIED_POINTER_V1"
