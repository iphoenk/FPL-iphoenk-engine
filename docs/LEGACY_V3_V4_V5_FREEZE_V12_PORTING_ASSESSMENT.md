# V3 / V4 / V5 Legacy Freeze + Capability Mining + V12 Porting Assessment

Status: COMPLETE ASSESSMENT / FREEZE GOVERNANCE
Baseline branch: fpl-master-v12-rebuild
Baseline head: b380066d309d1f0f7c647f9579d7de50b0d2d4cd
Program date: 2026-09-19
Scope: inventory + dependency audit + capability mining + V12 backlog only
V6 mutation: NONE
Scheduler mutation: NONE
V7 created: NO
New authority created: NO
Canonical V12 methodology changed by this audit: NO

## 1. Formal freeze declaration

Effective immediately for this repository:

- V3 = FROZEN LEGACY
- V4 = FROZEN LEGACY
- V5 = FROZEN LEGACY

Rules:

- NO NEW FEATURES in V3/V4/V5.
- NO independent methodology evolution in V3/V4/V5.
- NO new production dependency may point from V6 or V12 to V3/V4/V5.
- NO production fallback to V3/V4/V5.
- NO new scheduler may execute V3/V4/V5.
- NO V3/V4/V5 component may be a production authority.
- Legacy bugfix is permitted only for dependency audit, historical evidence recovery, migration-equivalence testing, bounded extraction, or repair of a migration test.
- Useful intelligence may move only forward into V12.
- Nothing from this program is ported into V6.

Historical documents may still contain earlier wording such as ACTIVE production or Production V3. Such wording is historical evidence only and is superseded by this freeze marker and Canonical V12.

## 2. Current architecture retained

V6:
- existing factual production data plane;
- preserved as-is by this program;
- no new features, calculations, metrics, observability, identity, health, freshness, acquisition, normalization, provenance, publisher, report-prefetch or cleanup work was performed.

V12:
- model + decision + optimization + report plane;
- Canonical authority remains control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt;
- useful legacy intelligence may be proposed for V12 only.

V3/V4/V5:
- frozen legacy;
- migration/regression oracle;
- historical reference;
- never a production fallback target.

## 3. Dependency classification summary

A. PRODUCTION_RUNTIME_DEPENDENCY ON V3/V4/V5: ZERO FOUND.

Evidence:
- .github/workflows/fpl-engine.yml is manual forensic-only, explicitly NO_PRODUCTION_PUBLICATION, and has no active schedule/workflow_run.
- repository production-path governance declares v3-runtime.yml, v3-package-precompute.yml, v4-prediction.yml, v4-timing-probe.yml, fpl-engine-recovery.yml and v5-evidence-dispatcher.yml retired and requires them to be absent.
- production-path governance rejects automatic triggers on any v3-/v4-/v5- workflow and rejects runtime-data-v3/v4/v5 publication references.
- current workflow tree contains no v3/v4/v5 production scheduler. Existing V3 workflows are CI/manual acceptance only.
- V6 architecture-independence validation recursively scans src/runtime_v6, config/v6 and all v6-*.yml workflows and fails on runtime_v3/v4/v5 imports or artifact tokens.
- V6 production ingestion targets runtime-data-v6 and is independently governed.

B. BUILD/CI DEPENDENCY:
- .github/workflows/v3-ci.yml runs V3 regression/release-acceptance code on PRs and main pushes outside V6-owned paths.
- .github/workflows/v3-sharded-optimizer-acceptance.yml runs migration/regression-grade exact optimizer acceptance on relevant PR changes.
- .github/workflows/v3-platform-governance.yml is manual governance acceptance.
- repository governance still validates version isolation and V6-only production path.
These are not production engines.

C. TEST-ONLY / CONTRACT DEPENDENCY:
- tests/test_fpl_master_v12_decision_conformance.py imports src.models.xmins_v3.estimate_xmins and src.models.package_optimizer_v2.simulate_objective as regression/contrast evidence.
- src/engines/lineup_governance.py imports legal_squad from src.models.package_optimizer_v2. This is a shared legacy-algorithm code dependency inside repository decision-contract code, not a legacy runtime authority or production fallback. It is a candidate for later V12 re-homing.
- V3 tests and optimizer tests remain useful as migration/regression oracles.

D. HISTORICAL/REFERENCE ONLY:
- MASTER_TASK_LIST_V3.md, V3 docs, V4/V5 donor-adoption docs and IMPLEMENTATION_STATUS.json.
- .github/scripts/v4_precompute_reuse_guard.py, .github/scripts/v4_runtime_watchdog.py and config/runtime/v4_operational_policy.json have no current workflow owner in the branch and are not production scheduled.

E. DEAD/UNREACHABLE RELATIVE TO PRODUCTION:
- V3 operational scheduler path is retired.
- V4/V5 operational workflows are absent.
- V4 watchdog/reuse scripts are not currently connected to a workflow.
- V5 has no runtime tree in this branch.

## 4. V3 exact inventory

### 4.1 Registry-defined V3 service surface

The frozen config/v3_service_registry.json declares architecture V3_BOUNDED_PROCESS_MICROSERVICES with 22 capability/service entries. These services are legacy registry ownership and are not current production runtime authority.

| Component | Exact implementation owner(s) | Category | Purpose | Currently called by | Prod runtime dep | Build/CI dep | Replacement / destination | Action |
|---|---|---|---|---|---|---|---|---|
| official_snapshot | src.engines.official_snapshot_service | DATA-RELATED-LEGACY | Official snapshot | V3 registry/compiler | NO | YES | Existing V6 factual plane | DEPRECATE |
| rules | src.engines.rules_compliance_audit | DECISION | Rules/Gate0 evidence | V3 registry/compiler | NO | YES | V12 Gate0 | TEST_ONLY |
| team_state | src.engines.team_state_service | DATA-RELATED-LEGACY | Team/chip state | V3 registry/compiler | NO | YES | Existing V6 factual personal data | DEPRECATE |
| market_state | src.engines.market_state_service | DATA-RELATED-LEGACY | Price/universe state | V3 registry/compiler | NO | YES | Existing V6 factual market data | DEPRECATE |
| live_state | src.engines.live_state_service | DATA-RELATED-LEGACY | Live state | V3 registry/compiler | NO | YES | Existing V6 factual live data | DEPRECATE |
| advanced_stats | src.engines.advanced_stats_service; src.engines.player_features | MODEL | Feature extraction | V3 registry/compiler | NO | YES | V12 model feature interpretation using V6 facts | MERGE_IDEA_INTO_V12 |
| tactical_context | src.engines.tactical_context_service | MODEL | Tactical/role evidence | V3 registry/compiler | NO | YES | V12 tactical/role component | MERGE_IDEA_INTO_V12 |
| base_snapshot | src.engines.base_snapshot_service | DATA-RELATED-LEGACY | V3 fan-in | V3 registry/compiler | NO | YES | V6 factual publication + V12 consumption | DEPRECATE |
| historical_prior | src.engines.historical_prior_runtime | MODEL | Historical priors | V3 registry/compiler | NO | YES | V12 Bayesian/shrinkage | PORT_TO_V12 |
| source_layer | src.engines.source_layer | DATA-RELATED-LEGACY | Legacy source layer | V3 registry/compiler | NO | YES | Existing V6 source layer | DEPRECATE |
| weather_context | src.engines.weather_context | MODEL | Advisory weather | V3 registry/compiler | NO | YES | V12 contextual interpretation if material | HISTORICAL_REFERENCE |
| price | src.engines.price_service | MODEL | Legacy price prediction/context | V3 registry/compiler | NO | YES | V12 price-risk interpretation from V6 factual observations | MERGE_IDEA_INTO_V12 |
| prediction | src.engines.prediction_service | MODEL | xPts/projection/package generation | V3 registry/compiler | NO | YES | V12 model plane | PORT_TO_V12 selectively |
| authenticated_official | src.engines.authenticated_official | DATA-RELATED-LEGACY | Private Official enrichment | V3 registry/compiler | NO | YES | Existing V6 factual personal acquisition | DEPRECATE |
| official_detail | src.engines.official_expansion; official_player_detail_enrichment; official_history_reconciliation | DATA-RELATED-LEGACY | Official fact expansion/history | V3 registry/compiler | NO | YES | Existing V6 factual plane | DEPRECATE |
| prediction_evaluation | src.engines.prediction_evaluation | TEST | Frozen forecast settlement/calibration | V3 registry/compiler | NO | YES | V12 post-match calibration | PORT_TO_V12 |
| lineup_governance | src.engines.lineup_governance | DECISION | XI/bench/C/VC/package governance | V3 registry/compiler + V12 contract tests | NO proven scheduler runtime | YES | V12 decision plane | KEEP_V12 / re-home shared legacy helpers |
| challenger | src.engines.challenger_scorecard | DECISION | Challenger evidence | V3 registry/compiler | NO | YES | V12 full-universe comparison | MERGE_IDEA_INTO_V12 |
| governance | framework_health_service + overlays | TEST | V3 governance/health | V3 registry/compiler | NO | YES | V12 semantic QA/decision proof | TEST_ONLY |
| watchlist | src.engines.dss_watchlist; watchlist_public_sanitize | REPORT | Legacy watchlist | V3 registry/compiler | NO | YES | V12 full-universe/Watchlist report | TEST_ONLY |
| reporting | report_architecture; report_enrichment; prediction_decision_snapshot | REPORT | Legacy report assembly | V3 registry/compiler | NO | YES | V12 report contracts | TEST_ONLY |
| report_materializer | report_materializer; report_transparency_overlay; report_serving_validate | REPORT | Serving artifacts | V3 registry/compiler | NO | YES | V12 visible report construction/QA | TEST_ONLY |

### 4.2 V3 runtime/control-plane source modules

Frozen runtime tree: src/runtime_v3/

Exact files:
- __init__.py
- artifact_contracts.py
- capability_telemetry.py
- capability_terminology_validate.py
- definition_of_done.py
- domain_orchestrator.py
- domain_process_runner.py
- equivalence_acceptance.py
- execution_profile_resolver.py
- fast_consistency_acceptance.py
- fast_lane_contract_validate.py
- frontier_evidence_contract.py
- full_authority_cache.py
- governance_metadata_validate.py
- incremental_reuse.py
- instant_serving.py
- interactive_slo_contract_validate.py
- main_pr_provenance.py
- measured_command.py
- module_batch_runner.py
- orchestrator.py
- package_optimizer_shards.py
- performance_guard.py
- platform_governance_audit.py
- precompute_checkpoint.py
- precompute_target_execution.py
- publication_verify.py
- publish_snapshot.py
- registry_compiler.py
- release_acceptance.py
- reuse_freshness.py
- rules_drift_refresh.py
- runtime_hydration_guard.py
- shard_policy_validate.py
- sharded_pipeline_resume.py
- sharded_resource_telemetry.py
- unified_fastpath.py
- version_scope_validate.py

Disposition by sub-surface:
- orchestration/runtime/publication/cache/performance: HISTORICAL_REFERENCE or RETIRE_AFTER_PORT;
- sharded package search/exact frontier/equivalence: MIGRATION_ORACLE / REGRESSION_ORACLE;
- governance/acceptance/provenance: TEST_ONLY where still useful;
- no item may regain production runtime authority.

### 4.3 V3 model/decision files with high migration value

- src/models/xmins_v2.py
- src/models/xmins_v3.py
- src/models/projection_components.py
- src/models/package_optimizer_v2.py
- src/models/package_optimizer_exact_batch.py
- src/models/rank_sim.py
- src/models/calibration.py
- src/engines/package_optimizer_exhaustive_accelerated.py
- src/engines/package_optimizer_exhaustive_finalize.py
- src/engines/package_optimizer_frontier_contract.py
- src/engines/tactical_decision_consumption.py
- src/models/tactical_matchup.py
- src/models/tactical_role_context.py
- src/engines/owned_challenger_comparator.py
- src/engines/prediction_evaluation.py
- config/gate0_registry.json
- config/intelligence/xmins_v2.json
- config/intelligence/package_optimizer.json
- config/intelligence/projection.json
- config/intelligence/lineup_governance.json
- config/intelligence/tactical_matchup.json
- config/intelligence/tactical_role_context.json

These files are frozen as legacy/shared migration sources. Their algorithms may be ported cleanly into V12 only after backlog review.

### 4.4 V3 tests and workflows retained for migration/regression

Workflows:
- .github/workflows/v3-ci.yml
- .github/workflows/v3-platform-governance.yml
- .github/workflows/v3-sharded-optimizer-acceptance.yml
- .github/workflows/fpl-engine.yml

Tests with explicit V3/runtime/sharded/package migration relevance:
- tests/test_definition_of_done_v3.py
- tests/test_hidden_gap_closeout_v3.py
- tests/test_model_validation_completeness_v3.py
- tests/test_official_price_predictor_v3.py
- tests/test_package_optimizer_exhaustive_finalize.py
- tests/test_package_optimizer_guardrail_telemetry.py
- tests/test_package_optimizer_hotpath.py
- tests/test_package_optimizer_sharded_equivalence.py
- tests/test_package_optimizer_sharded_runtime.py
- tests/test_runtime_compiled_control_plane.py
- tests/test_runtime_compiled_wave_parallelism.py
- tests/test_runtime_freshness_reuse_guard.py
- tests/test_runtime_hydration_guard.py
- tests/test_runtime_hydration_rerun_attestation.py
- tests/test_runtime_operational_policy.py
- tests/test_runtime_optimization.py
- tests/test_runtime_publication_atomicity.py
- tests/test_runtime_publish_attestation.py
- tests/test_runtime_reuse_contract_migration.py
- tests/test_sharded_late_recovery.py
- tests/test_sharded_pipeline_resume.py
- tests/test_sharded_pipeline_resume_domain_waves.py
- tests/test_sharded_resource_and_policy.py
- tests/test_system_formation_fit_v3.py
- tests/test_user_capture_authority_v3.py

## 5. V4 exact inventory

No src/runtime_v4 tree exists on the audited branch.
No current v4-*.yml workflow exists.

Exact V4 surface found:
- .github/scripts/v4_precompute_reuse_guard.py — UTILITY — exact checkpoint reuse/freshness guard.
- .github/scripts/v4_runtime_watchdog.py — UTILITY — evaluation-only freshness watchdog.
- config/runtime/v4_operational_policy.json — CONFIG — historical V4 runtime branch/ref/checkpoint policy.
- docs/V3_SUB3S_V4_V5_ADOPTION.md — DOCUMENTATION — V4 donor ideas adopted historically into V3.
- docs/V3_V4_OWNED_CHALLENGER_DECISION_ENGINE_EXECUTION.md — DOCUMENTATION — historical V3/V4 comparator integration design.

Current dependency:
- production runtime: NO;
- scheduled workflow: NO;
- test/build use: no active V4 workflow found;
- historical/reference: YES.

Useful V4 ideas:
- hot-orchestrator / reduce process-start overhead;
- preserve capability order and validation while optimizing execution boundary;
- fail closed on architecture/runtime-assurance drift;
- latency targets as release gates.
These are operational/test ideas, not football methodology and not candidates for V6 changes in this program.

Disposition:
- scripts/policy: HISTORICAL_REFERENCE, RETIRE_AFTER_PORT/DELETE_LATER candidate if no migration oracle remains;
- donor ideas: P2/P3 V12 CI/runtime-contract inspiration only.

## 6. V5 exact inventory

No src/runtime_v5 tree exists on the audited branch.
No current v5-*.yml workflow exists.

Exact V5-labeled source found:
- docs/V3_SUB3S_V4_V5_ADOPTION.md.

Useful V5 donor ideas recorded there:
- explicit performance policy registry;
- fail-closed degraded mode for critical failure;
- exact release/source provenance;
- repeated-run performance acceptance;
- rejected historical ideas include static degraded fallback payloads and a microservice transport layer.

Current dependency:
- production runtime: NO;
- scheduled workflow: NO;
- build/test direct dependency: NONE found;
- historical/reference: YES.

Disposition: HISTORICAL_REFERENCE.

## 7. Production dependency graph

Current path:

FPL Master Monitor V12 / Canonical V12
  -> existing V6 factual datasets and authenticated factual scopes
  -> V12 model / decision / optimization / report logic
  -> visible report

V6 production GitHub path:
  v6-natural-data-ingestion.yml
  -> src.runtime_v6.domains.control_plane.*
  -> acquisition / factual processing / publication
  -> runtime-data-v6

Legacy path:
  V3/V4/V5
  -> no automatic production scheduler
  -> no production runtime-data-v3/v4/v5 publication path
  -> CI/manual forensic/migration only

Build/test side path:
  PR/main CI
  -> v3-ci / sharded optimizer acceptance
  -> frozen legacy regression oracles
  -> must not be interpreted as production engine execution.

## 8. V6 read-only dependency findings

No V6 files were modified.

Existing repository validator src/runtime_v6/domains/governance/architecture_independence_validate.py recursively enforces:
- forbidden imports of src.runtime_v3, src.runtime_v4, src.runtime_v5;
- forbidden V3/V4/V5 runtime artifact tokens inside V6 source/config;
- no V6 workflow references to V3/V4/V5 CI or artifact branches;
- no workflow_run cross-engine chaining;
- runtime-data-v6 exact production branch;
- dedicated V6 dependency locks.

Observed V6 internal file src/runtime_v6/domains/control_plane/legacy_scheduler_compat.py is NOT a V3/V4/V5 engine dependency. It is a V6-local historical compatibility helper. runtime_control imports it only to interpret legacy nominal cron evidence and explicitly labels legacy scheduler evidence historical.

Result:
- legacy imports in V6: ZERO found by the existing recursive architecture contract;
- legacy configs referenced by V6: ZERO V3/V4/V5 config/artifact tokens permitted by contract;
- V6 fallback to V3/V4/V5: ZERO allowed;
- V6 workflow calls to legacy engine: ZERO;
- V6 mutation performed by this program: NO.

If a future failing CI run disproves this contract, classify it:
MIGRATION FINDING — SEPARATE BOUNDED REPAIR REQUIRED.
Do not repair V6 inside this legacy-mining program.

## 9. Capability comparison matrix

| Capability | V3 | V4 | V5 | V12 CURRENT | Best legacy idea | V12 gap | ACTION |
|---|---|---|---|---|---|---|---|
| Universe enumeration | Full eligible Official universe; exact exhaustive optimizer can run zero-pruning | no decision engine evidence in branch | none | Canonical full-universe-first invariant | exact denominator + zero-pruning diagnostics | V12-owned executable exhaustive search is not isolated from legacy/shared optimizer code | MERGE_IDEA_INTO_V12 |
| Gate0 | 16 fail-closed checks | none | none | mandatory Gate0 PASS in Canonical V12 | explicit 16-check regression contract | no critical semantic gap proven | KEEP_V12 + TEST_ONLY |
| Squad legality | exact 15/2/5/5/3, max3 club, legal XI/bench | none | none | present in V12 contracts and locked-team logic | deterministic legality oracle | re-home legacy legal_squad helper later | TEST_ONLY |
| xMins | xmins_v2 finite-state mixture + xmins_v3 historical confidence wrapper | none | none | V12 requires full xMins distribution; tests currently exercise legacy implementation | START/CAMEO/LATE_CAMEO/ZERO finite-state mixture with explicit variance | V12 ownership still relies on legacy/shared implementation in tests/contracts | PORT_TO_V12 |
| P(start) | weighted-logit hierarchy with shrinkage | none | none | V12 hierarchy contract exists | conditional-probability hierarchy; bench overlap handled correctly | dedicated V12-owned estimator + calibration lifecycle | PORT_TO_V12 |
| Rotation/cameo/DNP | explicit bench/cameo/late-cameo/DNP states | none | none | V12 state-conditional lineup utility exists | distinguish cameo from DNP; model late cameo | ownership/consolidation gap only | MERGE_IDEA_INTO_V12 |
| Bayesian/shrinkage | neutral/season/historical/role/manager evidence + robust rate shrinkage | none | none | V12 requires lineage and shrinkage | adaptive shrinkage + winsorization + historical prior provenance | no single V12-owned posterior update engine proven | MERGE_IDEA_INTO_V12 |
| Player scoring/xPts | event-component projection model | none | none | exact 20/25/30/25 football score contract + expected-points proof requirement | separate event components from decision score | posterior predictive event engine is not fully isolated as V12-owned implementation | PORT_TO_V12 selectively |
| Fixture adjustment | team expected goals / clean sheet / opponent context | none | none | required by Canonical V12 | bounded attack multiplier + factual fixture context | calibrated V12 opponent-adjustment implementation/provenance | MERGE_IDEA_INTO_V12 |
| Tactical/coach fit | explicit evidence matrix, observed/inferred labels, close-call-only consumption | none | none | tactical/role is 25% canonical component | never infer missing coach/system; expose availability dimensions | convert evidence to canonical component without double counting or fake precision | MERGE_IDEA_INTO_V12 |
| Role/set-piece/penalty | player role profiles + set-piece/penalty fields | none | none | canonical role/set-piece/penalty interpretation required | observed role profiles and return routes | V12-native scoring/uncertainty integration | MERGE_IDEA_INTO_V12 |
| DefCon | Poisson threshold probability from reconstructed per-90 counts | none | none | Canonical V12 requires DefCon interpretation | threshold-event probability rather than flat per90 points | V12-owned calibrated DefCon event component | PORT_TO_V12 |
| Transfer economics | sell price, ITB, package legality, change heuristic | none | none | richer V12 downstream economics + dynamic FT shadow | exact sell-value/ITB legality | legacy change penalty must not migrate as FT value | KEEP_V12 |
| Affordability | exact sell_cost + ITB vs incoming now_cost | none | none | V12 authenticated affordability finalization | deterministic arithmetic oracle | none material | KEEP_V12 + TEST_ONLY |
| FT shadow value | legacy change_penalty=0.2 explicitly non-canonical | none | none | dynamic future-optimization opportunity difference | none superior | execution implementation needs native V12 optimizer | KEEP_V12 |
| Multi-GW horizon | 3/5/10/15 weighted legacy horizons | none | none | 1/3/5, plus 2GW rental/exit | long horizon 10/15 may be background context only | optional long-term structural background | HISTORICAL_REFERENCE |
| One-GW rental | limited next-match comparator context | none | none | explicit V12 rental/exit lifecycle and 2GW economics | none superior | no legacy gap | KEEP_V12 |
| Package optimizer | exact legal 0/1/2 transfer search, batch accelerator, scalar boundary fallback | none | none | V12 owns package optimization conceptually | exhaustive zero-pruning + exact frontier + step-legal transfer recomputation | V12-owned implementation not yet cleanly separated from legacy/shared modules | PORT_TO_V12 |
| XI/formation | enumerates legal formations and selects mean-best; later robust governance | none | none | V12 robustness/cameo/autosub semantics stronger | exact legal enumeration | preserve exhaustive formation enumeration as oracle | MERGE_IDEA_INTO_V12 |
| Bench ordering | risk/start/ceiling scoring | none | none | V12 state-conditional utility + bench display/autosub logic | explicit bench uncertainty features | full distributional bench-order optimizer can be consolidated | MERGE_IDEA_INTO_V12 |
| Captain/vice | risk-adjusted captain score; vice role/set-piece context | none | none | V12 owns C/VC decisions | explicit start/DNP guards + vice contextual tie-break | fully distributional/correlated captain optimizer not isolated | MERGE_IDEA_INTO_V12 |
| Expected regret | realized decision regret in prediction_evaluation | none | none | expected regret required in decision proof | frozen pre-deadline realized regret settlement | connect ex-ante regret estimates to ex-post calibration | MERGE_IDEA_INTO_V12 |
| Robustness | mean - risk*std - costs/cluster penalties | none | none | stronger V12 robustness gate | explicit robust-score decomposition | legacy fixed heuristics should not become canonical | TEST_ONLY |
| Uncertainty/tails | std heuristics + independent Gaussian quantiles | none | none | V12 requires predictive distributions/tails | explicit uncertainty publication | calibrated posterior tails remain implementation gap | MERGE_IDEA_INTO_V12 |
| Correlation | legacy variance mostly independent | none | none | V12 requires covariance/correlation where material | no superior legacy implementation | V12-native covariance model needed | DEPRECATE legacy assumption |
| Monte Carlo | 300 aggregate Gaussian package paths; rank_sim 5000 independent normals | none | none | Canonical V12 rejects this and requires correlated >=500k when executed | deterministic seed/reproducibility only | native correlated event/state MC + CRN | DEPRECATE legacy simulator; PORT only reproducibility idea |
| Efficient frontier | exact skyline from all evaluated legal packages in exhaustive path | none | none | canonical frontier concept exists | frontier is representation, never second scoring authority | clean V12 frontier implementation/provenance | PORT_TO_V12 |
| Price-risk interpretation | predictor trajectory, freshness, ETA governance, no threshold=confirmed change | none | none | V12 price evidence lifecycle and authenticated economics | confirmation only from Official cost reconciliation | integrate risk as evidence, not football score | MERGE_IDEA_INTO_V12 |
| Mini-league/EO overlay | mini-league tracking + deferred/conditional strategy state | none | none | V12 exact exposure denominator logic exists | explicit denominator and exposure counts | decision overlay should remain downstream of football-optimal baseline and be formalized | MERGE_IDEA_INTO_V12 |
| Scenario lifecycle | limited historical decision snapshots | none | none | V12 CONTEMPLATED/EXECUTED/EXPIRED lifecycle is stronger | frozen pre-deadline snapshot concept | no legacy superiority | KEEP_V12 |
| Post-match learning | prediction ledger settles finished GWs | none | none | POST_ALL_MATCH contract and learning log exist | immutable pre-deadline freeze before settlement | connect settlement metrics to V12 calibration updates | PORT_TO_V12 |
| Calibration | MAE/RMSE/xMins MAE/Brier/Spearman + position drift | none | none | V12 requires Bayesian/calibration discipline | genuine pre-deadline forecast only, no retroactive rewrite | consolidated V12 calibration service/ledger | PORT_TO_V12 |
| Reporting/QA | user report, technical appendix, materializer, fail-closed completeness | none | none | V12 content contracts/visible QA are stronger | artifact completeness and factual/model separation tests | retain selective regression oracles | TEST_ONLY |
| Auditability | exact provenance, artifact contracts, exhaustive-search diagnostics | exact checkpoint reuse/freshness evidence | exact provenance/repeated acceptance principle | V12 decision proof/execution provenance | truthful FULL/PARTIAL search authority; exact denominator diagnostics | carry exact optimizer diagnostics into V12 native modules | MERGE_IDEA_INTO_V12 |

## 10. Mathematical audit of valuable legacy components

### 10.1 xMins / P(start)

Core implementation: src/models/xmins_v2.py.

Start-rate evidence:
- neutral prior default 0.72;
- season observed start rate = starts / matches;
- season rate shrunk toward neutral prior with default shrinkage equivalent of 4 matches.

Conditional start probability:
- evidence signals are combined in logit space:
  raw P(start | available) = sigmoid( sum(w_i * logit(p_i)) / sum(w_i) ).
- configured default signal weights:
  neutral prior 0.8;
  season start rate 1.4;
  historical prior start probability 1.2;
  role start probability 1.1;
  manager start probability 1.3.

Availability is separated from start selection.

Hierarchical appearance states:
- P(start) = P(available) * P(start | available).
- P(bench) = P(available) * (1 - P(start | available)) * P(bench | available, not start).
- P(cameo) = P(bench) * P(cameo | bench).
- P(late cameo) = P(cameo) * P(late cameo | cameo).
- P(DNP) = P(unavailable) + P(bench)*P(no appearance | bench) + P(available, not start, not benched).
- START + CAMEO + DNP are mutually exclusive; BENCH is an overlapping roster state and must not be flat-normalized together with them.

Configured defaults:
- bench share when not starting = 0.65;
- cameo probability when benched = 0.72;
- late-cameo share of cameos = 0.35;
- fallback starter minutes 72;
- fallback cameo minutes 18;
- fallback late cameo minutes 8.

Minutes:
- observed starter minutes are shrunk toward fallback starter minutes with 4-start prior;
- finite states: START, CAMEO, LATE_CAMEO, ZERO_MINUTES;
- mixture mean uses weighted state means;
- mixture variance uses law of total variance;
- additional calibration variance is added for entropy and small samples;
- default state standard deviations: starter 10, cameo 7, late cameo 4;
- small-sample uncertainty widens probability/minutes intervals.

xmins_v3 does not replace the finite-state estimator. It wraps xmins_v2 and upgrades confidence from historical evidence:
- MEDIUM prior threshold default 900 evidence minutes;
- HIGH prior threshold default 1800 evidence minutes plus current-start evidence;
- historical prior remains shrinkage evidence, never authority over current Official availability.

Assessment:
- useful and mathematically coherent;
- already aligned with V12 probability semantics;
- should be re-homed into a V12-owned implementation rather than invoked through a legacy-named wrapper.

### 10.2 Robust attacking-rate shrinkage

src/models/projection_components.py:
- observed per-90 rate is shrunk toward positional prior;
- adaptive tiers increase/decrease shrinkage by evidence minutes;
- small samples are winsorized with a prior-multiple upper bound;
- configured tiers:
  <=90 min: shrink 900 min, cap 2.5x prior;
  <=270: 675, 3.5x;
  <=450: 525, 4.5x;
  >450: 450, 6x.
- breakout protection relaxes the upper cap as evidence accumulates.

Assessment:
- useful for V12 Bayesian/shrinkage layer;
- should not be copied as an unexamined universal prior; calibration should remain position/event specific.

### 10.3 DefCon event model

Legacy projection component reconstructs a defensive-contribution count rate and uses a Poisson tail:
- prior event probability is translated into an implied Poisson count rate;
- observed reconstructed count/90 is shrunk toward the prior count rate;
- expected DefCon points = points_value * P(Poisson(lambda_minutes) >= threshold).

Assessment:
- superior to treating DefCon as a guaranteed floor;
- candidate V12 event component with calibration tests.

### 10.4 Legacy xPts

Legacy per-fixture expected points decomposes:
- appearance;
- attack from xG90/xA90 scaled by expected minutes and team attack multiplier;
- clean-sheet probability conditional on 60-minute likelihood;
- saves for goalkeepers;
- DefCon threshold probability;
- bonus proxy.

Uncertainty:
- minimum points std;
- coefficient-of-variation term;
- xMins uncertainty contribution;
- small-sample extra std.

Assessment:
- useful decomposition and provenance;
- not sufficient by itself for Canonical V12 posterior predictive tails;
- port component ideas, not the legacy score as authority.

### 10.5 Package optimizer

Legacy package objective uses horizons 3/5/10/15 with weights:
- 3GW 0.42;
- 5GW 0.33;
- 10GW 0.15;
- 15GW 0.10.

Per horizon it:
- enumerates legal formations;
- selects best XI by projected mean;
- adds bench utility with weight 0.10;
- adds captain bonus with weight 1.0;
- accumulates independent variance.

Robust objective:
- weighted objective mean
- minus risk_aversion * objective_std, default risk aversion 0.12
- minus change penalty 0.20 points per change
- minus team-cluster penalty, default 0.05 per player beyond 2 from a club.

Important governance:
- legacy change penalty is explicitly NOT FT shadow value;
- V12 canonical FT shadow = best future utility with FT - best future utility with FT consumed.

Exhaustive accelerated path:
- complete eligible Official FPL universe;
- zero candidate pruning;
- structural prefilters only for provably illegal cash/club cases;
- sequential transfer legality recomputed;
- every step-legal single/pair package exactly scored;
- vectorized batch kernel with scalar fallback near numerical boundaries;
- top packages are canonical-scalar rehydrated;
- efficient frontier is built from all evaluated legal packages and is never a second scoring authority;
- search authority is FULL only when all step-legal packages are scored.

Assessment:
- this is the strongest legacy migration candidate;
- port exact search, legality, numerical-fallback and search-authority semantics into V12;
- do not carry the old horizon weights/change penalty as canonical V12 methodology.

### 10.6 Legacy Monte Carlo

package_optimizer_v2.simulate_objective:
- independent Gaussian aggregate;
- configured 300 paths;
- deterministic seed;
- reports p25/p50/p75.

rank_sim:
- independent Normal per player;
- default 5000 simulations;
- sd heuristic max(1.2, 0.75*mean + 0.8);
- reports p10/p50/p90.

Canonical V12 explicitly rejects this as canonical MC because it does not sample correlated availability/start/cameo/DNP/minutes/scoring/shared-match states.

Assessment:
- do not port the stochastic assumptions;
- retain deterministic seed/reproducibility ideas only;
- V12 correlated path engine remains separate backlog.

### 10.7 Calibration / realized regret

prediction_evaluation:
- freezes genuine pre-deadline forecasts;
- settles only finished events;
- post-deadline information cannot rewrite frozen forecasts;
- metrics: points MAE/RMSE, xMins MAE, starter Brier, DNP Brier, clean-sheet Brier, Spearman;
- decision outcome metrics: captain regret, vice regret, XI regret, first-bench regret, transfer comparator realized net gain;
- transfer net gain requires exact hit cost; optimizer change penalty may not substitute for FPL hit cost;
- position drift is diagnostic only and may not change weights automatically.

Assessment:
- high-value V12 post-match/calibration source;
- port settlement discipline and metrics, not V3 authority.

### 10.8 Tactical/role model

Legacy tactical model:
- distinguishes OBSERVED_ROLE / INFERRED_ROLE / FPL_POSITION_ONLY / UNKNOWN;
- explicitly refuses to claim FPL position shape as true tactical formation;
- missing coach/system evidence remains unavailable rather than invented;
- captures opponent coach, formation/variants, build-up, pressing, defensive line, width, transition, set pieces, strengths/vulnerabilities and observed style proxies;
- tactical decision consumption historically acted as a close-call tie-break and did not directly mutate xPts.

Assessment:
- evidence discipline is valuable;
- V12 must map tactical evidence into the canonical 25% tactical/role component with explicit provenance and double-count controls;
- do not copy legacy fixed close-call thresholds as decision authority.

## 11. Valuable legacy ideas to retain

1. Exact full-universe denominator and truthful FULL/PARTIAL search authority.
2. Exhaustive legal package search with zero-pruning final authority.
3. Vectorized accelerator as execution-only, with canonical scalar fallback at numerical boundaries.
4. Efficient frontier as representation, never a second scoring authority.
5. Finite-state xMins with explicit conditional probability hierarchy.
6. Cameo and late-cameo separation from DNP.
7. Adaptive shrinkage/winsorization for early-season event rates.
8. Poisson threshold treatment for DefCon.
9. Frozen pre-deadline prediction ledger and no retroactive forecast rewriting.
10. Brier/MAE/RMSE/Spearman + realized decision-regret settlement.
11. Tactical evidence availability labels and no invented coach/formation facts.
12. Official-price confirmation distinct from predictor threshold/ETA.
13. Exact provenance and deterministic regression oracles.
14. V4/V5 fail-closed/equivalence/repeated-run acceptance principles.

## 12. V12 gaps discovered

No evidence justifies declaring an entire legacy version better than V12.

Proven gaps are capability/ownership-specific:

- V12 contracts are stronger than legacy in methodology separation, dynamic FT shadow, rental lifecycle, scenario lifecycle, robustness semantics and MC truthfulness.
- Some of the strongest executable implementations are still legacy/shared modules rather than clearly V12-owned modules.
- V12 lacks a cleanly isolated native exhaustive package optimizer despite having canonical full-universe requirements.
- xMins/P(start) implementation is mathematically useful but still exposed through legacy/shared xmins modules and tests.
- canonical correlated >=500k Monte Carlo has a validation contract but no dedicated implementation file was found; current legacy MC is intentionally non-canonical.
- V12 has covariance/correlation requirements but no superior legacy covariance implementation to port.
- post-match calibration/report contracts exist, but the strongest settlement ledger remains the legacy prediction_evaluation implementation.
- tactical evidence is rich in legacy, but its mapping into the exact V12 25% tactical/role component needs explicit calibrated V12 ownership.
- mini-league factual exposure is strong; the downstream decision overlay should be formalized without overriding football-optimal baseline.
- long-horizon 10/15GW logic is useful only as optional structural background and must not replace V12 1/2/3/5GW decision horizons.

## 13. Prioritized V12 backlog

### P0

No P0 capability is proven missing in a way that requires immediate methodology mutation. Canonical V12 already specifies the critical contracts. The main deficits are implementation ownership, calibration and decision-quality refinement. Do not manufacture a P0 merely because legacy code exists.

### P1 — measurable decision-quality / canonical implementation

P1.1 V12-owned xMins / P(start) finite-state engine
- legacy_source: src/models/xmins_v2.py + xmins_v3.py + config/intelligence/xmins_v2.json
- useful idea: weighted-logit conditional start hierarchy + START/CAMEO/LATE_CAMEO/ZERO mixture + uncertainty
- current V12: canonical probability/xMins contract exists; V12 tests use legacy wrapper
- gap: implementation ownership and calibration lifecycle
- proposed destination: src/engines or src/models V12-owned probability/minutes module
- required existing V6 inputs: Official availability/status, starts/minutes/history, factual role/manager evidence where available
- math: preserve conditional hierarchy and state-mixture formulas; calibrate weights from settled data
- tests: golden behavior, probability normalization, calibration, small-sample, injury/unknown evidence
- benefit: consistent lineup/bench/transfer probability basis
- risk: MEDIUM, because re-homing can silently alter numerical behavior.

P1.2 V12-owned exhaustive package optimizer + frontier
- legacy_source: package_optimizer_v2, package_optimizer_exact_batch, package_optimizer_exhaustive_accelerated, runtime_v3 package sharding
- useful idea: zero-pruning full universe, exact legality, batch accelerator, scalar boundary fallback, exact skyline
- current V12: conceptual ownership and proof contract, but implementation is legacy/shared
- proposed destination: V12 optimizer module, no runtime_v3 import
- required V6 inputs: factual squad, prices/sell value/ITB, eligibility, club/position, fixtures/player factual features
- math: retain search completeness and exact legality; replace legacy horizon/change heuristics with Canonical V12 utility/economics
- tests: legacy equivalence on search coverage and legality; new V12 utility golden tests
- benefit: full-universe decisions without legacy execution dependency
- risk: HIGH due search-space/performance/numerical equivalence.

P1.3 V12 posterior predictive event model
- legacy_source: projection_components.py, robust rate shrinkage, DefCon Poisson tail
- current V12: 20/25/30/25 + required expected-points distribution
- gap: V12-owned event posterior/predictive implementation
- destination: V12 model layer
- existing V6 inputs: factual xG/xA/shots/role/fixtures/DefCon observations and provenance
- math: hierarchical shrinkage, event distributions, opponent adjustment, mixture over minutes states
- tests: calibration, posterior predictive coverage, no double-counting, event decomposition
- benefit: more rigorous xPts and uncertainty
- risk: MEDIUM-HIGH.

P1.4 Correlated Monte Carlo + common random numbers
- legacy_source: deterministic seeding concept only; legacy Gaussian simulator explicitly rejected
- current V12: provenance validator requires correlated >=500k paths
- gap: executable correlated path engine
- destination: V12 simulation module
- V6 inputs: factual fixtures, teams, availability facts, current factual distributions inputs
- math: sample shared match/team factors, player availability/start/cameo/minutes/event outcomes; paired routes use common random numbers
- tests: seed reproducibility, convergence, correlation recovery, paired variance reduction, >=500k actual paths when executed
- benefit: reliable close-route P(outperform), tails and package covariance
- risk: HIGH computational/calibration risk.

P1.5 V12 post-match calibration ledger
- legacy_source: prediction_evaluation.py + calibration.py
- current V12: POST_ALL_MATCH report/learning contract
- gap: one native ledger binding pre-deadline predictions to settled outcomes and Bayesian updates
- destination: V12 calibration/learning module
- V6 inputs: finished-GW actual factual data and stored pre-deadline decision proof
- tests: no retroactive mutation, Brier/MAE/regret settlement, sample-size gates
- benefit: converts outcomes into calibration rather than hindsight rules
- risk: MEDIUM.

P1.6 Tactical/role evidence to canonical 25% component
- legacy_source: tactical_matchup.py, tactical_role_context.py, tactical_decision_consumption.py
- current V12: exact 25% tactical/role component required
- gap: calibrated mapping from evidence states to component score with double-count control
- destination: V12 tactical/role scorer
- V6 inputs: factual provider/Official tactical/role observations already available
- tests: unavailable stays unavailable; no invented formation; no direct duplication of underlying xG evidence
- benefit: disciplined coach/system/opponent-channel contribution
- risk: MEDIUM.

P1.7 Distributional captain/bench optimization
- legacy_source: p1_decision_governance + lineup_governance captain/bench heuristics
- current V12: robust lineup contract and state-conditional autosub value
- gap: unified distributional C/VC and bench-order objective using covariance/availability
- destination: V12 lineup optimizer
- tests: DNP vs cameo, vice fallback, bench-order legality, correlated captain upside/downside
- benefit: fewer mean-only lineup mistakes
- risk: MEDIUM.

P1.8 Mini-league decision overlay
- legacy_source: V3 mini-league tracking + current V12 exact exposure denominator
- current V12: overlay allowed only after football-optimal baseline
- gap: explicit leverage utility with complete/partial denominator discipline
- destination: V12 decision overlay
- V6 inputs: factual mini-league picks/ownership/captaincy
- tests: partial coverage cannot masquerade as full league; overlay never changes Gate0 or raw football score
- benefit: controlled relative-risk decisions
- risk: MEDIUM.

### P2 — robustness / tests / auditability

P2.1 Convert legacy exact package and xMins tests into explicit V12 migration oracles.
P2.2 Add a non-production legacy freeze governance check that rejects new V3/V4/V5 features/schedulers/dependencies while allowing approved migration-test edits.
P2.3 Preserve FULL/PARTIAL search-authority and exhaustive denominator diagnostics in V12 decision proof.
P2.4 Re-home shared helpers such as legal_squad so V12 tests/contracts no longer import legacy algorithm modules.
P2.5 Retain provenance/equivalence concepts from V4/V5 as CI-only controls.
P2.6 Retire misleading historical documentation wording only where needed for discoverability; preserve git history.

### P3 — optional/historical sophistication

P3.1 Keep 10/15GW horizon as optional structural context, never canonical substitute for 1/2/3/5GW.
P3.2 Preserve V4 hot-orchestrator and V5 repeated-performance ideas only if a future V12 implementation has measured latency need.
P3.3 Preserve legacy rank simulation as historical baseline only; do not expose it as canonical probability.

## 14. Legacy test/CI retention plan

| Surface | Classification | Retain now? | Retirement criterion |
|---|---|---|---|
| v3-ci.yml | KEEP_TEMPORARILY | YES | retire/split after all needed legacy regression oracles are moved to version-neutral/V12 tests and no freeze-governance check depends on V3 CI |
| v3-sharded-optimizer-acceptance.yml | MIGRATION_ORACLE | YES | retire after V12 native optimizer proves exact legal-search equivalence, frontier equivalence and performance on production-scale fixtures |
| v3-platform-governance.yml | OBSOLETE / HISTORICAL GOVERNANCE | TEMPORARY | retire when no V3 platform setting is relied upon for migration evidence |
| fpl-engine.yml | HISTORICAL_REFERENCE | TEMPORARY | retire when forensic workflow marker is no longer needed by production-path governance tests |
| explicit V3 tests | REGRESSION_ORACLE / RETIRE_AFTER_PORT | YES selective | retire test-by-test when equivalent V12/version-neutral contract exists |
| sharded/runtime optimizer tests | MIGRATION_ORACLE | YES | retire after V12 exact optimizer has equivalent coverage and no runtime_v3 dependency |
| old runtime/publication tests | DUPLICATE or HISTORICAL depending contract | selective | retain only unique invariants not already guaranteed by V6/V12 |
| V4 scripts/policy | HISTORICAL_REFERENCE | NO active execution | delete later only after no migration evidence/test references them |
| V5 donor doc | HISTORICAL_REFERENCE | YES | keep as history unless repository archival policy removes redundant docs |

Explicit invariant:
LEGACY TEST HARNESS != PRODUCTION ENGINE.

## 15. Deprecation candidates

Do not delete in this program.

- src/runtime_v3/ as runtime authority.
- config/v3_service_registry.json and config/v3_architecture_ownership_registry.json as production authority.
- V3 production wording in historical docs.
- src/models/xmins_v3.py after V12 xMins re-home.
- legacy independent Gaussian MC as decision authority.
- legacy 0.2 change penalty as any representation of FT shadow value.
- V4 runtime watchdog/reuse utilities as operational components.
- V4 operational policy as live configuration.
- V3 platform governance workflow after migration need ends.

## 16. Deletion candidates — DO NOT DELETE

Candidate only after proof of unreachability, no test/history requirement and migration completion:

- .github/scripts/v4_precompute_reuse_guard.py
- .github/scripts/v4_runtime_watchdog.py
- config/runtime/v4_operational_policy.json
- .github/workflows/v3-platform-governance.yml
- .github/workflows/fpl-engine.yml
- individual src/runtime_v3 modules after all migration oracles are replaced
- duplicate legacy tests after equivalent V12/version-neutral tests exist
- xmins_v3 wrapper after V12-native implementation and golden equivalence
- legacy MC helpers after all contrast/regression tests are replaced.

Historical documentation should normally remain rather than be deleted unless repository archival policy explicitly permits removal.

## 17. Acceptance

1. V3/V4/V5 formally FROZEN: PASS.
2. Legacy inventory complete at runtime/service/workflow/test/model surface: PASS.
3. Production dependency graph: PASS.
4. Production fallback inventory: PASS, zero active fallback found.
5. Useful capabilities catalogued: PASS.
6. Every major capability has disposition: PASS.
7. V12 gaps documented: PASS.
8. V12 backlog produced: PASS.
9. Legacy CI/tests classified: PASS.
10. Deprecation/removal candidates documented: PASS.
11. V6 unchanged by this program: PASS.
12. Scheduler unchanged: PASS.
13. No V7: PASS.
14. No new production authority: PASS.
15. No Canonical V12 methodology change from audit alone: PASS.

V6 MODIFIED = NO

STOP CONDITION MET:
Freeze + inventory + dependency audit + capability mining + V12 backlog only.
No mass port performed.
