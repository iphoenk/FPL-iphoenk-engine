# P0 P(start) individualization

Status: implementation candidate, 2026-10-13 UTC.

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
