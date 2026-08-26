# V5 Performance Strategy

V5 treats processing speed as a first-class acceptance dimension alongside correctness.

## Hot-path rules

- Load immutable configuration through a process-level cache.
- Do not re-read rules, registries or static lookup files per player.
- Resolve player/team/fixture identities once and reuse indexed maps.
- Batch network collection by endpoint/domain and prohibit duplicate source fetches within one run.
- Bound candidate universes before expensive projection, Monte Carlo or package evaluation.
- Prefer single-pass feature construction and reuse intermediate features across lineup, captaincy and transfer evaluation.
- Vectorize or parallelize only where measured workloads justify the added complexity.
- Keep network latency, CPU time and file I/O separately observable so optimization targets the real bottleneck.

## Acceptance

Performance budgets live in `config/v5_performance_budgets.json`. Bootstrap budgets are deliberately loose until representative end-to-end workloads are captured. Tightening budgets must follow measurements, not arbitrary targets.
