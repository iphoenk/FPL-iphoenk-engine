# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE  
Canonical roadmap owner: V3 operational stream  
Current production release: V3.23.1  
Current production schema: 49  
Production acceptance: COMPLETE  
Current release candidate: V3.24.0  
Current candidate schema: 49  
Candidate acceptance: FEATURE CI ACCEPTED / FINAL RELEASE CI PENDING  
FAST decision target: **<10 seconds**  
Active microservices: **20**

This file is the single human-readable roadmap for the operational V3 stream. Git history preserves detailed historical release notes; this file represents the **current canonical state**.

## Status legend
- **DONE PROD**: implemented, tested, merged and production-proven when runtime-impacting.
- **DONE FUNCTIONAL**: implementation complete without separate runtime activation.
- **CANDIDATE**: implemented and deterministic feature acceptance is green, but final release CI/merge/publication is not complete.
- **MONITOR**: engineering exists but genuine season/runtime evidence must accumulate.
- **DEFERRED**: intentionally postponed until dependencies justify it.
- **REJECTED**: original recommendation not adopted because a better control exists.

## Non-negotiable V3 invariants
1. Official FPL is the only native authority for Official fields and scoring.
2. External/challenger/community/weather/tactical enrichment may never overwrite Official-native truth.
3. Missing evidence is explicit; it is never fabricated to keep health GREEN.
4. OWNED is exactly 15 authoritative players.
5. WATCHLIST is exactly 20 external players, exactly 5 per position, excluding OWNED.
6. Gate0 must remain 16/16 PASS for unqualified GO.
7. DSS Core 50/50, Extensions 16/16 and Enhancements 8/8 remain ACTIVE.
8. Numerical formulas affecting decisions require deterministic regression tests.
9. Runtime data publishes to `runtime-data`, never protected `main`.
10. Runtime Git history is not a database.
11. Every declared JSON service artifact is validated before canonical promotion.
12. Critical internal artifact failure is fail-closed; optional external unavailability is fail-soft.
13. Weather remains advisory and cannot directly mutate decisions without calibrated governance.
14. Formula correctness and predictive accuracy are separate claims; predictive accuracy requires settled frozen forecasts.
15. FAST decision regeneration targets <10s and may reuse only complete, fresh, contract-valid artifacts.
16. Service boundaries follow ownership/failure semantics, not a target service count.
17. Report readiness and model evidence readiness are separate states.
18. FACT/CONSTRAINT actions may remain actionable while MODEL_DERIVED recommendations are calibration-gated.
19. Mutable runtime values belong to config/registry/environment owners.
20. Every V3 change must leave `main`, CI, runtime contracts and `runtime-data` mutually consistent.
21. Applicable REC work attempts public Official first; fallback requires an explicit allowed disposition.
22. Finished personal GWs are Official actual truth; planning-GW points are projections.
23. Previous Official submitted squad is default planning baseline; WC/FH/user composition overrides must target the exact planning GW.
24. Explicit user XI/C/VC/chip overrides preserve engine recommendation for comparison and may not be silently overwritten.
25. Human-facing report surfaces use natural Bahasa Indonesia; raw enums remain machine/audit state.
26. Required report checkpoints are explicit, persisted and auditable; missed due checkpoints surface as missed.
27. Tactical-role/system evidence must distinguish evidence from inference. `FPL_POSITION_SHAPE` is not a claim of true tactical formation.
28. REC-41 tactical/system evidence remains advisory-only in V3.24.0 and may not mutate xMins or xPts without a later calibrated model opt-in.

## Current health contract
| Area | Requirement | State |
| --- | --- | --- |
| Gate0 | 16/16 PASS | production required |
| DSS | 50 / 16 / 8 ACTIVE | production required |
| FAST runtime | <10s | production SLO |
| Runtime publication | rolling parentless snapshot | required |
| Official-first | closed explicit matrix | production through REC-40; V3.24 candidate through REC-41 |
| Predictive calibration | settled frozen forecasts | MONITOR |
| Price calibration | realized Official movement | MONITOR |
| Auth private precision | optional/fail-soft | MONITOR |
| Personal GW context | actual history + labelled planning xPts | production REC-39 |
| Natural report + checkpoints | 04:30 / 12:30 / 21:30 WIB | production REC-40 |
| Tactical role/system evidence | evidence-only, no xMins/xPts adjustment | V3.24 candidate REC-41 |

## Historical release anchors
### V3.20 Architecture Hardening
Canonical Source Registry ownership, generic DAG scheduling, artifact-owned services, config ownership and production contracts established the current architecture.

### V3.20.1 Correctness Hardening
Appearance probability, GK routing, captain variance/covariance, promotion failure semantics and lineup configuration were hardened.

### V3.20.2 Artifact Contract Hardening
Strict artifact contracts, valid-empty semantics, quarantine and canonical-promotion integrity were production accepted.

### V3.21 Weather Intelligence + Report Transparency
Weather became advisory-only and all 15 OWNED became selection-auditable.

### V3.22 Runtime Optimization Foundation
FAST/LIVE/FULL/DEEP profiles, rolling runtime-data, safe reuse and <10s FAST became the operating model.

### V3.23 Personal Gameweek Context + User Decision Authority
Official finished-GW actuals, planning-GW estimated team points, exact-GW WC/FH/user baseline authority and explicit user XI/C/VC/chip overrides became production active.

### V3.23.1 Report Completeness + Natural Presentation
REC-40 made natural Bahasa Indonesia the primary human-facing surface and persisted 04:30/12:30/21:30 checkpoint completeness. Production FAST run `33091398202` completed in 6.326s.

### V3.24 Tactical Role & System Evidence
REC-41 candidate derives observed player attacking-role profiles and team `FPL_POSITION_SHAPE` from current advanced match evidence while Official identity/FPL position remains authority. Missing evidence is explicit. Role/system evidence is published through the existing Player Feature Contract and projection artifact. It is **ADVISORY_ONLY**: no xMins or xPts rate adjustment is applied. PR #89 feature CI `33129623527` passed compile, architecture, **208 tests**, FULL **17.020s**, FAST **4.711s** and all composite gates.

## REC-01 through REC-41 canonical status
| REC | Work item | Status |
| --- | --- | --- |
| REC-01 | Player-specific Defensive Contribution | **DONE PROD** |
| REC-02 | Robust early-season attacking rates | **DONE PROD** |
| REC-03 | Mini-league-aware captain risk mode | **DEFERRED** |
| REC-04 | Settled prediction validation | **MONITOR** |
| REC-05 | Mini-league tracking | **DONE PROD** |
| REC-06 | Report transparency | **DONE PROD** |
| REC-07 | Confidence calibration | **MONITOR** |
| REC-08 | Authenticated 3xx handling | **DONE PROD** |
| REC-09a | Git/runtime-data hygiene | **DONE PROD** |
| REC-09b | Rewrite whole Git history | **DEFERRED / NOT REQUIRED** |
| REC-10 | Delete `src/engine.py` | **DEFERRED** |
| REC-11 | Composite release acceptance | **DONE PROD** |
| REC-12 | Runtime acceptance vs predictive validation terminology | **DONE FUNCTIONAL** |
| REC-13 | Version-neutral test ownership | **DONE PROD** |
| REC-14 | Reduce 20 services to ~8 | **REJECTED AS WRITTEN** |
| REC-15 | Runtime SLO + profiler | **DONE PROD** |
| REC-16 | FAST/LIVE/FULL/DEEP profiles | **DONE PROD** |
| REC-17 | Remove `official_detail` from FAST blocking path | **DONE PROD CORE** |
| REC-18 | Source/weather freshness reuse | **DONE PROD CORE** |
| REC-19 | Persistent runtime reuse/cache | **DONE PROD CORE** |
| REC-20 | Player Feature Contract | **DONE PROD + CONSUMED** |
| REC-21 | DSS evidence maturity semantics | **DONE PROD** |
| REC-22 | Price predictor health/calibration | **MONITOR** |
| REC-23 | Authenticated Official bootstrap/hardening | **MONITOR** |
| REC-24 | Runtime manifest/publication hygiene | **DONE PROD** |
| REC-25 | Final-report evidence readiness | **DONE PROD** |
| REC-26 | Model-derived Actionability Gate | **MONITOR** |
| REC-27 | Mini-League Strategy State | **DEFERRED / CONDITIONAL** |
| REC-28 | Split CI / FAST / FULL-DEEP workflows | **DONE PROD** |
| REC-29 | Rolling runtime snapshot + shallow checkout | **DONE PROD** |
| REC-30 | Runtime resource budget guard | **DONE PROD** |
| REC-31 | Profile-aware REUSED validation | **DONE PROD** |
| REC-32 | Reused latest-state carry-forward | **DONE PROD** |
| REC-33 | FULL Source-Layer latency variance | **DONE ENGINEERING / MONITOR** |
| REC-34 | Player-feature contract migration fence | **DONE PROD** |
| REC-35 | Compact projection diagnostics | **DONE PROD** |
| REC-36 | Official historical reconciliation + GW1 proxy baseline | **DONE PROD** |
| REC-37 | Official-detail migration fence closeout | **DONE PROD** |
| REC-38 | Official-First REC Coverage Contract | **DONE PROD** |
| REC-39 | Personal Gameweek Context + User Decision Authority | **DONE PROD** |
| REC-40 | Report Completeness + Natural Presentation | **DONE PROD** |
| REC-41 | Tactical Role & System Evidence Contract | **CANDIDATE** |

## REC-41 candidate acceptance evidence
- PR: **#89**.
- Feature CI run `33129623527`: compile PASS, architecture PASS, **208 tests PASS**.
- Composite FULL+FAST acceptance PASS.
- FULL: **17.020s** under 45s ceiling.
- FAST: **4.711s** under 10s SLO.
- No service added; active count remains **20**.
- Schema remains **49**.
- Official-first candidate matrix: **42 dispositions**, REC-41=`PUBLIC_FIRST_WITH_ENRICHMENT`.
- `TACTICAL_ROLE_CONTEXT_V1` requires `decision_influence=ADVISORY_ONLY`, `xmins_adjustment_enabled=false`, `xpts_rate_adjustment_enabled=false`.
- Production promotion still requires final release CI on V3.24 metadata, merge to main, merged-main CI and runtime-data publication.

## Calibration / operational monitors that must remain yellow
| Monitor | Why |
| --- | --- |
| REC-04 settled prediction validation | Needs genuine GWs frozen pre-deadline and later settled. |
| REC-07 confidence calibration | Confidence distribution needs realized outcomes. |
| REC-22 price direction/timing | Needs actual Official price movements. |
| REC-23 private precision | Unpublished draft requires authorized private access. |
| REC-26 model actionability | Requires enough settled validation evidence. |
| REC-33 FULL latency | Provider/network variance remains operational. |
| REC-41 tactical evidence maturity | Early-season role/shape samples are too small for xMins/xPts opt-in. |

## Remaining P1 intelligence roadmap after REC-41
1. **Rotation / competition intelligence**: convert competition depth and manager rotation evidence into bounded xMins inputs only after evidence contract exists.
2. **Set-piece / penalty hierarchy**: combine Official set-piece notes and observed evidence with succession/confidence semantics.
3. **International duty / travel / congestion**: call-up, minutes, travel burden and recovery risk as explicit xMins context.
4. **Settled calibration + model drift**: evaluate frozen forecasts and detect degradation before dynamic weighting.
5. **Challenger settled scorecard + dynamic evidence weighting**: challenger sources earn influence only through settled evidence.
6. **Price/value + optimizer sensitivity**: evaluate structure value and stability of decisions under bounded parameter changes.

Advanced blank/double simulation, long-horizon chip optimization, full EO/rival intelligence and production-grade ML remain better suited to V4/V5 unless a clear V3 production need emerges.

## Composite release checklist
1. Branch from current production `main`.
2. Keep mutable policy in config/registry/environment owners.
3. Update version/schema only when the relevant contract changes.
4. Compile + architecture + full deterministic tests PASS.
5. Update Official-first coverage for any REC touching FPL facts.
6. Composite FULL contracts/resource guard PASS.
7. FAST after FULL remains <10s.
8. Merge only when CI GREEN and change attributable.
9. Confirm `runtime-data` publication for runtime-impacting changes.
10. Verify Gate0 16/16, DSS 50/16/8, framework GREEN and Decision Engine HEALTHY.
11. Keep Master Task, Implementation Status and README consistent with evidence.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation and required production evidence agree. A file existing, source reachability, or an edited status label is not proof. Predictive accuracy, confidence quality, price accuracy and any decision influence from tactical evidence require genuine realized samples.

## Execution order from here
1. Complete V3.24 REC-41 final release CI.
2. Merge only if 208+ tests, architecture and composite FULL+FAST remain green.
3. Verify merged-main runtime publishes tactical-role/system evidence and `rec41_tactical_adjustment_applied=false`.
4. Close V3.24 governance to DONE PROD (evidence contract) while keeping tactical model influence advisory.
5. Start the next P1 tranche: rotation/competition plus set-piece/penalty intelligence.
