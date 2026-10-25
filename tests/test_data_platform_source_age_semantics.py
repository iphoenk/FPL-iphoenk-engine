from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.runtime_v6.consumer import MAX_CLOCK_SKEW_MINUTES, DEFAULT_MAX_AGE_MINUTES, assess_snapshot

from tests.test_data_platform_consumer import _write_snapshot

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def _iso(delta_minutes: float) -> str:
    return (NOW + timedelta(minutes=delta_minutes)).isoformat()


def test_missing_publish_time_is_unknown_and_invalid(tmp_path: Path):
    _write_snapshot(tmp_path, _iso(-1))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest.pop("generated_at")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    result = assess_snapshot(tmp_path, now=NOW)
    assert result["state"] == "INVALID" and result["usable"] is False
    assert "MISSING_GENERATED_AT" in result["failures"]
    assert result["generated_at"] is None and result["age_minutes"] is None
    assert result["source_time_semantics"]["publication_generated_at"] is None


def test_future_timestamp_is_rejected_beyond_clock_skew_only(tmp_path: Path):
    _write_snapshot(tmp_path, _iso(MAX_CLOCK_SKEW_MINUTES + 1))
    result = assess_snapshot(tmp_path, now=NOW)
    assert "GENERATED_AT_IN_FUTURE" in result["failures"] and result["usable"] is False
    _write_snapshot(tmp_path, _iso(MAX_CLOCK_SKEW_MINUTES - 1))
    assert "GENERATED_AT_IN_FUTURE" not in assess_snapshot(tmp_path, now=NOW)["failures"]


def test_policy_limits_are_unchanged():
    assert DEFAULT_MAX_AGE_MINUTES == 90 and MAX_CLOCK_SKEW_MINUTES == 5


def test_stale_publication_stays_stale(tmp_path: Path):
    _write_snapshot(tmp_path, _iso(-(DEFAULT_MAX_AGE_MINUTES + 1)))
    result = assess_snapshot(tmp_path, now=NOW)
    assert result["state"] == "STALE" and result["usable"] is False


def test_fresh_state_does_not_claim_source_freshness(tmp_path: Path):
    # A republished old source gets a fresh manifest time. FRESH therefore means "recently
    # published and integrity-checked", and the result says source times are unknown.
    _write_snapshot(tmp_path, _iso(-1))
    result = assess_snapshot(tmp_path, now=NOW)
    assert result["state"] == "FRESH" and result["usable"] is True
    assert result["freshness_basis"] == "PUBLICATION_TIME_ONLY"
    sem = result["source_time_semantics"]
    assert sem["source_acquired_at"] is None and sem["source_published_at"] is None
    assert sem["source_time_status"] == "UNKNOWN"
    assert sem["publication_generated_at"] == result["generated_at"]
    assert sem["checked_at"] == result["evaluated_at"] == NOW.isoformat()


def test_additive_fields_keep_legacy_contract(tmp_path: Path):
    _write_snapshot(tmp_path, _iso(-1))
    result = assess_snapshot(tmp_path, now=NOW)
    for key in ("state", "usable", "direct_fallback_eligible", "generated_at", "evaluated_at",
                "age_minutes", "max_age_minutes", "failures", "stored_tree_sha256", "recomputed_tree_sha256"):
        assert key in result
    assert result["engine_artifact_fallback_allowed"] is False
