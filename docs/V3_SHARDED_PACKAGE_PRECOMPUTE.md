# V3 Sharded Package Precompute

## Purpose

Move the compute-heavy exhaustive package search out of the monolithic V3 Runtime lane without creating a second optimizer or decision authority.

## Authority boundary

- `prediction` remains the single business owner of `package_optimizer.json`.
- `lineup_governance` remains the single owner of `package_decision.json`.
- Shard workers are execution-only and write only ephemeral shard-result artifacts.
- No shard can publish, select a transfer, mutate xPts, change sequential legality, or constrain the eligible Official FPL universe.
- The exact reducer is the only sharded-path component allowed to materialize the final FULL optimizer.

## Registry-driven execution

`config/runtime/package_optimizer_sharding.json` owns operational tuning:

- target estimated pair combinations per shard;
- minimum/maximum shard concurrency;
- batch size;
- local top retention used solely for exact global top-k fan-in;
- downstream resume boundary.

The planner derives shard count from the actual estimated pair workload. There is no hardcoded shard count in workflow or Python execution logic.

## Search completeness

The planner partitions the complete set of outgoing-player pairs. Every task remains the Cartesian/combination search over the complete eligible position pool already governed by the exhaustive optimizer.

FULL authority requires:

1. every outgoing-pair task appears exactly once;
2. no task is missing or duplicated;
3. every shard has the same optimizer-input fingerprint;
4. candidate pruning remains disabled;
5. every sequentially legal package is scored;
6. local frontier reduction is exact;
7. global frontier fan-in uses the union of exact local frontiers plus HOLD and exact singles;
8. retained top packages are canonically scalar-rehydrated before publication.

A violation fails closed and cannot publish runtime-data.

## Workflow boundaries

`V3 Package Precompute` has four bounded lanes:

1. **Prepare** — hydrate governed state, run the fast canonical seed pipeline, and derive the workload-balanced shard plan.
2. **Shard** — matrix workers score disjoint outgoing-pair task partitions using the same canonical-equivalent batch scorer and scalar fallback.
3. **Finalize** — verify exact shard coverage/fingerprint, reduce to one FULL optimizer, then resume the registered downstream execution-domain DAG from the registry-owned boundary.
4. **Publish** — revalidate the transferred snapshot and atomically publish under the same `v3-runtime-publication` concurrency lock.

The legacy `V3 Runtime` workflow keeps primary/live/report responsibilities. Its :15 and post-CI exhaustive triggers delegate to the sharded workflow rather than performing a second exhaustive computation.

## Optimizer authority fingerprint

FULL authority reuse uses persisted material optimizer inputs:

- `projections.json` with volatile timestamps ignored;
- exact team sell ledger and ITB;
- governed package-optimizer config;
- FPL ruleset identity;
- source-code identity.

It does not require `official_snapshot.json`, because that acquisition artifact is intentionally ephemeral and removed before runtime publication.

A FAST/live refresh may retain a previous FULL optimizer only when this fingerprint matches exactly. Otherwise it falls back to non-FULL computation internally and publication fails closed until a new exhaustive precompute succeeds.

## Non-goals

Sharding does not change:

- xPts/xMins mathematics;
- tactical scoring semantics;
- optimizer objective mathematics;
- transfer legality;
- eligible player universe;
- watchlist semantics;
- SLO ceilings.
