# FPL V12 PERF-0 Metric Contract

> Status: FROZEN DEFINITION / MEASUREMENT IN PROGRESS  
> Change timestamp: 2026-09-27T11:57:00+07:00  
> Primary production baseline: natural DEEP only.

PERF-0 exists to prevent optimization-by-anecdote. No PERF-A/B/C/D/E conclusion may be drawn until measurements use this contract.

## Comparable primary sample

Primary distributions use only genuine production-natural DEEP executions with:

- canonical V12 semantics;
- actual Monte Carlo paths >= 500,000;
- complete required phases rather than skipped/partial execution;
- one declared runtime class per sample;
- no synthetic or branch-only acceptance mixed into production latency percentiles.

Synthetic and branch-acceptance runs may be kept as engineering evidence, but they are a separate class.

## Frozen phase definitions

1. **GitHub queue/provisioning**: workflow creation to first runner job start.
2. **Setup**: first runner job start through completion of runtime dependency installation.
3. **Factual acquisition**: governed report-prefetch request observation to the exact bound prefetch terminal publication.
4. **Stage-2**: only explicit occurrence-bound Stage-2 timing.
5. **P1.2B**: only explicit package-utility phase timing.
6. **P1.7**: only explicit lineup phase timing.
7. **MC**: canonical Monte Carlo performance elapsed time and only when actual paths >=500,000.
8. **Render/QA**: render start through POST_RENDER QA completion.
9. **Publication/delivery**: private publication start through validated human-facing delivery completion.
10. **Cold total**: workflow creation through validated human-facing delivery.
11. **Warm T0→T1**: event/owner command already received by the warm worker through validated private result publication. GitHub cold queue/setup is explicitly excluded from the warm metric.

If a timestamp is absent, the phase is `UNAVAILABLE`. It is forbidden to infer a phase duration by subtracting unrelated totals.

## Summary support

- p50 requires n>=3.
- p90 requires n>=10.
- max requires n>=1.
- every statistic must report n.
- normalized/native runtime classes are never pooled.

The requested target sample remains approximately 20 comparable production executions. At preparation time, only a small number of clearly comparable successful integrated-runner executions were readily identifiable, so a production p90 is intentionally not declared yet.

## Optimization gate

PERF-A begins only after this definition is frozen and the sample basis is sufficient for the metric being reported. Warm acceptance later requires both:

`T1 - T0 <= 15 seconds`

and

`warm output == canonical cold output`

for correctness-equivalent inputs.
