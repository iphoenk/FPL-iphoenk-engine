from datetime import datetime, timedelta, timezone

import pytest

import src.v5.execution_plane as execution_plane
from src.v5.execution_plane import (
    build_hot_bundle,
    evaluate_hot_materialization,
    freshness_budget_seconds,
    plane,
    refresh_schedule,
    requires_active_refresh_worker,
)


def _bundle(now: datetime, fingerprint: str = "fp1", mode: str = "deadline"):
    return {
        "schema_version": 2,
        "contract": "V5_DECISION_HOT_BUNDLE_V2",
        "generated_at": now.isoformat(),
        "runtime_fingerprint": fingerprint,
        "mode": mode,
        "phase": {"phase": "PRE_DEADLINE"},
        "team_id": 1,
        "squad_authority": "user_lock",
        "decision_summary": {},
        "framework_health": {},
        "watchlist_summary": {},
        "user_report": {},
        "technical_appendix": {},
        "report_state": {},
    }


def test_hot_plane_is_subsecond_and_forbids_network_refresh():
    hot = plane("hot")
    assert hot["hard_limit_ms"] == 950
    assert hot["network_refresh_allowed"] is False
    assert hot["stale_materialization_action"] == "FAIL_CLOSED"
    assert "historical_prior_and_native_prediction" not in hot["allowed_stages"]


def test_refresh_schedule_has_strict_freshness_headroom_for_every_mode():
    for mode in ("daily", "deadline", "live", "on_demand"):
        schedule = refresh_schedule(mode)
        assert schedule["target_interval_seconds"] < schedule["freshness_budget_seconds"]
        assert schedule["freshness_headroom_seconds"] > 0
        assert schedule["hidden_request_time_refresh_forbidden"] is True
        assert schedule["overlapping_refreshes_forbidden"] is True
        assert schedule["worker_enablement_requires_explicit_deployment_config"] is True


def test_deadline_and_live_require_non_github_subminute_worker():
    for mode in ("deadline", "live"):
        schedule = refresh_schedule(mode)
        assert schedule["scheduler_class"] == "SUBMINUTE_WORKER_REQUIRED"
        assert schedule["target_interval_seconds"] < 60
        assert schedule["github_actions_authoritative"] is False
        assert requires_active_refresh_worker(mode) is True


def test_daily_allows_coarse_scheduler_and_on_demand_requires_explicit_prewarm():
    daily = refresh_schedule("daily")
    on_demand = refresh_schedule("on_demand")
    assert daily["scheduler_class"] == "COARSE_ALLOWED"
    assert daily["github_actions_authoritative"] is True
    assert requires_active_refresh_worker("daily") is False
    assert on_demand["scheduler_class"] == "EXPLICIT_PREWARM_REQUIRED"
    assert on_demand["activation"] == "EXPLICIT_PREWARM"
    assert requires_active_refresh_worker("on_demand") is False


def test_refresh_interval_equal_to_freshness_budget_is_rejected(monkeypatch):
    monkeypatch.setattr(execution_plane, "freshness_budget_seconds", lambda mode, name=None: 20)
    with pytest.raises(RuntimeError, match="must be below freshness budget"):
        execution_plane.refresh_schedule("deadline")


def test_build_hot_bundle_is_compact_and_declares_full_refresh_provenance():
    result = build_hot_bundle(
        {
            "mode": "daily",
            "phase": {"phase": "PRE_DEADLINE"},
            "team_id": 1,
            "squad_authority": "user_lock",
            "decision_summary": {"selected_package_id": "HOLD"},
            "framework_health": {"go_allowed": False},
            "prediction_summary": {"player_count": 700},
            "evaluation_summary": {"sample_size": 0},
        },
        {"status": "READY", "candidate_count": 20, "target_count": 20, "screening_contract": "FULL_DSS_SCREEN_V1"},
        {"user_report": {"layer": "USER_REPORT"}, "technical_appendix": {"layer": "TECHNICAL_APPENDIX"}, "report_state": {"state": {}}},
        generated_at="2026-08-28T00:00:00+00:00",
        runtime_fingerprint_value="fp1",
    )
    assert result["contract"] == "V5_DECISION_HOT_BUNDLE_V2"
    assert result["runtime_fingerprint"] == "fp1"
    assert result["watchlist_summary"]["candidate_count"] == 20
    assert result["governance"]["quality_reduction_for_latency"] is False
    assert "players" not in result


def test_fresh_materialization_is_hot_eligible():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    result = evaluate_hot_materialization(
        _bundle(now - timedelta(seconds=10)),
        mode="deadline",
        current_runtime_fingerprint="fp1",
        now=now,
    )
    assert result["status"] == "READY"
    assert result["eligible"] is True
    assert result["hard_limit_ms"] == 950


def test_mode_mismatch_fails_closed_even_when_timestamp_is_fresh():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    result = evaluate_hot_materialization(
        _bundle(now - timedelta(seconds=1), mode="daily"),
        mode="deadline",
        current_runtime_fingerprint="fp1",
        now=now,
    )
    assert result["status"] == "STALE"
    assert result["eligible"] is False
    assert result["reason"] == "MODE_MISMATCH"
    assert result["materialized_mode"] == "daily"
    assert result["requested_mode"] == "deadline"
    assert result["action"] == "FAIL_CLOSED"


def test_stale_materialization_fails_closed_without_hidden_refresh():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    budget = freshness_budget_seconds("deadline")
    result = evaluate_hot_materialization(
        _bundle(now - timedelta(seconds=budget + 1)),
        mode="deadline",
        current_runtime_fingerprint="fp1",
        now=now,
    )
    assert result["status"] == "STALE"
    assert result["eligible"] is False
    assert result["reason"] == "FRESHNESS_BUDGET_EXCEEDED"
    assert result["action"] == "FAIL_CLOSED"


def test_runtime_fingerprint_mismatch_is_stale():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    result = evaluate_hot_materialization(
        _bundle(now, fingerprint="old", mode="daily"),
        mode="daily",
        current_runtime_fingerprint="new",
        now=now,
    )
    assert result["status"] == "STALE"
    assert result["reason"] == "RUNTIME_FINGERPRINT_MISMATCH"


def test_missing_required_field_fails_closed():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    bundle = _bundle(now, mode="daily")
    del bundle["decision_summary"]
    result = evaluate_hot_materialization(
        bundle,
        mode="daily",
        current_runtime_fingerprint="fp1",
        now=now,
    )
    assert result["eligible"] is False
    assert result["reason"] == "MISSING_REQUIRED_FIELDS"
    assert "decision_summary" in result["missing_fields"]
