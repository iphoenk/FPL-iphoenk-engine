# V12 End-to-End Measurement Design Freeze — 2026-09-25

Status: FROZEN BEFORE END-TO-END PROFILING
Production main authority: `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`

## 1. User-facing execution lanes

The performance workstream MUST distinguish three production lanes.

### Lane A — repeated interactive scenario iteration

Authority:
- service: `src.runtime_v3.unified_fastpath`
- registry owner: `config/runtime/interactive_service_registry.json`
- performance profile: `instant_serving`

Purpose:
- repeated lineup/package/transfer-decision regeneration when canonical projections and package artifacts are already current;
- consumes materialized canonical artifacts;
- performs zero external network fetches;
- does not recompute football prediction formulas;
- recomputes governed lineup/package decision surfaces.

Current canonical SLO:
- preferred target: **500 ms**
- hard ceiling: **1,000 ms**

Binding stop gate:
- median engine wall-clock <= **500 ms**
- every measured run <= **1,000 ms**
- output material-decision fingerprint must be identical for the same canonical input set.

This lane is the normal path for repeated transfer-scenario comparison. It is **not** a DEEP rerun.

### Lane B — partial-change / deadline interactive refresh

Authority:
- execution profile: `fast_decision`
- `config/runtime/execution_profiles.json`
- `config/runtime/incremental_reuse.json`
- `config/runtime/fast_lane_policy.json`
- canonical performance profile: `fast_decision`

Purpose:
- decision-relevant facts or model inputs changed and the canonical decision state must be refreshed before further scenario iteration;
- typical examples include injury/availability, xMins, tactical role/system, Official current-state changes, price/team-state changes, or another dependency in the declared prediction/package inputs.

Current canonical SLO:
- target/hard ceiling: **3,000 ms**
- consistency requirement: **3 fresh-process candidate runs must each be <= 3,000 ms**

Reuse correctness contract:
- no age-based prediction reuse: `prediction.max_age_seconds = 0`;
- no age-based tactical-context reuse in `fast_decision`;
- prediction/tactical reuse is permitted only under exact content-addressed fingerprint match;
- stale or missing fingerprints fall back to execution;
- reuse never bypasses artifact validation;
- a new production job still performs fresh Official current-state acquisition; same-workspace Official snapshot warm retry may reuse only within the declared bounded 60-second retry window;
- unaffected services may reuse only when their declared input fingerprint remains exact.

Binding stop gate:
- all 3 fresh-process partial-change runs <= **3,000 ms compute wall-clock**;
- any reused service must prove exact input-fingerprint match;
- the material decision/artifact result from the reuse-enabled run must equal the no-reuse reference on the same resolved input set, excluding only explicitly declared nondeterministic provenance/timestamp fields;
- if a changed input participates in a service fingerprint, that service may not be treated as warm merely because the artifact is recent.

This lane, not warm DEEP, is the authoritative mode for injury/xMins/role/price-driven reevaluation near deadline.

### Lane C — full DEEP review

Authority:
- visible mode `NORMAL_DEEP_REVIEW`
- execution profile `deep_stats`
- integrated V12 DEEP report runner.

Purpose:
- complete analytical/report review, not rapid iterative scenario serving.

Repository profile contract:
- `deep_stats` current target: 60 s
- current legacy ceiling: 90 s
- profile-level fingerprint reuse: disabled.

Performance-hardening project goal already established before this profile:
- **fresh DEEP compute <= 30 s**

The pre-existing 30 s project goal remains a stricter engineering stop target than the current deep-stats SLO. It is secondary to the interactive gates but remains part of the performance-closure check.

There is **no binding 15 s warm-DEEP gate** in this design because the current execution registry explicitly states that `full_refresh` and `deep_stats` never use fingerprint reuse. A separate warm-DEEP product lane must not be invented from cache behavior. If a future supported warm-DEEP lane is introduced, it requires its own correctness and latency contract first.

## 2. Final performance stop rule

Performance hardening is complete only when ALL currently supported user-facing lanes meet their frozen requirements:

1. **Unified interactive fastpath**
   - median <= 500 ms
   - every measured run <= 1,000 ms
   - same-input material output identity PASS

2. **Partial-change fast_decision**
   - 3 fresh-process runs, each <= 3,000 ms compute
   - reuse/invalidation correctness PASS against no-reuse reference

3. **Fresh DEEP**
   - compute E2E <= 30 s on the frozen production snapshot
   - all required report/decision/QA contracts PASS

Once all three pass, do **not** open another optimization stage merely because profiling reveals a largest remaining component. Reopen performance work only for:
- a lane violating its frozen latency gate;
- deadline-delivery miss attributable to compute or I/O;
- reliability/correctness failure;
- a new supported interaction mode with a separately frozen latency requirement.

## 3. End-to-end boundary

Two clocks are required and MUST NOT be mixed.

### 3.1 Compute E2E

Compute starts after the benchmark input snapshot/artifact set is fully available locally and ends after the final human-facing artifact plus required validation/acceptance is complete.

For V12 DEEP, compute E2E includes:
- analytics foundation;
- P1.1 / P1.3 universe work;
- P1.7 lineup;
- P1.2A package search;
- P1.2B package utility/materialization;
- P1.4 Monte Carlo when production invocation requires it;
- mini-league/decision overlays;
- Stage3;
- render/materialization;
- PRE/POST render QA and human-facing acceptance.

Compute profiling MUST use the frozen local snapshot and no external network.

### 3.2 External I/O / acquisition

Real production acquisition is measured separately:
- Official FPL/network fetches;
- optional external source fetches;
- artifact hydration/download/publication where applicable.

Report per-I/O-stage wall-clock and total acquisition wall-clock.

I/O is relevant to user-perceived deadline latency, but MUST NOT be included in compute Amdahl shares.

A deadline-delivery miss caused by I/O remains a valid reason to reopen the performance/reliability workstream even when compute gates pass.

## 4. Instrumentation authority

Stage-level timing:
- use existing `v12_integrated_report_runner._stage()` `time.perf_counter()` ledger;
- leave `V12_STAGE_PROFILE_DIR` unset so cProfile is NOT active during stage-share measurement;
- add only bounded `perf_counter` wrappers for pipeline portions not already represented by the stage ledger.

cProfile:
- forbidden for the first end-to-end composition measurement;
- may be used only after the largest failing stage has been identified.

For each measured run report:
- total compute wall-clock;
- each stage wall-clock;
- each stage share = stage wall / that run's total wall;
- median share per run;
- stage min / median / max wall-clock;
- total min / median / max wall-clock.

Do NOT compute stage share as `median(stage) / median(total)`.

## 5. Monte Carlo measurement contract

Production MC settings are frozen from `config/intelligence/v12_monte_carlo.json`:

- minimum actual paths: **500,000**
- checkpoints: 50k / 100k / 250k / 500k
- max material routes: 8
- chunk size: 100,000
- parallel minimum paths: 200,000
- parallel workers: **4**
- RNG: NumPy Generator / PCG64
- deterministic SeedSequence child shards
- common random numbers: enabled

Benchmark requirements:
- preserve production MC invocation rules;
- fix the benchmark report slot/input state so the normal production seed derivation is deterministic;
- record the resolved canonical seed;
- do not lower path count;
- do not disable required material routes;
- record wall-clock and process CPU time for MC;
- record child-process CPU time when available;
- record `nproc` and configured worker count.

Amdahl share uses wall-clock. CPU/wall ratio is diagnostic for parallelism efficiency.

## 6. Hardware/runtime metadata

Every end-to-end run records:
- `/proc/cpuinfo` first model name;
- `nproc`;
- Python version;
- runner image/version;
- GC enabled state;
- `sys.gettrace()`;
- `sys.getprofile()`;
- relevant worker/process counts;
- frozen input fingerprint;
- production main SHA.

Cross-run absolute-second comparisons must not be treated as same-hardware evidence unless CPU/runtime metadata matches.

## 7. Correctness requirements by lane

### Interactive fastpath

Same canonical inputs must produce the same material:
- lineup;
- package decision;
- Gate0 result;
- authority/governance surfaces.

No stale artifact may be labeled fresh to meet latency.

### Partial-change fast_decision

For each invalidation fixture:
- execute normal reuse-enabled fast_decision;
- execute no-reuse reference on the exact same resolved input set;
- compare material decision/artifact fingerprints;
- record which services reused and their exact input fingerprints;
- changed fingerprint => affected service must execute;
- unchanged exact fingerprint => reuse may qualify if all declared artifact validation passes.

Required partial-change fixtures:
- injury/availability change;
- xMins change;
- tactical role/system change;
- Official current-state/price change;
- current team/finance change where supported by the input contract;
- unchanged input control.

### Full DEEP

All existing Stage3 / PRE_RENDER / POST_RENDER / HUMAN_FACING gates remain mandatory. Latency never relaxes report correctness.

## 8. Interpretation rule after profiling

The first end-to-end profile is a **closure test**, not an instruction to optimize the largest bar.

Examples:
- fresh DEEP = 18 s: DEEP performance target passes; do not optimize its largest stage merely because one exists.
- fast_decision = 3.4 s: workstream remains open even if DEEP is 18 s, because the binding partial-change interactive lane fails.
- unified fastpath median 0.7 s with max 0.9 s: hard ceiling passes but preferred interactive target fails, so performance closure is not complete.
- unified fastpath 0.3 s, partial-change 2.2 s, fresh DEEP 24 s: all frozen latency gates pass; performance hardening stops.

## 9. Strategic answer

Repeated transfer scenario comparison is **not** supposed to run a full DEEP rerun.

The production architecture is deliberately split:
- repeat decision iteration on current canonical evidence -> `unified_fastpath`;
- factual/model partial change -> `fast_decision` refresh with exact-fingerprint reuse only;
- complete analytical review -> DEEP / `deep_stats`.

This lane separation is the authority for the end-to-end measurement and stop rule.
