# P1.2A V12-native exact package search

## Baseline

P1.2A starts from exact GREEN head:

`31c1951689f0321640956d64d450891e011fccab`

P1.7 is already the production lineup owner. V6 remains the factual production
data plane and is not modified by this stage.

## Legacy donor audit

The legacy package search stack contains useful mechanics but mixes search and
decision utility.

### Useful search mechanics

- exact 15-player squad legality;
- 2 GK / 5 DEF / 5 MID / 3 FWD composition;
- max three players per club;
- current-squad sell-value and incoming now-cost affordability;
- complete Official candidate-pool construction;
- exhaustive 1-transfer and 2-transfer enumeration;
- exact scalar fallback;
- guarded batch/vector acceleration;
- deterministic outgoing-pair partitioning;
- sharding/parallel execution;
- skyline/frontier representation.

### Legacy mechanics deliberately rejected as P1.2A authority

`src/models/package_optimizer_v2.py` owns legacy scoring concerns that are not
search semantics:

- 3/5/10/15 horizon weights;
- risk-aversion scalar objective;
- fixed `change_penalty_points=0.20`;
- legacy bench/captain approximations;
- team-cluster decision penalty.

`src/models/package_optimizer_exact_batch.py` vectorizes that legacy scorer.
Its numerical-guard and scalar-fallback patterns are useful donors, but its
objective is not P1.2A authority.

`src/engines/package_optimizer_exhaustive_accelerated.py` demonstrates complete
candidate enumeration, partitioning and batch acceleration, but also invokes
legacy scoring and legacy independent-Gaussian diagnostics. Those scoring and
simulation concerns are excluded from P1.2A.

The legacy exhaustive finalizer includes safe structural mechanics, including
same-position multiset generation from an already legal squad. Those mechanics
are mined, not imported as production authority.

## P1.2A owner

Stable owner:

`src/engines/v12_package_search.py`

Contract:

`config/intelligence/v12_package_search.json`

P1.2A owns only:

- legal route existence;
- exact final-squad legality;
- factual candidate eligibility;
- exact sell-value/buy-price affordability;
- deterministic route identity;
- FULL/PARTIAL coverage truth;
- execution-only batching and sharding;
- representation-only search frontier.

It does not own any route score or recommendation.

## Exact legality model

Every emitted route reconstructs the final 15 and requires:

- exactly 15 players;
- unique element IDs;
- exactly 2 GK;
- exactly 5 DEF;
- exactly 5 MID;
- exactly 3 FWD;
- no more than 3 players from one club.

Since the current squad is legal and a route has equal numbers of outgoing and
incoming players, a legal final squad must preserve the outgoing positional
multiset. Using this identity to construct incoming combinations is therefore
lossless.

## Affordability

For every outgoing player, authenticated `sell_value` or the existing
authenticated-ledger alias `sell_cost` is required.

P1.2A never substitutes `now_cost` for missing sell value.

When a required outgoing sell value is unavailable:

- `economics_status=UNRESOLVED_SELL_VALUE`;
- `gross_sell_value=null`;
- `bank_after=null`;
- `affordable=null`.

The route may remain structurally legal search evidence but cannot be treated as
an executable affordable package by P1.2B.

Incoming prices always use current Official `now_cost`.

## FULL/PARTIAL

`FULL` requires all of:

- caller proves the supplied universe is complete;
- observed eligible candidate count equals expected eligible denominator;
- searched eligible count equals eligible denominator;
- no lossy pruning.

Any denominator mismatch, incomplete-universe signal or lossy-pruning signal
forces `PARTIAL`.

## Batch/scalar/shard equivalence

The scalar kernel is the reference search implementation.

The current batch surface deliberately changes materialization cadence only.
It does not have a second route-generation formula. This provides an exact
compatibility point for future vectorization without changing authority.

Sharding partitions outgoing combinations deterministically by ordinal modulo
shard count. Shards are disjoint and their exact union is the scalar route set.
HOLD is emitted by shard zero only.

Any overlap is a hard error.

## Frontier

P1.2A may expose a search/economic skyline for representation, but it cannot
change the route set and has `scoring_authority=false`.

No football utility, horizon score, FT shadow, WAIT/PREPARE/ACT, Monte Carlo or
mini-league value exists in this owner.
