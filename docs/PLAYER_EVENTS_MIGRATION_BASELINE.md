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
- P1.3 originally published moments only and left quantiles null. P1.3B adds a deterministic discrete core-point PMF and discrete quantiles while retaining explicit bonus-residual limits.
- Cross-player and cross-fixture correlation remain explicitly NOT_MODELLED_YET. P1.3B does not claim Monte Carlo, P1.7, mini-league or optimizer capability.

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


## P1.3B joint event probability + point-distribution completion

P1.3B keeps the same P1.1 finite-state minutes owner and the same robust
goal/assist posterior-rate construction. It completes the deterministic
player-fixture probability surface without Monte Carlo.

### Joint goal / assist dependence

The joint model is `BIVARIATE_POISSON_SHARED_COMPONENT_V1`.

For each finite-state/minute atom:

- `lambda_goal` and `lambda_assist` remain the governed fixture-adjusted
  P1.3 marginal rates;
- `lambda_shared = shared_fraction * min(lambda_goal, lambda_assist)`;
- the goal-only and assist-only latent rates are the corresponding residuals.

This preserves both Poisson marginal means while making positive within-player
dependence explicit. The initial shared fraction is a conservative structural
fallback, not an outcome-fitted estimate. At introduction the P1.5 settled
pre-deadline sample size is zero, so the dependence calibration status is
`LOW_CONFIDENCE_CONSERVATIVE`. Silent independence and automatic retuning are
forbidden.

The joint layer publishes:

- P(goal >= 1);
- P(assist >= 1);
- P(goal and assist);
- P(attacking return);
- P(no attacking return);
- P(total G+A >= 2);
- P(total G+A >= 3).

### Deterministic point PMF

For every P1.1 state/minute atom the engine builds integer point mass for:

- appearance;
- joint goal+assist points;
- clean-sheet reward when the 60-minute rule is met;
- DefCon threshold reward;
- goalkeeper save-interval reward.

The per-atom point distributions are combined before the P1.1 mixture is
integrated. Therefore DNP, cameo and >=60-minute qualification are represented
inside the distribution rather than added after the fact.

The canonical PMF is bounded numerically using governed count-support limits.
Any truncated probability mass is published in diagnostics. The bounded grid
is renormalized deterministically and has a governed reconciliation tolerance.

### Bonus limitation

Bonus remains `RESIDUAL_EXPECTATION_COMPONENT` and has no separately justified
stochastic model. P1.3B therefore publishes
`distribution_completeness=PARTIAL_BONUS_RESIDUAL`.

The PMF is the stochastic core distribution. Bonus is published as a residual
expectation and is added only when reconciling the expected total. Blank, tail
and quantile surfaces explicitly state that bonus is not stochastically
incorporated.

### Blank, tails and quantiles

`P_NO_ATTACKING_RETURN` means no goal and no assist.

It is not `P_FPL_BLANK`.

`P_FPL_BLANK` is the probability that core stochastic FPL points are at or
below the governed blank threshold stored in
`config/intelligence/player_events.json`.

The minimum canonical tails are 5+, 8+, 10+, 12+ and 15+. Human-facing “haul”
may alias 10+ only when that threshold is visible.

Discrete quantiles use the smallest integer support value whose cumulative
probability reaches the requested level. P10/P25/P50/P75/P90 are mandatory;
P95 is also published by the current parameter set. No Gaussian approximation
is used.

### Mean and variance

The PMF core mean plus residual bonus expectation is reconciled to the existing
P1.3 expected FPL points. The published stochastic variance comes from the PMF.
The pre-P1.3B moment variance is retained as reconciliation evidence because
explicit goal-assist covariance can change variance by design.

### Bayesian uncertainty boundary

The existing robust xG/xA prior/historical shrinkage, early-season adaptive
shrinkage and winsorisation remain unchanged.

P1.3B propagates process uncertainty and P1.1 minutes uncertainty
deterministically. It does not claim a full posterior over shrinkage parameters
or player rates. `parameter_uncertainty_propagation=PARTIAL`.

### Key-pass / chances-created audit

The current canonical player-feature enrichment exposes
`chances_created`. The audited runtime-data-v6 Vaastav payload exposes
expected assists but does not establish a distinct canonical
`key_passes` field. P1.3B therefore does not create a key-pass alias or a
duplicate feature. Provider-level semantic/provenance proof is required before
that can change.

P1.6 scoring coefficients/formula are unchanged by this audit.

### Multi-fixture / horizon boundary

GW+1, 3GW and 5GW expected points and zero-cross-fixture-covariance variance
remain available. Exact single-fixture tails/quantiles/return probabilities are
published. Multi-fixture and multi-GW tail aggregation remains PARTIAL until a
governed cross-fixture dependence model exists.

No Monte Carlo is introduced in P1.3B.
