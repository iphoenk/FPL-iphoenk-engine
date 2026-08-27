# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE
Canonical roadmap owner: V3 operational stream
Production baseline: V3.18.1 / schema 47
Current release candidate: V3.19.0
Current candidate schema: 48
Candidate scope: Report-Time Intelligence + Pundit Consensus vs DSS
Candidate acceptance: PENDING

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
12. Microservice boundaries are coarse-grained and evidence-driven. New process boundaries must reduce coupling, duplicate I/O, or failure blast radius; file size alone is not a reason to split a service.
13. Pundit consensus is advisory only. Consensus may challenge DSS, but may not silently mutate DSS.
14. Community sentiment is a lead, not a fact. Fact promotion requires authoritative or independent corroboration.
15. Fixture-strategy expertise is separate from player-projection voting.

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

V3.18.1 production acceptance completed 27 August 2026: engine 3.18.1/schema47, workflow/collector SUCCESS, source contract PASS, framework GREEN/HEALTHY/GO, Gate0 16/16, DSS Core 50/50, Extensions 16/16, Enhancements 8/8.

## C. V3.19 Report-Time Intelligence
Release objective: add fresh report-time expert/model/community evidence while keeping unattended machine collection lean and keeping DSS independent.

| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-RTI-101 | Dedicated report-time source registry | ACTIVE | V3.19.0 | source classes/domains/query intents/freshness/authority ceilings registry-owned |
| V3-RTI-102 | OneFPL collector-to-report-time delegation | ACTIVE | V3.19.0 | machine registry disabled; report-time registry enabled; no collector HTTP attempts |
| V3-RTI-103 | Report-time evidence contract | ACTIVE | V3.19.0 | source/class/topic/subject/stance/time/URL/summary required |
| V3-RTI-104 | Pundit consensus engine | ACTIVE | V3.19.0 | current opinions aggregated only from eligible pundit class |
| V3-RTI-105 | Pundit consensus vs DSS comparison | ACTIVE | V3.19.0 | explicit ALIGN/DIVERGE/REVIEW_DIVERGENCE/NEUTRAL; DSS not mutated |
| V3-RTI-106 | Ben Crellin fixture-strategy class | ACTIVE | V3.19.0 | BGW/DGW/rearrangement/chip-window context; no player-projection vote |
| V3-RTI-107 | Reddit r/FantasyPL community-signal class | ACTIVE | V3.19.0 | eye-test/poll/role/rotation/injury/sentiment treated as cross-check-required leads |
| V3-RTI-108 | Verified-news class | ACTIVE | V3.19.0 | official availability/suspension/fixture/manager context may corroborate facts |
| V3-RTI-109 | Report-time freshness governance | ACTIVE | V3.19.0 | stale evidence visible but excluded from current consensus |
| V3-RTI-110 | Report serving integration | ACTIVE | V3.19.0 | user_report, decision_brief and deep_review contain report-time intelligence |
| V3-RTI-111 | Explicit refresh-required state | ACTIVE | V3.19.0 | collector snapshot says REFRESH_REQUIRED when no report-time web pass occurred |
| V3-RTI-112 | Machine-cache ownership cleanup | ACTIVE | V3.19.0 | delegated OneFPL LKG/stale observations purged from collector-owned artifacts |
| V3-RTI-113 | Report-time contract validator | ACTIVE | V3.19.0 | CI/integration checks registry, OneFPL delegation, advisory policy and serving output |
| V3-RTI-114 | Schema/serving contract v2 | ACTIVE | V3.19.0 | schema48, REPORT_ARTIFACT_REGISTRY_V2, DEEP_REVIEW_PAYLOAD_V2 |
| V3-RTI-115 | V3.19 release governance | ACTIVE | V3.19.0 | version/README/task/workflow/tests/CI/production all consistent |

### V3.19 report-time source classes
- `MODEL_CHALLENGER`: OneFPL. Advisory model/price/transfer/captaincy/planner context only.
- `FIXTURE_STRATEGY_EXPERT`: Ben Crellin. Schedule and chip-window context only.
- `PUNDIT_CONSENSUS`: FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar, Fantasy Football Scout editorial.
- `COMMUNITY_SIGNAL`: Reddit r/FantasyPL. Leads and sentiment; requires cross-check.
- `VERIFIED_NEWS`: Premier League/official-club factual context.

### V3.19 architectural boundary
Report-time intelligence stays inside the existing report boundary. It is not a new unattended collector microservice. The collector publishes the machine/DSS baseline and marks report-time evidence `REFRESH_REQUIRED`; the chat/report orchestration performs normal web review for scheduled or on-demand reports and synthesizes the evidence under the same contract. This avoids duplicate unattended I/O and keeps source-policy restrictions outside the collector.

## D. P1 Intelligence quality and calibration
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

## E. User-facing report and operational UX
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-RPT-301 | Natural Bahasa Indonesia renderer | OPEN | P1 | no raw HOLD/LOCK-style machine shorthand in user narrative |
| V3-RPT-302 | Freshness/source-health block | ACTIVE | V3.19+ | authoritative + machine + report-time freshness visible |
| V3-RPT-303 | Decision-first report layout | MONITOR | Continuous | recommendation first; technical detail separated |
| V3-RPT-304 | Delta-first stable-report behavior | MONITOR | Continuous | unchanged analysis shrinks |
| V3-RPT-305 | Price Radar two-group contract | ACTIVE | Continuous | OWNED and WATCHLIST groups remain complete |
| V3-RPT-306 | Scheduled-report completeness checks | OPEN | P1 | checkpoints cannot silently disappear |
| V3-RPT-307 | Deadline-mode report governance | MONITOR | Continuous | timing/captain/XI/chip phase-aware |
| V3-RPT-308 | Match-mode report governance | MONITOR | Continuous | submitted picks + event-live authority |
| V3-RPT-309 | Confidence-language standard | OPEN | P1 | FACT/MODEL/DECISION wording consistent |
| V3-RPT-310 | Scheduled report-time web refresh | ACTIVE | V3.19+ | OneFPL/strategy/pundit/community/verified-news pass performed when report is generated |
| V3-RPT-311 | On-demand report-time web refresh | ACTIVE | V3.19+ | same source pass when user requests a fresh report |
| V3-RPT-312 | Consensus-vs-DSS explanation | ACTIVE | V3.19+ | disagreements surfaced with source/provenance, not silently averaged away |

## F. P2 strategic capabilities
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-STR-401 | True overall-rank conversion model | DEFERRED | P2 | validated points/EO-to-rank distribution |
| V3-STR-402 | Live EO population model | DEFERRED | P2 | reliable provenance + calibration |
| V3-STR-403 | Production-grade ML projection | DEFERRED | P2 | leakage-safe model beats interpretable baseline |
| V3-STR-404 | Full mini-league rival intelligence | DEFERRED | P2 | lawful/read-only robust identity |
| V3-STR-405 | Literal heatmap renderer | DEFERRED | P2 | grounded spatial/event data |
| V3-STR-406 | Advanced blank/double simulator | OPEN | P2 | schedule uncertainty + chips + squad structure |
| V3-STR-407 | Long-horizon chip-window optimizer | OPEN | P2 | secondary to near-term quality/rule legality |

## G. Maintenance and engineering hygiene
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

## H. Release checklist for every V3 change
1. Create dedicated branch from current production `main`.
2. Update this Master Task List in the same PR.
3. Keep mutable values in the correct config/registry owner.
4. Update `src/version.py` when version changes.
5. Bump schema only for contract changes.
6. Keep README, IMPLEMENTATION_STATUS, workflow, engine schema metadata, service/report registries and release tests consistent.
7. Compile runtime modules.
8. Full unit/regression suite PASS.
9. Integration runtime PASS for runtime-impacting changes.
10. Source capability contract PASS.
11. Report-time intelligence contract PASS when applicable.
12. Production decision contract PASS.
13. 15 OWNED + 20 WATCHLIST contract PASS.
14. Report-serving contract PASS.
15. Runtime budget PASS.
16. Merge only when PR is mergeable and all applicable CI GREEN.
17. Confirm production push/collector.
18. Confirm validated publication to `runtime-data`.
19. Verify production framework: Gate0 16/16, Core50, Ext16, Enh8, overall GREEN, HEALTHY, GO.
20. Move candidate tasks to DONE only after production evidence exists.

## Definition of Done
A V3 task is DONE only when implementation, tests, documentation, version governance, and production evidence agree. File existence, registry presence, source reachability, or a manually changed status label alone are insufficient.

For external evidence, missing values may never be synthesized solely to keep a module green. For report-time intelligence, a report that did not perform the web pass must explicitly state `REFRESH_REQUIRED`; it may not reuse stale evidence as if current.

## Execution order
1. Keep V3.18.1 production GREEN while V3.19.0 is under acceptance.
2. Complete V3.19 unit/integration/report-time contract and serving-contract validation.
3. Merge and production-validate V3.19.0/schema48.
4. Continue natural-language renderer and scheduled-report completeness hardening.
5. Replace P1 proxies with richer evidence where reliable.
6. Accumulate settled Gameweeks and calibrate prediction/weighting models.
7. Pursue P2 only after P1 evidence is sufficient and without destabilizing V3.

## Change log
- V3.19.0 candidate: report-time intelligence source registry; OneFPL delegated out of unattended collector; Ben Crellin fixture-strategy evidence; pundit consensus-vs-DSS; Reddit/community cross-check governance; verified-news class; report serving contract v2/schema48.
- V3.18.1: production accepted OneFPL automated-access reliability diagnosis and source capability contract.
- V3.18.0: production accepted structured challenger observations, reachability/capability separation, TTL/LKG/stale/disagreement governance, Price Radar context integration and architecture hardening.
- V3.17.1: canonical V3 master task governance and Definition of Done.
