# V12 Partial-Change Preconditions — Frozen 2026-09-25

Status: **FROZEN BEFORE NEW PARTIAL-CHANGE RESULTS**

This document freezes the correctness interpretation, cache invalidation
expectations, anchor policy, and runtime-class policy before the next
partial-change matrix or E2E profiling run is inspected.

## 1. Anchor policy

All partial-change matrix runs and E2E profiling MUST resolve the same immutable
measurement anchor. Do not use a moving `main` ref.

Planned tag name after closure merge:

`v12-partial-change-anchor-20260925-r1`

Re-anchor is allowed only as an explicit scheduled validation event after a
declared production change. Never silently re-anchor between cold/warm/partial
pairs.

The runtime-data snapshot MUST also be frozen and reported by exact SHA.

## 2. Result interpretation

The correctness rules are asymmetric and are fixed before measurement:

| Observation | Frozen expectation | Classification |
| --- | --- | --- |
| HIT | MISS | **FAIL correctness**: incomplete key / stale-output risk |
| MISS | HIT | **Performance finding**, not correctness failure: over-invalidation |
| warm/partial B output != cold B output | any | **FAIL correctness** |
| HIT | HIT | PASS only if output equals cold oracle for identical semantic input |
| MISS | MISS | PASS only if recomputed output equals cold oracle for state B |

A cache status is never inferred from runtime alone. Use the stage's explicit
cache proof/key evidence.

## 3. Partial-change mutation contract

Each class has a fixed mutation point so results cannot be rationalized after
inspection.

| Change class | Exact semantic mutation |
| --- | --- |
| injury | availability/injury fact entering public Stage-2 inputs |
| xMins | one player's governed Stage-2 xMins projection surface, with unrelated fields held fixed |
| role | one player's governed P1.6/tactical-role surface after Stage-2, with xMins/xPts held fixed |
| price | official `now_cost` only, no injury/xMins/role/team mutation |
| team/finance | private CURRENT15 identity + its finance state; public projection universe held fixed |
| unchanged control | byte-equivalent semantic inputs and same runtime class |

For `team/finance`, the controlled case MUST change team identity, not bank
alone, so P1.7/MC invalidation has one unambiguous expectation.

## 4. Frozen HIT/MISS expectations

These expectations are frozen before the new matrix is run.

| Change class | Stage-2 | P1.7 | MC | Reason |
| --- | --- | --- | --- | --- |
| injury | MISS | MISS | MISS | public projection input changes, then consumed player surface and MC projection change |
| xMins | HIT | MISS | MISS | Stage-2 cache itself is not re-keyed by a post-Stage-2 controlled surface mutation; P1.7 consumes xMins; MC consumes projections |
| role | HIT | MISS | MISS | P1.6 role is downstream of Stage-2; P1.7 consumes tactical role; MC consumes projections |
| price | MISS | HIT | MISS | Stage-2 output carries `now_cost`; P1.7 player decision surface excludes price; MC fingerprints full projections |
| team/finance | HIT | MISS | MISS | private CURRENT15 is intentionally absent from Stage-2 key; changed 15 changes exact P1.7 squad and MC route definition |
| unchanged control | HIT | HIT | HIT | same semantic input and same runtime class must reuse exact cached output |

If a future refactor changes which fields a stage actually consumes/publishes,
this table must be revised in a separate pre-measurement commit before running
a new matrix.

## 5. Upstream lineage requirement

Persistent keys must bind both the consumed upstream output and code lineage:

`Foundation -> Stage-2 -> P1.7 -> MC`

Minimum correctness contract:

- Stage-2 binds Foundation/Stage-2 dependency code plus deterministic public
  inputs.
- P1.7 binds its exact consumed player surfaces plus Stage-2/Foundation code
  lineage.
- MC binds full projections + normalized route definition plus P1.7 code
  lineage.
- A behavior-affecting upstream code fingerprint change MUST force a downstream
  cache MISS even when a coincidental numerical output remains equal.

## 6. Numeric runtime-class policy

Decision: **bind persistent cache keys to the numeric runtime class** rather
than weakening the cold==warm claim.

The runtime identity MUST include at least:

- Python major.minor;
- NumPy version;
- machine architecture and CPU model;
- logical CPU/core count;
- active NumPy SIMD feature set;
- BLAS/OpenBLAS identity/configuration;
- OpenBLAS/OMP thread settings.

Therefore cold==warm exactness is asserted only when the full runtime identity
matches. Cross-runtime cache reuse must MISS by construction.

## 7. Go-live closure gates before matrix

The matrix remains blocked until all of the following are evidenced against the
selected production anchor:

- #690 class-wide rounding closure remains present, including chunk/HOLD;
- same-snapshot default-vs-oracle A/B on latest selected production SHA;
- S02 current identity COMPLETE/CURRENT_VALID;
- PRE_RENDER, POST_RENDER, and HUMAN_FACING all PASS;
- scheduler state explicitly evidenced, not inferred;
- at least one verified NATURAL DEEP on the anchor;
- Tzolakis captain / governed vice result explicitly inspected;
- lineage/runtime invalidation tests green.

No partial-change result may be used to alter the expectations above.
