# Player Minutes Migration Baseline

Baseline SHA: `247979ece6e6d0ebf652cf3c9c3f176d90fb6d3c`

This document freezes the numerical behavior used as the migration/regression oracle for the V12-native player-minutes owner. It is documentation only and is not an authority.

## Donors

- `src/models/xmins_v2.py`: hierarchical probability/minutes mathematics.
- `src/models/xmins_v3.py`: v2 wrapper, historical-prior confidence escalation, historical-prior lineage, and `enrich_xmins_contract`.
- `config/intelligence/xmins_v2.json`: legacy numerical parameters.
- `config/intelligence/historical_priors.json`: historical-prior confidence thresholds and governance.
- `src/engines/p0_decision_quality.py::enrich_xmins_contract`: probability/finite-state contract validation.

## Inputs and defaults

Player factual inputs: `chance_of_playing_next_round`, `status`, `starts`, `minutes`.

Context inputs: `team_matches_played`, `prior_start_probability`, `prior_evidence_minutes`, `prior_source`, `prior_identity_match`, `role_start_probability`, `manager_start_probability`, `rotation_risk`, `congestion_factor`, `starter_minutes_prior`, `bench_minutes_prior`, `late_cameo_minutes_prior`.

Official availability is upstream factual authority. Explicit chance is `clamp(chance/100,0,1)`; otherwise status defaults are `a=1`, `d=0.75`, `i=0.25`, `s=0`, `u=0`, unknown status=1.

Frozen numerical defaults: neutral start prior 0.72; weighted-logit weights neutral 0.8, season rate 1.4, historical prior 1.2, role 1.1, manager 1.3; season shrinkage 4 matches; rotation strength 0.55; bench share 0.65; cameo-given-bench 0.72; late-cameo share 0.35; starter fallback 72 with 4-start shrinkage and 45..90 clamp; cameo fallback 18; late cameo 8; state std START/CAMEO/LATE/ZERO = 10/7/4/0; small sample <3 matches; start-probability half-width 0.12 plus 0.12 small-sample; minutes uncertainty base 11 + normalized four-state entropy*18 + 8 small-sample. Base confidence HIGH requires starts>=6, >=2 signals and availability>=0.95; MEDIUM requires starts>=2 and availability>=0.75. Historical evidence can lift LOW to MEDIUM at 900 prior minutes and to HIGH at 1800 prior minutes plus >=2 current starts.

## Formulas

`observed_rate = clamp(starts / max(1,matches),0,1)`

`season_rate = (observed_rate*matches + neutral*4) / (matches+4)`

`raw_start_given_available = sigmoid(sum(w_i*logit(p_i))/sum(w_i))`

`P(start|available) = clamp(raw * (1-rotation_risk*0.55) * congestion_factor,0,1)`

`P(start) = P(available)*P(start|available)`

`P(bench) = P(available)*(1-P(start|available))*P(bench|available,not start)`

`P(cameo) = P(bench)*P(cameo|bench)`

`P(late cameo) = P(cameo)*P(late cameo|cameo)`

`P(regular cameo) = P(cameo)-P(late cameo)`

`P(DNP) = (1-P(available)) + P(bench)*(1-P(cameo|bench)) + P(available)*(1-P(start|available))*(1-P(bench|available,not start))`

Only START + REGULAR_CAMEO + LATE_CAMEO + ZERO_MINUTES are mutually exclusive. BENCH overlaps cameo and unused-bench outcomes and must never be flat-normalized with START/CAMEO/DNP.

Starter minutes use observed minutes/start shrunk toward 72 by four starts unless an explicit starter prior is supplied. State-mixture mean is `sum(p_s*mean_s)`; mixture variance is `sum(p_s*(std_s^2+mean_s^2))-mean^2`. Published total minutes std adds calibration/entropy/small-sample uncertainty in quadrature.

## V12 ownership and difference classification

Production owner: `src/engines/v12_player_minutes.py`.
Stable production parameter file: `config/intelligence/player_minutes.json`.
Legacy xmins_v2/xmins_v3 remain migration/regression oracles only.

Expected classifications:
- shared deterministic numerical outputs: EXACT_EQUIVALENT;
- presentation-only float differences if ever observed: ROUNDING_ONLY;
- explicit derived probabilities, evidence lineage, calibration hook, Phase-0 model-evidence binding, appearance-state labels, stable model owner/config: INTENTIONAL_V12_NORMALIZATION;
- CALIBRATION_CHANGE: none in P1.1;
- BUG_FIX: none in P1.1;
- UNEXPECTED_REGRESSION: blocking and required to remain zero.

Golden fixture file covers nailed starter, uncertain starter, rotation risk, availability reduction, likely bench cameo, late cameo, likely DNP, early-season low sample, strong historical prior, missing historical prior, role evidence available, and manager evidence unavailable.
