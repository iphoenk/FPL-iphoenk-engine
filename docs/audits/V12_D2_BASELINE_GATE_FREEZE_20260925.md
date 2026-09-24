# V12 D2 Baseline + Gate Freeze — Walk-Forward Indexing

Date: 2026-09-25
Status: FROZEN BEFORE IMPLEMENTATION

## Authority linkage

Production main after D1 merge:
- merge method: merge commit
- main / merge SHA: `daf7247c320b1bb61eebd943b23f3ca694b088ef`
- D1 source SHA: `f5f990fbaa6c5954e789b869388562d19abcb80b`
- PR #692 final head before merge: `027abc701bac602b3a67d101e93d717d8915ccc2`

Frozen runtime-data-v6:
- `9fc2ce5e590518c399765e6fd576bb96db6e5897`

Post-D1 Stage C evidence:
- workflow run: `36066627638`
- validation branch head: `02e47fd8fbee7252effa522a4a299fb34aa94d71`
- rows: 3,191
- rows fingerprint: `a36eaf2f623c811f4d5d942aa4da3fb8842fa3d456724bb4c9e32fcec5b4b99f`
- foundation fingerprint: `afa20a169b6f2018b0d47e0381086847bd21eba89569a12e2bc29df43b31979b`
- planning GW: 6
- Python: 3.12.14
- runner image: ubuntu24 / 20260920.314.1

## GC / harness finding

All three historical harness styles run with Python cyclic GC enabled:
- Stage C profiler style: GC enabled
- timing-per-scope style: GC enabled
- D1 paired A/B style after its explicit `gc.collect()`: GC still enabled

No historical harness uses `timeit`.

The D1 A/B harness did explicitly call `gc.collect()` before each timed sample. A same-run old-oracle diagnostic on the frozen input disproved that as the explanation for the historical ~8.8 s vs ~4.89 s discrepancy:
- natural-GC median: **8.987981 s**
- forced-precollect median: **8.980602 s**
- precollect / natural ratio: **0.999179**

Therefore the historical absolute discrepancy remains unexplained. It MUST NOT be attributed to GC or generic runner variance as a proven fact. D2 uses a new baseline measured under explicitly production-like GC conditions.

## D2 production-like baseline

Measurement policy:
- GC enabled;
- no forced `gc.collect()` before measured foundation runs;
- five measured runs;
- same frozen input and exact merged main;
- component wrapper uses only `perf_counter`;
- median share is median of per-run component/total shares, not ratio of medians.

Foundation total:
- median **3.333352 s**
- min 3.319087 s
- max 3.357300 s

Component medians:
- `walk_forward_validate`: **2.726033 s**, median per-run share **81.9162%**
- `build_hierarchical_priors`: 0.476359 s, share 14.2677%
- `_select_match_source`: 0.052452 s, share 1.5688%
- `distribution_selection_matrix`: 0.021716 s, share 0.6527%
- `opponent_adjust_match_rows`: 0.013266 s, share 0.3959%
- `_supplemental_player_evidence`: 0.006918 s, share 0.2076%
- `probabilistic_tactical_states`: 0.002167 s, share 0.0645%

`walk_forward_validate` is therefore the factual D2 bottleneck.

GC collections observed inside `walk_forward_validate` are small (3–4 generation-0 collections and at most one generation-1 collection per measured invocation), while the whole foundation performs roughly 49–51 generation-0 and 4–5 generation-1 collections. GC is not the dominant explanation for the walk-forward cost.

## cProfile evidence

The post-D1 cProfile run recorded 51,455,576 calls in 16.203 s of profiled wall time.

Relevant cumulative evidence:
- `walk_forward_validate`: 13.957 s cumulative
- `builtins.sum`: 4.456 s cumulative across 30,565 calls
- `_rate90`: 3.758 s cumulative across 10,096 calls
- `dict.get`: 2.686 s across ~18.4 million calls
- `_position`: 2.098 s across ~4.1 million calls

Source audit explains the repetition:
- each fold rebuilds `train` and `test`;
- each test row scans `train` again to build `player_train`;
- each test row scans `train` again to build `position_train`;
- the same position rate/start evidence is recomputed for many players in the same fold;
- the same player historical predictions can be recomputed for duplicate/DGW test rows in the same fold.

## D2 semantic boundary

D2 may optimize only `walk_forward_validate()` execution.

Permitted execution changes:
- invocation-local indexes over the existing `clean` rows;
- invocation-local fold/player/position caches;
- reuse of exact historical row views when the semantic input is identical;
- reuse of exact player/fold predictions for multiple test rows sharing the same `(target_gw, player)`;
- reuse of exact position/fold statistics for multiple test rows sharing the same `(target_gw, position)`.

D2 MUST preserve:
- input-row order wherever the scalar oracle currently observes it;
- `gw < target_gw` train semantics and `gw == target_gw` test semantics;
- expanding-window behavior;
- exact `_rate90` implementation and accumulation order;
- recency weight formula and order;
- opponent-strength clamp and weight order;
- Bayesian formulas;
- start-probability formulas;
- `recent = player_train[-min(4, len(player_train)) :]` semantics;
- rounding, labels, selected-variant tie behavior, and final payload schema;
- behavior on unsorted input rows.

D2 MUST NOT:
- introduce prefix-sum/reassociated floating-point arithmetic unless separately proven bitwise;
- sort player history differently from the oracle;
- mutate `rows`, `clean`, or indexed row objects;
- use module/global/cross-invocation caches;
- alter hierarchical priors, V6, P1.7, package utility, MC, report QA, or factual ownership.

## Frozen correctness gates

1. **Raw prediction oracle**
   For every evaluated test row/fold, scalar oracle vs D2 must match exactly via `float.hex()` for every numeric intermediate that feeds metrics:
   - `pos_rate`
   - `season`
   - `recency`
   - `opponent`
   - `effective`
   - `bayes`
   - observed xGI rate when applicable
   - `pos_start`
   - `season_start`
   - `recent_start`
   - `bayes_start`
   - clamped probabilities used for Brier/logloss.

2. **Payload**
   - full `walk_forward_validate` payload fingerprint bit-identical to current-main oracle;
   - full foundation fingerprint bit-identical on frozen production snapshot.

3. **Determinism**
   Explicit `PYTHONHASHSEED`: 0, 1, 7, 42, 12345. Raw trace and payload fingerprints must be identical.

4. **Input immutability**
   Hash of input rows before and after invocation must match. Indexed/grouped row sequences must retain the same row-object content and oracle-visible order.

5. **Leakage**
   Instrumented proof must show every train row has `gw < target_gw`, every test row has `gw == target_gw`, and no cached value crosses an incompatible target GW.

6. **Cache/index key completeness**
   - player-derived reusable state must be keyed at least by `(target_gw, player identity)`;
   - position-derived reusable state must be keyed at least by `(target_gw, normalized position)`;
   - all caches must be invocation-local.

7. **Edge fixtures**
   - empty rows;
   - only one GW / no completed training fold;
   - negative/zero GW rows filtered exactly as today;
   - player with no prior history;
   - position with no prior history;
   - unknown/missing position;
   - zero minutes;
   - missing/zero xGI;
   - opponent weight outside clamp bounds;
   - duplicate player rows in one target GW / DGW-like test rows;
   - unsorted input GW order;
   - equal metric values that exercise selected-variant tie order.

8. **Structural work proof**
   On the frozen snapshot:
   - no full-`train` player scan may remain inside the per-test-row loop;
   - no full-`train` position scan may remain inside the per-test-row loop;
   - each requested `(target_gw, position)` position historical view/statistic is materialized at most once;
   - each requested `(target_gw, player)` reusable historical state is materialized at most once;
   - `_rate90` continues to receive row/weight sequences in the same order as the scalar oracle.

## Frozen performance gate

Benchmark policy:
- exact main oracle `daf7247c320b1bb61eebd943b23f3ca694b088ef` vs D2 candidate;
- exact runtime/input fingerprint above;
- GC enabled in both paths;
- **no forced pre-collection** before timed samples;
- at least 11 interleaved A/B pairs;
- record Python version, runner image, CPU model, row count/fingerprint, GC state, and GC collection deltas;
- correctness gates must pass before performance timing is accepted.

D2 passes only if ALL are true:
- paired median `walk_forward_validate` **<= 0.75 s**;
- paired median reduction versus oracle **>= 70%**;
- full foundation median under the production-like Stage C harness **<= 1.50 s**;
- D2 does not increase median foundation GC collection count by more than 20% in any generation;
- peak RSS attributable delta **<= 8 MiB**, with a structural fallback proof allowed if runner RSS granularity prevents reliable attribution.

Rationale:
- current walk-forward median is 2.726 s;
- a 70% reduction implies ~0.818 s, so the 0.75 s absolute gate is slightly stronger on the frozen baseline;
- non-walk-forward foundation work is ~0.61 s, making a <=1.50 s total-foundation gate coherent while leaving headroom for runner variation;
- the optimization target is repeated indexing/filtering/recomputation, not numerical approximation.

No performance target may be relaxed after seeing D2 candidate results without an explicit new gate revision committed before further tuning.

## D2 branch rule

No D2 implementation branch should be created until this baseline/gate memo is committed. The implementation branch must start from exact production main `daf7247c320b1bb61eebd943b23f3ca694b088ef`.
