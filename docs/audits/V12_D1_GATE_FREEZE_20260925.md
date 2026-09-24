# V12 D1 Gate Freeze — Hierarchical Invariant-Stat Caching

Date: 2026-09-25
Status: FROZEN BEFORE IMPLEMENTATION
Production main authority: `083c5ed82458b4e9cc6505820ac6a88818c3d202`
Frozen runtime-data-v6: `9fc2ce5e590518c399765e6fd576bb96db6e5897`

## Evidence authority

- Foundation profiler: run `35999711891`
- Invariance/count-only: run `36001832581`, head `3ee8b1a14ded0b6c7472a2e3f9a0b995d9bee0ba`
- Timing-per-scope: run `36024157643`, head `93b10648d2fb0f3553fcac86230719ba9449e044`

## Count evidence

Current snapshot:
- rows: 3,191
- players: 667
- variables: 4
- total `_sufficient` calls: 8,004
- league: 2,668
- position: 2,668
- team leave-one-player-out: 2,668
- role leave-one-player-out: 0 on the production snapshot
- safe invariant league+position calls: 5,336
- unique league+position keys actually needed: 20
- redundant invariant scans: 5,316

## Timing evidence

Seven paired oracle/instrumented runs on the same runner/snapshot.

Oracle `build_hierarchical_priors` median: **8.815222 s**.

Instrumented scope medians:
- league `_sufficient`: **6.270457 s**
- position `_sufficient`: **2.123916 s**
- team-LOO construction: **0.116855 s**
- team `_sufficient`: **0.308108 s**
- loop remainder: **0.044483 s**
- setup/grouping: **0.003968 s**
- instrumented total: **8.867618 s**

League + position therefore consume **8.394373 s**, approximately **94.83%** of the instrumented total. Team-LOO construction + team sufficient consume approximately **0.424962 s**.

Timer calibration for 10,672 perf-counter pairs: median **0.002450 s**, negligible relative to measured scope totals.

The instrumented copy matched the oracle payload fingerprint on every measured run.

## D1 semantic boundary

D1 may cache only:
- league sufficient statistics keyed by the exact requested `(field, weight)`;
- position sufficient statistics keyed by the exact requested `(position, field, weight)`.

The cache MUST:
- be local to one `build_hierarchical_priors` invocation;
- be lazy get-or-compute, not module-level and not cross-invocation;
- call the existing `_sufficient` implementation on cache miss;
- use the same row objects and preserve their current order;
- use the exact current position access semantics: `by_position.get(position, [])`.

D1 MUST NOT cache or otherwise alter:
- team leave-one-player-out construction;
- team `_sufficient`;
- role leave-one-player-out;
- role `_sufficient`;
- sample-exposure computation (reserved for D1b);
- walk-forward validation;
- V6 factual plane;
- P1.7, package utility, MC, pruning, timeout, or report QA.

## Frozen correctness gates

1. **Raw oracle**
   - For every league and position key requested, old path vs D1 must be exactly identical via `float.hex()` for mass, exposure and derived rate.
2. **Payload**
   - Full `build_hierarchical_priors` payload fingerprint bit-identical to the scalar/current-main oracle.
   - Full foundation payload fingerprint bit-identical on frozen production snapshot.
3. **Input immutability**
   - Canonical hash of `clean` and each `by_position` row sequence before player loop equals after player loop.
4. **Call-count**
   - On the frozen snapshot, league+position `_sufficient` calls collapse from 5,336 to exactly 20 cache misses.
   - Team `_sufficient` remains exactly 2,668 calls.
5. **Determinism**
   - Explicit `PYTHONHASHSEED` values: 0, 1, 7, 42, 12345. All produce identical fingerprints and raw-oracle comparisons.
6. **Edge fixtures**
   - zero players;
   - position with one player;
   - player whose resolved position is absent from `by_position`, preserving current `.get(position, [])` behavior;
   - single player in a team, therefore empty team-LOO;
   - zero exposure;
   - factual `actual_role` active, exercising role-LOO;
   - duplicate player/GW rows / DGW-like ordering where applicable.
7. **No exception-set widening**
   - Lazy cache must not evaluate any league/position key that the original loop would never request.

## Frozen performance gate

Benchmark must be an interleaved A/B on the same runner, same frozen snapshot, after warm-up, with **at least 9 measured pairs**.

D1 passes performance only if BOTH are true:
- median D1 `build_hierarchical_priors` wall-clock **<= 1.00 second**; and
- median reduction vs paired current-main oracle **>= 85%**.

Rationale:
- measured removable league+position work is ~8.394 s of an ~8.868 s instrumented total;
- measured non-D1 remainder is ~0.47 s before cache lookup/miss overhead;
- a 1.00 s gate leaves >2x headroom over the measured residual while still requiring a material architectural gain;
- 85% relative reduction protects against runner-to-run absolute timing variation.

No target may be relaxed after observing candidate results without a new explicit gate revision committed before further candidate tuning.

## Frozen memory gate

Measure peak RSS in the same A/B harness.

D1 must:
- add no persistent/module-level cache;
- keep invocation-local cache cardinality equal to requested unique keys;
- have median/representative peak RSS delta **<= 2 MiB** attributable to D1 on the frozen benchmark.

If runner RSS granularity/noise prevents attributing a <=2 MiB difference reliably, the gate is satisfied only by structural proof that the cache holds at most 20 immutable 2-float tuples plus scalar/hashable keys on the frozen snapshot, with no retained references after function return.

## Branch creation rule

Only after this gate is committed may an implementation branch be created from exact production main `083c5ed82458b4e9cc6505820ac6a88818c3d202`.
