# V12 Post-D2 End-to-End Performance Baseline — 2026-09-25

Status: MEASUREMENT COMPLETE — NO D3 IMPLEMENTATION AUTHORIZED
Production main: `bb2d9f1f4b5387a7a9dd39ef6b23ad72de5caa94`
Runtime-data-v6: `9fc2ce5e590518c399765e6fd576bb96db6e5897`
Report slot: `2026-09-24T14:20:00+07:00`

D2 PR #693 was merged before these measurements.

## Measurement contract

Two end-to-end modes were measured separately.

### Fresh / cold-compute
Run: `36086126019`

- 3 integrated DEEP samples
- Stage2, P1.7 and MC compute-cache directories cleared before every sample
- no cProfile / no `V12_STAGE_PROFILE_DIR`
- stage authority = integrated runner `[V12_STAGE]` wall-clock ledger
- total authority = full integrated-runner subprocess wall clock
- external Stage3 acceptance measured separately
- every run: runner PASS, PRE_RENDER PASS, POST_RENDER PASS, HUMAN_FACING PASS, external Stage3 PASS
- MC paths: 500,000 on every run

Hardware:
- AMD EPYC 7763 64-Core Processor
- nproc = 4
- Python 3.12.14
- Ubuntu image 20260920.314.1

Median:
- integrated runner: **141.471 s**
- runner + external Stage3 acceptance: **141.810 s**

### Warm / unchanged-snapshot
Run: `36086794774`

- one unmeasured cache primer, then 3 measured integrated DEEP samples
- same local Stage2/P1.7/MC cache directories retained after primer
- no cProfile
- every measured run: runner PASS and HUMAN_FACING PASS
- MC paths: 500,000
- Stage2 cache proof on all measured samples: **HIT**
- primer produced Stage2=1 file / 97,490,967 bytes; P1.7=5 files / 198,998 bytes; MC=1 file / 54,757 bytes

Hardware:
- AMD EPYC 9V45 96-Core Processor
- nproc = 4
- Python 3.12.14
- Ubuntu image 20260920.314.1

Median:
- warm integrated runner: **37.571 s**
- runner + external Stage3 acceptance: **37.803 s**

Cold and warm absolute seconds MUST NOT be ratio-compared directly because the jobs landed on different CPU models. Composition within each job/mode is authoritative.

## Fresh composition

| Group | Median s | Median runner share |
|---|---:|---:|
| STAGE2_PROJECTION | **60.333** | **42.68%** |
| MONTE_CARLO | **36.050** | **25.47%** |
| PACKAGE_SEARCH_UTILITY | **27.458** | **19.35%** |
| NONSTAGED_RENDER_QA_CONTROL_IO | **12.153** | **8.59%** |
| MINI_LEAGUE | 2.315 | 1.65% |
| LINEUP_TACTICAL | 1.644 | 1.17% |
| FOUNDATION | **0.682** | **0.48%** |
| REPORT_SURFACES | 0.475 | 0.34% |
| FACTUAL_SETUP | 0.252 | 0.18% |

Largest individual stages:
- `P1_1_P1_3_FULL_UNIVERSE`: **60.333 s / 42.68%**
- `P1_4_MONTE_CARLO`: **34.751 s / 24.56%**
- `P1_2_PACKAGE_UTILITY`: **18.692 s / 13.15%**
- `P1_2B_FUNDED_PACKAGE_UTILITY`: **5.994 s / 4.24%**
- `P1_7_LINEUP`: **0.515 s / 0.36%**
- `V12_ANALYTICS_FOUNDATION`: **0.682 s / 0.48%**

## Warm composition

| Group | Median s | Median runner share |
|---|---:|---:|
| PACKAGE_SEARCH_UTILITY | **16.197** | **43.41%** |
| MONTE_CARLO | **10.137** | **27.16%** |
| NONSTAGED_RENDER_QA_CONTROL_IO | **7.321** | **19.57%** |
| LINEUP_TACTICAL | 1.198 | 3.19% |
| MINI_LEAGUE | 0.870 | 2.32% |
| STAGE2_PROJECTION | **0.853** | **2.28%** |
| FOUNDATION | **0.362** | **1.00%** |
| REPORT_SURFACES | 0.265 | 0.70% |
| FACTUAL_SETUP | 0.156 | 0.42% |

Largest individual warm stages:
- `P1_2_PACKAGE_UTILITY`: **11.376 s / 30.29%**
- `P1_4_MONTE_CARLO`: **9.215 s / 24.75%**
- `P1_2B_FUNDED_PACKAGE_UTILITY`: **2.919 s / 7.93%**
- `P1_2_STAGE3_DECISION_BINDING`: **1.151 s / 3.06%**
- `P1_6_TACTICAL_ROLE`: **1.123 s / 2.99%**
- `P1_1_P1_3_FULL_UNIVERSE`: **0.853 s / 2.28%**
- `P1_7_LINEUP`: **0.075 s / 0.20%**
- `V12_ANALYTICS_FOUNDATION`: **0.362 s / 1.00%**

## Strategic conclusions

### Foundation is closed as a performance target

Foundation is now:
- 0.48% of fresh runner wall;
- 1.00% of warm runner wall.

Even removing it entirely would not materially change either end-to-end target. No D3 should be opened against foundation based on local foundation share.

### Standalone P1.7 lineup is also not the next target

`P1_7_LINEUP` is:
- 0.515 s fresh;
- 0.075 s warm.

The remaining package-utility cost may internally consume exact P1.7 semantics, but the standalone lineup stage is not an end-to-end bottleneck.

### Fresh and warm have different hard blockers

Fresh:
- Stage2 full-universe is the largest stage at 60.333 s.
- This single stage alone exceeds the architecture-class fresh target of 30 s.
- Therefore the fresh target is mathematically impossible without materially reducing the cold Stage2 path.

Warm:
- package search/utility = 16.197 s;
- MC = 10.137 s;
- non-staged render/QA/control/I/O residual = 7.321 s.
- These three groups account for ~90% of warm runner wall.

Therefore one generic next optimization would mix distinct problems. Discovery should remain separated.

## MC warm-cache observation

The warm primer creates exactly one MC cache file (~54.8 KiB), and the cache inventory remains at one file before/after measured warm runs.

Source audit shows that `run_correlated_monte_carlo()` computes, before `_load_mc_summary_cache()`:
- `projection_fp = fingerprint(projections)`;
- route definitions/signature;
- model-run binding inputs;
- full simulation-cache key.

A 9.215 s warm MC stage despite a stable one-file cache is therefore consistent with expensive **pre-cache-key / pre-cache-lookup work**, especially fingerprinting the very large projection payload. This is a discovery hypothesis, not yet a proven root cause. A bounded micro-timing run should split:
1. package route definitions;
2. projection fingerprint;
3. route signature;
4. cache-key construction;
5. cache load/deepcopy;
6. post-cache envelope/binding.

Do not alter MC math or cache keys until that timing proves the cost.

## Next bounded discovery tracks

No implementation branch is authorized by this memo.

### Track A — FRESH blocker: Stage2 cold full-universe

Measure the 60.333 s `P1_1_P1_3_FULL_UNIVERSE` cold path by non-cProfile scope timing and identify its Amdahl-removable work.

The warm Stage2 cache path is already a proven HIT at ~0.85 s and is not the primary warm target.

### Track B — WARM/shared blocker: package utility

Profile:
- direct `P1_2_PACKAGE_UTILITY`;
- funded `P1_2B_FUNDED_PACKAGE_UTILITY`;
- exact P1.7/batch ownership inside package evaluation;
- data/materialization/fingerprint/serialization overhead;
- cache hit/miss counts and route cardinalities.

This track matters in both modes and is the largest warm group.

### Track C — WARM/shared blocker: MC cache path

Run the bounded cache-path micro-timing described above before considering any MC algorithm change.

### Track D — residual only after A/B/C

The non-staged warm residual is 7.321 s. Decompose render, PRE_RENDER QA, POST_RENDER QA, HUMAN_FACING QA, report assembly/fingerprinting, and artifact I/O only after the larger package/MC work is understood.

## Decision

D1/D2 local foundation hardening succeeded, but further local foundation optimization is no longer justified.

The next performance phase must be driven by end-to-end evidence:
- cold/fresh first-order blocker: **P1.1/P1.3 full-universe**;
- warm first-order blocker: **P1.2 package utility**;
- warm second-order blocker: **P1.4 MC/cache path**.

No D3 implementation should begin until the chosen track has its own bounded scope timing, semantic boundary, and frozen correctness/performance gate.
