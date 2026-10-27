# Model evidence: temporal and coverage honesty (E04)

Two gaps found by the 2026-10-25 audit: one closed (additive coverage), one recorded and deliberately left open. No score, weight or rule changed.

1. NOT FIXED, recorded: `build_model_run_binding` accepts a `calibration_cutoff` later than `generated_at`. A blanket guard was tried and reverted: it fail-closed 34 `test_mini_league_overlay` tests, because the shipped overlay cutoff (2026-09-20T02:01:16Z) postdates the fixture run times, i.e. historical replays bind a later configured cutoff. Production runs use the current time and would pass, but replay behaviour is a design decision. `tests/test_audit_model_evidence_temporal.py` pins the current behaviour.
2. `prediction_calibration_metrics` adds `coverage` (`forecast_count`, `settled_count`, `unsettled_count`, `unsettled_elements`). Forecasts without a settled actual used to disappear from `sample_size`; they are now counted. Metrics themselves are unchanged.

Already covered by existing suites, not re-tested: post-deadline forecast rejection and immutable freeze (`test_model_evidence_calibration`, `test_model_evidence_execution_binding`), settlement only after a finished event, fingerprints independent of wall clock, FPL availability flags as observation rather than a direct start probability (`test_player_minutes_finite_state`).

3. Added in the second E04 step (additive keys only; existing metrics and fingerprints unchanged; `tests/test_model_evidence_cohorts_baselines.py`):
   - `coverage.cohort`: names the population (`FROZEN_FORECAST_PLAYERS`) and states that players outside the frozen forecast are excluded.
   - `by_position` and `by_minutes_cohort`: the same metrics per position and per predicted-minutes cohort (<30, 30-<60, >=60). Minutes cohorts use the minutes frozen before the deadline, never realised minutes. Diagnostic only.
   - `baselines`: model vs reference projections when the frozen forecast row carries `baseline_xpts` (for example `official_ep`, `form`). Same players on both sides, no winner field. Without baselines the result is `NO_BASELINE_PROVIDED`; non-numeric values are ignored, never read as 0. No producer emits `baseline_xpts` yet, so today this is `NO_BASELINE_PROVIDED` in real records.
   - `decision_ranking_metrics` (also stored as `decision_ranking_calibration` on settlement): MAE and Spearman for the frozen captain candidates and transfer comparisons. Spearman needs at least 3 items. After-hit metrics use only comparisons with a numeric `exact_hit_cost`; the current snapshot producer always writes `None`, so after-hit is `UNAVAILABLE_EXACT_HIT_COST` in real records. The hit cost is never invented.
   - `aggregate_settled_ledgers`: `gameweek_count`, `gameweeks`, `evidence_scope.conclusive_model_comparison = false` and `governance.model_selection_from_aggregate_forbidden = true`. A few gameweeks cannot select a model.

Still not done: a walk-forward design, calibration-cutoff enforcement for replays (item 1), a producer for `baseline_xpts`, an exact hit-cost capture, and any parameter tuning (separate PR by the plan). Rollback: revert this change; the added keys are not consumed by any other module.
