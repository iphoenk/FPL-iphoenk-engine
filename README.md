# FPL iphoenk Engine V4.9.6

A production-oriented personal FPL data platform.

## Design goal
Combine:
- Official FPL API authority
- FPL-Core-Insights advanced community stats
- vaastav historical backbone
- live score/persistence
- exact team-value logic
- leakage-safe modelling
- projection/calibration/portfolio frameworks
- human-in-the-loop decision authority: engine recommends, user decides

## P0 Production Core
Implemented:
- phase-aware FPL state
- target-GW-aware pre-deadline squad authority
- previous submitted GW as the default planning/projection baseline
- user override layer for legal squad, XI/formation, captain/vice and chip decisions
- exact sell-value logic
- sell-cost-correct Wildcard affordability (owned sell cost, unowned current cost)
- endpoint health/retry/latency
- live FPL player stat expansion
- price deltas and momentum
- Core Insights + vaastav sync
- leakage guard
- fail-closed validation
- immutable pre-deadline validation snapshots and idempotent post-GW reconciliation
- immutable finished-GW personal scorecards plus planning-GW projected team points
- persistent snapshots
- safe GitHub workflow

## P1 Intelligence
Working base:
- official-ID integration of Core Insights players, shots and player-match stats
- dedicated prior-season vaastav snapshot with stable-code reconciliation
- Bayesian team shares from official set-piece/penalty orders plus observed deep events, used as a bounded zero-centred prior reallocation
- Bayesian opponent-defence resistance from finished Official FPL results, shrunk to the league prior and combined with official diagnostics
- direct-evidence xMins priors with inferred tactical-role competition and protection for proven starters
- advanced-enrichment full-vs-ablated observational evaluation with prediction and optimizer impact metrics
- advanced-stat CLI
- fixture model
- interpretable xMins/xPts scaffold
- FastAPI JSON endpoints
- SSE live streaming

## P2 Advanced
Framework implemented:
- Monte Carlo points scenarios
- package/portfolio legality evaluator
- MAE/Brier/Spearman calibration utilities
- model versioning hooks

P2 is deliberately not marketed as a trained production model until enough season data exists.

## Main commands
```bash
pip install -r requirements.txt

python fpl_daily_tasks.py daily --stats
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live

python fpl_daily_tasks.py stats-sync --gw 1
python fpl_daily_tasks.py stats-sync --gw 1 --deep
python fpl_daily_tasks.py advanced-stats --gw 1 --query "Haaland"

python -m src.services.orchestrator daily --stats --deep-stats
python -m src.services.orchestrator deadline --stats --deep-stats --as-of "2026-08-28T21:30:00+07:00"
python -m src.engines.v4_validation_cycle cycle
python -m src.services.user_decision_overlay_service
python -m src.services.gw_scorecard_service
python -m src.engines.v4_advanced_ablation
python -m src.engines.v4_quality_gate

uvicorn live_service:app --host 0.0.0.0 --port 8000
```

`--deep-stats` enables deep tactical-role, competition, and set-piece/penalty evidence. Omitting it is a faster fallback run and may use official-position proxies; the scheduled production workflow always enables it.

## Live endpoints
- GET `/health`
- GET `/latest`
- GET `/live`
- GET `/team`
- GET `/prices`
- POST `/refresh`
- GET `/stream` via Server-Sent Events

`POST /refresh` is fail-closed and requires either `Authorization: Bearer $FPL_REFRESH_TOKEN` or `X-FPL-Refresh-Token`. SSE clients share one polling broadcaster, so additional clients do not multiply Official FPL refreshes.

## Source authority
1. Official FPL API for factual submitted/live/history state
2. Explicit target-GW user planning override for the effective personal plan
3. FPL-Core-Insights community enrichment
4. vaastav historical dataset
5. Understat/mirrors if explicitly enabled
6. web/news/tactical overlays outside this repository

Optimizer output is advisory. A valid user override may intentionally differ from the model; the engine must preserve the recommendation and comparison evidence but may not silently replace the user's effective plan.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
Historical xP-like fields should be shifted or excluded unless timestamp eligibility is proven.

## Important
FPL-Core-Insights and vaastav are community-maintained. They are useful enrichments, not licensed Opta feeds.

GitHub Actions is persistence/archive, not true streaming infrastructure. Deploy `live_service.py` to an always-on host for near-live polling.

## V4.7.1 correctness hotfix

- V4.6.4 remains the sell-cost and truthful-health correctness baseline.
- V4.7.1 removes the mechanical xMins floor and prevents broad FPL positions from suppressing nailed starters.
- Set-piece and penalty taker orders remain visible metadata but add no blanket scoring multiplier because current xG/xA already contains those events.
- Overall team strength is diagnostic-only when official defence splits are zero, preventing duplicate fixture adjustment through FDR.
- Advanced-data health reports materially distinct enrichment separately from matched records.
- Role competition, empirical set-piece shares, weak advanced enrichment and opponent-defence fallback remain truthfully `PARTIAL`.
- Remaining unrelated framework debt stays `PARTIAL`, so health may remain `AMBER` and unqualified `GO` remains blocked while governed recommendations may still be produced.

## V4.7.2 performance hotfix

- Official FPL snapshot endpoints and independent statistics sources refresh concurrently, while bootstrap remains the phase authority and no polling is added.
- GW1 purchase-price reconstruction is fetched only when the sell-cost ledger actually lacks evidence.
- Framework health reads one immutable prediction snapshot per audit and memoizes repeated operational probes within that audit only.
- WC optimization keeps beam size 6000 and the same ranking key, using packed precomputed club bits and bounded top-k selection instead of full sorting.
- Package audit preserves its frontier and beam widths, while materializing JSON payloads only for retained top packages.
- Decision equivalence is an acceptance requirement; V4.7.1 prediction formulas and V4.6.4 correctness thresholds are unchanged.

## V4.7.3 checkpoint governance

- Checkpoint selection is registry-driven for 04.30, 12.30, 21.30, deadline review, post-final emergency watch, and matchday live monitoring.
- Snapshot freshness limits follow the active checkpoint and block recommendations when exceeded.
- `LOCKED_15` squad composition is reported separately from the still-adjustable XI, bench order, captain, and vice-captain.
- Deterministic `--as-of` runs are labelled simulations and can never authorize a live action.
- The final action is produced only after POST-FLIGHT health, while V4.7.1 predictions and V4.7.2 optimizer search widths remain unchanged.

## V4.8.2 independent process-isolated services

- Eight registry-driven services run as isolated Python processes under one fail-closed orchestrator.
- Every service publishes versioned JSON contracts that are validated before its dependants may run.
- The raw, enrichment, and latest prediction artifacts are hashed after PASS and checked after every downstream service.
- The registry contains eight independent process boundaries. `raw_snapshot` is the sole Official FPL API authority, `enrichment` consumes `snapshot.v1`, and `prediction` consumes both immutable runtime contracts without refetching official data.
- `snapshot.v1` and `enrichment.v1` live only under ignored `data/runtime/`; SHA-256 lineage binds raw input, enrichment, and the latest prediction.
- The orchestrator locks raw snapshot, enrichment, and latest prediction immediately after each service passes, then fails closed on any mutation.
- Prediction preserves every V4.8.0 operational artifact: live state, prices and price cache, source health, chips, per-GW archive, and append-only snapshot history; `latest.json` retains the complete compatibility pointer set.
- Authoritative squads remain fail-closed on 15-player identity, exact 2/5/5/3 composition, uniqueness, and the three-per-club limit. Live player identity/captain fields and truthful endpoint-state normalization remain backward compatible.
- Community enrichment sources are submitted concurrently before results are collected; `latest.json` reports raw snapshot, enrichment, prediction, and compatibility-total timings.
- Prediction V4.7.1, optimizer V4.7.2, checkpoint governance V4.7.3, sell-cost logic, Gate 0, and registry counts remain unchanged.
- `data/service_orchestration_v4.json` provides service status, timings, contract hashes, and failure evidence.

See `docs/v4-microservices.md` for service ownership, failure semantics, and preserved invariants.

## V4.8.2 truthful health separation

- `pipeline_health` reports API, freshness, registry, contract, rules, and Gate-0 operability.
- `prediction_health` reports whether critical prediction capabilities have production evidence.
- `capability_health` and `capability_coverage` expose all 74 DSS and enhancement states without hiding `PARTIAL` modules.
- `decision_engine` follows prediction readiness, while the backward-compatible `overall` field now represents operational pipeline health.
- A GREEN pipeline with AMBER prediction health may produce governed recommendations, but `go_allowed` remains false.

## V4.9.1 prediction quality and operational hardening

- Fixes appearance scoring so unconditional `p60` is not multiplied by start probability twice; an exact numeric regression test protects the formula.
- Deep shot and match metrics feed rate estimation, tactical-role inference, role competition, and set-piece/penalty priors; decision coverage is measured separately from mere synchronization.
- Finished Official FPL results drive opponent-defence resistance with explicit Bayesian shrinkage instead of a permanent neutral default.
- Player value is published as points per million and consumed by the WC objective as a bounded secondary term; owned-player affordability still uses sell cost.
- Critical prediction probes are evidence-based. Calibration and learning stores report `WARMUP` until an eligible post-GW sample exists; optional unavailable capabilities remain `PARTIAL` rather than being painted green.
- The process-isolated workflow is scheduled at 04.30, 12.30, and 21.30 Asia/Jakarta. The old monolith cron is removed; its manual compatibility workflow now delegates to the same orchestrator and quality gate.
- Live refresh is authenticated and fail-closed, while all SSE clients share one orchestrated polling loop.

## V4.9.2 truthful-health correctness hotfix

- Competition evidence is calculated from the same canonical factor used by fixture projection; a player is marked adjusted only when the applied factor is materially below 1.
- Rotation health requires truthful flag/factor consistency, adjusted and unadjusted players, legal bounds, and factor variation. File presence or a constant flag cannot make the module ACTIVE.
- Critical calibration and learning modules in `WARMUP` make prediction health AMBER and the decision engine PROVISIONAL. Governed recommendations remain available, but automatic GO is held until an eligible reconciled post-GW sample exists.
- Quality-gate version failures explain that artifacts are stale or incompatible and instruct operators to regenerate them through the orchestrator.
- Advanced integration reports synchronization, consumption, and material distinction separately; V4.9.3 adds a controlled ablation measurement for incremental impact.

## V4.9.3 validation lifecycle and optimizer hardening

- A ninth process-isolated validation lifecycle service freezes one genuine pre-deadline prediction snapshot per planning GW and reconciles it exactly once after the GW finishes.
- Retroactive snapshot creation is rejected. GW1 is intentionally not backfilled because no genuine pre-deadline V4 snapshot exists; GW2 is the first clean calibration baseline.
- Reconciliation archives are immutable and idempotent. Framework health consumes a rebuilt current-model-only eligibility view, so stale or malformed historical samples cannot keep calibration or learning falsely ACTIVE.
- Simulation runs never mutate validation storage and the validation service does not refetch Official FPL data.
- Advanced-enrichment ablation compares a full shadow model with the same model minus current-season community enrichment. Full-shadow numerical parity is mandatory before prediction/ranking/optimizer impact is interpreted.
- Ablation effect size is diagnostic evidence, not an arbitrary health threshold. It reports xPts shifts, rank displacement, top-N overlap, optimized-squad changes, and decision flips.
- WC optimization uses exact streaming top-k with objective-bound pruning while preserving search semantics. Package-audit parity tests protect output equivalence rather than accepting speed through reduced search quality.

## V4.9.3.1 compact validation snapshot hotfix

- Existing immutable deadline snapshots remain untouched and fully backward-compatible.
- New deadline snapshots retain every prediction player but store at most the target-GW fixture and only reconciliation-required xPts interval and xMins fields.
- The SHA-256 of the full prediction artifact remains attached to the compact snapshot for provenance, so storage reduction does not weaken point-in-time traceability.
- Full-vs-compact reconciliation output must be exactly identical in regression tests.
- Repeated snapshot attempts preserve the first frozen artifact, and a storage-budget regression test requires the compact projection to stay below 15% of an equivalent full synthetic prediction payload.

## V4.9.4 personal GW scorecard and projection

- A tenth process-isolated `personal_gw_scorecard` service consumes only existing runtime contracts and optimizer output. `raw_snapshot` remains the sole Official FPL API authority; the scorecard service performs zero Official FPL refetches.
- Finished GWs are presented as actual results with squad-level and player-level scoring evidence, captain/vice multipliers, chip, gross points, transfer-hit cost, net points, and bench points.
- Finished results are persisted under `data/gw_results/gwXX.json`. The first valid finished result is frozen; later runs preserve the archive instead of rewriting history. Simulated `--as-of` runs never create or modify this archive.
- Planning GWs expose formation, XI, bench, captain, vice-captain, active chip and estimated team xPts. Captain, Triple Captain, and Bench Boost multipliers are applied explicitly once; Wildcard and Free Hit do not add scoring points.
- Team xPts is an estimate, never labelled as an actual score. Player lower/upper intervals are deliberately not summed into a team range because correlated team-score uncertainty has not yet been calibrated.
- `report_governance` depends on both post-flight health and the scorecard contract, and every checkpoint report scope includes `personal_gw_scorecard`.
- The V4 production registry contains ten independent microservices at this release point.

## V4.9.4.1 projection baseline authority and human decision overlay

- Planning GW N defaults to the Official FPL submitted squad from GW N-1. A planning composition override is allowed only when it declares the exact `target_gw`; an expired Wildcard/draft flag cannot leak into the next GW.
- GW2 is intentionally using the user-captured Wildcard draft because that override is explicitly scoped to GW2. After GW2 becomes the submitted baseline, GW3 automatically reverts to the official submitted GW2 squad unless a new GW3-specific override is supplied.
- The production registry now has eleven process-isolated services. `user_decision_overlay` sits between advisory optimization and `personal_gw_scorecard`.
- `optimization` produces a pure engine recommendation and no longer consumes `manual_lineup.json`. The overlay service is the only layer that applies a user decision to the effective plan.
- A valid user decision may override legal squad composition, XI/formation, captain, vice-captain and chip. The engine retains its alternative and publishes the xPts/formation/captain/chip delta, but `engine_never_auto_overwrites_valid_user_override` is a release guardrail.
- FPL legality remains fail-closed. Human authority cannot create an illegal 15-player structure, illegal formation, captain/vice outside the XI, duplicate picks, invalid chip, or a Wildcard-composition plan that claims a contradictory chip state.
- Scorecard projection consumes `data/effective_plan_v4.json`, not the optimizer lineup directly. This means projected team points always describe the effective human plan while still exposing the model alternative for comparison.
- `GO` is a recommendation state, not an automatic command. `execution_authorized` remains false until the effective plan has an explicit `FINAL_LOCKED` user status and all other governance gates pass.
- The V4.9.4.1 quality gate requires all eleven service contracts, previous-GW baseline lineage, stale-override expiry, optimizer/advisory separation, effective-plan lineage, and human-final-authority semantics to pass before production publish.

## V4.9.4.2 architecture hygiene and diagnostic isolation

- Core daily data now passes unit tests, the eleven-service orchestrator, centralized quality gate, and core acceptance summary before it is persisted. Advanced-enrichment ablation runs afterward as a strict post-publish diagnostic.
- Ablation parity remains fail-closed for the diagnostic itself; a broken full-shadow harness still makes the workflow visibly fail, but it can no longer prevent otherwise-valid price, prediction, health, effective-plan, and scorecard data from being published first.
- Successful ablation output is persisted separately after its diagnostic assertions pass.
- `snapshot.v1` is bumped to schema version 492 because projection-baseline authority became part of the contract; the service contract registry rejects older raw snapshots.
- The redundant manually-maintained `IMPLEMENTATION_STATUS.json` is removed. README, service registries, runtime health artifacts, and CI assertions are the maintained sources of truth.
- Regression tests lock the post-publish ablation ordering, forbid a silent `continue-on-error` downgrade, enforce raw-snapshot schema 492, and prevent the stale implementation-status file from being reintroduced.

## V4.9.4.3 reconciliation truthfulness and deterministic runtime SLO

- Post-GW starter truth comes only from Official FPL `stats.starts`; minutes are never used to infer whether a player started.
- If Official FPL does not provide starter evidence, `actual_started` remains unknown and that row is excluded from start-probability Brier scoring while remaining eligible for minutes-MAE and p60 evaluation.
- POST-FLIGHT Gate 0 validates the advisory engine plan and the effective user plan separately. Both must be legal, while the effective user plan remains the authoritative personal decision.
- The optimization microservice enforces a hard deterministic decision-compute SLO below 5,000 ms for candidate construction, WC optimization, package audit, lineup optimization, and recommendation sanity.
- External Official/community network latency is measured separately and is explicitly outside the deterministic <5s SLO; the engine does not mislabel variable internet latency as compute performance.
- The eleven process-isolated services, prediction formulas, optimizer search widths, sell-value logic, human-authority semantics, calibration lifecycle, and post-publish ablation architecture remain unchanged.
- Production acceptance on GitHub Actions passed 135 tests, all 11 services, Gate 0 16/16, dual-plan legality, strict ablation, and a 1.71s deterministic decision compute on the merge verification run.

## V4.9.6 architecture consolidation
- 12 process-isolated microservices; Architecture Ownership Guard runs independently and fail-closes duplicate ownership.
- One canonical FPL rules registry (`config/fpl_rules_2026_27.json`).
- One canonical plan-legality primitive (`src/engines/fpl_legality.py`) reused by optimizer/health/postflight.
- Main and recovery schedules call one reusable production workflow.
- Shared DSS evidence is explicitly reused as a primitive rather than recomputed by parallel modules.
- Release metadata is sourced from `config/release_manifest.json` and verified by the architecture guard.


## V4.9.6 GW2 reconciliation readiness closeout

- A thirteenth process-isolated `reconciliation_readiness` service audits the frozen deadline snapshot → Official submitted-picks → finished-GW actuals → immutable reconciliation → calibration-entry chain without performing reconciliation itself.
- The readiness audit is read-only and performs zero Official FPL refetches; Official acquisition remains owned only by `raw_snapshot`.
- Snapshot and reconciliation integrity are reused from the canonical validation-store primitives rather than reimplemented.
- Expected future states are reported as pending (`PREDEADLINE_READY`, `WAITING_SUBMITTED_PICKS`, `WAITING_GW_FINISH`) rather than falsely treated as failures; structural integrity/ownership failures remain fail-closed.
- `READY_TO_RECONCILE` is emitted only when a valid frozen target-GW snapshot and the target GW's Official event-live actuals are simultaneously present; `RECONCILED` requires the immutable reconciliation archive.


## V4.9.6 internal evidence closeout

- DSS-16 Goal Involvement Sustainability is ACTIVE only when production prediction proves raw-vs-shrunk attacking rates, bounded current/last-season weights, and canonical attacking-rate shrinkage provenance.
- DSS-29 Fixture Swing is ACTIVE through a prediction-owned `fixture_run` summary derived from the already canonical Official-FPL fixture-adjustment path; health/reporting do not rescore fixtures.
- Ownership registry explicitly assigns rate-shrinkage sustainability and fixture-run summarization to the prediction model so future services must reuse rather than reimplement them.
- DSS-08 System/Formation Fit and DSS-36 Multi-Season Prior remain PARTIAL until genuinely stronger evidence exists; they are not promoted by proxy.
