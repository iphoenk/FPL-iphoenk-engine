from datetime import datetime, timedelta, timezone

from src.v5.execution_plane import evaluate_hot_materialization, freshness_budget_seconds, plane


def _bundle(now: datetime, fingerprint: str = "fp1"):
    return {
        "generated_at": now.isoformat(),
        "runtime_fingerprint": fingerprint,
        "mode": "deadline",
        "phase": {"phase": "PRE_DEADLINE"},
        "truth": {},
        "price": {},
        "prediction": {},
        "evaluation": {},
        "prepared_decision": {},
        "watchlist": {},
    }


def test_hot_plane_is_subsecond_and_forbids_network_refresh():
    hot = plane("hot")
    assert hot["hard_limit_ms"] == 950
    assert hot["network_refresh_allowed"] is False
    assert hot["stale_materialization_action"] == "FAIL_CLOSED"


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
        _bundle(now, fingerprint="old"),
        mode="daily",
        current_runtime_fingerprint="new",
        now=now,
    )
    assert result["status"] == "STALE"
    assert result["reason"] == "RUNTIME_FINGERPRINT_MISMATCH"


def test_missing_required_field_fails_closed():
    now = datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    bundle = _bundle(now)
    del bundle["prepared_decision"]
    result = evaluate_hot_materialization(
        bundle,
        mode="daily",
        current_runtime_fingerprint="fp1",
        now=now,
    )
    assert result["eligible"] is False
    assert result["reason"] == "MISSING_REQUIRED_FIELDS"
    assert "prepared_decision" in result["missing_fields"]
