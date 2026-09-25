# V12 Analytics Foundation performance discovery — 2026-09-25

## Scope

Discovery only. No production implementation.

Base production main:

`f1402818519237d3628184e298bd58c0240983bb`

Historical occurrence that motivated this work:

- run `35979672473`
- model SHA `31b3e45c5089e9ea1ea2be10de3793b91df99a32`
- `V12_ANALYTICS_FOUNDATION=11.992 s`

Current production comparison:

- run `36126675342`
- model SHA `f1402818519237d3628184e298bd58c0240983bb`
- `V12_ANALYTICS_FOUNDATION=0.544 s`

Observed cross-run ratio: about 22.0x faster. This is not a controlled same-runner A/B, so runner variance must not be interpreted as code-only speedup; however the code history directly targets the historical hotspots identified below.

## Historical profiling evidence

COLD profile run `35861004775` used model SHA `918da08b892320592b9d51684e0130933a6fbb7a`.

The Stage-1/Foundation source that dominates the profile is identical between `918da08...` and the model SHA used by run `35979672473`; the latter added no changes to `v12_analytics_foundation.py` or `v12_stage1_analytics.py`.

cProfile increases absolute runtime because this path performs a very large number of Python calls, so its 46.115 s total must not be compared directly to normal-run wall clock. Its cumulative proportions are still useful for locating work.

Top cumulative consumers:

| Consumer | cProfile cumulative | Share of profiled Foundation |
| --- | ---: | ---: |
| `build_hierarchical_priors` | 32.176 s | 69.8% |
| `_sufficient` | 31.425 s | 68.1% |
| `walk_forward_validate` | 13.602 s | 29.5% |
| JSON parsing, all five loads | 0.050 s | 0.1% |
| match-source selection | 0.072 s | 0.2% |
| opponent adjustment | 0.035 s | <0.1% |

The historical path generated about 151.5 million profiled function calls. It was therefore CPU-bound Python aggregation, not file-I/O-bound.

## C1 — top wall-clock consumers

Historical source:
1. hierarchical empirical-Bayes sufficient-stat aggregation;
2. walk-forward validation and repeated history filtering;
3. everything else is minor by comparison.

Current main:
Foundation is 0.544 s in run 36126675342, so it is no longer a material DEEP bottleneck relative to later stages.

## C2 — CPU-bound vs I/O-bound

CPU-bound.

The historical COLD profile attributes about 0.05 s to JSON parsing versus 46.115 s profiled Foundation time. File reads themselves are smaller still. Optimizing JSON/file I/O cannot explain or materially reduce the historical 12 s normal-run cost.

## C3 — duplicate deterministic work

The historical code repeatedly:
- calculated sufficient statistics over the same league/position/team/role rows for player-variable combinations;
- rebuilt walk-forward player and position histories by scanning rows for each target GW;
- recalculated invariant position rates and start probabilities.

Current main already contains bounded fixes for those exact classes:

- `f5f990fbaa6c5954e789b869388562d19abcb80b`: memoize invariant hierarchical sufficient stats;
- `b00ffb14e3cc3b7347f5dabb7a4059baa4a6d3f3`: index walk-forward history by player and position;
- `ac3e4d64ab4b19d0ab8211086eb4031fba6641e8`: reuse invariant walk-forward position state;
- `2b35d62ffe21f53c2e05c33359fac55412da45b6`: freeze cached position history as tuple.

Remaining deterministic duplication visible in current source includes:
- per-player/team leave-one-out lists still materialized inside each variable spec;
- role leave-one-out lists likewise materialized inside each variable spec;
- `sample_exposure_minutes` is recomputed inside each variable bundle;
- walk-forward still constructs target-GW `train`/`test` lists and per-player prefix filters that could be indexed/prefixed further.

These are discovery findings only. At 0.544 s current stage time they are not automatically worth changing.

## C4 — reusable immutable structures

Safe immutable candidates inside one occurrence:

- rows grouped by player, position, team, role and GW;
- per-group sufficient-stat totals by (field, weight);
- per-player contribution totals that permit leave-one-out by subtraction;
- per-(target GW, position) historical prefixes;
- per-(target GW, player) historical prefixes;
- immutable bootstrap element index;
- immutable selected normalized match rows;
- immutable supplemental player evidence.

Any reuse must bind to the exact factual snapshot and code/schema lineage.

## C5 — safe memo/cache candidates

Safest:
1. process-local memoization of immutable group totals/prefixes;
2. whole-Foundation cache only if keyed by deterministic fingerprints of:
   - selected normalized match source payload;
   - supplemental normalized evidence payloads;
   - bootstrap events/elements consumed by Foundation;
   - team-strength input;
   - planning GW;
   - Foundation/Stage-1 code lineage and cache schema.

A cache hit must reproduce bit-identical Foundation output. Missing dependency fingerprint must be a MISS, never a permissive HIT.

Given current 0.544 s wall time, persistent cross-run caching is low priority unless a later regression makes Foundation material again.

## C6 — candidate parallel boundaries

Possible but not recommended for implementation now:

- hierarchical per-player work after parent precomputes immutable global/position/team/role sufficient stats;
- walk-forward per-target-GW folds after parent builds immutable row indexes/prefixes.

Merge must be deterministic by player ID / target GW and exceptions must fail closed.

At the current stage duration, process creation, serialization and merge overhead can consume the available gain. Do not implement a process pool from this discovery.

## C7 — expected theoretical speedup

For the historical 11.992 s occurrence, the profile showed nearly all time in two deterministic CPU kernels, so the theoretical optimization ceiling was high.

The current natural production evidence already realizes the important gain:

`11.992 / 0.544 ≈ 22.0x`

Again, that ratio is cross-run and not a controlled runner-normalized benchmark, but it is strong evidence that Foundation is no longer the priority performance blocker.

Even a further 4x acceleration from 0.544 s would save only about 0.41 s per DEEP run. That is not a rational reason to introduce multiprocessing complexity while larger downstream stages remain material.

## Decision

Stage C discovery result: **NO IMPLEMENTATION RECOMMENDED NOW**.

Keep the remaining micro-optimization and immutable-cache candidates documented. Re-open only if a current-main controlled profile shows Foundation materially above its present sub-second range.
