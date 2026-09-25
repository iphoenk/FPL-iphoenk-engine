# V12 End-to-End Measurement Design Freeze — 2026-09-25

Status: REVISION 3 FROZEN BEFORE END-TO-END PROFILING
Production main authority: `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`
Supersedes Revision 2 commit: `adb0ffd65e4f93a066556503309cb13b611afc7d` (which superseded initial freeze `d0dad6e47ddad49b7c7f480990e3908d6bdebf82`)

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


## 10. Cache restore authority and two-level key model

The active V12 workflow uses broad GitHub Actions cache-directory restore plus exact content-addressed files inside each restored directory.

### 10.1 GitHub Actions restore keys

All three workflow caches use a unique write key ending in `github.run_id` and a prefix fallback that removes that run id.

Stage-2 directory:

```
key:
v12-stage2-derived-${runner.os}-${hashFiles(stage2 code/config dependencies)}-${github.run_id}

restore-keys:
v12-stage2-derived-${runner.os}-${hashFiles(stage2 code/config dependencies)}-
```

P1.7 directory:

```
key:
v12-p17-decision-${runner.os}-${hashFiles(optimizer/config/rules/canonical)}-${github.run_id}

restore-keys:
v12-p17-decision-${runner.os}-${hashFiles(optimizer/config/rules/canonical)}-
```

MC directory:

```
key:
v12-mc-summary-${runner.os}-${hashFiles(mc/config/rules/canonical)}-${github.run_id}

restore-keys:
v12-mc-summary-${runner.os}-${hashFiles(mc/config/rules/canonical)}-
```

Therefore:
- a previous directory may be restored whenever code/config authority matches;
- factual runtime input identity is **not** part of the GitHub Actions restore prefix;
- prefix restore is expected and is not itself proof of semantic cache validity.

Partial-change correctness MUST therefore test the internal cache key, not merely the outer GitHub cache restore result.

### 10.2 Stage-2 exact internal key

`stage2_derived_input_fingerprint()` includes:
- planning GW;
- full bootstrap;
- strength;
- historical prior;
- player-features payload;
- ordered player-match rows;
- ordered opponent-history rows;
- opponent-history scope;
- exact model-dependency file hashes.

The cache file path is derived from that fingerprint and the loaded payload must contain the same key.

Private CURRENT15 is deliberately outside this cache key because Stage-2 projection math does not own private current-team state.

### 10.3 P1.7 exact internal key

`_decision_core_cache_key(players)` includes:
- cache schema;
- optimizer source SHA256;
- canonical V12 revision SHA;
- ruleset id;
- lineup rules;
- full optimizer config;
- the exact normalized player-surface list passed to P1.7.

Any change that changes the P1.7 player surfaces produces a new internal file key.

### 10.4 MC exact internal key

The MC simulation-summary key includes:
- MC source SHA256;
- canonical V12 revision;
- config fingerprint;
- projection fingerprint;
- route signature with economics included;
- actual path count;
- deterministic seed;
- horizons;
- selected route id;
- canonical flag;
- NumPy version.

Thus a restored MC directory may contain stale files, but the runtime only loads a summary whose exact simulation key matches current inputs.

### 10.5 Safety interpretation

GitHub prefix fallback is intentionally broad storage reuse, not semantic reuse.

The safety boundary is:
1. outer cache directory may restore;
2. runtime computes current exact internal key;
3. only exact-key file may hit;
4. otherwise current computation executes and writes a new exact-key file.

The partial-change matrix must prove that every tested mutation changes every internal key whose declared semantic input depends on that mutation.

## 11. Partial-change test sequence — cache restore MUST be active

A partial-change fixture is valid only when it exercises the risky path: a prior-state cache directory is actually restored before running the changed input.

For each mutation class:

1. **Prime old state**
   - run input state A with normal cache-enabled execution;
   - require successful cache save for every applicable cache layer;
   - persist exact internal cache fingerprints/keys and material output fingerprint.

2. **Mutate exactly one semantic input**
   - create state B changing only the declared fixture dimension.

3. **Restore prior cache**
   - run state B in a fresh GitHub-hosted job with normal cache restore active;
   - require evidence that a previous matching-prefix cache directory was restored;
   - record the matched outer cache key/path for Stage-2, P1.7, and MC.

4. **Observe internal decision**
   - for every cache semantically affected by the mutation, assert current internal fingerprint/key differs from state A and runtime reports MISS/recompute;
   - for an unaffected cache, exact internal hit is allowed only if key completeness proves its semantic inputs did not change.

5. **Cold/no-reuse oracle for new input**
   - execute state B again with empty cache directories and no profiler;
   - compare material decision/report fingerprint against the restore-enabled state-B run.

6. **Acceptance**
   - restored-directory run and cold state-B oracle must be materially identical;
   - any affected internal cache that incorrectly hits is a correctness failure even if the final output happens to match on that fixture.

This sequence applies separately to:
- injury / availability;
- xMins;
- tactical role/system;
- Official current-state / price;
- current-team / finance;
- unchanged-input control.

The unchanged control is the inverse proof:
- outer cache restore must qualify;
- expected exact internal keys must remain equal;
- expected internal caches must hit.

## 12. Warm-cache gate semantics

The unchanged-input warm-cache gate remains **N = 7 independent new-process jobs**, but a measured run is never removed from the denominator because restore failed.

A warm run passes only when ALL are true:
- the expected GitHub cache directory is restored from an eligible prior cache;
- the matched restore key is recorded;
- every cache stage expected to execute in the frozen scenario reports the expected exact internal HIT;
- material output is identical to the cold oracle;
- compute E2E <= 15 s.

For the frozen DEEP benchmark scenario, choose an occurrence where Stage-2, P1.7, and MC are all invoked so all three persistent cache layers are exercised.

Any of the following counts as a failed warm run:
- outer restore missing;
- restored directory present but expected exact internal file missing;
- unexpected internal MISS/recompute;
- stale/incorrect internal HIT;
- material-output mismatch;
- compute > 15 s.

Therefore the warm gate is literally:
- **7 attempts**
- **7 qualifying outer restores**
- **7 expected internal-hit sets**
- **7 correct outputs**
- **7 compute times <= 15 s**

Report outer restore hit rate and exact internal hit rate separately even though both are required for closure.

Because the primary GitHub cache key contains the current unique `github.run_id`, exact primary-key reuse across independent runs is not the normal expectation. Evidence must record the matched fallback key/prefix rather than treating a non-exact outer restore as a semantic miss.

## 13. Workflow-total latency policy

No empirically justified user-accepted end-to-end GitHub workflow SLO has been established yet.

Therefore **workflow total is frozen as REPORT-ONLY, with no pass/fail threshold** for this profiling round.

Mandatory reported timings:
- queue wait;
- checkout;
- Python setup;
- dependency installation;
- cache transfer;
- V12 compute;
- downstream acceptance;
- artifact/comment publication;
- total dispatch-to-artifact wall-clock.

Consequences:
- passing the 30 s / 15 s compute gates does **not** authorize a claim that real interactive waiting time is acceptable;
- this workstream may close **compute hardening** if compute gates pass;
- it may not close a future “interactive user-experience SLO” because no workflow-total SLO has been frozen;
- the decision to build a resident serving architecture must use these observed workflow timings plus a separately frozen user-facing latency requirement, not a threshold invented after seeing the data.

This explicitly prevents post-hoc interpretation of workflow overhead.

## 14. Cold-cache emulation equivalence

The repository's current `profile_mode=COLD` is unsuitable for a latency gate because it enables cProfile.

A source/workflow audit shows `PROFILE_MODE` is not read by `v12_integrated_report_runner.py`; it only controls workflow orchestration.

Relative to OFF, COLD does exactly these performance-relevant orchestration changes:
- skips Stage-2 cache restore;
- skips P1.7 cache restore;
- skips MC cache restore;
- deletes and recreates the three cache directories;
- creates the stage-profile directory;
- sets `V12_STAGE_PROFILE_DIR`, which activates cProfile in selected stages;
- tees the runner log and generates profile summaries;
- skips all three cache-save steps.

No MC worker count, path count, runner argument, mathematical config, report mode, or model input is changed by `PROFILE_MODE` itself.

Therefore the latency-safe cold emulation is:

- use the same integrated-runner CLI arguments and frozen inputs as production;
- do not restore any of the three cache directories;
- start all three directories empty;
- leave `V12_STAGE_PROFILE_DIR` unset;
- do not invoke profile-summary generation;
- do not save the resulting cache directories into the shared warm-cache namespace.

Correctness equivalence check:
- emulated-cold material output must match ordinary COLD output on the same frozen input, excluding only profiling/provenance metadata that explicitly describes instrumentation.


## 15. Strategic answer

As of production main `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`, repeated scenario/report recomputation is **not served by a resident fastpath**.

The active V12 execution model is GitHub Actions + new Python process per dispatch, with optional deterministic cache restore.

Therefore:
- cold and warm-cache DEEP are the current measurable compute lanes;
- partial-change invalidation is a cache-correctness problem inside that new-process model;
- the legacy V3 fastpath is not a current binding latency lane;
- true sub-second interactive serving would require an active V12 serving ingress rather than merely optimizing the DEEP runner.
