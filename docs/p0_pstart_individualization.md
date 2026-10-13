# P0 P(start) individualization

Status: implementation candidate, 2026-10-13 UTC. Documentation timestamp: 2026-10-13T21:10:00+07:00.

## Change

`V12_PLAYER_MINUTES` remains the only mathematical owner. Verified
`V6_NORMALIZED_PLAYER_MATCH_ROWS` now supplies a player-conditioned selection
posterior when available. The posterior uses exact official element identity,
match-level starter outcomes, a conservative neutral Beta prior, and a recent
three-match window. Provisional, pending, unavailable, and ambiguous rows are
excluded. No coach-fit or tactical-fit claim is converted into a probability.

The projection builder uses the verified match-level starts and minutes for
P1.1 when present. Official aggregate fields remain the fallback when the
match-level evidence is absent. This prevents five identical aggregate inputs
from being mistaken for individual evidence.

## Published evidence

Each P1.1 output includes `selection_evidence`, its source, observed-match
count, start and recent-start rates, minutes when starting, and an explicit
missing-evidence reason. S02 acceptance separates evidence binding, historical
coverage, individual evidence, model resolution, calibration, temporal
integrity, and production verification.

## Safety boundaries

- No player override is hardcoded.
- No second P(start) owner is created.
- FPL injury flags remain observations, not probabilities.
- Coach and formation evidence remains advisory unless calibrated.
- Provisional GW6 observations cannot become FINAL through this change.
- Stage2 cache fingerprints already include the player-match evidence and the
  model/config dependency hashes, so evidence or model changes invalidate the
  derived cache.

## Validation required before promotion

The existing golden and contract suites must pass. A walk-forward backtest
must compare starter Brier score, log loss, calibration, xMins error, DNP and
cameo calibration by position and team. Six gameweeks are evidence coverage,
not sufficient sample size for claiming high calibration confidence.

## GW1–GW6 player selection: resolution and universe calibration acceptance

**Canonical mathematical owner remains V12_PLAYER_MINUTES.** The resolution
audit now compares provenance-backed player selection inputs, reports shared
rounded P(start) with identical/different evidence fingerprints, and explicitly
separates historical individual evidence from missing calibrated role, manager,
prior and availability signals. Probability diversity alone never promotes a
model. Report S02 shows these diagnostics without changing xMins or xPts.

The Stage1 V6 normalized official match fixture rows now feed an expanding-GW
paired backtest of the *existing* baseline and individual posterior model,
using GW strictly earlier than the target for training. Diagnostics include
starter Brier/log loss, xMins MAE, DNP/cameo Brier, reliability bins and per
GK/DEF/MID/FWD and team metrics. Rows with invalid identity, minutes,
duplicate fixture or provisional state are rejected. No synthetic player
override, parameter retuning or second model is introduced.

A **retrospective split is not archived predeadline proof**. Production
calibration is `RETROSPECTIVE_DIAGNOSTIC_ONLY` unless historical predeadline
source finalization timestamps and deadline identities are available and
passing, position sample coverage is adequate and individualized model is
noninferior on all specified paired metrics. Without those facts:
`CALIBRATION` and `MODEL_RESOLUTION` must not claim FULL/PASS, even if the
calculation or entire 667-player dataset completed successfully.

Explicit tolerances, fixed in the diagnostic (not optimized on holdout):
Brier delta <= +0.01, log loss <= +0.02, xMins MAE <= +1.0.
Diagnostic eligibility requires >=200 paired fixtures and >=25 per position,
plus predeadline lineage and zero temporal/partition errors. Report
`NONINFERIORITY` separately from `SOURCE_AS_OF`.

This is an evidence and promotion-gating change, not an asserted accuracy
improvement. Future genuine predeadline archives are needed for formal
calibration promotion.

Change timestamp: 2026-10-14T05:45:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T05:45:00+07:00
