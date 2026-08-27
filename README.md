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

V5.0.0-beta.3 converges against the accepted V3.18.1 production baseline at commit `02d0ce597e111e9b7d464f88479d78d462b616eb`, schema 47.

V3.18.1 changed production source reliability and architecture contracts after the previous beta.2 shadow acceptance. Because V5 acceptance is intentionally scoped to the exact V5 version and exact production baseline SHA, the older beta.2 3/3 shadow cycles do not carry forward. Beta.3 must prove itself again on V3.18.1.

Current V5 capability set includes:

- V3 Official FPL rules registry as V5 single rules authority
- projection scoring wired to the shared rules registry
- goalkeeper-goal scoring corrected to the 2026/27 10-point rule
- V5 contracts for TruthState, PlayerProjection and DecisionTrace
- bounded-context microservices for ingestion, truth, price, prediction, evaluation, decision, governance, watchlist, reporting, snapshot and orchestration
- strict 50/50 DSS core + 16/16 DSS extension postflight governance
- exactly 15 owned players and exactly 20 external watchlist players, with 5 per position
- persistence registry coverage for orchestrator-routed runtime artifacts including source fusion
- V3.18.1 challenger-source contract parity: reachability is distinct from capability health, stale observations cannot be silently current, and challenger observations use an explicit versioned contract
- registry-owned LiveFPL and OneFPL structured-access metadata, including parser contract, TTL and OneFPL approved fallback/host allow-list
- source-fusion observability for Understat and API-Football, with provider availability class, fail-neutral state, reason, and cache evidence preserved into the orchestrator summary used by shadow acceptance
- API-Football provider restrictions classified explicitly, with `PLAN_RESTRICTED` treated as fail-neutral optional-source unavailability rather than fabricated evidence or engine failure
- cached provider-restriction evidence to avoid repeated quota-wasting calls during the configured TTL
- convergence, shadow-parity, architecture, persistence, reporting and performance regression gates
- postvalidated real-shadow acceptance accounting: a cycle counts only after core parity/invariants and the workflow-level reporting/source-health validator both pass
- acceptance accounting is version- and production-baseline-scoped, so old beta cycles cannot silently satisfy a newer release or changed production baseline
- on-demand reporting route for fresh team snapshots; until V5 production promotion, the report refreshes the current production V3 engine and publishes a read-only full snapshot without auto-submitting FPL changes
- V5 reporting supports forced-full report mode so on-demand snapshots do not collapse into compact delta output

Official FPL remains the native external authority. Challenger/enrichment sources never override Official FPL identity, price, rules or authoritative squad state, and missing data is never fabricated.

## On-demand team report

The on-demand route is triggered independently from the normal collector cadence. A request refreshes the current production authority, validates production/watchlist/report-serving contracts, packages a full team snapshot, and publishes the latest result under the isolated runtime-data report path. Trigger-only pushes do not run the full V5 regression suite.

While V5 remains beta, on-demand report authority is V3 production. V5 beta may be used only as a non-authoritative shadow overlay. After an explicit production cutover, the routing registry can be changed without altering the report contract.

## Promotion rule

V5.0.0-beta.3 requires three successful postvalidated real-shadow cycles on the same V5 version and the exact V3.18.1 production baseline SHA before it can become production-candidate eligible. Failed, pending, older-version, or baseline-mismatched cycles do not count. Reaching 3/3 never auto-promotes V5; production promotion remains an explicit manual governance action.
