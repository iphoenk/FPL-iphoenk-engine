# FPL V12 PERF-0 Metric Contract

> Status: FROZEN DEFINITION / SAMPLE COLLECTION PENDING  
> Change timestamp: 2026-09-27T14:59:46+07:00  
> Production base at preparation: `508f1ed919b9b37540cc604d92bdfe5075e96366`

PERF-0 prevents optimization-by-anecdote. No PERF-A/B/C/D/E selection may use a one-off fast run or a metric definition changed after observing results.

## Primary comparable sample

The primary baseline uses about 20 genuine production-natural DEEP executions with:

- canonical V12 semantics;
- actual Monte Carlo paths >= 500,000;
- complete required phases;
- declared runtime and cache profile;
- no synthetic/branch-only runs mixed into the production percentile distribution;
- normalized and native runtime classes kept separate;
- a frozen sample basis before p50/p90/max are computed.

Every sample records:

- production main SHA;
- runtime-data-v6 SHA;
- run ID;
- logical CPU count;
- physical-core estimate only when directly supportable, otherwise `UNAVAILABLE`;
- CPU model;
- runtime class;
- Python version;
- NumPy version;
- OpenBLAS version where available;
- SIMD features where available;
- effective thread count where available;
- cache profile and cache state.

Four logical CPUs are never reported as four physical cores without evidence.

## Frozen timing buckets

1. GitHub queue, when separable and observable.
2. Runner provisioning/startup, when separable and observable.
3. Combined queue+startup only as a diagnostic when the split is unavailable.
4. Checkout/setup.
5. Factual acquisition.
6. Stage-2.
7. P1.2A.
8. P1.2B.
9. P1.7.
10. Canonical Monte Carlo.
11. Render.
12. Post-render QA.
13. Private publication.
14. Cold total.
15. Warm T0→T1 for the later P6 worker acceptance.

If a phase timestamp is absent, the phase is `UNAVAILABLE`. It must not be inferred by subtracting unrelated totals.

## Summary rules

- p50 requires n>=3;
- p90 requires n>=10;
- max requires n>=1;
- every statistic reports n;
- per-stage distributions are retained;
- no cherry-picked fast-run baseline;
- sample basis is frozen before percentile computation.

The requested PERF-0 closure still requires approximately 20 comparable real production/public-runner executions. Current public-safe extraction is recorded in `docs/audits/FPL_V12_PERF0_BASELINE_EVIDENCE_20260927.json`. Three real DEEP runs were recovered with 500,000-path MC and successful private delivery, but all three had required `CORE_SLOT_BINDING=PARTIAL / CORE_SLOT_MISMATCH`; therefore they remain diagnostic-only and the primary comparable sample count is truthfully `0/20`. No p50/p90 is computed from them.

## Warm acceptance relation

PERF-0 is not the <=15s acceptance itself. Later P6 acceptance requires:

`T1 - T0 <= 15 seconds`

with the worker already warm, and:

`warm semantic fingerprint == canonical cold semantic fingerprint`.

Cold GitHub queue, provisioning, checkout, and setup remain monitored separately and are not counted against the warm target.
