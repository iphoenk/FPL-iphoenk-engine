# V4.9.6 service architecture

V4.9.6 is the canonical production release on `v4-prediction-engine`. `config/release_manifest.json` is the release-identity source of truth. The production engine runs 13 independent, process-isolated services on one host under a dependency-ready DAG orchestrator. Mutable runtime state is published separately to `runtime-data-v4`, so the protected canonical code branch is not used as a rolling data store.

## Service graph

1. `architecture_guard` validates ownership, registry uniqueness, release coherence, canonical rule ownership, Official FPL fetch ownership, and duplicate implementation guardrails.
2. `raw_snapshot` is the sole service permitted to acquire Official FPL snapshot data and publishes the immutable raw contract.
3. `enrichment` consumes the raw contract, optionally refreshes community statistics, and publishes enrichment evidence with lineage.
4. `prediction` consumes the locked raw and enrichment contracts and publishes the current V4.9.6 prediction/runtime surface.
5. `validation_lifecycle` freezes genuine point-in-time deadline snapshots and manages the immutable reconciliation lifecycle without retroactive backfilling.
6. `reconciliation_readiness` audits the frozen-snapshot to submitted-picks to finished-GW to reconciliation chain without performing Official FPL refetches.
7. `rules_compliance` validates the canonical FPL 2026/27 rules contract.
8. `framework_preflight` runs the checkpoint-aware PRE-FLIGHT health and governance audit.
9. `optimization` runs the deterministic decision-compute path, Wildcard/package evaluation, lineup optimization, and recommendation sanity checks.
10. `user_decision_overlay` applies a legal target-GW user decision without overwriting the advisory engine recommendation.
11. `personal_gw_scorecard` produces immutable finished-GW scorecards and planning-GW projected team points from the effective plan.
12. `framework_postflight` validates both engine and effective plans, promotes evidence-backed Official-FPL-first capabilities, and finalizes framework health.
13. `report_governance` emits the checkpoint-governed decision/report state after post-flight and scorecard evidence are available.

Every service boundary remains `INDEPENDENT`. Dependency edges determine execution order, while services with no dependency edge may run concurrently. Raw snapshot, enrichment, and prediction artifacts are lineage-locked after PASS; mutation or contract mismatch fails closed.

## Authority and invariants

Official FPL factual state is acquired only by `raw_snapshot`. Downstream services consume contracts rather than refetching the same authority. The engine recommendation remains advisory. A valid user override may change the legal squad, XI, formation, captain, vice-captain, or chip for its declared target GW, while the model alternative and comparison evidence remain preserved.

Squad and plan legality remain fail-closed. The authoritative 15-player structure must retain exact 2 GK / 5 DEF / 5 MID / 3 FWD composition, unique elements, position identity, affordability, and the three-per-club limit. XI, captaincy, vice-captaincy, chip, and formation legality are checked again after the human overlay.

The validation lifecycle is point-in-time and immutable. Retroactive deadline snapshots are rejected, finished-GW reconciliation is idempotent, and starter truth is taken from Official FPL `stats.starts` rather than inferred from minutes.

## Health semantics

`pipeline_health`, `prediction_health`, and `capability_health` are intentionally separate. `pipeline_health` describes operational integrity such as source availability, freshness, registries, contracts, rules, and Gate 0. `prediction_health` describes readiness of critical predictive capabilities. `capability_health` exposes the complete registry state, including truthful `PARTIAL` and `WARMUP` capabilities.

Therefore a production run may legitimately have a GREEN operational pipeline while prediction health remains AMBER and the decision engine remains PROVISIONAL. In that state governed recommendations may still be available, but `go_allowed` remains false until the predictive readiness requirements are satisfied. Operational GREEN must not be misreported as predictive GREEN.

## Protected code and runtime publication

The canonical code branch is `v4-prediction-engine` and remains protected by the required `core / validate-v4` check. Generated production data must not push directly to that branch.

The reusable production workflow hydrates prior mutable state from `runtime-data-v4` when it exists. It then runs deterministic tests, the 13-service orchestrator, the centralized quality gate, and the core acceptance summary. Only after those checks pass may the core runtime snapshot be published to `runtime-data-v4`.

Advanced-enrichment ablation remains a strict diagnostic after core publication. Full-shadow parity is still required for that diagnostic. Successful ablation evidence is then committed to the same runtime branch, followed by a publication verification that confirms the expected runtime artifacts exist.

This separation preserves branch protection while retaining rolling persistence. Recovery also reads the dedicated V4 runtime branch rather than depending on mutable data commits to the canonical code branch.

## Scheduling and visibility governance

The production gate performs the master internal evaluation every hour at minute `:30` WIB. GitHub cron is UTC, and the minute component remains `:30` after timezone conversion. The checkpoint policy, not the cron expression alone, determines whether a run is internal-only or authorized to emit a visible report, and it governs deadline-day, live-match, price-alert, and permitted emergency modes.

The recovery workflow remains a scheduled safety net for stale runtime checkpoints. Manual deep-stats execution delegates to the same reusable production core instead of maintaining a second implementation path.

## Release status

Canonical release: `4.9.6`

Canonical code branch: `v4-prediction-engine`

Mutable runtime branch: `runtime-data-v4`

Release status: `CANONICAL_PRODUCTION_GREEN`

Required canonical check: `core / validate-v4`
