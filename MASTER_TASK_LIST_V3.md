# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE  
Canonical roadmap owner: V3 operational stream  
Current production release: V3.23.1  
Current production schema: 49  
Production acceptance: COMPLETE  
FAST decision target: **<10 seconds**  
Active microservices: **20**

This file is the single human-readable roadmap for the operational V3 stream. Git history preserves detailed historical release notes; this file represents the **current canonical state**.

## Status legend
- **DONE PROD**: implemented, tested, merged and production-proven when runtime-impacting.
- **DONE FUNCTIONAL**: implementation is complete and does not require separate runtime activation.
- **CANDIDATE**: implemented on a release branch and deterministic acceptance is green, but production merge/publication is not yet complete.
- **MONITOR**: engineering is implemented but genuine season/runtime evidence must continue accumulating.
- **DEFERRED**: intentionally postponed until its dependency is justified.
- **REJECTED**: original recommendation is not adopted because a better architecture or control exists.

## Non-negotiable V3 invariants
1. Official FPL remains the only native authority for Official fields and scoring.
2. External/challenger/community/weather evidence may never overwrite Official-native truth.
3. Missing evidence is explicit; it is never fabricated to keep health GREEN.
4. OWNED is exactly 15 authoritative players.
5. WATCHLIST is exactly 20 external players, exactly 5 per position, excluding OWNED.
6. Gate0 must remain 16/16 PASS for unqualified GO.
7. DSS Core remains 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE.
8. Numerical formulas affecting decisions require deterministic regression tests.
9. Runtime data publishes to `runtime-data`, never protected `main`.
10. Runtime Git history is not a database; persistent history belongs in explicit compact ledgers.
11. Every declared JSON service artifact is validated before canonical promotion.
12. Critical internal artifact failure is fail-closed; optional external unavailability is fail-soft.
13. Weather remains advisory and may not directly mutate xPts/XI/C/VC/transfers/watchlist/packages without calibrated governance.
14. Formula correctness and predictive accuracy are separate claims; predictive accuracy requires settled frozen forecasts.
15. FAST decision regeneration targets <10s and may reuse only complete, fresh, contract-valid artifacts.
16. Service boundaries follow ownership/failure semantics, not a target service count.
17. Report readiness and model evidence readiness are separate states.
18. FACT/CONSTRAINT actions may remain actionable while MODEL_DERIVED recommendations can be calibration-gated.
19. Mutable runtime values belong to config/registry/environment owners, not scattered literals.
20. Every V3 change must leave `main`, CI, runtime contracts and `runtime-data` mutually consistent.
21. For every REC touching native or potentially native FPL facts, public Official FPL is attempted first; fallback requires an explicit `OFFICIAL_UNAVAILABLE`, `FIELD_NOT_EXPOSED`, or `PRIVATE_AUTH_REQUIRED` disposition. `OFFICIAL_NOT_APPLICABLE` is valid only for REC work that genuinely does not depend on Official data.
22. Finished personal GWs are Official actual truth; planning-GW points are projections and must never be presented as actual scores.
23. The previous Official submitted squad is the default planning baseline. WC/FH/user composition overrides must target the exact planning GW and may never leak into later GWs.
24. Explicit user XI/C/VC/chip overrides may replace the effective planning decision while preserving the engine recommendation for comparison; the engine may warn but may not silently overwrite the user decision.
25. Human-facing report surfaces use natural Bahasa Indonesia; raw decision enums remain machine/audit state and must not become the primary user narrative.
26. Required scheduled report checkpoints are explicit, persisted and auditable. A due checkpoint that was not completed must surface as missed rather than silently appearing complete.

## Current production health contract
| Area | Requirement | Current policy |
| --- | --- | --- |
| Gate0 | 16/16 PASS | required for GO |
| DSS | Core50 / Ext16 / Enh8 ACTIVE | required |
| Decision engine | HEALTHY | required |
| FAST runtime | <10s target | production SLO |
| Runtime publication | rolling parentless snapshot | required |
| Runtime source | `runtime-data` | authoritative current-state branch |
| Official-first REC coverage | explicit matrix + closed fallback dispositions | production active through REC-40 |
| Authenticated Official | optional/read-only/fail-soft | MONITOR |
| Predictive calibration | settled frozen forecasts only | MONITOR |
| Price calibration | realized price-change samples only | MONITOR |
| Report-time web evidence | READY/PENDING separate from engine health | required semantics |
| Personal GW history | Official submitted/history actual truth | production active via REC-39 |
| Planning team score | labelled estimated xPts, never actual | production active via REC-39 |
| User decision override | explicit only; engine comparison retained | production active via REC-39 |
| Natural user presentation | primary human-facing surface | production active via REC-40 |
| Scheduled report checkpoints | 04:30 / 12:30 / 21:30 WIB, explicit missed state | production active via REC-40 |

## Historical release anchors
### V3.20 Architecture Hardening
Canonical Source Registry ownership, monolith removal, generic DAG scheduling, artifact-owned services, config ownership, architecture anti-regression and production contracts were established in the V3.20 line and remain non-negotiable foundations.

### V3.20.1 Correctness Hardening
Appearance probability, GK position/save routing, captain variance/covariance, promotion failure semantics, legacy direct-fetch removal and XI battle configuration were hardened and production accepted.

### V3.20.2 Artifact Contract Hardening
Strict JSON/artifact contracts, challenger observation validation, valid-empty fail-soft semantics, stale-output quarantine and canonical-promotion integrity were production accepted.

### V3.21 Weather Intelligence + Report Transparency
Weather became advisory-only contextual evidence, all 15 OWNED became selection-auditable, and predictive accuracy was explicitly separated from deterministic formula correctness.

### V3.22 Runtime Optimization Foundation
FAST/LIVE/FULL/DEEP execution profiles, rolling runtime-data, shallow checkout, resource telemetry, safe reuse and <10s FAST decision regeneration became the production operating model.

### V3.23 Personal Gameweek Context + User Decision Authority
Production release adds Official actual finished-GW history, planning-GW estimated team points, exact-GW WC/FH/user baseline authority, and explicit user XI/C/VC/chip override while preserving engine comparison. It is additive to the existing report-serving boundary, keeps schema 49, retains `REPORT_ARTIFACT_REGISTRY_V3` / `DEEP_REVIEW_PAYLOAD_V2`, and does not add a microservice.

### V3.23.1 Report Completeness + Natural Presentation
REC-40 is production accepted. Natural Bahasa Indonesia is the primary human-facing presentation while raw machine decisions remain audit/API compatible. Persistent completeness covers the 04:30, 12:30 and 21:30 WIB checkpoints and missed due checkpoints are explicit. PR #85 final candidate CI `33091248132` passed compile, architecture, **203 tests** and composite FULL/FAST acceptance. It was squash-merged as `e30123f7a12634b770ca1ab501aa3914bd7506ae`; main CI `33091398189` passed 203 tests; production FAST run `33091398202` completed in **6.326s** and published a 48-file rolling snapshot to `runtime-data` commit `dd9e134`. Schema remains 49 and service count remains 20.

## REC-01 through REC-40 canonical status
| REC | Work item | Status | Current evidence / disposition |
| --- | --- | --- | --- |
| REC-01 | Player-specific Defensive Contribution | **DONE PROD** | PR #63; player-specific threshold probability with shrinkage and GK ineligibility. |
| REC-02 | Robust early-season attacking rates | **DONE PROD** | PR #65; evidence-aware xG/xA shrinkage, bounded extremes and breakout relaxation. |
| REC-03 | Mini-league-aware captain risk mode | **DEFERRED** | Wait for sufficient rival/objective and settled evidence. |
| REC-04 | Settled prediction validation | **MONITOR** | Frozen forecast settlement exists; genuine completed pre-deadline samples must accumulate. |
| REC-05 | Mini-league tracking | **DONE PROD** | Official-entry league discovery plus bounded rank/gap/trend tracking. |
| REC-06 | Report transparency | **DONE PROD** | All 15 OWNED expose xPts, uncertainty, xMins, selection score and lineup/choice state. |
| REC-07 | Confidence calibration | **MONITOR** | Early-season conservative guard active; confidence needs realized outcomes. |
| REC-08 | Authenticated 3xx handling | **DONE PROD** | Redirects explicitly rejected and never persisted. |
| REC-09a | Git/runtime-data hygiene | **DONE PROD** | Mutable runtime removed from main; rolling runtime-data active. |
| REC-09b | Rewrite whole Git history | **DEFERRED / NOT REQUIRED** | Rolling runtime snapshot removed the operational need. |
| REC-10 | Delete `src/engine.py` | **DEFERRED** | Compatibility facade retained until usage reaches zero. |
| REC-11 | Composite release acceptance | **DONE PROD** | FULL + contracts + resource guard + FAST + SLO fail-closed runner. |
| REC-12 | Runtime acceptance vs predictive validation terminology | **DONE FUNCTIONAL** | Claims explicitly separated. |
| REC-13 | Version-neutral test ownership | **DONE PROD** | Domain-owned active tests; version-stamped runtime tests prohibited. |
| REC-14 | Reduce 20 services to ~8 | **REJECTED AS WRITTEN** | Service count is not a KPI; ownership/performance evidence governs boundaries. |
| REC-15 | Runtime SLO + profiler | **DONE PROD** | FAST target and wall/RSS/I/O telemetry active. |
| REC-16 | FAST/LIVE/FULL/DEEP profiles | **DONE PROD** | Profile-specific execution/reuse active. |
| REC-17 | Remove `official_detail` from FAST blocking path | **DONE PROD CORE** | Fresh complete artifact may be safely reused. |
| REC-18 | Source/weather freshness reuse | **DONE PROD CORE** | TTL-aware reuse active. |
| REC-19 | Persistent runtime reuse/cache | **DONE PROD CORE** | Cross-run artifact reuse active. |
| REC-20 | Player Feature Contract | **DONE PROD + CONSUMED** | Normalized feature artifact is production active and consumed by REC-01. |
| REC-21 | DSS evidence maturity semantics | **DONE PROD** | NATIVE/DERIVED/PROXY/SAFE_FALLBACK/UNAVAILABLE separated from module health. |
| REC-22 | Price predictor health/calibration | **MONITOR** | Realized Official price movement is truth; timing/direction accuracy remains WARMUP. |
| REC-23 | Authenticated Official bootstrap/hardening | **MONITOR** | Private precision remains optional; public Official first where sufficient. |
| REC-24 | Runtime manifest/publication hygiene | **DONE PROD** | Provenance, whitelist and rolling publication production-proven. |
| REC-25 | Final-report evidence readiness | **DONE PROD** | ENGINE_READY separated from final report evidence readiness. |
| REC-26 | Model-derived Actionability Gate | **MONITOR** | MODEL_DERIVED actions remain gated until settled evidence eligibility. |
| REC-27 | Mini-League Strategy State microservice | **DEFERRED / CONDITIONAL** | Add only when rival/EO strategy justifies a separate owner. |
| REC-28 | Split CI / FAST / FULL-DEEP workflows | **DONE PROD** | Workload/cadence separated. |
| REC-29 | Rolling runtime snapshot + shallow checkout | **DONE PROD** | Parentless rolling publication and shallow fetch proven. |
| REC-30 | Runtime resource budget guard | **DONE PROD** | Wall/RSS/resource regression guard active. |
| REC-31 | Profile-aware REUSED validation | **DONE PROD** | Only declared complete contract-valid reuse is accepted. |
| REC-32 | Reused latest-state carry-forward | **DONE PROD** | Registry-owned canonical state survives base fan-in. |
| REC-33 | FULL Source-Layer latency variance | **DONE ENGINEERING / MONITOR** | Bounded concurrency/freshness active; network/provider variance monitored. |
| REC-34 | Player-feature contract migration fence | **DONE PROD** | Contract regenerated and normal reuse TTL restored. |
| REC-35 | Compact projection diagnostics | **DONE PROD** | Duplicate diagnostics removed without formula/decision change. |
| REC-36 | Official historical reconciliation + GW1 proxy baseline | **DONE PROD** | Official history/picks own historical submitted truth; retrospective proxy cannot count as old forecast. |
| REC-37 | Official-detail migration fence closeout | **DONE PROD** | Migration published and normal FAST/LIVE reuse TTL restored. |
| REC-38 | Official-First REC Coverage Contract | **DONE PROD** | Explicit closed matrix enforced by source contract. |
| REC-39 | Personal Gameweek Context + User Decision Authority | **DONE PROD** | PR #82; final CI + production FAST publication proven. |
| REC-40 | Report Completeness + Natural Presentation | **DONE PROD** | PR #85; final candidate CI `33091248132`, main CI `33091398189`, production FAST `33091398202`; runtime-data `dd9e134`. |

## Production evidence
- REC-38 production FULL run `33077874024`: 8.410s, contracts PASS, Gate0 16/16, framework GREEN, prediction quality HEALTHY, 15 OWNED + 20 WATCHLIST, Official-first matrix integrity proven.
- REC-39 PR #82 final CI `33082069327`: 199 tests PASS + composite FULL/FAST acceptance. Production FAST run `33082344334`: 5.124s and rolling runtime-data publication succeeded.
- REC-40 PR #85 final candidate CI `33091248132`: compile PASS, architecture PASS, **203 tests PASS**, composite FULL/FAST acceptance PASS.
- REC-40 squash merge source `e30123f7a12634b770ca1ab501aa3914bd7506ae`; merged-main CI `33091398189` passed **203 tests**.
- REC-40 production FAST run `33091398202`: **6.326s**, source/production/watchlist/report-serving/report-time contracts PASS, Gate0 16/16, framework GREEN, prediction quality HEALTHY, 15 OWNED + 20 WATCHLIST, Official-first matrix **41/41**, and 48 files / 18,759,921 bytes published to rolling `runtime-data` commit `dd9e134`.
- Production schema remains **49** and active service count remains **20**.

## Calibration / operational monitors that must remain yellow honestly
| Monitor | Why it cannot be forced green |
| --- | --- |
| REC-04 settled prediction validation | Needs genuine completed GWs that were frozen pre-deadline. |
| REC-07 confidence calibration | Confidence distribution must be validated against realized Official outcomes. |
| REC-22 price direction/timing calibration | Requires actual Official price movements after predictions. |
| REC-23 authenticated private precision | Unpublished current pre-deadline draft requires authorized private access; public historical/submitted state is already green. |
| REC-26 model actionability | Requires prediction evaluation to become dynamically eligible from settled evidence. |
| REC-33 FULL latency | Provider/network variance remains an operational metric after engineering fixes. |

## Engineering hygiene
| Task | Status |
| --- | --- |
| Config ownership / anti-hardcode | ACTIVE |
| Registry integrity | ACTIVE |
| Official-first REC coverage / explicit fallback disposition | ACTIVE |
| Runtime artifact contracts | ACTIVE |
| Production/report/source/watchlist contracts | ACTIVE |
| FAST <10s + resource telemetry | ACTIVE |
| Rolling runtime-data storage hygiene | ACTIVE |
| Version-neutral active test ownership | ACTIVE |
| Scheduled report completeness | ACTIVE |
| Natural user-report language | ACTIVE |
| README / Implementation Status / Master Task synchronization | ACTIVE |

## Composite release checklist for every V3 change
1. Branch from current production `main`.
2. Keep mutable policy in its config/registry/environment owner.
3. Update version/schema only when the relevant contract changes.
4. Compile + architecture + full deterministic tests PASS.
5. For any REC touching FPL facts, validate Official-first coverage and require explicit fallback disposition before external/proxy evidence is accepted.
6. Run composite FULL acceptance: source, production, watchlist, serving and report-time contracts + resource guard.
7. Run FAST after FULL and enforce <10s SLO.
8. Merge only when CI is GREEN and the change is attributable.
9. Confirm `runtime-data` publication for runtime-impacting changes.
10. Verify Gate0 16/16, DSS 50/16/8, framework GREEN and Decision Engine HEALTHY.
11. Keep Master Task, Implementation Status and README consistent with actual evidence.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation and required production evidence agree. A file existing, a source being reachable, or a manually edited status label is not proof. Predictive accuracy, confidence quality, price accuracy and causal weather claims require genuine realized samples.

## Execution order from here
1. Keep V3.23.1 production GREEN and treat REC-40 natural presentation/checkpoint completeness as the production report-serving contract.
2. Preserve REC-39 personal-gameweek authority while keeping report-time external evidence readiness separate from engine health.
3. Accumulate settled-GW, confidence, price and weather calibration evidence without forcing status upgrades.
4. Use public Official data first for every applicable REC; authenticated Official precision remains optional/fail-soft where public Official cannot expose private state.
5. Improve remaining P1 intelligence only through attributable changes that preserve Official authority, report truthfulness and production stability.
