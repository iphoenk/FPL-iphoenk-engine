from src.v5.evaluation.temporal_backtest import compare_to_frozen_baseline, validate_frozen_ledger

def test_temporal_guard_detects_post_deadline_forecast():
    ledger={"records":{"2":{"gw":2,"deadline_time":"2026-08-28T10:00:00+00:00","frozen_forecast":{"generated_at":"2026-08-28T10:01:00+00:00"},"frozen_at":"2026-08-28T10:02:00+00:00"}}}
    out=validate_frozen_ledger(ledger); assert out["status"]=="FAIL"; assert out["time_travel_detected"] is True

def test_no_frozen_baseline_never_claims_non_regression():
    out=compare_to_frozen_baseline({"points_mae":2.0},None); assert out["status"]=="NO_FROZEN_BASELINE"; assert out["non_regression_pass"] is False
