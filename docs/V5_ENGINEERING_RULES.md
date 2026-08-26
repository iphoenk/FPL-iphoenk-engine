# V5 Engineering Rules

These rules are mandatory for the V5 unified engine.

1. Avoid hardcoded domain knowledge. Rules, thresholds, weights, source authority, cadence, and performance limits belong in config or registries whenever they can change independently of code.
2. Separate independent authorities. If a domain has its own provenance, lifecycle, validation, or tuning surface, create a dedicated module or registry and make all consumers depend on it.
3. Optimize correctness and speed together. Material changes must be benchmarked. Prefer single-pass transforms, cached immutable configuration, batched or vectorized operations, bounded candidate universes, and no duplicate source fetches or repeated file reads in hot paths.
4. Hardcode exceptions require rationale and tests. Structural constants may remain in code only when externalization would add indirection without creating a meaningful tuning or authority surface.
5. Performance budgets are configuration, not scattered constants. CI must fail on unreviewed regressions beyond the current V5 performance budget.
6. A faster implementation is not acceptable if it weakens source authority, provenance, leakage protection, legality, or rules compliance.
