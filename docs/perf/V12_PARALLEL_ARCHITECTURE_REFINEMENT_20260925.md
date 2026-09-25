# V12 Parallel Architecture Design Refinement — 2026-09-25

## Status

**DESIGN ONLY / P2-P3 IMPLEMENTATION BLOCKED**

Base production main:

`f1402818519237d3628184e298bd58c0240983bb`

Input discovery authority:

- PR #688, `docs/v12_stage_dag.md`, head `31bb9ff42394dd55255fa37017fd7a8384370baf`
- latest-main source revalidation performed before this design.

Do not implement P2/P3 until all of the following are true:

1. P1.7 performance/go-live workstream is CLOSED;
2. S02/HUMAN_FACING blocker is CLOSED;
3. latest main is re-read immediately before implementation;
4. no overlapping PR changes the implementation source files.

This document changes no runtime, workflow, config, V6, P1.7, package-utility, or MC source.

## 1. Revalidation of PR #688 findings against current main

All six required architectural findings remain valid.

### 1.1 Stage2 worker boundary requires immutable parent precompute

Current `historical_projection.py` still builds global/shared state before fixture projection:

- global position calibration from all match rows;
- match rows indexed by player;
- opponent-history rows indexed by player;
- players grouped by team;
- team pairwise linkup edges;
- teammate start probabilities and multi-player chains.

A raw player×fixture worker is therefore not a complete mathematical unit unless these shared structures are bound first.

**Design rule:** parent computes and fingerprints all immutable global/shared context before any worker task is emitted.

### 1.2 Contextual dynamics cannot use a team/opponent/GW-only cache key

Current `build_contextual_dynamics` consumes:

- player match rows;
- player ID;
- current GW;
- opponent team;
- current context;
- pairwise linkups;
- multi-player chains;
- teammate start probabilities;
- opponent historical rows;
- opponent-history scope.

It also builds player trajectory internally and applies probability-weighted teammate/linkup effects.

**Design rule:** no contextual-dynamics cache may omit player/linkup/teammate/history dependencies.

### 1.3 P1.2B task count is dynamic; HOLD is explicit

Current family construction still tracks HOLD separately and infers route families from actual squad differences.

**Design rule:** task cardinality is derived from the concrete family plan. Never assert `75` as a semantic constant.

### 1.4 Owned P1.7 and P1.2B HOLD share football semantics, not payload shape

Current P1.2B `_lineup_decision` invokes the same P1.7 optimizer for the exact 15-player squad/GW, then projects the full result into a route-utility payload.

**Design rule:** no direct object reuse until a shared canonical result contract exists and equivalence is proven.

### 1.5 Early HOLD MC remains prohibited

Current `canonical_package_seed` fingerprints both projections and the material football route signature. HOLD is mandatory but the root seed depends on the route set.

**Design rule:** do not execute HOLD MC before material route selection is final.

### 1.6 MC must preserve common random numbers across routes

Current-main MC already uses the correct architectural shape: deterministic **path shards**, with every shard evaluating **all material routes in the same sampled football worlds**. SeedSequence children are derived from one canonical root seed and shards merge by deterministic shard index.

**Design rule:** retain path-shard parallelism. Do not switch to one RNG stream/process per route.

---

## 2. Deterministic execution model

Every parallel phase has four layers:

```text
BOUND INPUTS
  -> IMMUTABLE PARENT STATE
  -> DETERMINISTIC TASK MANIFEST
  -> WORKER RESULTS
  -> FAIL-CLOSED VALIDATION + ORDERED MERGE
```

No worker decides its own factual inputs, discovers new dependencies, writes shared mutable caches, chooses task order, or mutates the task manifest.

## 3. Immutable parent state

### 3.1 Common header

Every parent-state object must include:

```text
schema_version
phase_id
production_model_sha
runtime_data_snapshot_sha
planning_gw
code_lineage_fingerprint
numeric_runtime_class
input_fingerprint
created_for_execution_mode
```

`input_fingerprint` must be a deterministic hash of every mathematical dependency consumed by the phase.

### 3.2 Stage2 parent state

Minimum immutable content:

```text
bootstrap element index
fixture index / requested horizon
team strength maps
selected Foundation rows
match_rows_by_player
opponent_history_by_player
global_position_calibration
players_by_team
team_pairwise_edges
player feature map
historical map / priors
team rows
model evidence binding
calibration summary
context/linkup schema version
```

The parent computes these once. Workers receive references/copies read-only.

### 3.3 P1.2B family parent state

Minimum immutable content:

```text
projection fingerprint
planning_gw
actual ordered route list
exact HOLD squad
derived family plan
GW horizon list
prebuilt player surfaces by GW
static formation/bench/captain structures
numeric runtime class
P1.7 semantic/code lineage
```

The actual family plan, not an assumed number, is the source of task cardinality.

### 3.4 MC parent state

No early-HOLD state exists.

After material route selection only:

```text
canonical projections fingerprint
ordered material route definitions including HOLD
football_route_signature
canonical root seed
configured actual_paths
configured worker_count
deterministic shard path counts
SeedSequence child seeds
correlation-model version
MC code/schema lineage
```

Workers receive the complete ordered route definition set for each path shard.

---

## 4. Deterministic task schemas

### 4.1 Stage2 player-chunk task

```json
{
  "schema": "V12_STAGE2_PLAYER_CHUNK_TASK_V1",
  "phase": "STAGE2",
  "snapshot_fingerprint": "<parent input fp>",
  "task_id": "stage2:<chunk_ordinal>:<player_range_fp>",
  "chunk_ordinal": 0,
  "player_ids": [1, 2, 3],
  "planning_gw": 6,
  "horizon": 5,
  "parent_context_fingerprint": "<immutable parent fp>",
  "code_lineage_fingerprint": "<stage2 code fp>"
}
```

Rules:

- `player_ids` sorted ascending;
- chunks generated only by parent;
- no task may rebuild global calibration or global link graph;
- player may occur in exactly one chunk.

### 4.2 P1.2B family×GW task

```json
{
  "schema": "V12_P12B_FAMILY_GW_TASK_V1",
  "phase": "P1_2B",
  "snapshot_fingerprint": "<parent input fp>",
  "task_id": "p12b:<gw>:<family_fp>",
  "gw": 6,
  "family_kind": "CHANGE_FAMILY",
  "family_key": "<deterministic family tuple/hash>",
  "route_ids": ["..."],
  "squad_fingerprints": ["..."],
  "surface_catalog_fingerprint": "<GW-specific immutable surface fp>",
  "p17_lineage_fingerprint": "<exact P1.7 owner fp>"
}
```

HOLD is represented explicitly:

```json
{
  "task_id": "p12b:6:HOLD",
  "gw": 6,
  "family_kind": "HOLD",
  "family_key": "HOLD",
  "route_ids": ["HOLD"]
}
```

Task manifest cardinality is:

`sum(actual change families per GW) + explicit HOLD tasks + any explicitly classified fallback squads`

It is never hard-coded.

### 4.3 MC path-shard task

```json
{
  "schema": "V12_MC_PATH_SHARD_TASK_V1",
  "phase": "P1_4_MC",
  "task_id": "mc:<shard_index>",
  "root_seed": 123,
  "child_seed": 456,
  "shard_index": 0,
  "path_count": 125000,
  "ordered_route_ids": ["HOLD", "R1", "R2"],
  "route_signature": "<canonical football route fp>",
  "projection_fingerprint": "<projection fp>",
  "correlation_model_version": "<version>"
}
```

Each MC task evaluates **all** ordered material routes. A route-local MC task is forbidden.

---

## 5. Worker input/output contracts

### 5.1 General worker input

Worker input consists only of:

1. immutable parent-state reference/value;
2. one manifest task;
3. explicit schema/code/runtime fingerprints.

Forbidden worker behavior:

- live file/network acquisition;
- V6 reads not already represented in parent fingerprint;
- mutation of shared dictionaries/NumPy arrays;
- hidden process-local discovery that changes semantics;
- nondeterministic task-derived seeds;
- write-through shared caches.

### 5.2 General worker result

```json
{
  "schema": "V12_PARALLEL_WORKER_RESULT_V1",
  "task_id": "...",
  "status": "PASS",
  "parent_fingerprint": "...",
  "output_fingerprint": "...",
  "payload": {},
  "diagnostics": {
    "worker_index": 0,
    "elapsed_seconds": 0.0
  }
}
```

Diagnostics are non-authoritative and must not enter mathematical hashes unless explicitly declared.

### 5.3 Failure result

A worker exception is normalized by the parent into:

```json
{
  "task_id": "...",
  "status": "FAIL",
  "error_class": "...",
  "error_message": "...",
  "payload": null
}
```

No failed task can be silently dropped.

---

## 6. Deterministic merge ordering

### 6.1 Stage2

Merge players by canonical player/element ID, then GW/fixture ordering already required by the sequential owner.

Worker completion order is irrelevant.

### 6.2 P1.2B

Merge key:

`(gw, family_kind_rank, canonical_family_key, route_id)`

Recommended `family_kind_rank`:

1. HOLD
2. CHANGE_FAMILY
3. EXPLICIT_FALLBACK

This ordering is a transport order only. It must not replace the existing football tie/order semantics inside P1.7.

### 6.3 MC

Merge strictly by `shard_index`.

Within each shard, route arrays retain the exact canonical `ordered_route_ids`. Concatenate paths by shard index before quantile/convergence calculations.

---

## 7. Exception and fail-closed semantics

The parent fails the whole stage if any of these occurs:

- task missing from expected manifest;
- unexpected task returned;
- duplicate task result;
- worker FAIL/exception;
- parent fingerprint mismatch;
- code/schema/runtime fingerprint mismatch;
- output cannot be canonicalized;
- output hash mismatch on deterministic replay;
- task count differs from manifest;
- route/family/GW/player coverage differs from expected;
- MC shard path counts do not sum exactly to `actual_paths`;
- MC route ordering differs between shards;
- CRN evidence is absent.

Do not convert these into DEGRADED analytics. They are execution correctness failures.

A controlled validation harness may explicitly rerun the **entire stage** sequentially after a failed experimental run, but that must be labeled rollback/validation and must not masquerade as a successful parallel execution.

---

## 8. Cache policy

### 8.1 Stage2 global/shared state

Parent may precompute process-local immutable state. Persistent caching requires complete upstream lineage and schema binding.

### 8.2 Contextual-dynamics cache key

Minimum semantic key:

```text
player_id
current_gw
opponent_team_id
current_context_fingerprint
player_match_rows_fingerprint
linkups_fingerprint
chains_fingerprint
teammate_start_probabilities_fingerprint
opponent_history_rows_fingerprint
opponent_history_scope
contextual_dynamics_code/schema_fingerprint
numeric runtime class where numeric execution can differ
```

A team/opponent/GW-only key is invalid.

### 8.3 P1.2B cache key

Minimum semantic key:

```text
projection_fingerprint
planning_gw
actual family-plan fingerprint
GW
family key
exact squad/route fingerprints
surface catalog fingerprint
P1.7 code/schema lineage
numeric runtime class
```

### 8.4 Owned P1.7 / HOLD reuse

No cache entry from one payload surface is substituted for the other until both consume a shared canonical-result contract.

Proposed future contract:

```text
V12_P17_CANONICAL_RESULT
  input:
    projection_fingerprint
    exact sorted squad15
    GW
    P1.7 code/schema/runtime lineage
  output:
    full canonical optimizer result
    canonical output fingerprint
```

Owned reporting and P1.2B route utility would become adapters over that same full canonical result. This is a prerequisite design, not current production behavior.

### 8.5 MC cache policy

No cache or speculative execution for HOLD before final route materialization.

MC cache identity must include the full canonical route signature and root seed contract. Existing CRN/path-shard semantics remain authoritative.

---

## 9. Equality and hash acceptance

Before any production parallel implementation is eligible:

### 9.1 Stage2

For identical bound input snapshot:

- sequential vs candidate parallel output canonical JSON SHA-256 identical;
- player denominator identical;
- player ordering identical;
- per-player/per-GW fixture rows identical;
- contextual dynamics/linkup evidence identical;
- no missing or duplicated player.

Test across at least:
- unchanged control;
- injury/xMins change;
- role/linkup change;
- fixture/DGW/BGW change;
- runtime-class change.

### 9.2 P1.2B

Require:

- identical route denominator;
- identical HOLD;
- identical per-route, per-GW XI/bench/C/VC;
- identical football route utility;
- identical family/fallback coverage;
- identical final package utility hash.

Count-aware acceptance must report exact squad/GW units evaluated, not binary HIT/MISS only.

### 9.3 Owned P1.7 vs HOLD canonical contract

Before reuse is enabled:

- exact same projection fingerprint, squad15 and GW;
- full canonical P1.7 result hash identical;
- adapters may differ in payload shape only after the shared canonical result is fixed and tested;
- any decision-critical field divergence blocks reuse.

### 9.4 MC

For a candidate implementation at the same configured worker count/runtime contract:

- identical canonical root seed;
- identical route signature/order;
- identical child-seed policy;
- identical path counts per shard;
- identical raw route arrays or their canonical hashes;
- identical pairwise-vs-HOLD metrics;
- identical quantiles/tails;
- identical convergence evidence;
- identical Stage3 decision inputs.

Changing worker-count seed partitioning is a separate RNG-contract change and is not part of this design refinement.

---

## 10. Rollback boundary

Each future implementation phase must have one coarse rollback boundary:

```text
SEQUENTIAL_CANONICAL (existing)
PARALLEL_CANDIDATE (new)
```

Do not mix modes inside one accepted stage after partial worker failure.

Requirements:

- existing sequential owner remains callable and unchanged through validation;
- experimental cache namespace is versioned separately;
- rollback means re-run the whole affected stage in canonical sequential mode;
- execution proof records selected mode;
- production default cannot switch until same-snapshot equality gate is green;
- after switch, one natural DEEP must pass before further phase expansion.

---

## 11. Implementation phase ordering after unblock

Only after prerequisites close:

1. **P2 parent-state extraction/precompute**, no worker fan-out yet.
2. **P2 Stage2 bounded player-chunk executor**, feature-flagged, same-snapshot equality.
3. **P3 dynamic P1.2B family×GW manifest**, still sequential manifest execution first.
4. **P3 bounded parallel family executor**, equality on route/GW outputs.
5. **Owned/HOLD canonical-result contract** only if profiling still justifies it.
6. **MC:** keep current path-shard CRN architecture. No early HOLD overlap and no route-per-process redesign.

Each phase gets its own branch/PR and must re-read exact latest main before implementation.

## 12. Current design verdict

**READY AS A DESIGN, NOT LEGAL TO IMPLEMENT YET.**

The most important refinement relative to a generic multiprocessing plan is that the unit of parallelism is not simply “whatever loop is slow.” The unit must preserve the existing mathematical dependency boundary:

- Stage2: player chunks only after global/context precompute;
- P1.2B: tasks derived from actual family plan with explicit HOLD;
- P1.7 reuse: canonical result first, adapters second;
- MC: parallelize sampled worlds by path shard while every shard keeps all routes together.

That preserves determinism, cache correctness, CRN, and fail-closed semantics without weakening analytics.
