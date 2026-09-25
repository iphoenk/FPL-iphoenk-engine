# V12 End-to-End Measurement Design Freeze — 2026-09-25

Status: REVISION 2 FROZEN BEFORE END-TO-END PROFILING
Production main authority: `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`
Supersedes initial freeze commit: `d0dad6e47ddad49b7c7f480990e3908d6bdebf82`

## 0. Execution-truth correction

A repository audit after the initial freeze changed the lane classification.

`src/runtime_v3.unified_fastpath` exists and has an interactive SLO registry, but it is **not an active production ingress for current V12 MaenBola**:

- `.github/workflows/fpl-engine.yml` is explicitly `LEGACY_FORENSIC_ONLY` and states V3/V4/V5 operational ingress remains disabled;
- the active V12 workflow is `.github/workflows/v12-integrated-report-runner.yml`;
- that workflow accepts only `DEEP` or `PRICE`;
- every dispatch runs on a new GitHub-hosted `ubuntu-latest` job and launches a new Python process;
- the workflow explicitly fails if `v12_integrated_report_runner.py` imports `src.runtime_v3`, `runtime_v4`, or `runtime_v5`;
- with `profile_mode=OFF`, deterministic Stage-2, P1.7, and MC caches may be restored across jobs;
- with `profile_mode=COLD`, those caches are removed.

Therefore the initial claim that repeated current V12 scenario comparison is served by the resident/unified fastpath is not production truth.

The V3 `instant_serving` 500 ms / 1 s contract remains useful as a future architecture reference, but it is **non-binding for current production closure** until a supported V12 ingress actually invokes it.

## 1. Current production process model

Current scenario/report recomputation is a **new-process CI execution model**:

1. new GitHub-hosted runner allocation;
2. checkout production main and factual runtime-data;
3. setup Python;
4. install dependencies;
5. optionally restore deterministic caches;
6. launch `python -m src.engines.v12_integrated_report_runner`;
7. run downstream Stage3 / QA / artifact delivery.

There is no resident Python service in the current V12 production path.

Consequently every latency report MUST separate:
- queue time;
- runner/bootstrap time;
- dependency-install time;
- cache restore time;
- V12 compute time;
- downstream acceptance/render time;
- total workflow wall-clock visible to the operator.

The 30 s / 15 s engineering goals below are **compute goals**, not claims of sub-second user-perceived service latency.

If GitHub Actions overhead dominates real waiting time after compute gates pass, the remedy is an execution-architecture change (for example a supported resident V12 service), not further micro-optimization of already-compliant compute stages.

## 2. Frozen run counts

A max-based gate is meaningless without a frozen sample count. Counts are now fixed before measurement.

### 2.1 Fresh / cold V12 DEEP compute

- **N = 5 independent GitHub-hosted jobs**
- each job starts a fresh Python process;
- each uses the exact same frozen production snapshot and report slot;
- no Stage-2/P1.7/MC cache may be restored;
- measurement harness MUST clear those cache directories but MUST NOT enable cProfile.

Important: current workflow `profile_mode=COLD` enables `V12_STAGE_PROFILE_DIR` and therefore cProfile. The E2E latency harness must reproduce cold-cache semantics **without** that profiler, otherwise the performance gate would be contaminated.

Gate:
- **all 5 compute E2E runs <= 30 s**
- all report/Stage3/PRE_RENDER/POST_RENDER/HUMAN_FACING correctness gates PASS.

### 2.2 Unchanged-input warm-cache V12 DEEP

- one unmeasured cache-priming run;
- then **N = 7 independent GitHub-hosted jobs**;
- every measured job is still a new runner/new Python process;
- exact same frozen inputs/report slot;
- Stage-2/P1.7/MC cache restore must report a qualifying hit;
- no stale-state substitution is allowed.

Gate:
- **all 7 compute E2E runs <= 15 s**
- each warm-cache material result must match the cold no-cache oracle on the same input, excluding only explicitly declared timestamp/provenance fields.

This is a new-process **warm-cache** mode, not a resident-process warm mode.

### 2.3 Partial-change deadline reevaluation

Partial-change is current V12 DEEP execution with cache eligibility determined by the changed inputs. It is not the dormant V3 `fast_decision` lane.

Required change classes:
- injury / availability;
- xMins;
- tactical role/system;
- Official current-state / price;
- current-team / finance where represented by the production input contract;
- unchanged-input control.

For each change class:
- **N = 3 independent fresh-process jobs**
- one input dimension changes at a time;
- compare normal cache-enabled execution with a no-reuse reference on the exact resolved input set.

Latency gate:
- **all 3 runs for each change class <= 30 s compute E2E**.

Correctness gate:
- any service/cache whose declared semantic input changed MUST miss/invalidate/recompute;
- unaffected cache reuse is permitted only when exact cache/fingerprint authority proves equivalence;
- material output must equal the no-reuse reference for the exact same changed input.

Three-of-three is the existing bounded engineering evidence target for this lane. It is **not evidence that production p95 <= 30 s**, and reports must say so explicitly.

## 3. Hardware model

Production itself runs on GitHub-hosted `ubuntu-latest`, whose physical CPU allocation is not fixed.

Therefore E2E production-representative measurements intentionally use **independent GitHub-hosted jobs**, not a single pinned EPYC validation runner.

Every measured job records:
- first `/proc/cpuinfo` model name;
- `nproc`;
- Python version;
- runner image/version;
- GC state;
- `sys.gettrace()`;
- `sys.getprofile()`;
- cache-hit/miss state.

Interpretation:
- absolute latency gates are judged on the actual hosted-runner sample because that heterogeneity is part of current production;
- stage-to-stage attribution within one run uses that run only;
- cross-run normalized comparisons must stratify/report CPU model;
- no historical 1.4x–1.8x difference may be called a code regression without hardware-matched evidence.

If MaenBola is later moved to a fixed local/server host, these production latency gates must be re-baselined on that actual execution hardware before claiming user-visible SLO compliance.

## 4. Compute and workflow boundaries

### Compute E2E

Begins immediately before invocation of the integrated V12 Python runner and ends after the final human-facing artifact plus required V12 validation/acceptance compute belonging to that occurrence is complete.

The measurement must include the same decision/report compute required by production, including:
- foundation;
- P1.1/P1.3;
- P1.7;
- P1.2A/P1.2B;
- MC when production invocation requires it;
- mini-league/decision overlay;
- Stage3;
- materialization/render;
- PRE/POST/HUMAN_FACING QA.

### Workflow latency

Separately report:
- GitHub queue delay;
- checkout;
- Python setup;
- dependency installation;
- cache transfer;
- compute E2E;
- downstream artifact/upload/comment overhead;
- total workflow duration.

Workflow latency is not folded into compute Amdahl shares.

No claim that the current architecture is “interactive sub-second” is permitted from compute timing alone.

## 5. Stage instrumentation

First-pass E2E stage composition uses only `time.perf_counter()`.

- leave `V12_STAGE_PROFILE_DIR` unset;
- do not use cProfile in the first composition run;
- use existing `_stage()` timing ledger where available;
- add bounded perf-counter wrappers only for unledgered compute portions.

For every stage:
- per-run wall-clock;
- per-run share = stage wall / that run's compute E2E wall;
- min / median / max wall;
- median of per-run shares.

Never report `median(stage) / median(total)` as the median stage share.

## 6. Monte Carlo contract

Production MC benchmark preserves:
- 500,000 minimum actual paths;
- configured checkpoints;
- max material routes = 8;
- chunk size = 100,000;
- parallel workers = 4;
- PCG64 / deterministic SeedSequence child shards;
- common random numbers;
- production invocation rules.

Freeze the benchmark report slot/input so normal production seed derivation is deterministic.

Record:
- resolved canonical seed;
- MC wall-clock;
- process CPU time;
- child-process CPU time where available;
- configured workers;
- `nproc`.

Amdahl uses wall-clock. CPU/wall is diagnostic for parallel efficiency.

## 7. Correctness key-completeness matrix

Partial-change correctness is tested **per change class**, not by one aggregate fingerprint test.

For every fixture, record:
- the exact field/artifact mutated;
- services/caches whose declared input set includes that mutation;
- before/after input fingerprints for each affected service/cache;
- reuse/miss/recompute decision;
- no-reuse oracle material fingerprint;
- normal cache-enabled material fingerprint.

Required assertions:
- injury/availability mutation invalidates every consumer that semantically depends on availability;
- xMins mutation invalidates every consumer whose projection/lineup/package state depends on xMins;
- role/system mutation invalidates tactical/projection consumers that declare that input;
- Official price/current-state mutation invalidates package economics/search/decision consumers as applicable;
- current-team/finance mutation invalidates personal/package decision consumers as applicable;
- unchanged-input control proves qualifying exact reuse rather than unconditional recomputation.

A cache key is acceptable only if the test proves key completeness for that mutation class. Recency alone is never a substitute for input identity.

## 8. Current stop rule

Current compute-performance hardening closes only if ALL are true:

1. fresh cold-cache DEEP: **5/5 <= 30 s**;
2. unchanged-input warm-cache DEEP: **7/7 <= 15 s** and warm-vs-cold correctness PASS;
3. each partial-change class: **3/3 <= 30 s** and invalidation/no-reuse-oracle correctness PASS.

After these pass, do not optimize the next largest compute stage merely because it is largest.

Separately, always report actual GitHub workflow total latency. If workflow overhead makes the real interaction unacceptably slow while compute is already compliant, that is evidence for a serving-architecture change, not D3-style kernel optimization.

## 9. Dormant fastpath benchmark policy

The existing `runtime_v3.unified_fastpath` may be benchmarked only as a non-blocking architecture diagnostic until it is wired into active V12 production.

If benchmarked:
- **N = 20 in-process steady-state calls** after one warm-up;
- **N = 5 fresh Python processes** to expose import/startup cost;
- report first-call, steady-state median/max, and fresh-process total separately;
- do not use its 500 ms / 1 s SLO to claim current V12 production closure.

If a supported resident V12 fastpath is later deployed, process model and hardware must be frozen from that deployment and this section must be replaced by a new production gate.

## 10. Strategic answer

As of production main `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`, repeated scenario/report recomputation is **not served by a resident fastpath**.

The active V12 execution model is GitHub Actions + new Python process per dispatch, with optional deterministic cache restore.

Therefore:
- cold and warm-cache DEEP are the current measurable compute lanes;
- partial-change invalidation is a cache-correctness problem inside that new-process model;
- the legacy V3 fastpath is not a current binding latency lane;
- true sub-second interactive serving would require an active V12 serving ingress rather than merely optimizing the DEEP runner.
