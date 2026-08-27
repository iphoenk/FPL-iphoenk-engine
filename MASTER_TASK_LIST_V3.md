# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE
Canonical roadmap owner: V3 operational stream
Current production release: V3.22.0
Current production schema: 49
Accepted production baseline: V3.22.0 / schema49
Production acceptance: COMPLETE
Accepted source commit: `3f35c06f39869e594f6e1a127437a2272c0fc515`
Accepted production run: `33059540147`
Accepted runtime-data commit: `5678fcb2f4f8e5934728ff6a8b955a401a42883d`
Accepted FAST runtime: 6.419s / target <10s
Accepted scope: Runtime Optimization Foundation, Fast <10s, Resource/Storage Governance, Decision-Neutral Player Features, REC-31/REC-32 reuse correctness

This file is the single human-readable master roadmap for the operational V3 stream. Every V3 feature, refactor, hardening change and release-governance change must update this file in the same pull request.

## Status legend
- DONE: implemented, tested, merged and production-validated when runtime-impacting.
- ACTIVE: continuously enforced requirement or release-candidate item under acceptance.
- NEXT: highest-priority planned work.
- OPEN: planned but not immediate.
- BLOCKED: dependency prevents progress.
- DEFERRED: intentionally postponed.
- MONITOR: implemented but needs continuing runtime/calibration evidence.

## Non-negotiable V3 invariants
1. Official FPL remains the only native authority for Official fields and scoring.
2. Challenger, enrichment, report-time expert, community and weather sources may never overwrite Official-native truth.
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
25. Weather is observational/advisory context and may not directly mutate xPts, XI, C/VC, transfers, watchlist or packages until calibrated governance explicitly permits it.
26. Rain probability is not rainfall intensity.
27. Every visible report must make all 15 OWNED selection evidence auditable with current-GW xPts, uncertainty, selection score and lineup/choice state.
28. Formula correctness and predictive accuracy are separate claims; predictive accuracy requires settled frozen forecasts.
29. Confidence labels must be monitored for calibration drift rather than forced to HIGH.
30. FAST decision regeneration has a 10-second target and may reuse only complete, contract-valid, fresh artifacts.
31. Runtime Git history is not a database; persistent domain history belongs in explicit compact ledgers.
32. Runtime optimization may not silently opt normalized player features into model behavior.
33. A reused service must preserve only its registry-owned canonical latest state through base fan-in; unrelated prior state may not be carried forward.
34. Weather refresh must reuse confidence-appropriate fresh observations and bound concurrent provider requests; FULL latency may not be reduced by unbounded worker fan-out.

## A. Production keep-green
| ID | Task | Status | Acceptance |
| --- | --- | --- | --- |
| V3-OPS-001 | Gate0 hard constraints | DONE | 16/16 PASS |
| V3-OPS-002 | DSS Core health | DONE | 50/50 ACTIVE |
| V3-OPS-003 | DSS Extension health | DONE | 16/16 ACTIVE |
| V3-OPS-004 | Enhancement health | DONE | 8/8 ACTIVE |
| V3-OPS-005 | 15 OWNED + 20 WATCHLIST | ACTIVE | exact counts, 5/position, no overlap |
| V3-OPS-006 | Official authority / fail-soft optional sources | ACTIVE | no external overwrite |
| V3-OPS-007 | Isolated runtime-data publication | ACTIVE | validated rolling current-state publication only |
| V3-OPS-008 | Runtime performance | MONITOR | FAST target <10s; FULL separate budget |
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
| V3-ARCH-201 | Canonical Source Registry and remove legacy config | DONE |
| V3-ARCH-202 | Registry-owned collector cadence/windows | DONE |
| V3-ARCH-203 | Remove active monolithic collector | DONE |
| V3-ARCH-204 | Official snapshot single owner | DONE |
| V3-ARCH-205 | Team/market/live/advanced-stats/base-snapshot ownership | DONE |
| V3-ARCH-206 | Generic root DAG scheduling | DONE |
| V3-ARCH-207 | Current stats aliases | DONE |
| V3-ARCH-208 | Semantic model IDs | DONE |
| V3-ARCH-209 | Deep-stats runtime-data publication | DONE |
| V3-ARCH-210 | Architecture anti-regression gate | DONE |
| V3-ARCH-211 | Framework mutable-policy ownership | DONE |
| V3-ARCH-212 | Microservice over-splitting review | DONE |
| V3-ARCH-213 | Full CI/production acceptance | DONE |

### V3.20.1 Correctness Hardening
Appearance probability, GK `element_type`/save route, captain variance/covariance, promotion failure semantics, obsolete direct-fetch projection removal, config-owned XI battle threshold, challenger failure-class semantics and package-vs-final-XI boundary are DONE and production accepted.

### V3.20.2 Artifact Contract Hardening
Strict JSON validation, latest sidecar validation, challenger observation contract, valid-empty fail-soft handling, stale-output quarantine, non-isolated validation and production artifact-validation metadata are DONE and production accepted.

## C. V3.21 Weather Intelligence + Report Transparency
Release objective: add weather as bounded explanatory context, make lineup choices transparent for every owned player, and expose calibration/settled-validation state without overclaiming predictive accuracy.

| ID | Task | Status | Acceptance |
| --- | --- | --- | --- |
| V3-WXR-601 | Open-Meteo Source Registry capability | DONE | noncritical ENRICHMENT; no authority/challenger role |
| V3-WXR-602 | No new weather microservice | DONE | active service count stays 20; Source Layer owns weather |
| V3-WXR-603 | Reuse Official fixture snapshot | DONE | no standard Official fixture refetch from weather code |
| V3-WXR-604 | Venue Registry | DONE | 20 current PL team venues; Official team ID + name identity; unique registry-owned coordinates |
| V3-WXR-605 | Weather policy config ownership | DONE | endpoint/timeout/fields/horizon/freshness/severity outside Python |
| V3-WXR-606 | Weather variables | DONE | temp, precip probability, precip intensity, wind speed/gusts, weather code |
| V3-WXR-607 | Forecast retention / closest kickoff observation | DONE | bounded observations; post-match context uses closest retained evidence |
| V3-WXR-608 | Weather fail-soft semantics | DONE | provider/venue/window gaps do not block Official/DSS baseline |
| V3-WXR-609 | Weather decision-authority guard | DONE | cannot directly mutate xPts/XI/C/VC/transfer/watchlist/package |
| V3-WXR-610 | Post-match anomaly attribution guard | DONE | only `POSSIBLE_CONTRIBUTING_FACTOR`; alternatives required |
| V3-WXR-611 | Weather artifact contract | DONE | `fixture_weather.json` contract-validated before promotion |
| V3-WXR-612 | Owned 15 xPts transparency | DONE | all 15 report rows expose current-GW xPts + uncertainty |
| V3-WXR-613 | Owned lineup/choice transparency | DONE | all 15 expose selection score, START/BENCH and OPEN/CURRENT state |
| V3-WXR-614 | Confidence calibration monitor | DONE | zero HIGH before GW5 allowed; GW5+ triggers review if still absent |
| V3-WXR-615 | Settled prediction validation visibility | DONE | serving reports expose sample/status and accuracy-governance disclaimer |
| V3-WXR-616 | Source/Report/Runtime registry bumps | DONE | SOURCE V4, REPORT V3, RUNTIME ARTIFACT V2 consistent |
| V3-WXR-617 | V3.21 schema change | DONE | schema49 because required serving fields changed |
| V3-WXR-618 | Deterministic weather/transparency tests | DONE | severity, registry, no-service, confidence, selection and report contracts covered |
| V3-WXR-619 | Architecture/source/report contract gates | DONE | all applicable validators PASS |
| V3-WXR-620 | Full CI/integration/runtime budget | DONE | unit + bounded runtime + 16.606s <45s PASS |
| V3-WXR-621 | Production acceptance | DONE | production run 33047071671; runtime-data source commit `da2be79045c0eb1015b75697eb24b030ffaa4abe`; 10/10 weather coverage; zero unresolved venue identity |
| V3-WXR-622 | Master Monitor V3.21 sync | DONE | authoritative task validated 3.21.0/schema49, SOURCE V4, selection score, weather context and model-validation fields |

### V3.21 model-validation decision
`prediction_evaluation.py` freezes the last pre-deadline forecast and settles completed Gameweeks using points MAE/RMSE, xMins MAE, starter Brier, clean-sheet Brier and Spearman. Predictive accuracy claims require settled samples.

## C2. V3.22 Runtime Optimization Foundation
Release objective: make frequent decision regeneration fast and resource-aware without changing serving schema, model behavior, Official authority or the 20-service domain boundary.

| REC | Work item | Production status | Acceptance evidence |
| --- | --- | --- | --- |
| REC-15 | Runtime SLO + profiler/resource telemetry | DONE | FAST target 10s; parent/child RSS and I/O telemetry production-proven |
| REC-16 | FAST/LIVE/FULL/DEEP execution profiles | DONE | profile registry + bounded worker limits production-proven |
| REC-17 | Decouple heavy official detail from FAST via fresh reuse | PHASE-1 DONE / ACCEPTED | `official_detail` reused in 7.8ms on accepted production run |
| REC-18 | Source/weather freshness reuse | PHASE-1 DONE / ACCEPTED | `source_layer` reused in 0.76ms on accepted production run |
| REC-19 | Persisted runtime-artifact reuse | PHASE-1 DONE / ACCEPTED | reusable state retained across production FAST cycle |
| REC-20 | Normalized player-feature contract | PHASE-1 DONE / ACCEPTED | prediction path unchanged; decision-neutral regression retained |
| REC-28 | Split CI / FAST / FULL-DEEP workflows | DONE | production FAST and background FULL ownership separated |
| REC-29 | Shallow checkout + whitelist + rolling runtime-data | DONE / PRODUCTION-PROVEN | parentless root snapshot; 48 files / ~17.84MB; `history.jsonl` absent |
| REC-30 | Runtime resource regression guard | DONE | accepted FAST 85.3MB parent / 109.5MB child peak RSS |
| REC-31 | Profile-aware REUSED validation + complete source hydrate | DONE | only declared, artifact-validated REUSED states accepted |
| REC-32 | Registry-owned reusable latest-state carry-forward | DONE | production contracts and publication PASS after FAST reuse |
| REC-09a | Stop new mutable data tracking on main | PHASE-1 DONE | `/data/**` ignored; tracked legacy cleanup deferred until cold-start proof |
| REC-33 | FULL Refresh Source-Layer latency variance | IMPLEMENTED / CI-PROVEN | CI `33061348137`: 154 tests PASS; FULL 17.068s; Source Layer 3.043s; FAST 5.268s; production proof pending |

Production acceptance evidence:
- Foundation CI `33055271837`: architecture PASS, 147 tests PASS, FULL 18.656s, FAST 5.160s.
- Foundation CI `33055599122`: architecture PASS, 148 tests PASS including REC-20 guard, FULL 18.151s, FAST 5.113s.
- REC-32 CI `33059384073`: **150 tests PASS**, all integration contracts PASS, FAST **4.602s**.
- Accepted production run `33059540147`: FAST **6.419s**, framework GREEN, prediction quality HEALTHY, Gate0 16/16, 15 OWNED + 20 WATCHLIST, source/report/report-time contracts PASS.
- Accepted runtime-data commit `5678fcb2f4f8e5934728ff6a8b955a401a42883d` is a **root commit with zero parents**, proving rolling publication rather than runtime Git-history accumulation.
- Accepted runtime manifest: V3.22.0/schema49, source commit `3f35c06f39869e594f6e1a127437a2272c0fc515`, 48 files, 17,835,453 bytes, no `history.jsonl` publication.
- REC-33 CI `33061348137`: FULL **17.068s**, `source_layer` **3.043s**, FAST **5.268s**, with bounded weather concurrency and confidence-aware fresh observation reuse.
- Report-time external intelligence may remain `REFRESH_REQUIRED`; that is a truthful report-time state and not a runtime-integrity failure.

V3.22 does not implement REC-01 or REC-02 model changes. `player_features.json` remains plumbing-only until those recommendations are separately developed, tested and attributed.

## D. P1 intelligence quality
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
| V3-INT-213 | Weather-performance historical calibration | MONITOR |

## E. User-facing report UX
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
| V3-RPT-309 | Confidence-language standard | ACTIVE |
| V3-RPT-310 | Scheduled report-time web refresh | ACTIVE |
| V3-RPT-311 | On-demand report-time web refresh | ACTIVE |
| V3-RPT-312 | Consensus-vs-DSS explanation | ACTIVE |
| V3-RPT-313 | All-15 xPts/selection/choice transparency | ACTIVE |
| V3-RPT-314 | Settled-prediction/calibration status | ACTIVE |
| V3-RPT-315 | Material weather context / anomaly caveat | ACTIVE |

Every visible report must explicitly show recommended formation, exact XI, Captain, Vice-Captain, Bench 1/2/3 and GK Bench, all 15 OWNED, all 20 WATCHLIST, and the V3.21+ owned transparency fields.

## F. P2 strategic capabilities
| ID | Task | Status |
| --- | --- | --- |
| V3-STR-401 | True overall-rank conversion | DEFERRED |
| V3-STR-402 | Live EO population model | DEFERRED |
| V3-STR-403 | Production ML projection | DEFERRED |
| V3-STR-404 | Full rival intelligence | DEFERRED |
| V3-STR-405 | Literal heatmap renderer | DEFERRED |
| V3-STR-406 | Advanced BGW/DGW simulator | OPEN |
| V3-STR-407 | Long-horizon chip optimizer | OPEN |
| V3-STR-408 | Calibrated causal weather-performance model | DEFERRED |

## G. Engineering hygiene
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
| V3-ENG-510 | Weather no-direct-decision regression | ACTIVE |
| V3-ENG-511 | FAST <10s SLO and resource telemetry | ACTIVE |
| V3-ENG-512 | Rolling runtime-data publication / storage hygiene | ACTIVE |
| V3-ENG-513 | REC-33 FULL Source Layer latency variance | ACTIVE / ACCEPTANCE PENDING |

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
17. Runtime/resource budget PASS.
18. Merge only when PR is mergeable and CI GREEN.
19. Confirm production collector and `runtime-data` publication.
20. Verify Gate0 16/16, Core50, Extensions16, Enhancements8, overall GREEN, HEALTHY and GO.
21. Verify rolling publication manifest, whitelist, shallow-fetch policy and no unwanted runtime-history artifact.
22. Move candidate tasks to DONE only after production evidence exists.
23. Update FPL Master Monitor version/schema only after production acceptance.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation, version governance and production evidence agree. File existence, registry presence, source reachability, or a manually edited status label is insufficient.

For external evidence, missing values may never be synthesized merely to keep health GREEN. For weather, correlation alone may never be presented as causation. For runtime artifacts, malformed JSON or contract mismatch may never be downgraded to an ordinary no-observation state when the producing service declared that artifact as its output. For prediction quality, passing deterministic formula tests is not evidence of forecasting accuracy; settled frozen forecasts are required.

## Execution order
1. Complete REC-33 production proof without weakening the accepted FAST <10s path.
2. Accumulate settled Gameweeks for projection-confidence and weather-performance calibration.
3. Implement REC-01 and REC-02 as separate, attributable model changes after normalized player-feature plumbing is accepted.
4. Improve remaining P1 intelligence evidence without weakening Official authority or fail-closed internal integrity.
5. Pursue P2 capabilities only when production V3 remains stable and their evidence contracts are explicit.
