# Model evidence: temporal and coverage honesty (E04)

Two gaps found by the 2026-10-25 audit: one closed (additive coverage), one recorded and deliberately left open. No score, weight or rule changed.

1. NOT FIXED, recorded: `build_model_run_binding` accepts a `calibration_cutoff` later than `generated_at`. A blanket guard was tried and reverted: it fail-closed 34 `test_mini_league_overlay` tests, because the shipped overlay cutoff (2026-09-20T02:01:16Z) postdates the fixture run times, i.e. historical replays bind a later configured cutoff. Production runs use the current time and would pass, but replay behaviour is a design decision. `tests/test_audit_model_evidence_temporal.py` pins the current behaviour.
2. `prediction_calibration_metrics` adds `coverage` (`forecast_count`, `settled_count`, `unsettled_count`, `unsettled_elements`). Forecasts without a settled actual used to disappear from `sample_size`; they are now counted. Metrics themselves are unchanged.

Already covered by existing suites, not re-tested: post-deadline forecast rejection and immutable freeze (`test_model_evidence_calibration`, `test_model_evidence_execution_binding`), settlement only after a finished event, fingerprints independent of wall clock, FPL availability flags as observation rather than a direct start probability (`test_player_minutes_finite_state`).

Not done: a disclosure field for the frozen cohort, explicit baseline-vs-model comparison (official/form), position and minutes cohort splits, and MAE/Spearman for captain and transfer-after-hit decisions. They need a design (walk-forward) and parameter tuning is a separate PR per the plan; nothing here selects a better model from three gameweeks.
