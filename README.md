# FPL iphoenk Engine V5

Unified Decision Engine, currently in alpha and not production-promoted.

## Operating tracks

- V3.x remains the production/runtime baseline for scheduled tasks and reliability-sensitive operation.
- V4.x remains the active prediction development and tuning branch.
- V5.x is the architectural overhaul that converges V3 truth/reliability with V4 prediction intelligence.

## V5 design goal

Unify truth, intelligence, and governance without duplicating authority:

- Official FPL and authenticated Official state
- externalized Official rules registry
- exact finance and sell-value logic
- phase-aware authoritative squad state
- price trajectory and provenance
- xMins/xPts, advanced stats, priors and opponent models
- Monte Carlo and package optimisation
- Gate0, DSS and quality governance
- evidence-to-prediction-to-decision traceability

## Mandatory engineering principles

1. Avoid hardcoded domain knowledge. Changeable rules, thresholds, weights, source authority, cadence and performance limits belong in config or registries.
2. Create dedicated modules or registries whenever a domain has its own authority, provenance, lifecycle or tuning surface.
3. Tune correctness and processing speed together. V5 uses configurable performance budgets and CI gates for material regressions.
4. Prefer single-pass transforms, cached immutable configuration, bounded candidate universes, batched/vectorized work where useful, and no duplicate source fetches in hot paths.
5. Hardcoded structural literals are permitted only where externalization provides no meaningful authority or tuning benefit, and exceptions must be test-covered.

See `docs/V5_ENGINEERING_RULES.md` and `config/v5_architecture_principles.json`.

## Current bootstrap

V5.0.0-alpha.1 establishes:

- V3 Official FPL rules registry as V5 single rules authority
- projection scoring wired to the shared rules registry
- goalkeeper-goal scoring corrected to the 2026/27 10-point rule
- V5 contracts for TruthState, PlayerProjection and DecisionTrace
- convergence and migration manifest
- bootstrap acceptance and architecture/performance CI gates

Production promotion remains blocked until V3 truth capability parity and V4 prediction capability parity are accepted.
