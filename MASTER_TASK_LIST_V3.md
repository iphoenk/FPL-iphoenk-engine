# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE
Canonical roadmap owner: V3 operational stream
Production baseline: V3.18.0 / schema 47
Current release candidate: V3.18.1
Current candidate schema: 47
Candidate scope: OneFPL adapter reachability and structured-access reliability
Candidate acceptance: PENDING

This file is the single human-readable master roadmap for the V3 operational engine. Every V3 feature, refactor, hardening change, operational improvement, and release-governance change must update this file in the same pull request.

## Status legend
- DONE: implemented, tested, merged, production-validated when runtime-impacting.
- ACTIVE: continuously enforced operational requirement or release candidate under acceptance.
- NEXT: highest-priority planned work.
- OPEN: planned but not the immediate next release.
- BLOCKED: cannot progress until a named dependency is resolved.
- DEFERRED: intentionally postponed.
- MONITOR: implemented but requires ongoing runtime observation/calibration.

## Non-negotiable V3 invariants
1. Official FPL remains the only native authority for Official fields and scoring.
2. Challenger/enrichment sources are fail-soft and may not overwrite Official-native truth.
3. Missing external evidence is never fabricated. Safe fallback states must be explicit.
4. Operational squad contract is exactly 15 OWNED players.
5. External WATCHLIST is exactly 20 players total, maximum 5 per position, with no OWNED overlap.
6. Gate 0 must remain 16/16 PASS for unqualified GO.
7. DSS Core must remain 50/50 ACTIVE, DSS Extensions 16/16 ACTIVE, and Enhancement Layers 8/8 ACTIVE.
8. Mutable runtime values belong in config/registry/environment ownership, not scattered hardcoded literals.
9. Release metadata must remain consistent across source, README, implementation status, workflow naming, schema metadata, and tests.
10. User-facing reports must never expose raw internal shorthand or falsely imply that source reachability equals structured data availability.
11. V3 production remains operationally stable while new work is developed on separate branches and merged only after full acceptance.
12. Microservice boundaries are coarse-grained and evidence-driven. New process boundaries must reduce coupling, duplicate I/O, or failure blast radius; file size alone is not a reason to split a service.

## A. Production baseline and keep-green work
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-OPS-001 | Gate 0 hard constraints | DONE | V3.17 | 16/16 PASS in production postflight |
| V3-OPS-002 | DSS Core operational health | DONE | V3.17 | 50/50 ACTIVE with runtime evidence |
| V3-OPS-003 | DSS Extension operational health | DONE | V3.17 | 16/16 ACTIVE with runtime evidence |
| V3-OPS-004 | Enhancement Layer operational health | DONE | V3.17 | 8/8 ACTIVE with runtime evidence |
| V3-OPS-005 | 15 OWNED + 20 WATCHLIST contract | ACTIVE | Continuous | exactly 15 owned, 20 external watchlist, max 5/position, no overlap |
| V3-OPS-006 | Official FPL authority and fail-soft challenger policy | ACTIVE | Continuous | no challenger overwrite of Official-native fields |
| V3-OPS-007 | Runtime publication to isolated `runtime-data` | ACTIVE | Continuous | validated artifacts publish successfully without protected-main writes |
| V3-OPS-008 | Bounded microservice runtime performance | MONITOR | Continuous | runtime stays within configured production budget |
| V3-OPS-009 | Configuration ownership / anti-hardcode discipline | ACTIVE | Continuous | mutable settings live in config/registry/env and CI catches known regressions |
| V3-OPS-010 | Release/version/README consistency | ACTIVE | Continuous | metadata consistency tests pass on every release |
| V3-OPS-011 | Rules Registry integrity and drift review | ACTIVE | Continuous | active ruleset valid; drift never auto-mutates authority |
| V3-OPS-012 | Authenticated Official read-only precision layer | MONITOR | Continuous | optional, read-only, fail-soft, no credential/raw-private persistence |

## B. V3.18 Structured Challenger Ingestion
Release objective: convert selected challenger sources from probe-only reachability into normalized, provenance-safe observations without weakening Official FPL authority or production reliability.

| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-SRC-101 | Normalized challenger observation contract | DONE | V3.18.0 | typed observation with source, capability, payload/value, timestamp, provenance, confidence, stale state, parser/schema version |
| V3-SRC-102 | Separate source reachability from capability-data health | DONE | V3.18.0 | source may be LIVE while a capability is UNAVAILABLE/STALE/ERROR |
| V3-SRC-103 | LiveFPL structured ingestion | DONE | V3.18.0 | robust public observation only; no invented EO/price/rank values |
| V3-SRC-104 | OneFPL structured ingestion | DONE | V3.18.0 | robust public observation only; transfer/price/planner context normalized when actually available |
| V3-SRC-105 | Provenance and observation timestamps | DONE | V3.18.0 | every accepted observation has traceable source and observed/fetched time |
| V3-SRC-106 | TTL, stale cache, last-known-good policy | DONE | V3.18.0 | stale observations explicitly labelled and never silently treated as current |
| V3-SRC-107 | Confidence and cross-source disagreement state | DONE | V3.18.0 | agreement may raise confidence; disagreement is explicit and never silently overwrites Official data |
| V3-SRC-108 | Price Radar challenger integration | DONE | V3.18.0 | LiveFPL/OneFPL values consumed only when a valid normalized observation exists |
| V3-SRC-109 | User-facing source availability rendering | DONE | V3.18.0 | report distinguishes reachable source from available structured prediction data |
| V3-SRC-110 | Challenger failure isolation tests | DONE | V3.18.0 | challenger outage cannot block Official baseline |
| V3-SRC-111 | No-fabrication regression tests | DONE | V3.18.0 | missing observation stays missing/explicit fallback |
| V3-SRC-112 | Official-authority precedence tests | DONE | V3.18.0 | challenger cannot override Official-native field |
| V3-SRC-113 | Structured-ingestion performance budget | DONE | V3.18.0 | bounded parallel ingestion remains inside production runtime budget |
| V3-SRC-114 | Parser/contract drift handling | DONE | V3.18.0 | unexpected source shape degrades capability safely instead of corrupting output |
| V3-SRC-115 | V3.18 release governance | DONE | V3.18.0 | version/schema, README, implementation status, workflow, tests, CI and production collect all consistent |
| V3-SRC-116 | OneFPL reachability / structured-access reliability | ACTIVE | V3.18.1 | homepage reachability separated from structured endpoint restriction; approved public fallback owned by registry; no UA spoofing; no fabrication; CI/integration/production evidence required |

### V3.18 architecture-hardening scope
- Version-neutral runtime entrypoints replace version-stamped active service names; historical compatibility modules may remain as shims only.
- Mutable projection horizon, Price Radar thresholds, refresh cadence and related serving limits are config/registry-owned.
- DSS Core, DSS Extensions, Enhancement and Gate0 expected counts are declared by their registries and consumed by the active framework-health entrypoint.
- Production validators consume challenger/report/price/registry contracts instead of duplicating mutable constants.
- The price service is a single coarse-grained process that runs Official Price Radar then challenger context overlay serially on the same artifact.
- Collector and prediction remain separate coarse-grained services. Repeated Official reads use the shared cross-process HTTP cache, so a new raw-snapshot microservice is not justified in V3.18.
- Governance overlays remain one ordered service because they intentionally mutate one framework-health artifact sequentially.
- Reporting remains decision-output plus a separate serving/materializer boundary; additional process fragmentation is not justified by current dependency or failure-isolation evidence.

### V3.18 production acceptance evidence
Production acceptance completed on 26 August 2026:
- merged production release commit: `6ad79610f74893e3badbd3feccb63c4f052440b8`
- production workflow: full regression suite PASS and collector SUCCESS
- production contract, WATCHLIST contract and report-serving validation: PASS
- `runtime-data` publication: SUCCESS
- Gate 0: 16/16 PASS
- DSS Core: 50/50 ACTIVE
- DSS Extensions: 16/16 ACTIVE
- Enhancement Layers: 8/8 ACTIVE
- framework: GREEN
- decision engine: HEALTHY
- GO allowed: true
- production runtime: 6.58 seconds against a 45-second budget
- source-layer challenger degradation remains fail-soft and non-blocking; missing observations are not fabricated

## C. P1 Intelligence quality and calibration
These items improve evidence quality behind already-operational DSS capabilities. A current safe proxy/fallback may keep a module healthy, but richer evidence should replace proxies when reliable data becomes available.

| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-INT-201 | Real tactical-role evidence | OPEN | P1 | verified role evidence improves proxy without unsupported claims |
| V3-INT-202 | Formation/system-fit evidence | OPEN | P1 | role/system fit grounded in reliable evidence and time-stamped |
| V3-INT-203 | Rotation/competition evidence | OPEN | P1 | xMins proxy augmented by reliable competition/manager evidence |
| V3-INT-204 | Set-piece role evidence | OPEN | P1 | explicit taker evidence when available; safe fallback otherwise |
| V3-INT-205 | Penalty role evidence | OPEN | P1 | explicit penalty hierarchy evidence when available; safe fallback otherwise |
| V3-INT-206 | International duty, travel and congestion evidence | OPEN | P1 | call-up/minutes/travel/congestion affect risk only when verified |
| V3-INT-207 | Settled-GW prediction calibration loop | MONITOR | P1 | MAE/RMSE/Brier/Spearman computed from point-in-time frozen forecasts |
| V3-INT-208 | Dynamic evidence-weight calibration | OPEN | P1 | weighting changes are data-driven, versioned, and regression-tested |
| V3-INT-209 | Model drift monitoring | OPEN | P1 | degradation detected across xMins, points and starter probabilities |
| V3-INT-210 | Challenger scorecard based on settled accuracy | OPEN | P1 | external provider weight earned from observed accuracy, never reputation |
| V3-INT-211 | Package optimizer sensitivity audit | OPEN | P1 | risk, churn, cluster and horizon weights have explainable sensitivity bounds |
| V3-INT-212 | Price/value calibration | OPEN | P1 | price pressure remains overlay while affordability/sell-value effects are measured correctly |

## D. User-facing report and operational UX
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-RPT-301 | Natural Bahasa Indonesia report renderer | OPEN | P1 | no raw labels such as HOLD/LOCK shorthand; machine state translated into clear user language |
| V3-RPT-302 | Freshness/source-health block in every report | OPEN | P1 | timestamp, authoritative source freshness, challenger capability status, and degraded states visible |
| V3-RPT-303 | Decision-first report layout | MONITOR | Continuous | recommendation first; technical detail separated from user report |
| V3-RPT-304 | Delta-first stable-report behavior | MONITOR | Continuous | unchanged analysis shrinks; meaningful changes are surfaced |
| V3-RPT-305 | Price Radar two-group contract | ACTIVE | Continuous | OWNED and WATCHLIST groups show current price, direction, signal, ETA/urgency when supportable, action |
| V3-RPT-306 | Scheduled-report completeness checks | OPEN | P1 | expected report checkpoint cannot silently disappear without visible health/error state |
| V3-RPT-307 | Deadline-mode report governance | MONITOR | Continuous | timing and captain/XI/chip state match deadline rules and phase authority |
| V3-RPT-308 | Match-mode report governance | MONITOR | Continuous | live/match reports use submitted picks + event live authority |
| V3-RPT-309 | Confidence language standard | OPEN | P1 | FACT/MODEL/DECISION and confidence wording remain consistent across reports |

## E. P2 strategic capabilities
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-STR-401 | True overall-rank conversion model | DEFERRED | P2 | validated mapping from points/EO scenarios to rank distribution |
| V3-STR-402 | Live effective-ownership population model | DEFERRED | P2 | reliable EO population model with provenance and calibration |
| V3-STR-403 | Production-grade ML projection model | DEFERRED | P2 | leakage-safe model beats interpretable baseline on settled samples before promotion |
| V3-STR-404 | Full mini-league rival intelligence | DEFERRED | P2 | lawful/read-only rival context with robust identity and no credential leakage |
| V3-STR-405 | Literal heatmap renderer | DEFERRED | P2 | visual output grounded in valid spatial/event data |
| V3-STR-406 | Advanced blank/double scenario simulator | OPEN | P2 | scenario engine integrates schedule uncertainty, chips and squad structure |
| V3-STR-407 | Long-horizon chip-window optimizer | OPEN | P2 | 10-15 GW planning remains secondary to near-term decision quality and rule legality |

## F. Maintenance and engineering hygiene
| ID | Task | Status | Target | Acceptance |
| --- | --- | --- | --- | --- |
| V3-ENG-501 | Central configuration ownership audit | ACTIVE | Every release | one clear owner for each mutable parameter; avoid duplicated config values |
| V3-ENG-502 | Hardcode regression scan | ACTIVE | Every release | known mutable literals rejected by tests; new config-sensitive logic reviewed |
| V3-ENG-503 | Registry integrity tests | ACTIVE | Every release | rules, DSS, extensions, enhancements, sources and service registries remain valid |
| V3-ENG-504 | Production-contract regression suite | ACTIVE | Every release | no schema/decision/watchlist/report contract regression |
| V3-ENG-505 | Runtime performance regression check | ACTIVE | Every release | total runtime and critical service budgets remain within policy |
| V3-ENG-506 | Fail-closed critical path / fail-soft optional path | ACTIVE | Every release | critical authority failures block GO; optional enrichment failures do not corrupt baseline |
| V3-ENG-507 | README and task-list synchronization | ACTIVE | Every release | README points to this canonical roadmap and current status is updated |
| V3-ENG-508 | Historical version references remain explicitly historical | ACTIVE | Every release | stale active-version labels are not allowed |

## G. Release checklist for every V3 change
A release cannot be marked DONE until all applicable checks below pass.

1. Create a dedicated branch from current production `main`.
2. Update this `MASTER_TASK_LIST_V3.md` in the same PR.
3. Keep mutable values in the correct config/registry owner; do not introduce avoidable hardcode.
4. Update `src/version.py` when the release version changes.
5. Decide schema bump based on contract change, not merely code volume.
6. Keep `README.md`, `IMPLEMENTATION_STATUS.json`, workflow display name, engine schema metadata and release tests consistent.
7. Compile runtime modules successfully.
8. Run the full unit/regression suite successfully.
9. Run integration runtime for runtime-impacting changes.
10. Validate production decision contract.
11. Validate 15 OWNED + 20 WATCHLIST contract.
12. Validate report-serving contract.
13. Verify runtime budget.
14. Merge only when PR is mergeable and all required CI is GREEN.
15. Confirm production push/collector run.
16. Confirm validated publication to `runtime-data`.
17. Re-read production `framework_health.json`: Gate0 16/16, DSS 50/50, Extensions 16/16, Enhancements 8/8, overall GREEN, decision engine HEALTHY, GO allowed.
18. Update task status from ACTIVE to DONE only after the applicable production acceptance is complete.

## Definition of Done
A V3 task is DONE only when implementation, tests, documentation, version governance, and production evidence agree. File existence, registry presence, source reachability, or a manually changed status label alone are not sufficient.

For external evidence tasks, DONE means the adapter/evaluator can explicitly distinguish at least AVAILABLE, UNAVAILABLE/SAFE_FALLBACK, STALE, and ERROR states where applicable. Missing values may never be synthesized solely to keep a module green.

## Execution order
1. Keep V3.18.0 production GREEN while V3.18.1 is under acceptance.
2. Complete V3.18.1 OneFPL adapter CI, integration and production verification.
3. Report-source availability and natural-language rendering hardening.
4. Replace P1 proxies with richer evidence where reliable.
5. Accumulate settled Gameweeks and calibrate prediction/weighting models.
6. Pursue P2 capabilities only after P1 calibration has enough evidence and without destabilizing V3 operations.

## Change log
- V3.18.1 candidate: OneFPL reachability/structured-access separation, registry-owned approved fallback deployment, parser v2, endpoint-attempt evidence, no spoofing, no fabrication. Remains ACTIVE until production acceptance.
- V3.18.0: production accepted. Structured LiveFPL/OneFPL observations, reachability/capability separation, TTL/LKG/stale and disagreement governance, Price Radar context integration, registry-driven mutable policy, version-neutral service entrypoints, validator/microservice boundary hardening, full production validation and runtime-data publication completed.
- V3.17.1: established this canonical master task list, release checklist, Definition of Done, execution order, and mandatory roadmap synchronization rule.