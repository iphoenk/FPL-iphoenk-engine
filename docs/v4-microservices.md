# V4.9.6 service architecture

V4.9.6 is the canonical production release on `v4-prediction-engine`. `config/release_manifest.json` is the release-identity source of truth. The production engine runs eight independent, process-isolated execution boundaries on one host under a dependency-ready DAG orchestrator. Logical responsibility ownership remains finer-grained than process boundaries, so consolidation does not erase the single-owner model. Mutable runtime state is published separately to `runtime-data-v4`, so the protected canonical code branch is not used as a rolling data store.

## Service graph

1. `raw_snapshot` is the sole service permitted to acquire Official FPL snapshot data and publishes the immutable raw contract.
2. `enrichment` consumes the raw contract, optionally refreshes governed community/advanced evidence, and publishes enrichment evidence with lineage.
3. `prediction` consumes the locked raw and enrichment contracts and publishes the current V4.9.6 prediction/runtime surface.
4. `validation` is one execution boundary for validation lifecycle, reconciliation-readiness audit, FPL 2026/27 rules compliance, and PRE-FLIGHT health. These remain separate logical responsibilities and preserve their existing artifacts/contracts.
5. `optimization` runs deterministic decision compute, squad/package evaluation, lineup optimization, captaincy/bench/transfer arbitration, and recommendation sanity checks.
6. `user_decision_overlay` applies a legal target-GW user decision without overwriting the advisory engine recommendation.
7. `personal_gw_scorecard` produces immutable finished-GW scorecards and planning-GW projected team points from the effective plan.
8. `governance` runs POST-FLIGHT truth and checkpoint/report governance sequentially, preserving canonical HOLD/REVIEW/CHANGE resolution and the user-final-authority contract.

`architecture_guard` is no longer counted as a business runtime microservice. The orchestrator executes it synchronously as startup assurance before launching the eight-service DAG. It still validates ownership, registry uniqueness, release coherence, canonical rule ownership, Official FPL fetch ownership, and duplicate implementation guardrails.

Every registered service boundary remains `INDEPENDENT`. Dependency edges determine execution order, while services with no dependency edge may run concurrently. `validation` and `optimization` deliberately share the same DAG level after `prediction`. Raw snapshot, enrichment, and prediction artifacts are lineage-locked after PASS. The immutable file paths are declared by their service registry rows rather than by hidden orchestrator conventions; mutation or contract mismatch fails closed.

## Logical ownership versus execution boundary

Simplification changes process boundaries, not domain truth ownership. `VALIDATION_STORE`, `RECONCILIATION_TRUTH`, `VALIDATION_LIFECYCLE`, and `RECONCILIATION_READINESS` retain distinct logical owners but declare `validation` as their execution boundary. Likewise, POST-FLIGHT truth and human-report decision ownership remain distinct while executing under `governance`. This keeps the architecture principle: one responsibility, one owner; shared primitives are reused rather than reimplemented.

## Authority and invariants

Official FPL factual state is acquired only by `raw_snapshot`. Downstream services consume contracts rather than refetching the same authority. The engine recommendation remains advisory. A valid user override may change the legal squad, XI, formation, captain, vice-captain, or chip for its declared target GW, while the model alternative and comparison evidence remain preserved.

Squad and plan legality remain fail-closed. The authoritative 15-player structure must retain exact 2 GK / 5 DEF / 5 MID / 3 FWD composition, unique elements, position identity, affordability, and the three-per-club limit. XI, captaincy, vice-captaincy, chip, and formation legality are checked again after the human overlay.

The validation lifecycle remains point-in-time and immutable. Retroactive deadline snapshots are rejected, finished-GW reconciliation is idempotent, and starter truth is taken from Official FPL `stats.starts` rather than inferred from minutes. Consolidating the validation subprocess does not permit an Official FPL refetch or move reconciliation truth into another implementation.

## Health semantics

`pipeline_health`, `prediction_health`, and `capability_health` are intentionally separate. `pipeline_health` describes operational integrity such as source availability, freshness, registries, contracts, rules, and Gate 0. `prediction_health` describes readiness of critical predictive capabilities. `capability_health` exposes the complete registry state, including truthful `PARTIAL` and `WARMUP` capabilities.

Decision readiness follows explicit severity precedence: critical FAILED -> BLOCKED, critical PARTIAL -> DEGRADED, critical WARMUP -> PROVISIONAL, otherwise HEALTHY. Therefore a production run may legitimately have a GREEN operational pipeline while prediction health remains AMBER and the decision engine remains DEGRADED or PROVISIONAL. In those states governed recommendations may still be available, but unqualified GO remains blocked.

## Protected code and runtime publication

The canonical code branch is `v4-prediction-engine` and remains protected by the required `core / validate-v4` check. Generated production data must not push directly to that branch.

The reusable production workflow hydrates prior mutable state from `runtime-data-v4` when it exists. It then runs deterministic tests, the eight-service orchestrator including startup architecture assurance, the centralized quality gate, and the core acceptance summary. Only after those checks pass may the core runtime snapshot be published to `runtime-data-v4`.

Advanced-enrichment ablation remains a strict diagnostic after core publication. Full-shadow parity is still required for that diagnostic. Successful ablation evidence is then committed to the same runtime branch, followed by a publication verification that confirms the expected runtime artifacts exist.

## Scheduling and visibility governance

The default-branch production scheduler performs the master internal evaluation every hour at minute `:30` WIB and dispatches the reusable canonical V4 core. The checkpoint policy, not the cron expression alone, determines whether a run is internal-only or authorized to emit a visible report, and it governs deadline-day, live-match, price-alert, and permitted emergency modes.

The recovery workflow remains a scheduled safety net for stale runtime checkpoints. Manual deep-stats execution delegates to the same reusable production core instead of maintaining a second implementation path.

## Release status

Canonical release: `4.9.6`

Canonical code branch: `v4-prediction-engine`

Mutable runtime branch: `runtime-data-v4`

Release status: `CANONICAL_PRODUCTION_GREEN`

Required canonical check: `core / validate-v4`
