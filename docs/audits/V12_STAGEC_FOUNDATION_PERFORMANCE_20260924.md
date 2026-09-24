# V12 Stage C/D Foundation Performance Discovery and Design

Date: 2026-09-24
Mode: DISCOVERY / DESIGN ONLY
Production mutation: NONE
V6 mutation: NONE

## Authority and frozen evidence

- Production main SHA after Stage B: `083c5ed82458b4e9cc6505820ac6a88818c3d202`
- Frozen runtime-data-v6 SHA: `9fc2ce5e590518c399765e6fd576bb96db6e5897`
- Stage C profiler run: `35999711891`
- Joinable Official FPL player-match rows: 3,191
- Supplemental players: 415
- Planning GW: 6
- Foundation output deterministic across three repeated runs: YES
- Repeated output fingerprint: `afa20a169b6f2018b0d47e0381086847bd21eba89569a12e2bc29df43b31979b`

Absolute wall-clock varies materially by runner, so component shares from the same run are the primary evidence. No production timing gate is inferred from this isolated runner alone.

## Measured component breakdown

| Component | Median seconds | Share of median foundation run |
| --- | ---: | ---: |
| build_hierarchical_priors | 9.223 | 76.14% |
| walk_forward_validate | 2.787 | 23.01% |
| _select_match_source | 0.054 | 0.45% |
| distribution_selection_matrix | 0.023 | 0.19% |
| opponent_adjust_match_rows | 0.015 | 0.12% |
| _supplemental_player_evidence | 0.008 | 0.06% |
| probabilistic_tactical_states | 0.002 | 0.02% |

The top two functions account for approximately 99.15% of measured non-profiled foundation time.

cProfile confirms the same shape:
- `build_hierarchical_priors`: 33.980 s cumulative under profiler.
- `_sufficient`: 8,004 calls, 33.152 s cumulative.
- `walk_forward_validate`: 14.350 s cumulative under profiler.
- Full profiled foundation: 48.665 s and 151.5 million function calls.

## Root-cause classification

### C1. build_hierarchical_priors: repeated invariant rescans

For every player and every variable, the implementation recomputes:
- league-wide sufficient statistics over the full match-row set;
- position sufficient statistics over the same position set;
- team leave-one-player-out list construction and sufficient statistics;
- role leave-one-player-out statistics when factual role exists.

The league and position terms are invariant for many player iterations but are recomputed repeatedly. This is the dominant source of unnecessary work.

### C2. walk_forward_validate: repeated filtering of expanding windows

For every target GW the implementation rebuilds `train` and `test`. Then for every test observation it scans `train` again to construct:
- player history;
- position history;
- recency weights;
- opponent-adjusted weights;
- start-probability evidence.

This is semantically correct but repeatedly reconstructs identical or overlapping views.

## Stage D design refinement, no implementation

### D1. Exact-order cache for invariant hierarchical sufficient statistics

First optimization should be deliberately conservative:

1. Precompute league sufficient statistics once per variable using the existing `_sufficient(clean, ...)` in the exact current row order.
2. Precompute position sufficient statistics once per `(position, variable)`, again through the same `_sufficient` function and same row order.
3. Preserve the current team leave-one-player-out scan initially. Do not introduce subtractive aggregate arithmetic in the first patch because float reassociation could change values near six-decimal publication boundaries.
4. Preserve role leave-one-out semantics unchanged.
5. Precompute per-player sample exposure minutes once.

This removes the largest invariant rescans while minimizing semantic risk.

### D2. Indexed walk-forward views with row-order preservation

Build read-only indexes once from `clean`:
- `rows_by_gw`;
- `rows_by_player`;
- `rows_by_position`.

For each target GW:
1. Retrieve test rows from `rows_by_gw[target_gw]`.
2. Build player and position training views by filtering only their indexed history on `gw < target_gw`, preserving original row order.
3. Cache position-level rates/start priors per `(target_gw, position)`.
4. Cache player-level season/recency/opponent/start evidence per `(target_gw, player_id)`, which is reusable for double-GW test observations.
5. Preserve current formulas, weights, clamp behavior, recent-history slicing and result rounding exactly.

### D3. Do not optimize negligible components

Do not spend implementation risk on source JSON loading, supplemental evidence, distribution matrix, opponent adjustment or tactical-state materialization at this stage. Together they are below 1% of measured foundation time.

## Required acceptance before any production implementation

Any future implementation must be separate from this discovery branch and must prove:

1. Full foundation payload fingerprint identical to scalar/current-main oracle on the frozen production snapshot.
2. Boundary-dense tests for all published rounded fields.
3. Randomized and adversarial row-order fixtures, including DGW-like duplicate player/GW rows.
4. Identical walk-forward selected variants, MAE/Brier/log-loss and hierarchical player priors.
5. No change to V6 factual ownership or schemas.
6. No P1.7, package utility, MC, route-pruning, timeout or report-QA changes.
7. Full repository governance / V12 required tests green.
8. A/B benchmark on the same runner and snapshot, with repeated samples rather than one wall-clock observation.

## Current conclusion

Stage C discovery is complete. The first implementation candidate should be bounded to invariant-stat caching inside `build_hierarchical_priors`, followed separately by indexed walk-forward views. No production code has been changed in this Stage C/D work.
