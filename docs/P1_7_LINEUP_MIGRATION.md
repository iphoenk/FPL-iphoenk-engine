# P1.7 V12-native distributional lineup migration

## Baseline inventory

Before P1.7, `src/engines/lineup_governance.py` already enumerated legal XI
and preserved captain/vice/bench legality, but selection ownership was split
across heuristic surfaces:

- selection score = mean xPts - std penalty - DNP penalty;
- captain score = mean xPts - std penalty - DNP penalty;
- vice was ranked after captain with small role/context adjustments;
- bench order was a direct `bench_score` sort;
- autosub value was evaluated independently per starter by selecting a first
  locally legal substitute;
- cameo blocking used a minutes-scaled mean proxy rather than the P1.3B PMF;
- global multi-DNP bench priority was not resolved as one team outcome;
- captain and vice were not optimized as an ordered pair.

The legacy implementation remains in place as a migration/regression oracle.

## P1.7 owner

`src/engines/v12_lineup_optimizer.py` is the stable P1.7 owner.

It consumes read-only:

- P1.1 START / REGULAR_CAMEO / LATE_CAMEO / DNP and xMins;
- P1.3B deterministic core point PMF, variance and tails;
- P1.6 canonical tactical-role component at exact weight 0.25.

It does not import or implement V6, runtime_v3, package optimization, Monte
Carlo or mini-league logic.

## XI and formation

All legal OUR15 combinations are enumerated. A route is admitted only when it
contains exactly 11 starters, exactly one GK and a formation in the active
rules registry.

Formation is never scored by label.

## Global autosub

The resolver operates at team level.

For each joint starter DNP-count state and bench appearance state, outfield
bench players are considered in exact priority order. A bench player may
replace a remaining DNP starter slot only when the resulting nominal formation
remains legal. Multiple DNPs are resolved jointly.

Reserve GK is evaluated independently from outfield priority.

Expected autosub points are probability-weighted. Bench points are never
treated as guaranteed.

Regular and late cameos count as appearances. The difference between actual
DNP-only autosub value and the counterfactual DNP+cameo opportunity is exposed
as cameo-blocked autosub option value.

## Distributional utility

P1.7 does not alter P1.3 expected points.

When P1.3B PMF is available, it derives:

- expected shortfall below the configured downside threshold;
- expected excess above the configured upside threshold;
- blank probability;
- 8+ and 10+ tails.

These enter a versioned decision-only utility. If exact PMF is unavailable,
P1.7 stays PARTIAL/MOMENTS_ONLY and does not fabricate tails.

Cross-player covariance remains `COVARIANCE_NOT_MODELLED_YET`.

## Bench order

All six outfield bench permutations are evaluated.

Bench ordering consumes:

- global reach probability;
- legal substitution probability;
- expected autosub points;
- appearance-conditioned blank probability;
- appearance-conditioned 8+/10+ tail evidence.

Thus bench priority may differ from a raw mean-xPts ordering.

## Captain / vice

Every ordered C/VC pair among starters is evaluated.

Captain extra value is distributional. Vice fallback is conditional on captain
DNP and vice appearance. Captain regular or late cameo blocks vice takeover.

Because cross-player covariance is not yet modelled, the captain-DNP/vice
outcome coupling is explicitly labelled an independence approximation.

## Evidence, freeze and settlement

P1.7 binds every serious decision to the existing Phase 0/P1.5 model evidence
contract with:

- input_snapshot_id;
- model_version;
- feature_version;
- parameter_version;
- calibration_version;
- calibration_cutoff;
- run_fingerprint;
- output_fingerprint.

The binding is evidence only, `authority=false`.

Selected XI, bench, captain and vice can be frozen immutably before deadline
using the existing `freeze_prediction` primitive. Settlement reuses existing
P1.5 decision metrics for XI regret, bench-order regret, captain regret, vice
consequence and cameo-block autosub regret.

## Migration

The production entrypoint remains `src.engines.lineup_governance` so runtime
service topology and scheduler/report cadence do not change.

That orchestration calls the P1.7 owner for the production decision and calls
the old implementation only as `MIGRATION_ORACLE`. An illegal native XI,
missing reserve GK or illegal C/VC pair is an unexpected regression and blocks
ownership migration.


## Final consumer compatibility hardening

The production tactical close-call overlay predates P1.7 and historically
re-ranked XI, bench, captain and vice after lineup governance. After P1.7
ownership migration that behavior would create a second decision owner and
could overwrite the distributional bench/C/VC result.

For a lineup artifact carrying
`native_model=v12_distributional_lineup_optimizer` and
`production_owner=V12_LINEUP_OPTIMIZER`, the tactical consumer runs in
`P1_7_NATIVE_OWNER_PRESERVE` mode:

- XI, formation, bench order, reserve GK, captain, vice and lineup utility are
  immutable to the post-owner overlay;
- P1.6 tactical/role evidence remains consumed by the native P1.7 route
  decision itself;
- the overlay only adds presentation/governance metadata and verifies the
  selected formation row reconciles with the final XI;
- legacy lineup artifacts retain old close-call behavior as migration oracles.

P1.7 also publishes `selection_score` on each squad row as a
non-authoritative compatibility alias of the already-computed
`distributional_utility`. This satisfies report-transparency consumers
without creating a second scoring formula or mutating upstream xPts.


## Exact performance hardening

P1.7 release acceptance exposed a runtime cost from repeatedly rebuilding the
same positional Poisson-binomial DNP count distributions and bench appearance
mask probabilities while enumerating all legal XI routes.

The optimized implementation remains exact:

- all legal XI are still enumerated;
- all six outfield bench permutations are still evaluated;
- no route pruning, stochastic sampling, Monte Carlo, or approximation was
  introduced;
- per-position DNP count probabilities are cached by the exact positional
  probability subset and then combined deterministically;
- the eight three-player bench appearance-mask probabilities are computed once
  per exact probability tuple rather than inside every DNP-count state;
- immutable player surfaces are reused by reference during route evaluation
  instead of shallow-copying them for every route.

These changes alter computation reuse only. Autosub legality, cameo blocking,
bench-order utility, captain/vice utility, and selected-route ordering are
unchanged.


## Exact two-pass route materialization

The second performance hardening stage preserves the same exhaustive decision
set while separating exact route scoring from publish-only payload materialization.

- all legal XI remain enumerated and scored;
- all six outfield bench permutations remain evaluated for every legal XI;
- the canonical global formation-legal autosub resolver remains the only
  substitution authority;
- a cached resolver-mask table reuses the canonical result for all eight bench
  appearance masks without changing any selected or reached substitute;
- compact route scoring uses the same distributional utility, exact bench
  winner and exact ordered captain/vice winner as the full route;
- only the top published alternatives and best route per formation are expanded
  into full bench-slot, cameo-block counterfactual and captain/vice-alternative
  payloads;
- compact and materialized sort keys, bench winner and captain/vice winner are
  runtime-asserted identical before publication.

This is lazy materialization, not route pruning. No legal XI, bench permutation,
captain/vice pair or decision objective is removed from optimization.
