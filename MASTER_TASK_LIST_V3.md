# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE
Canonical roadmap owner: V3 operational stream
Current production release: V3.20.1
Current production schema: 48
Current release candidate: V3.20.2
Current candidate schema: 48
Candidate scope: Artifact Contract Hardening
Candidate acceptance: PENDING

This file is the single human-readable master roadmap for the operational V3 stream. Every V3 feature, refactor, hardening change and release-governance change must update this file in the same pull request.

## Status legend
- DONE: implemented, tested, merged and production-validated when runtime-impacting.
- ACTIVE: continuously enforced operational requirement or candidate under acceptance.
- NEXT: highest-priority planned work.
- OPEN: planned but not immediate.
- BLOCKED: dependency prevents progress.
- DEFERRED: intentionally postponed.
- MONITOR: implemented but needs continuing runtime/calibration evidence.

## Non-negotiable V3 invariants
1. Official FPL remains the only native authority for Official fields and scoring.
2. Challenger, enrichment, report-time expert and community sources may never overwrite Official-native truth.
3. Missing external evidence is never fabricated; unavailable/stale/safe-fallback states are explicit.
4. OWNED is exactly 15 authoritative players.
5. WATCHLIST is exactly 20 external players, exactly 5 GK + 5 DEF + 5 MID + 5 FWD, excluding OWNED.
6. Gate0 must remain 16/16 PASS for unqualified GO.
7. DSS Core must remain 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE.
8. Mutable runtime values belong in config/registry/environment ownership, not scattered hardcoded literals.
9. Release metadata must remain consistent across source, README, implementation status, workflow, schema metadata, registries and tests.
10. User-facing reports must not expose raw machine shorthand or imply a source was checked when it was not.
11. Production remains stable while candidate work is developed on a separate branch.
12. Microservice boundaries follow artifact ownership/failure semantics, not file size.
13. Pundit consensus is advisory only and may not silently mutate DSS.
14. Community sentiment is a lead, not a fact, without corroboration.
15. Fixture-strategy expertise is separate from player-projection voting.
16. Standard Official public baseline fetches have one runtime owner.
17. Active evidence paths must not pin a fixed GW when intended to mean current state.
18. Compatibility/version-stamped modules may not become active production service entrypoints.
19. Runtime data publishes to `runtime-data`, never protected `main`.
20. Numerical formulas affecting decisions require deterministic regressions.
21. External-source unavailability and internal computation/artifact-integrity failure are separate classes.
22. Every declared JSON service artifact must be structurally parseable before acceptance.
23. Contract-critical artifacts must satisfy registry-owned contract/schema validation before canonical promotion.
24. Valid empty external observations remain fail-soft; malformed internal artifacts never masquerade as empty external evidence.

## A. Production keep-green
| ID | Task | Status | Acceptance |
| --- | --- | --- | --- |
| V3-OPS-001 | Gate0 hard constraints | DONE | 16/16 PASS |
| V3-OPS-002 | DSS Core health | DONE | 50/50 ACTIVE |
| V3-OPS-003 | DSS Extension health | DONE | 16/16 ACTIVE |
| V3-OPS-004 | Enhancement health | DONE | 8/8 ACTIVE |
| V3-OPS-005 | 15 OWNED + 20 WATCHLIST | ACTIVE | exact counts, max 5/position, no overlap |
| V3-OPS-006 | Official authority / fail-soft optional sources | ACTIVE | no challenger overwrite |
| V3-OPS-007 | Isolated runtime-data publication | ACTIVE | validated bridge publication only |
| V3-OPS-008 | Runtime performance | MONITOR | under configured 45s budget |
| V3-OPS-009 | Config ownership / anti-hardcode | ACTIVE | mutable policy registry/config-owned |
| V3-OPS-010 | Release/version/README consistency | ACTIVE | CI consistency gate |
| V3-OPS-011 | Rules Registry integrity | ACTIVE | active ruleset valid |
| V3-OPS-012 | Authenticated Official precision layer | MONITOR | optional/read-only/fail-soft |

## B. Completed platform milestones
### V3.18 Structured Challenger
Normalized challenger observations, provenance/freshness, reachability-vs-capability health, TTL/LKG/stale/disagreement governance, non-authoritative price context and registry-driven source ownership are DONE.

### V3.19 Report-Time Intelligence
Dedicated report-time registry, OneFPL delegation, Ben Crellin fixture strategy, pundit consensus-vs-DSS, Reddit/community governance, verified news, freshness, report serving and explicit `REFRESH_REQUIRED` state are DONE.

### V3.20 Architecture Hardening
| ID | Task | Status |
| --- | --- | --- |
| V3-ARCH-201 | Canonical Source Registry V3 | DONE |
| V3-ARCH-202 | Remove legacy `config/sources.json` | DONE |
| V3-ARCH-203 | Registry-owned collector cadence/window | DONE |
| V3-ARCH-204 | Dynamic Official User-Agent/version | DONE |
| V3-ARCH-205 | Remove active monolithic collector | DONE |
| V3-ARCH-206 | Official snapshot single owner | DONE |
| V3-ARCH-207 | Team-state service | DONE |
| V3-ARCH-208 | Market-state service | DONE |
| V3-ARCH-209 | Live-state service | DONE |
| V3-ARCH-210 | Advanced-stats service | DONE |
| V3-ARCH-211 | Base snapshot fan-in | DONE |
| V3-ARCH-212 | Generic root DAG scheduling | DONE |
| V3-ARCH-213 | Current stats aliases | DONE |
| V3-ARCH-214 | Semantic model IDs | DONE |
| V3-ARCH-215 | Deep-stats runtime-data publication | DONE |
| V3-ARCH-216 | Architecture anti-regression gate | DONE |
| V3-ARCH-217 | Framework mutable-policy ownership | DONE |
| V3-ARCH-218 | Microservice over-splitting review | DONE |
| V3-ARCH-219 | V3.20 release metadata consistency | DONE |
| V3-ARCH-220 | Full CI/integration acceptance | DONE |
| V3-ARCH-221 | Production acceptance | DONE |

V3.20.0 production acceptance completed 27 August 2026 with framework GREEN/HEALTHY/GO, Gate0 16/16, Core50, Extensions16 and Enhancements8.

## C. V3.20.1 Correctness Hardening
| ID | Task | Status | Acceptance |
| --- | --- | --- | --- |
| V3-COR-231 | Appearance probability arithmetic | DONE | unconditional p60 used once |
| V3-COR-232 | GK position/save-route derivation | DONE | native element_type=GK receives save projection |
| V3-COR-233 | Captain variance/covariance | DONE | same captain row and double-score variance |
| V3-COR-234 | Promotion failure semantics | DONE | criticality honored, stale noncritical outputs quarantined |
| V3-COR-235 | Remove legacy direct-fetch projection path | DONE | one production projection path |
| V3-COR-236 | Config-owned XI battle threshold | DONE | mutable threshold in config |
| V3-COR-237 | Challenger failure-class contract | DONE | source outage fail-soft, internal scorecard integrity fail-closed |
| V3-COR-238 | Package-vs-final-XI boundary review | DONE | separate objectives retained intentionally |
| V3-COR-239 | Full CI/production acceptance | DONE | V3.20.1 production accepted |

V3.20.1 production acceptance completed 27 August 2026 with schema48 unchanged, 20 services, full production contracts GREEN and runtime within budget.

## D. V3.20.2 Artifact Contract Hardening
Release objective: prevent malformed or wrong-contract internal artifacts from being silently interpreted as missing external evidence, without weakening legitimate fail-soft source behavior.

| ID | Task | Status | Acceptance |
| --- | --- | --- | --- |
| V3-ART-241 | Runtime Artifact Contract Registry | ACTIVE | `RUNTIME_ARTIFACT_CONTRACTS_V1` owns validation policy |
| V3-ART-242 | Generic declared-JSON parse validation | ACTIVE | every declared `.json` artifact parses before acceptance |
| V3-ART-243 | latest.json sidecar validation | ACTIVE | isolated latest sidecar must parse as object before merge |
| V3-ART-244 | Challenger observation explicit contract | ACTIVE | schema2 + `challenger_observation_v2` + observations list |
| V3-ART-245 | Valid-empty external state preservation | ACTIVE | empty observations accepted as legitimate fail-soft state |
| V3-ART-246 | Malformed artifact fail-closed semantics | ACTIVE | critical producer corruption blocks run |
| V3-ART-247 | Noncritical corruption stale-output quarantine | ACTIVE | old outputs cannot masquerade as current |
| V3-ART-248 | Non-isolated output integrity validation | ACTIVE | direct-canonical services are validated too |
| V3-ART-249 | Artifact-validation runtime metadata | ACTIVE | service result records acceptance validation state |
| V3-ART-250 | Deterministic artifact regression suite | ACTIVE | malformed JSON/wrong contract/valid-empty/nonisolated cases covered |
| V3-ART-251 | V3.20.2 release consistency | ACTIVE | version/readme/workflow/implementation/registries/tests/master aligned |
| V3-ART-252 | Full CI/integration acceptance | ACTIVE | compile/unit/architecture/source/decision/watchlist/report/report-time/runtime budget PASS |
| V3-ART-253 | Production acceptance | ACTIVE | merge + production collect + runtime-data + GREEN/HEALTHY/GO verified |

### V3.20.2 boundary decision
`read_json()` remains a convenience fail-soft reader for optional consumers. Integrity enforcement belongs at the service output acceptance boundary because that is where producer ownership, declared artifacts and criticality are known. This avoids making every optional read globally fail-closed while still preventing corrupt service outputs from becoming canonical truth.

### V3.20.2 schema decision
- Candidate engine: `3.20.2`.
- Serving/runtime schema: `48`, unchanged because user/report output structure does not change.
- Service Registry schema: `12`, because artifact acceptance semantics change.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V1`.

## E. P1 intelligence quality
| ID | Task | Status |
| --- | --- | --- |
| V3-INT-201 | Tactical-role evidence | OPEN |
| V3-INT-202 | Formation/system-fit evidence | OPEN |
| V3-INT-203 | Rotation/competition evidence | OPEN |
| V3-INT-204 | Set-piece role evidence | OPEN |
| V3-INT-205 | Penalty role evidence | OPEN |
| V3-INT-206 | International duty/travel/congestion | OPEN |
| V3-INT-207 | Settled-GW calibration | MONITOR |
| V3-INT-208 | Dynamic evidence-weight calibration | OPEN |
| V3-INT-209 | Model drift monitoring | OPEN |
| V3-INT-210 | Challenger scorecard accuracy weighting | OPEN |
| V3-INT-211 | Package optimizer sensitivity audit | OPEN |
| V3-INT-212 | Price/value calibration | OPEN |

## F. User-facing report UX
| ID | Task | Status |
| --- | --- | --- |
| V3-RPT-301 | Natural Bahasa Indonesia renderer | OPEN |
| V3-RPT-302 | Freshness/source-health block | ACTIVE |
| V3-RPT-303 | Decision-first report layout | MONITOR |
| V3-RPT-304 | Delta-first stable reports | MONITOR |
| V3-RPT-305 | Price Radar OWNED/WATCHLIST contract | ACTIVE |
| V3-RPT-306 | Scheduled-report completeness | OPEN |
| V3-RPT-307 | Deadline-mode governance | MONITOR |
| V3-RPT-308 | Match-mode governance | MONITOR |
| V3-RPT-309 | Confidence-language standard | OPEN |
| V3-RPT-310 | Scheduled report-time web refresh | ACTIVE |
| V3-RPT-311 | On-demand report-time web refresh | ACTIVE |
| V3-RPT-312 | Consensus-vs-DSS explanation | ACTIVE |

Every visible report must explicitly show recommended formation, exact XI, Captain, Vice-Captain, Bench 1/2/3 and GK Bench in addition to all 15 OWNED and 20 WATCHLIST players.

## G. P2 strategic capabilities
| ID | Task | Status |
| --- | --- | --- |
| V3-STR-401 | True overall-rank conversion | DEFERRED |
| V3-STR-402 | Live EO population model | DEFERRED |
| V3-STR-403 | Production ML projection | DEFERRED |
| V3-STR-404 | Full rival intelligence | DEFERRED |
| V3-STR-405 | Literal heatmap renderer | DEFERRED |
| V3-STR-406 | Advanced BGW/DGW simulator | OPEN |
| V3-STR-407 | Long-horizon chip optimizer | OPEN |

## H. Engineering hygiene
| ID | Task | Status |
| --- | --- | --- |
| V3-ENG-501 | Central config ownership audit | ACTIVE |
| V3-ENG-502 | Hardcode regression scan | ACTIVE |
| V3-ENG-503 | Registry integrity tests | ACTIVE |
| V3-ENG-504 | Production-contract regression | ACTIVE |
| V3-ENG-505 | Runtime performance regression | ACTIVE |
| V3-ENG-506 | Fail-closed critical / fail-soft optional | ACTIVE |
| V3-ENG-507 | README/task synchronization | ACTIVE |
| V3-ENG-508 | Historical version-reference hygiene | ACTIVE |
| V3-ENG-509 | Runtime artifact contract integrity | ACTIVE |

## Release checklist for every V3 change
1. Branch from current production `main`.
2. Update this Master Task List in the same PR.
3. Keep mutable values in the correct registry/config owner.
4. Update `src/version.py` when engine version changes.
5. Bump serving schema only for output-contract changes.
6. Keep README, IMPLEMENTATION_STATUS, workflow, engine schema, service/source/runtime-artifact/report registries and release tests consistent.
7. Compile runtime modules.
8. Full unit/regression suite PASS.
9. Architecture contract PASS.
10. Runtime artifact-contract regressions PASS when applicable.
11. Full bounded runtime PASS.
12. Source capability contract PASS.
13. Production decision/report contract PASS.
14. 15 OWNED + 20 WATCHLIST PASS.
15. Report serving PASS.
16. Report-time intelligence PASS.
17. Runtime budget PASS.
18. Merge only when PR is mergeable and CI GREEN.
19. Confirm production collector and `runtime-data` publication.
20. Verify Gate0 16/16, Core50, Extensions16, Enhancements8, overall GREEN, HEALTHY and GO.
21. Move candidate tasks to DONE only after production evidence exists.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation, version governance and production evidence agree. File existence, registry presence, source reachability, or a manually edited status label is insufficient.

For external evidence, missing values may never be synthesized merely to keep health GREEN. For runtime artifacts, malformed JSON or contract mismatch may never be downgraded to an ordinary `NO_OBSERVATION` state when the producing service declared that artifact as its output.

## Execution order
1. Keep V3.20.1 production GREEN while V3.20.2 is under acceptance.
2. Complete artifact-contract coding and deterministic regressions.
3. Full PR CI/integration.
4. Merge and production-validate V3.20.2/schema48.
5. Update production acceptance state and active Master Monitor baseline.
6. Continue P1 calibration and report UX work without destabilizing V3.
