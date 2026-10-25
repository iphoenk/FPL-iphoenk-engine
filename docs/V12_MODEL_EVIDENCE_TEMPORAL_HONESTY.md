# Model evidence: temporal and coverage honesty (E04)

Two gaps found by the 2026-10-25 audit and closed here, both additive or fail-closed and neither changing a score, weight or rule.

1. `build_model_run_binding` now rejects a `calibration_cutoff` later than `generated_at` (`ModelEvidenceError`). Equal is accepted. The four shipped configs (`v12_monte_carlo`, `v12_package_utility`, `v12_mini_league_overlay`, `v12_lineup_optimizer`) carry September cutoffs, which a regression test pins. Limit: the binding does not know the target deadline, so "before the target" is enforced against the run time only; the deadline rule stays in `freeze_prediction`.
2. `prediction_calibration_metrics` adds `coverage` (`forecast_count`, `settled_count`, `unsettled_count`, `unsettled_elements`). Forecasts without a settled actual used to disappear from `sample_size`; they are now counted. Metrics themselves are unchanged.

Already covered by existing suites, not re-tested: post-deadline forecast rejection and immutable freeze (`test_model_evidence_calibration`, `test_model_evidence_execution_binding`), settlement only after a finished event, fingerprints independent of wall clock, FPL availability flags as observation rather than a direct start probability (`test_player_minutes_finite_state`).

Not done: a disclosure field for the frozen cohort, explicit baseline-vs-model comparison (official/form), position and minutes cohort splits, and MAE/Spearman for captain and transfer-after-hit decisions. They need a design (walk-forward) and parameter tuning is a separate PR per the plan; nothing here selects a better model from three gameweeks.
