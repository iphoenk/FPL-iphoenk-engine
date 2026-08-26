# FPL iphoenk Engine V5

Unified Decision Engine, currently in beta and not production-promoted.

## Operating tracks

- V3.x remains the production/runtime baseline for scheduled tasks and reliability-sensitive operation.
- V4.x remains the prediction development and calibration reference track.
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

## Current beta baseline

V5.0.0-beta.1 currently converges against the accepted V3.17.1 production baseline. V3.17.1 is a release-governance/metadata update over V3.17.0 and does not change the accepted V3.17 decision schema or decision logic.

Current V5 capability set includes:

- V3 Official FPL rules registry as V5 single rules authority
- projection scoring wired to the shared rules registry
- goalkeeper-goal scoring corrected to the 2026/27 10-point rule
- V5 contracts for TruthState, PlayerProjection and DecisionTrace
- bounded-context microservices for ingestion, truth, price, prediction, evaluation, decision, governance, watchlist, reporting, snapshot and orchestration
- strict 50/50 DSS core + 16/16 DSS extension postflight governance
- exactly 15 owned players and exactly 20 external watchlist players, with 5 per position
- persistence registry coverage for orchestrator-routed runtime artifacts including source fusion
- source-fusion observability for Understat and API-Football, with provider availability class, fail-neutral state, reason, and cache evidence preserved into the orchestrator summary used by shadow acceptance
- API-Football provider restrictions classified explicitly, with `PLAN_RESTRICTED` treated as fail-neutral optional-source unavailability rather than fabricated evidence or engine failure
- cached provider-restriction evidence to avoid repeated quota-wasting calls during the configured TTL
- convergence, shadow-parity, architecture, persistence, reporting and performance regression gates

Official FPL remains the native external authority. External enrichment never overrides Official FPL identity, price, rules or authoritative squad state.

Production promotion remains blocked until the configured real-shadow acceptance criteria are satisfied.
