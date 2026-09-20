# P1.2B V12-native canonical package utility

## Intermediate baseline

P1.2B starts only after P1.2A is GREEN.

Exact P1.2A intermediate head:

`a50c1b14f7d2943a5174b1bfe0fa5d887daafd3d`

The P1.2A search kernel is not changed by P1.2B. Search remains responsible
only for legal route existence and factual economics.

## Owner

Stable owner:

`src/engines/v12_package_utility.py`

Contract:

`config/intelligence/v12_package_utility.json`

Decision chain:

`P1.2A legal route -> P1.7 lineup consequence -> separate horizons -> transfer economics -> robustness / information value -> package decision`

P1.2B never generates a candidate universe and never decides search coverage.

## HOLD baseline

Every comparison contains exactly one `HOLD`.

All change-route deltas are relative to HOLD. If no change route satisfies the
explicit canonical horizon mapping, HOLD is a valid final football decision.

## Native inputs

P1.2B consumes existing native surfaces read-only:

- P1.1 availability/minutes through the P1.7 owner;
- P1.3 posterior predictive xPts/distribution through P1.7;
- P1.6 canonical tactical-role component through P1.7;
- P1.7 XI / bench / autosub / captain / vice consequences directly;
- Canonical 20/25/30/25 conformance unchanged.

P1.2B does not reconstruct a second player-scoring formula.

For each evaluated package the final 15-player squad is passed to P1.7 for the
relevant GW. The immediate package artifact therefore exposes the new XI,
formation, reserve goalkeeper, bench order, autosub option value,
cameo-blocking cost, captain and vice.

## Horizon semantics

Horizon outputs remain separate:

- GW+1;
- 2GW only for an explicitly marked rental/short route;
- 3GW;
- 5GW.

`build_horizon_analysis` from the existing Canonical V12 conformance module is
used to enforce separation.

There is no legacy 3/5/10/15 weighted sum and no hidden replacement weighted
sum. The decision mapping is explicit and versioned:

`GW_PLUS_1_POSITIVE_AND_3GW_5GW_NONINFERIOR_EXPLICIT_VECTOR_V1`.

This mapping is not a rewrite of player xPts. It chooses among already
evaluated package vectors.

## Transfer economics

P1.2B keeps football utility and execution economics separate.

Hit semantics:

- if free transfers are known, excess transfers are charged using the supplied
  exact hit cost;
- if free transfers are unknown, hit cost remains unresolved;
- if a hit is required but its exact cost is unavailable, hit remains
  unresolved;
- no guessed hit is allowed.

Dynamic FT shadow value is obtained only through
`derive_dynamic_ft_shadow_value` using future optimization opportunity:

`best future utility with FT - best future utility with that FT consumed`.

The legacy fixed `0.20` change penalty is never used as FT value.

Current buy-back difficulty uses the factual gap between current Official
reacquisition price and authenticated selling value. Future price prediction
is not embedded into football utility.

## Rental semantics

An explicitly marked rental route publishes 2GW separately.

The next GW is a fresh reoptimization. P1.2B does not manufacture a
precommitted exit. An exit appears only when supplied as an explicit evaluated
route/scenario.

## Uncertainty and robustness

P1.2B consumes genuine P1.7 distributional surfaces:

- distributional downside;
- supportable upside;
- autosub option value;
- cameo-blocking cost;
- captain/vice consequence.

Cross-route covariance is not invented.

Until P1.4 exists:

`P_BEATS_HOLD = NOT_COMPUTED`

and:

`MONTE_CARLO = NOT_RUN`.

Expected regret is the deterministic opportunity gap to the best evaluated
resolved GW+1 canonical net route. It is not described as a Monte Carlo
probability.

## Information value and price risk

Information value is explicit route evidence and may include:

- pending lineup information;
- injury news;
- role uncertainty;
- price movement;
- future FT accrual;
- fixture information.

Missing information value does not get invented. A change route with
unresolved information value is PREPARE rather than ACT.

Price/economic risk is a separate timing/constraint surface with
`football_authority=false`.

## Action semantics

The utility output distinguishes football action from operational action.

- no canonical change edge -> football HOLD, operational WAIT;
- valid change edge but unresolved execution economics -> PREPARE;
- valid change edge but unresolved information value -> PREPARE;
- value of waiting greater than current GW+1 edge -> WAIT;
- resolved canonical change edge greater than explicit information value -> ACT.

No mini-league leverage is included.

## Evidence, freeze, settlement

Every serious P1.2B decision carries existing `MODEL_EVIDENCE_BINDING` fields:

- input snapshot ID;
- model version;
- feature version;
- parameter version;
- calibration version;
- calibration cutoff;
- run fingerprint;
- output fingerprint.

Evidence is non-authoritative and does not duplicate raw V6 payloads.

The package freeze records the selected route, HOLD baseline, every evaluated
alternative, horizon vectors, transfer economics, information value,
frontier and model-evidence fingerprint before the deadline.

Post-event settlement reuses Phase 0/P1.5 decision metrics for:

- transfer counterfactual regret;
- HOLD vs ACT realized regret;
- one-GW rental realized P&L.

Prediction error remains separate from decision error.

## Ownership migration

`src/engines/lineup_governance.py` is the existing package-decision consumer.

After P1.2:

- a `V12_PACKAGE_UTILITY` artifact may own the V12 package decision;
- native selected final squad is revalidated at the consumer boundary;
- authoritative pre-deadline composition freeze still overrides execution;
- legacy optimizer artifacts can remain migration/regression/performance
  references;
- a legacy artifact cannot authorize a transfer action and is reduced to
  safe HOLD/PREPARE when a native P1.2B artifact is not materialized.

This avoids falsely replacing the production runtime with a naive
P1.7-times-millions implementation while removing legacy heuristic utility as
V12 decision authority.

## Migration taxonomy

Native-vs-legacy comparison uses the bounded taxonomy:

- SEARCH_EQUIVALENT;
- CANONICAL_UTILITY_REPLACEMENT;
- FT_ECONOMICS_IMPROVEMENT;
- HORIZON_SEPARATION_IMPROVEMENT;
- LINEUP_INTEGRATION_IMPROVEMENT;
- BUG_FIX;
- UNEXPECTED_REGRESSION.

Legacy utility equivalence is intentionally not required. Search/legal
equivalence remains the relevant regression boundary where both systems cover
the same domain.

## Explicit non-goals

P1.2B does not start:

- P1.4 Monte Carlo;
- Mini-League Overlay;
- V7;
- a scheduler;
- a new authority.

V6 remains unchanged.
