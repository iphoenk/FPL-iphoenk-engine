# P1.3 Player Event Migration Baseline

Baseline SHA: `e4ae01512e87e53d605dbbf94d6302bce2f57bd6`

This document freezes the donor behavior used as the P1.3 migration oracle. It is documentation and regression evidence only, not methodology authority.

## Donor inventory

- `src/models/projection_components.py`: robust observed-rate shrinkage, early-season winsorization, Poisson DefCon threshold, fixture attack multiplier, clean-sheet probability consumption, legacy heuristic mean/std.
- `src/models/historical_projection.py` at the baseline SHA: position/historical attacking prior blend, bonus90/saves90 shrinkage, player-fixture projection consumer.
- `src/engines/player_features.py`: current advanced defensive evidence (`dc_reconstructed_per90`, evidence minutes, sample quality).
- `src/engines/v12_player_minutes.py`: P1.1 finite-state START / REGULAR_CAMEO / LATE_CAMEO / ZERO_MINUTES owner.

Frozen numerical cases live in `tests/fixtures/player_events_golden.json`: nailed attacking MID, uncertain/rotation MID, high-xG FWD, creative MID, low-sample attacker, attacking DEF, DefCon-heavy DEF, sub-threshold DefCon DEF, save-heavy GK, strong-CS DEF, bad-fixture attacker, good-fixture attacker, DGW fixture case, and DNP/ZERO_MINUTES. The freeze records xG90, xA90, bonus90, saves90, DefCon count rate, fixture multiplier, clean-sheet probability, legacy mean and legacy std.

## V12-native ownership

Production event owner after P1.3: `src/engines/v12_player_events.py`.
Stable parameters: `config/intelligence/player_events.json`.
The actual historical projection consumer imports the V12 event owner and no longer imports `projection_components` for decision-bearing player event projection.

## Intentional migration changes

- Attack posterior numerics preserve donor shrinkage/winsorization unless input provenance changes.
- P1.1 finite-state minutes are consumed directly; opportunity is not reduced to only `E[minutes]/90`.
- Goal and assist counts are state-conditional Poisson mixtures.
- Clean-sheet value is minutes-threshold aware inside the finite-state mixture.
- DefCon remains a probabilistic Poisson-threshold event, never a guaranteed floor.
- GK saves use a Poisson count model plus the actual FPL save interval reward, not `saves90/3` deterministic certainty.
- Bonus is retained once as a residual expectation component and is not introduced as an independent stochastic process.
- Canonical points uncertainty is derived from event/state moments and law of total variance. The legacy heuristic Gaussian std remains frozen only as a migration oracle.
- Quantiles are not published because no justified full predictive quantile construction is implemented in P1.3.
- Cross-player and cross-fixture correlation remain explicitly NOT_MODELLED_YET. This stage does not claim P1.4, P1.6, Monte Carlo or optimizer capability.

## Difference classification

EXACT_EQUIVALENT:
- robust xG90/xA90 posterior donor numerics for the same prior and evidence;
- fixture attack multiplier;
- upstream clean-sheet probability input;
- DefCon posterior count-rate donor mechanics.

INTENTIONAL_V12_NORMALIZATION:
- explicit posterior lineage and confidence;
- state-conditional event distributions;
- threshold-aware clean-sheet and DefCon opportunity;
- non-deterministic GK save reward;
- event-derived variance;
- explicit residual bonus semantics;
- multi-fixture dependency statement;
- Phase-0 model-evidence binding.

CALIBRATION_CHANGE: none.
P1.6 tactical scoring change: none.
20/25/30/25 change: none.
UNEXPECTED_REGRESSION: blocking and required to remain zero.
