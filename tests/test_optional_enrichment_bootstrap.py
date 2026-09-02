from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.runtime_v3 import execution_profile_resolver as resolver


NOW = datetime(2026, 9, 2, 12, 31, tzinfo=timezone.utc)
REVISION = "UNDERSTAT_XHR_JSON_V1"


def _completed_report_state() -> dict:
    local_date = "2026-09-02"
    return {
        "checkpoint_history": [
            {"slot_id": "DAILY_DEEP", "local_date": local_date, "status": "COMPLETED"},
            {"slot_id": "MIDDAY_CATCHUP", "local_date": local_date, "status": "COMPLETED"},
            {"slot_id": "EVENING_CHECK", "local_date": local_date, "status": "COMPLETED"},
        ]
    }


def _write_raw(tmp_path, payload: dict) -> None:
    target = tmp_path / "stats" / "understat_epl_2026.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")


def _resolve() -> dict:
    return resolver.resolve_execution_profile(
        visible_mode="SILENT",
        deadline_intensive=False,
        match_window=False,
        post_deadline_reconciliation=False,
        now_utc=NOW,
        report_state=_completed_report_state(),
    )


def test_prior_transport_failure_retries_immediately_after_adapter_revision_change(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "source_availability": "UNAVAILABLE",
            "schema_valid": False,
            "refresh_attempted_at": (NOW - timedelta(minutes=1)).isoformat(),
            "error": "teamsData_missing_or_invalid;playersData_missing_or_invalid;datesData_missing_or_invalid",
        },
    )

    result = _resolve()

    assert result["profile"] == "deep_stats"
    assert result["optional_enrichment_bootstrap_required"] is True
    assert result["optional_enrichment_bootstrap_upgraded"] is True
    assert result["optional_enrichment_bootstrap_reason"] == "SOURCE_ADAPTER_REVISION_CHANGED"
    assert result["optional_enrichment_expected_source_revision"] == REVISION
    assert result["optional_enrichment_artifact_source_revision"] is None
    assert result["optional_enrichment_refresh_source_revision"] is None


def test_fast_deferred_current_transport_bootstraps_once_outside_fast(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "UNAVAILABLE",
            "schema_valid": False,
            "refresh_attempted_at": NOW.isoformat(),
            "refresh_error": "network_refresh_deferred_in_fast_decision",
        },
    )

    result = _resolve()

    assert result["profile"] == "deep_stats"
    assert result["mode"] == "daily"
    assert result["extra"] == "--deep-stats"
    assert result["optional_enrichment_bootstrap_required"] is True
    assert result["optional_enrichment_bootstrap_upgraded"] is True
    assert result["optional_enrichment_bootstrap_reason"] == "FAST_DEFERRED_WITHOUT_NETWORK_ATTEMPT"


def test_fresh_usable_understat_cache_keeps_normal_fast_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "AVAILABLE",
            "freshness": "FRESH",
            "schema_valid": True,
            "fetched_at": NOW.isoformat(),
        },
    )

    result = _resolve()

    assert result["profile"] == "fast_decision"
    assert result["optional_enrichment_bootstrap_required"] is False
    assert result["optional_enrichment_bootstrap_upgraded"] is False
    assert result["optional_enrichment_bootstrap_reason"] == "USABLE_CACHE_PRESENT"
    assert result["optional_enrichment_artifact_freshness"] == "FRESH"


def test_stale_available_cache_upgrades_daily_run_for_governed_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "AVAILABLE",
            "freshness": "STALE",
            "schema_valid": True,
            "fetched_at": (NOW - timedelta(hours=7)).isoformat(),
        },
    )

    result = _resolve()

    assert result["profile"] == "deep_stats"
    assert result["mode"] == "daily"
    assert result["extra"] == "--deep-stats"
    assert result["optional_enrichment_bootstrap_required"] is True
    assert result["optional_enrichment_bootstrap_upgraded"] is True
    assert result["optional_enrichment_bootstrap_reason"] == "CACHE_FRESHNESS_NOT_USABLE"
    assert result["optional_enrichment_artifact_freshness"] == "STALE"


def test_recent_real_refresh_failure_on_current_transport_obeys_retry_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "UNAVAILABLE",
            "schema_valid": False,
            "refresh_attempted_at": (NOW - timedelta(minutes=10)).isoformat(),
            "error": "RuntimeError: bounded source failure",
        },
    )

    result = _resolve()

    assert result["profile"] == "fast_decision"
    assert result["optional_enrichment_bootstrap_required"] is False
    assert result["optional_enrichment_bootstrap_upgraded"] is False
    assert result["optional_enrichment_bootstrap_reason"] == "REAL_REFRESH_FAILURE_COOLDOWN"
    assert result["optional_enrichment_retry_after"] is not None


def test_current_transport_failure_after_cooldown_becomes_retry_eligible(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "UNAVAILABLE",
            "schema_valid": False,
            "refresh_attempted_at": (NOW - timedelta(minutes=61)).isoformat(),
            "error": "RuntimeError: prior bounded source failure",
        },
    )

    result = _resolve()

    assert result["profile"] == "deep_stats"
    assert result["optional_enrichment_bootstrap_required"] is True
    assert result["optional_enrichment_bootstrap_upgraded"] is True
    assert result["optional_enrichment_bootstrap_reason"] == "MISSING_OR_INVALID_CACHE"


def test_current_transport_refresh_failure_with_old_lkg_still_honors_cooldown(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": "UNDERSTAT_HTML_V0",
            "refresh_transport_revision": REVISION,
            "source_availability": "STALE_FALLBACK",
            "freshness": "STALE",
            "schema_valid": True,
            "refresh_attempted_at": (NOW - timedelta(minutes=5)).isoformat(),
            "fetched_at": (NOW - timedelta(hours=7)).isoformat(),
        },
    )

    result = _resolve()

    assert result["profile"] == "fast_decision"
    assert result["optional_enrichment_bootstrap_required"] is False
    assert result["optional_enrichment_bootstrap_reason"] == "REAL_REFRESH_FAILURE_COOLDOWN"
    assert result["optional_enrichment_artifact_freshness"] == "STALE"


def test_stale_fallback_after_cooldown_retries_via_existing_deep_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "STALE_FALLBACK",
            "freshness": "STALE",
            "schema_valid": True,
            "refresh_attempted_at": (NOW - timedelta(minutes=61)).isoformat(),
            "fetched_at": (NOW - timedelta(hours=7)).isoformat(),
        },
    )

    result = _resolve()

    assert result["profile"] == "deep_stats"
    assert result["optional_enrichment_bootstrap_required"] is True
    assert result["optional_enrichment_bootstrap_upgraded"] is True
    assert result["optional_enrichment_bootstrap_reason"] == "CACHE_FRESHNESS_NOT_USABLE"


def test_deadline_mode_is_never_upgraded_for_optional_understat_bootstrap(monkeypatch, tmp_path):
    monkeypatch.setattr(resolver, "DATA", tmp_path)
    _write_raw(
        tmp_path,
        {
            "contract": "UNDERSTAT_RAW_SOURCE_V1",
            "transport_revision": REVISION,
            "refresh_transport_revision": REVISION,
            "source_availability": "AVAILABLE",
            "freshness": "STALE",
            "schema_valid": True,
            "fetched_at": (NOW - timedelta(hours=7)).isoformat(),
        },
    )

    result = resolver.resolve_execution_profile(
        visible_mode="SILENT",
        deadline_intensive=True,
        match_window=False,
        post_deadline_reconciliation=False,
        now_utc=NOW,
        report_state=_completed_report_state(),
    )

    assert result["profile"] == "fast_decision"
    assert result["mode"] == "deadline"
    assert result["optional_enrichment_bootstrap_required"] is False
    assert result["optional_enrichment_bootstrap_reason"] == "BASE_MODE_NOT_ELIGIBLE"
