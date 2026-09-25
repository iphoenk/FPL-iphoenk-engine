# V12 Partial-Change Preconditions — Frozen 2026-09-25

Status: **FROZEN BEFORE NEW PARTIAL-CHANGE RESULTS**

This document freezes correctness interpretation, count-aware cache invalidation
expectations, anchor policy, numeric-runtime normalization, and the remaining
go-live gates before a new partial-change matrix or E2E profile is inspected.

## 1. Anchor policy

All partial-change matrix runs and E2E profiling MUST resolve one immutable
measurement anchor. Never measure against a moving `main`.

Planned tag after final production closure:

`v12-partial-change-anchor-20260925-r1`

Re-anchor is allowed only as an explicit scheduled validation event after a
declared production change. Never silently re-anchor between cold/warm/partial
pairs. The runtime-data snapshot MUST also be frozen and reported by exact SHA.

## 2. Correctness interpretation

The asymmetric rules are frozen before measurement:

| Observation | Frozen expectation | Classification |
| --- | --- | --- |
| HIT | MISS | **FAIL correctness**: incomplete key / stale-output risk |
| MISS | HIT | **Performance finding**, not correctness failure: over-invalidation |
| warm/partial B output != cold B output | any | **FAIL correctness** |
| HIT | HIT | PASS only if output equals the cold oracle for the same semantic unit |
| MISS | MISS | PASS only if recomputed output equals the cold oracle for state B |

A cache status is never inferred from elapsed time. Use explicit cache proof,
semantic key identity, and cold-oracle output equality.

## 3. Count-aware semantic units

P1.7 and MC are not judged as one binary cache.

For P1.7 define `S_A` and `S_B` as the sets of unique exact
`(GW, 15-player decision surface)` keys before and after mutation.

- expected P1.7 HIT count = `|S_A ∩ S_B|`;
- expected P1.7 MISS count = `|S_B \ S_A|`;
- unchanged squads/GWs must HIT;
- new or changed squads/GWs must MISS.

For MC define `R_A` and `R_B` as the sets of normalized route/horizon
simulation signatures before and after mutation.

- logical MC route HIT count = `|R_A ∩ R_B|`;
- logical MC route MISS count = `|R_B \ R_A|`.

The current physical MC persistent cache stores one summary over the complete
material route set and common-random-number world. Therefore it is coarser than
the logical route counts:

- if logical route MISS count is zero, MC bundle is expected to HIT;
- if one or more logical routes change, the current MC bundle may MISS as a
  whole;
- an unchanged logical route lost only because another route changed is
  **over-invalidation/performance debt**, not a correctness failure;
- route-level partial reuse must not be claimed until the storage architecture
  actually supports it.

## 4. Partial-change mutation contract and frozen expectations

Each class has a fixed mutation point. `U_S`/`D_S` denote unchanged/changed
P1.7 semantic units in state B. `U_R`/`D_R` are the corresponding MC
route/horizon units.

| Change class | Exact mutation | Stage-2 | P1.7 expected counts | MC logical expected counts |
| --- | --- | --- | --- | --- |
| injury | one governed public availability/injury fact entering Stage-2 | MISS | HIT=`|U_S|`, MISS=`|D_S|` | HIT=`|U_R|`, MISS=`|D_R|` |
| xMins | one player's governed xMins surface injected **after Stage-2 cache materialization**; unrelated fields fixed | HIT | HIT=`|U_S|`, MISS=`|D_S|` | HIT=`|U_R|`, MISS=`|D_R|` |
| role | one player's governed P1.6/tactical-role surface after Stage-2; xMins/xPts fixed | HIT | HIT=`|U_S|`, MISS=`|D_S|` | HIT=`|U_R|`, MISS=`|D_R|` |
| price-only | official `now_cost` only; status, fixtures, xMins, role, team and finance otherwise fixed | **MISS** | HIT=`|S_B|`, MISS=0 if P1.7 player surfaces remain price-free | HIT=`|R_B|`, MISS=0 at football-route semantic level; any current MC bundle MISS is over-invalidation |
| team/finance | private CURRENT15 identity changes with its finance state; public universe fixed | HIT | HIT=`|U_S|`, MISS=`|D_S|` | HIT=`|U_R|`, MISS=`|D_R|` |
| fixture change | one governed postpone/DGW/BGW fixture mutation | MISS | HIT=`|U_S|`, MISS=`|D_S|` for fixture-affected GW surfaces | HIT=`|U_R|`, MISS=`|D_R|` for affected route/horizon signatures |
| runtime-class change | change Python, NumPy, normalized OpenBLAS core, active SIMD set, or OpenBLAS thread count | MISS | HIT=0, MISS=`|S_B|` | HIT=0, MISS=`|R_B|`; MC bundle MISS mandatory |
| physical CPU change, normalized class unchanged | different host CPU model while canonical numeric runtime is identical | HIT | HIT=`|S_B|`, MISS=0 | HIT=`|R_B|`, MISS=0; MC bundle HIT |
| unchanged control | byte-equivalent semantic inputs and same normalized runtime class | HIT | HIT=`|S_B|`, MISS=0 | HIT=`|R_B|`, MISS=0; MC bundle HIT |

For `team/finance`, the controlled matrix case MUST change team identity, not
bank alone, so the P1.7 expectation is unambiguous.

If a future refactor changes which fields a stage consumes or publishes, this
table must be revised in a separate pre-measurement commit before a new matrix.

## 5. Price-only Stage-2 proof

The Stage-2 MISS expectation for price is evidence-backed, not post-hoc:

1. `src/engines/v12_stage2_derived_cache.py:104` includes
   `"bootstrap": bootstrap` in the persistent Stage-2 fingerprint.
2. `src/engines/v12_integrated_report_runner.py:3023-3024` passes the current
   `bootstrap` into `load_or_build_stage2_projections`.
3. `src/engines/v12_integrated_report_runner.py:3040` invokes
   `build_player_projections` from that same governed occurrence.
4. `src/models/historical_projection.py:652` publishes
   `"now_cost": int(player.get("now_cost") or 0)` into the Stage-2 projection.

Therefore a price-only `now_cost` change changes both the current Stage-2
fingerprint and the cached Stage-2 projection payload. Regression test
`tests/test_cache_partial_change_contract.py` locks this path.

P1.7's normalized player decision surface currently excludes `now_cost`, so
price-only changes are expected to leave its semantic units unchanged. MC's
current full-projection bundle fingerprint may still invalidate even though
football-route simulation semantics did not change; that is classified as
over-invalidation.

## 6. Upstream lineage requirement

Persistent keys bind both consumed upstream output and code lineage:

`Foundation -> Stage-2 -> P1.7 -> MC`

Minimum contract:

- Stage-2 binds Foundation/Stage-2 dependency code plus deterministic public
  inputs.
- P1.7 binds exact consumed player surfaces plus Stage-2/Foundation code
  lineage.
- MC binds projections + normalized route definitions plus P1.7/Stage-2 code
  lineage.
- A behavior-affecting upstream code fingerprint change MUST force the affected
  downstream cache unit to MISS even if a coincidental numerical output happens
  to remain equal.

## 7. Canonical numeric runtime class

Physical CPU model and host logical-core count are **observability only** and
must not enter persistent cache keys.

Before NumPy is imported in governed CI/report execution, runtime is normalized
to:

- `OPENBLAS_CORETYPE=Haswell`;
- `OPENBLAS_NUM_THREADS=1`;
- `OMP_NUM_THREADS=1`;
- `NPY_DISABLE_CPU_FEATURES` disables `X86_V4` plus the AVX512-family names
  supported by the current NumPy runtime contract, leaving the governed
  NumPy dispatch class at Haswell-compatible `X86_V3` or below.

The persistent runtime key is exactly:

- Python major.minor;
- NumPy version;
- effective OpenBLAS core;
- effective active NumPy SIMD set;
- effective OpenBLAS thread count.

The runtime validator must fail closed if effective NumPy/OpenBLAS state does
not match the requested normalized class.

A cross-host acceptance gate must execute the same governed deterministic P1.7
probe on at least **two distinct physical CPU models** and require:

- one identical normalized runtime key;
- one bit-identical canonical output SHA-256.

A different physical CPU with the same normalized numeric class is therefore an
unchanged-runtime control, not a runtime-class change.

### Historical CPU distribution before instrumentation

The last 20 distinct V12 report runs recorded on control issue #431 were
inspected. Their job logs did not emit a physical CPU model, so the defensible
historical distribution is:

| CPU model | Runs |
| --- | ---: |
| UNKNOWN / not logged | 20 |
| Identified physical model | 0 |

Do not infer AMD/Intel distribution from GitHub's runner label. The integrated
report workflow must now persist the physical CPU model and normalized runtime
evidence so future distributions are measurable.

## 8. Tzolakis captain audit on last accepted production evidence

Evidence source: accepted DEEP run `36108029034`, production
`106d229acd92ef1b6434a786f77b4983ff86747a`, report slot
`2026-09-25T14:30:00+07:00`.

Tzolakis is a **goalkeeper (GK)** in the governed FPL projection. P1.7 selected
Tzolakis captain and Bruno Fernandes vice.

The captain/vice formula in `src/engines/v12_lineup_optimizer.py:1316-1389`
uses:

`captain_base = xPts - 0.15 * expected_shortfall + 0.10 * expected_excess_ge8`

plus the DNP-weighted vice fallback utility.

Observed leading captain candidates:

| Captain | 1GW xPts | Downside | Upside >=8 excess | Captain base utility | Best-pair utility |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tzolakis | 4.811181 | 0.371945 | 0.688922 | 4.824100 | **5.250876** |
| Bruno Fernandes | 4.681309 | 0.334955 | 0.849903 | 4.715747 | 5.152328 |
| De Cuyper | 4.540000 | 0.510505 | 0.902713 | 4.553696 | 4.990277 |
| Haaland | 4.485000 | 0.301449 | 0.725400 | 4.512323 | 4.948904 |
| Gvardiol | 4.425000 | 0.424966 | 0.666531 | 4.427908 | 4.864489 |

Tzolakis's best ordered pair leads the Bruno-captain pair by approximately
0.098548 utility points. His own captain base is 4.824100. The Bruno vice
contribution to **pair utility** is approximately 0.426775 after the same
downside/upside adjustment. The separately published
`expected_vice_takeover_value=0.423630` is the DNP-weighted **raw mean**
fallback, so those two numbers intentionally have different semantics.

The important interpretation is that tactical-role score did **not** make a
goalkeeper captain. Tzolakis's tactical-role score was lower than Bruno's in
the same report. His edge came from the governed 1GW point distribution,
downside/upside terms, and vice fallback. Upstream fixture evidence also gave
his goalkeeper projection a strong clean-sheet environment. Mini-league EO did
not enter P1.7 captain selection.

This audit must be repeated against the final anchor after final-SHA A/B, rather
than assuming the pre-anchor captain remains unchanged.

## 9. Scheduler and closure sequence

The ChatGPT scheduler is intentionally disabled during final validation.

Required sequence:

1. finish #711 and all pre-merge correctness/runtime gates;
2. merge to the selected final production SHA;
3. run same-snapshot default-vs-oracle A/B on that exact SHA;
4. require A/B GREEN and human-facing acceptance GREEN;
5. only then enable the ChatGPT scheduler;
6. require a subsequent **natural DEEP** from that scheduler;
7. only after natural DEEP acceptance create/finalize the measurement anchor
   and run the partial-change matrix/E2E profile against it.

Manual or validation-only DEEP runs do not substitute for the natural-DEEP
gate.

## 10. Go-live closure gates before matrix

The matrix remains blocked until all of the following are evidenced against the
selected production anchor:

- #690 class-wide rounding closure remains present, including chunk/HOLD;
- normalized-runtime cross-CPU bit-identical proof spans >=2 physical CPU
  models;
- lineage/runtime/price invalidation tests are GREEN;
- same-snapshot default-vs-oracle A/B on final production SHA is GREEN;
- S02 current identity is COMPLETE/CURRENT_VALID;
- PRE_RENDER, POST_RENDER, and HUMAN_FACING are PASS;
- scheduler is enabled only after final-SHA A/B is GREEN;
- at least one verified NATURAL DEEP occurs after that enablement;
- Tzolakis captain/vice audit is rechecked on the final anchor.

No new partial-change result may be used to rewrite the expectations above.
