# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE
Canonical roadmap owner: V3 operational stream
Current production release: V3.20.1
Current production schema: 48
Production acceptance: COMPLETE on 27 August 2026

This file is the single human-readable master roadmap for the V3 operational engine. Every V3 feature, refactor, hardening change, operational improvement, and release-governance change must update this file in the same pull request.

## Status legend
- DONE: implemented, tested, merged, and production-validated when runtime-impacting.
- ACTIVE: continuously enforced operational requirement or release candidate under acceptance.
- NEXT: highest-priority planned work.
- OPEN: planned but not the immediate next release.
- BLOCKED: cannot progress until a named dependency is resolved.
- DEFERRED: intentionally postponed.
- MONITOR: implemented but requires ongoing runtime observation/calibration.

## Non-negotiable V3 invariants
1. Official FPL remains the only native authority for Official fields and scoring.
2. Challenger, enrichment, report-time expert and community sources may never overwrite Official-native truth.
3. Missing external evidence is never fabricated. Safe fallback/unavailable/stale states must be explicit.
4. Operational squad contract is exactly 15 OWNED players.
5. External WATCHLIST is exactly 20 players total, maximum 5 per position, with no OWNED overlap.
6. Gate 0 must remain 16/16 PASS for unqualified GO.
7. DSS Core must remain 50/50 ACTIVE, DSS Extensions 16/16 ACTIVE, and Enhancement Layers 8/8 ACTIVE.
8. Mutable runtime values belong in config/registry/environment ownership, not scattered hardcoded literals.
9. Release metadata must remain consistent across source, README, implementation status, workflow naming, schema metadata, registries and tests.
10. User-facing reports must never expose raw internal shorthand or falsely imply that reachability equals data availability or that a source was checked when it was not.
11. V3 production remains stable while new work is developed on separate branches and merged only after full acceptance.
12. Microservice boundaries are coarse-grained and evidence-driven. New process boundaries must reduce coupling, duplicate I/O, unclear artifact ownership, or failure blast radius; file size alone is not a reason to split a service.
13. Pundit consensus is advisory only. Consensus may challenge DSS, but may not silently mutate DSS.
14. Community sentiment is a lead, not a fact. Fact promotion requires authoritative or independent corroboration.
15. Fixture-strategy expertise is separate from player-projection voting.
16. Standard Official public fetches have one runtime owner; downstream services consume promoted artifacts instead of independently refetching the same baseline.
17. Active evidence paths must not pin a fixed Gameweek when the evidence is intended to represent the current Gameweek.
18. Compatibility facades and historical version-stamped modules may exist only outside the active production service registry.
19. Runtime data publishes to `runtime-data`, never directly to protected `main`.
20. An architecture refactor is not accepted if it creates unnecessary process boundaries without a clear data owner or operational benefit.
21. Numerical projection/scoring formulas that affect decisions require deterministic unit regressions, not only end-to-end health checks.
22. External-source unavailability and internal artifact-integrity failure are separate failure classes; fail-soft source policy must not conceal broken internal computation or stale evidence.

## A. Production baseline and keep-green work
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-OPS-001 | Gate 0 hard constraints | DONE | V3.17 | 16/16 PASS in production postflight |
| V3-OPS-002 | DSS Core operational health | DONE | V3.17 | 50/50 ACTIVE with runtime evidence |
| V3-OPS-003 | DSS Extension operational health | DONE | V3.17 | 16/16 ACTIVE with runtime evidence |
| V3-OPS-004 | Enhancement Layer operational health | DONE | V3.17 | 8/8 ACTIVE with runtime evidence |
| V3-OPS-005 | 15 OWNED + 20 WATCHLIST contract | ACTIVE | Continuous | exactly 15 owned, 20 external watchlist, max 5/position, no overlap |
| V3-OPS-006 | Official FPL authority and fail-soft external-source policy | ACTIVE | Continuous | no external source overrides Official-native fields |
| V3-OPS-007 | Runtime publication to isolated `runtime-data` | ACTIVE | Continuous | validated artifacts publish successfully without protected-main writes |
| V3-OPS-008 | Bounded microservice runtime performance | MONITOR | Continuous | runtime stays within configured production budget |
| V3-OPS-009 | Configuration ownership / anti-hardcode discipline | ACTIVE | Continuous | mutable settings live in config/registry/env and CI catches known regressions |
| V3-OPS-010 | Release/version/README consistency | ACTIVE | Continuous | metadata consistency tests pass on every release |
| V3-OPS-011 | Rules Registry integrity and drift review | ACTIVE | Continuous | active ruleset valid; drift never auto-mutates authority |
| V3-OPS-012 | Authenticated Official read-only precision layer | MONITOR | Continuous | optional, read-only, fail-soft, no credential/raw-private persistence |

## B. V3.18 Structured Challenger Ingestion
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-SRC-101 | Normalized challenger observation contract | DONE | V3.18.0 | typed observation with provenance/freshness/status |
| V3-SRC-102 | Separate reachability from capability-data health | DONE | V3.18.0 | source may be LIVE while capability unavailable/stale/error |
| V3-SRC-103 | LiveFPL structured ingestion framework | DONE | V3.18.0 | no invented EO/price/rank values |
| V3-SRC-104 | OneFPL structured-ingestion framework | DONE | V3.18.0 | parser/fail-soft contract exists; only actual values accepted |
| V3-SRC-105 | Provenance and observation timestamps | DONE | V3.18.0 | accepted observations traceable |
| V3-SRC-106 | TTL, stale cache, last-known-good policy | DONE | V3.18.0 | stale never silently current |
| V3-SRC-107 | Confidence and cross-source disagreement | DONE | V3.18.0 | disagreements explicit |
| V3-SRC-108 | Price Radar challenger context | DONE | V3.18.0 | context-only, Official fields preserved |
| V3-SRC-109 | User-facing source availability rendering | DONE | V3.18.0 | reachability distinguished from data availability |
| V3-SRC-110 | Challenger failure isolation | DONE | V3.18.0 | optional outage cannot block baseline |
| V3-SRC-111 | No-fabrication regression | DONE | V3.18.0 | missing stays missing |
| V3-SRC-112 | Official precedence regression | DONE | V3.18.0 | challenger cannot override Official-native field |
| V3-SRC-113 | Structured-ingestion performance budget | DONE | V3.18.0 | bounded within production budget |
| V3-SRC-114 | Parser/contract drift handling | DONE | V3.18.0 | unexpected shape degrades safely |
| V3-SRC-115 | V3.18 release governance | DONE | V3.18.0 | release surfaces + production collect consistent |
| V3-SRC-116 | OneFPL automated-access reliability diagnosis | DONE | V3.18.1 | production confirmed explicit HTTP restriction state without spoofing/fabrication |

## C. V3.19 Report-Time Intelligence
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-RTI-101 | Dedicated report-time source registry | DONE | V3.19.0 | source classes/domains/query intents/freshness/authority ceilings registry-owned |
| V3-RTI-102 | OneFPL collector-to-report-time delegation | DONE | V3.19.0 | machine registry disabled; report-time registry enabled; no collector HTTP attempts |
| V3-RTI-103 | Report-time evidence contract | DONE | V3.19.0 | source/class/topic/subject/stance/time/URL/summary required |
| V3-RTI-104 | Pundit consensus engine | DONE | V3.19.0 | current opinions aggregated only from eligible pundit class |
| V3-RTI-105 | Pundit consensus vs DSS comparison | DONE | V3.19.0 | explicit ALIGN/DIVERGE/REVIEW_DIVERGENCE/NEUTRAL; DSS not mutated |
| V3-RTI-106 | Ben Crellin fixture-strategy class | DONE | V3.19.0 | BGW/DGW/rearrangement/chip-window context; no player-projection vote |
| V3-RTI-107 | Reddit r/FantasyPL community-signal class | DONE | V3.19.0 | community observations are cross-check-required leads |
| V3-RTI-108 | Verified-news class | DONE | V3.19.0 | official availability/suspension/fixture/manager context may corroborate facts |
| V3-RTI-109 | Report-time freshness governance | DONE | V3.19.0 | stale evidence visible but excluded from current consensus |
| V3-RTI-110 | Report serving integration | DONE | V3.19.0 | user_report, decision_brief and deep_review contain report-time intelligence |
| V3-RTI-111 | Explicit refresh-required state | DONE | V3.19.0 | collector snapshot says REFRESH_REQUIRED when no report-time web pass occurred |
| V3-RTI-112 | Machine-cache ownership cleanup | DONE | V3.19.0 | delegated OneFPL LKG/stale observations purged from collector-owned artifacts |
| V3-RTI-113 | Report-time contract validator | DONE | V3.19.0 | CI/integration validates advisory-source governance |
| V3-RTI-114 | Schema/serving contract v2 | DONE | V3.19.0 | schema48, REPORT_ARTIFACT_REGISTRY_V2, DEEP_REVIEW_PAYLOAD_V2 |
| V3-RTI-115 | V3.19 release governance | DONE | V3.19.0 | version/README/task/workflow/tests/CI/production consistent |

V3.19.0 production acceptance completed on 27 August 2026. PR #32 merged as `4b5f5f72146400a25c956e7628105b7680effe84`; production collector and runtime-data publication passed; framework GREEN/HEALTHY/GO; Gate0 16/16, Core50, Extensions16, Enhancements8.

## D. V3.20 Architecture Hardening
Release objective: eliminate remaining active monolithic runtime ownership and duplicate mutable policy while preserving the serving schema and avoiding unnecessary microservice fragmentation.

| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-ARCH-201 | Canonical Source Registry V3 | DONE | V3.20.0 | network locations, source season/files/timeouts have one registry owner |
| V3-ARCH-202 | Remove legacy `config/sources.json` | DONE | V3.20.0 | file absent and CI prevents reintroduction |
| V3-ARCH-203 | Registry-owned collector cadence/window policy | DONE | V3.20.0 | timezone, primary/adaptive/deep cron, deadline/match windows and probe timeout config-owned |
| V3-ARCH-204 | Dynamic Official User-Agent/version | DONE | V3.20.0 | no stale release string in active Official/collector HTTP path |
| V3-ARCH-205 | Replace monolithic collector service | DONE | V3.20.0 | no active `collector` service and no active `src.engine` command |
| V3-ARCH-206 | Official snapshot single owner | DONE | V3.20.0 | standard Official baseline fetched once, downstream consumes snapshot artifact |
| V3-ARCH-207 | Team-state service boundary | DONE | V3.20.0 | squad identity/finance/chips owned by team_state service |
| V3-ARCH-208 | Market-state service boundary | DONE | V3.20.0 | universe/current price cache/market pressure owned by market_state |
| V3-ARCH-209 | Live-state service boundary | DONE | V3.20.0 | personalized live scoring artifact owned by live_state |
| V3-ARCH-210 | Advanced-stats service boundary | DONE | V3.20.0 | current enrichment aliases and optional deep sync have one owner |
| V3-ARCH-211 | Base snapshot deterministic fan-in | DONE | V3.20.0 | latest/native/history snapshot assembled without network/business-decision duplication |
| V3-ARCH-212 | Generic root DAG scheduling | DONE | V3.20.0 | orchestrator has no collector-name special case and validates cycles/dependencies |
| V3-ARCH-213 | Current advanced-stat aliases | DONE | V3.20.0 | active source/DSS paths use `shots_current`/`playermatchstats_current`, GW files archive only |
| V3-ARCH-214 | Semantic model IDs | DONE | V3.20.0 | active model identity is independent of engine-release number |
| V3-ARCH-215 | Deep-stats runtime-data publication | DONE | V3.20.0 | legacy workflow removed, deep sync uses production workflow and runtime-data |
| V3-ARCH-216 | Architecture anti-regression gate | DONE | V3.20.0 | CI rejects monolithic collector, duplicate source config, fixed-GW current pins, inline code and active version-stamped services |
| V3-ARCH-217 | Framework mutable-policy ownership audit | DONE | V3.20.0 | active expected counts come from registries and active freshness policy is config-owned or explicitly compatibility-only |
| V3-ARCH-218 | Microservice over-splitting review | DONE | V3.20.0 | existing DSS/report/governance services stay grouped unless a clear owner/failure boundary justifies split |
| V3-ARCH-219 | V3.20 release metadata consistency | DONE | V3.20.0 | version 3.20.0/schema48 consistent across source, README, workflow, implementation, tests and roadmap |
| V3-ARCH-220 | Full CI/integration acceptance | DONE | V3.20.0 | compile, unit, architecture, source, production, watchlist, report, report-time and runtime-budget gates PASS |
| V3-ARCH-221 | Production acceptance | DONE | V3.20.0 | merge/push/runtime-data publication and GREEN/HEALTHY/GO evidence verified before DONE |

### V3.20 boundary decision
The base collector was split because it owned unrelated network, squad/finance, market, live, statistics and snapshot responsibilities. The existing price, prediction, lineup, governance, watchlist, reporting and report-materializer services remain coarse-grained because their internal stages share one decision/artifact owner. They must not be split further solely to reduce file size.

### V3.20 schema decision
Engine version changes to `3.20.0`. Serving schema remains `48` because `decision_brief`, `deep_review_payload`, report-time intelligence and the 15+20 user contract do not change. Service Registry schema changes independently to `11`; Source Registry changes independently to `SOURCE_REGISTRY_V3`.

### V3.20 production acceptance evidence
Production acceptance completed on 27 August 2026. PR #34 merged to `main` as `edeaff7a5b1f8173392cb528f93e132836608ed5`. Production push run `33032958368` passed and published validated artifacts to `runtime-data`. Runtime evidence confirms engine `3.20.0` / schema `48`, overall GREEN, decision engine HEALTHY, recommendation allowed, GO allowed, Gate0 16/16 PASS, Core 50/50 ACTIVE, Extensions 16/16 ACTIVE and Enhancements 8/8 ACTIVE. Source health uses `SOURCE_REGISTRY_V3`, is GREEN/non-blocking, OneFPL is disabled in unattended machine ingestion, and the ephemeral `official_snapshot.json` is absent from `runtime-data`.

## E. V3.20.1 Correctness Hardening
Release objective: fix verified numerical and orchestration correctness defects without changing the serving schema or over-splitting the V3 service topology.

| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-COR-231 | Appearance probability arithmetic | DONE | V3.20.1 | unconditional p60 used exactly once; deterministic numeric regression passes |
| V3-COR-232 | Goalkeeper save-route position derivation | DONE | V3.20.1 | Official element_type=GK produces GK save component without requiring synthetic position string |
| V3-COR-233 | Captain variance/covariance correctness | DONE | V3.20.1 | captain mean/std come from same row and double-points variance includes covariance |
| V3-COR-234 | Artifact-promotion failure semantics | DONE | V3.20.1 | promotion failure obeys service criticality and noncritical failures quarantine stale owned outputs |
| V3-COR-235 | Remove legacy direct-fetch projection path | DONE | V3.20.1 | decision_intelligence has no alternate Official fetch/projection runner; production projection components have neutral model ownership |
| V3-COR-236 | Config-owned XI battle threshold | DONE | V3.20.1 | positive close-margin threshold owned by lineup_governance config and architecture gate |
| V3-COR-237 | Challenger failure-class contract | DONE | V3.20.1 | external source outage remains fail-soft while internal scorecard-integrity failure remains fail-closed |
| V3-COR-238 | Preserve distinct package vs final-XI objectives | DONE | V3.20.1 | no forced selector unification; raw package mean and risk/DNP-aware final lineup remain explicit separate objectives |
| V3-COR-239 | Correctness anti-regression coverage | DONE | V3.20.1 | appearance, GK saves, captain variance, promotion failure, layering and threshold tests PASS |
| V3-COR-240 | Full CI/integration and production acceptance | DONE | V3.20.1 | all existing gates + production runtime-data + framework GREEN/HEALTHY/GO verified before DONE |

### V3.20.1 review adjudication
The external review findings for appearance arithmetic, promotion handling, legacy direct-fetch projection code, captain variance and hardcoded battle threshold were confirmed. The review recommendation to make the internal `challenger` scorecard noncritical was not applied verbatim because external-source availability is already normalized fail-soft upstream, while an internal code/artifact failure is an integrity failure. The recommendation to unify the package optimizer and final lineup selector was also not applied because their objectives are intentionally different.

### V3.20.1 schema decision
Engine patch version changes to `3.20.1`. Serving/runtime schema remains `48` because the artifact shapes and report consumer contracts do not change. The lineup-governance policy schema moves to `2` to own `battle.close_margin_threshold`; the Service Registry remains schema `11` because topology/transport/artifact contracts are unchanged.

### V3.20.1 production acceptance evidence
Production acceptance completed on 27 August 2026. PR #39 merged to `main` as `8a4e090fa4d8e702da54b85ecda3477990390039`. Production push workflow run `33038620362` passed the full test suite, architecture validation, bounded 20-service runtime, source capability, production decision/report, full DSS watchlist, report serving and report-time contracts, then published validated runtime artifacts to `runtime-data` as commit `6b34381`. Runtime evidence confirms engine `3.20.1` / schema `48`, total wall time `6652.56 ms` inside the `45000 ms` budget, overall GREEN, decision engine HEALTHY, recommendation allowed, GO allowed, Gate0 16/16 PASS, Core 50/50 ACTIVE, Extensions 16/16 ACTIVE and Enhancements 8/8 ACTIVE. Source health is GREEN/non-blocking and the 15 OWNED + 20 WATCHLIST serving contract passes.

## F. P1 Intelligence quality and calibration
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-INT-201 | Real tactical-role evidence | OPEN | P1 | verified role evidence improves proxy without unsupported claims |
| V3-INT-202 | Formation/system-fit evidence | OPEN | P1 | reliable, time-stamped evidence |
| V3-INT-203 | Rotation/competition evidence | OPEN | P1 | xMins augmented by reliable competition/manager evidence |
| V3-INT-204 | Set-piece role evidence | OPEN | P1 | explicit taker evidence when available |
| V3-INT-205 | Penalty role evidence | OPEN | P1 | explicit hierarchy evidence when available |
| V3-INT-206 | International duty/travel/congestion | OPEN | P1 | verified load affects risk |
| V3-INT-207 | Settled-GW prediction calibration | MONITOR | P1 | MAE/RMSE/Brier/Spearman from frozen forecasts |
| V3-INT-208 | Dynamic evidence-weight calibration | OPEN | P1 | data-driven/versioned/regression-tested |
| V3-INT-209 | Model drift monitoring | OPEN | P1 | degradation detected across xMins/points/start probability |
| V3-INT-210 | Challenger scorecard from settled accuracy | OPEN | P1 | provider weight earned from observed accuracy |
| V3-INT-211 | Package optimizer sensitivity audit | OPEN | P1 | explainable sensitivity bounds |
| V3-INT-212 | Price/value calibration | OPEN | P1 | pressure overlay separated from affordability/sell-value effects |

## G. User-facing report and operational UX
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-RPT-301 | Natural Bahasa Indonesia renderer | OPEN | P1 | no raw machine shorthand in user narrative |
| V3-RPT-302 | Freshness/source-health block | ACTIVE | V3.19+ | authoritative + machine + report-time freshness visible |
| V3-RPT-303 | Decision-first report layout | MONITOR | Continuous | recommendation first; technical detail separated |
| V3-RPT-304 | Delta-first stable-report behavior | MONITOR | Continuous | unchanged analysis shrinks without omitting mandatory roster |
| V3-RPT-305 | Price Radar two-group contract | ACTIVE | Continuous | OWNED and WATCHLIST groups remain complete |
| V3-RPT-306 | Scheduled-report completeness checks | OPEN | P1 | checkpoints cannot silently disappear |
| V3-RPT-307 | Deadline-mode report governance | MONITOR | Continuous | timing/formasi/XI/bench/C/VC/chip phase-aware |
| V3-RPT-308 | Match-mode report governance | MONITOR | Continuous | submitted picks + event-live authority |
| V3-RPT-309 | Confidence-language standard | OPEN | P1 | FACT/MODEL/DECISION wording consistent |
| V3-RPT-310 | Scheduled report-time web refresh | ACTIVE | V3.19+ | OneFPL/strategy/pundit/community/verified-news pass performed when report is generated |
| V3-RPT-311 | On-demand report-time web refresh | ACTIVE | V3.19+ | same source pass for fresh user report |
| V3-RPT-312 | Consensus-vs-DSS explanation | ACTIVE | V3.19+ | disagreement surfaced rather than silently averaged |
| V3-RPT-313 | Formation/XI/C/VC/bench completeness | ACTIVE | Continuous | every visible report prints formation, exact XI, C, VC, Bench1/2/3 and GK Bench |

## H. P2 strategic capabilities
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-STR-401 | True overall-rank conversion model | DEFERRED | P2 | validated points/EO-to-rank distribution |
| V3-STR-402 | Live EO population model | DEFERRED | P2 | reliable provenance + calibration |
| V3-STR-403 | Production-grade ML projection | DEFERRED | P2 | leakage-safe model beats interpretable baseline |
| V3-STR-404 | Full mini-league rival intelligence | DEFERRED | P2 | lawful/read-only robust identity |
| V3-STR-405 | Literal heatmap renderer | DEFERRED | P2 | grounded spatial/event data |
| V3-STR-406 | Advanced blank/double simulator | OPEN | P2 | schedule uncertainty + chips + squad structure |
| V3-STR-407 | Long-horizon chip-window optimizer | OPEN | P2 | secondary to near-term quality/rule legality |

## I. Maintenance and engineering hygiene
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-ENG-501 | Central config ownership audit | ACTIVE | Every release | one owner for each mutable parameter |
| V3-ENG-502 | Hardcode regression scan | ACTIVE | Every release | mutable literals rejected/reviewed |
| V3-ENG-503 | Registry integrity tests | ACTIVE | Every release | rules/DSS/source/report-time/service registries valid |
| V3-ENG-504 | Production-contract regression | ACTIVE | Every release | no schema/decision/watchlist/report regression |
| V3-ENG-505 | Runtime performance regression | ACTIVE | Every release | production budget preserved |
| V3-ENG-506 | Fail-closed critical / fail-soft optional | ACTIVE | Every release | optional evidence cannot corrupt baseline |
| V3-ENG-507 | README/task synchronization | ACTIVE | Every release | roadmap/current release accurate |
| V3-ENG-508 | Historical version-reference hygiene | ACTIVE | Every release | stale active labels forbidden |
| V3-ENG-509 | Active artifact ownership audit | ACTIVE | Every release | each promoted artifact has one service owner or explicit serial overlay owner |
| V3-ENG-510 | Microservice boundary audit | ACTIVE | Every release | no active monolith and no gratuitous process fragmentation |

## J. Release checklist for every V3 change
1. Create dedicated branch from current production `main`.
2. Update this Master Task List in the same PR.
3. Keep mutable values in the correct config/registry owner.
4. Update `src/version.py` when version changes.
5. Bump serving schema only for serving/runtime-output contract changes.
6. Keep README, IMPLEMENTATION_STATUS, workflow, engine schema metadata, service/report/source registries and release tests consistent.
7. Compile runtime modules.
8. Run architecture ownership contract PASS.
9. Full unit/regression suite PASS.
10. Integration runtime PASS for runtime-impacting changes.
11. Source capability contract PASS.
12. Report-time intelligence contract PASS when applicable.
13. Production decision contract PASS.
14. 15 OWNED + 20 WATCHLIST contract PASS.
15. Report-serving contract PASS.
16. Runtime budget PASS.
17. Merge only when PR is mergeable and all applicable CI GREEN.
18. Confirm production push/collector.
19. Confirm validated publication to `runtime-data`.
20. Verify production framework: Gate0 16/16, Core50, Ext16, Enh8, overall GREEN, HEALTHY, GO.
21. Move candidate tasks to DONE only after production evidence exists.

## Definition of Done
A V3 task is DONE only when implementation, tests, documentation, version governance, and production evidence agree. File existence, registry presence, source reachability, a manually changed status label, or a locally successful command alone are insufficient.

For external evidence, missing values may never be synthesized solely to keep a module green. For report-time intelligence, a report that did not perform the web pass must explicitly state `REFRESH_REQUIRED`; it may not reuse stale evidence as if current.

For architecture work, a file split is not DONE merely because code moved. The new boundary must have explicit inputs, outputs, ownership, failure semantics, DAG dependencies, tests, and no duplicate active authority.

For numerical correctness work, a formula change is not DONE until a deterministic example demonstrates the intended arithmetic and the production integration path consumes that same implementation.

## Execution order
1. Keep V3.20.1 production GREEN and use it as the authoritative engine for scheduled/on-demand task reports.
2. Continue V3-RPT-301 natural Bahasa Indonesia renderer and V3-RPT-306 scheduled-report completeness hardening.
3. Replace P1 proxy evidence with verified tactical-role, formation, rotation, set-piece, penalty and international-duty evidence where reliable.
4. Accumulate settled Gameweeks for calibration, model drift and challenger scorecard work.
5. Keep architecture/configuration ownership and numerical-correctness gates active on every release.
6. Pursue P2 only after P1 evidence quality is sufficient and without destabilizing V3 production.

## Change log
- V3.20.1: production accepted appearance/p60 arithmetic correction; goalkeeper position/save-route correction; captain variance/covariance correction; promotion-failure criticality/stale-output quarantine; legacy direct-fetch projection cleanup; config-owned XI battle threshold; serving schema remains 48.
- V3.20.0: production accepted architecture hardening; artifact-owned base-service decomposition; generic root DAG; Source Registry V3; collector policy registry; current advanced-stat aliases; deep-stats runtime-data publication; semantic model IDs; architecture anti-monolith gate; serving schema remains 48.
- V3.19.0: production accepted report-time intelligence source registry; OneFPL delegated out of unattended collector; Ben Crellin fixture strategy; pundit consensus-vs-DSS; Reddit/community cross-check governance; report serving contract v2/schema48.
- V3.18.1: production accepted OneFPL automated-access reliability diagnosis and source capability contract.
- V3.18.0: production accepted structured challenger observations, reachability/capability separation, TTL/LKG/stale/disagreement governance, Price Radar context integration and architecture hardening.
- V3.17.1: canonical V3 master task governance and Definition of Done.
