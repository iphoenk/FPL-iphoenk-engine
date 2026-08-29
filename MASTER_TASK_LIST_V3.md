# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE  
Canonical roadmap owner: V3 operational stream  
Current production release: V3.39.0  
Current production schema: 49  
Production acceptance: COMPLETE  
FAST refresh target: **<10 seconds**  
Validated warm serving hard ceiling: **<1 second**  
Active background capabilities: **21**, grouped into **7 execution domains**

This file is the single human-readable roadmap for the operational V3 stream. Git history preserves historical release notes; this file represents the **current canonical state**.

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
15. FAST refresh targets <10s and may reuse only complete, fresh, contract-valid artifacts.
16. User-facing validated warm serving is a separate lane from source/model refresh and has a hard <1s ceiling.
17. Service boundaries follow ownership/failure semantics, not a target service count.
18. Exactly one authoritative owner exists per business responsibility; shared primitives are reused, not reimplemented.
19. Enhancement layers aggregate capabilities and may not create alternate business authority.
20. Gate0 is a validator, not an alternate rules/optimizer engine.
21. REC items are change/remediation records, not business capabilities.
22. FACT/CONSTRAINT actions may remain actionable while MODEL_DERIVED recommendations are calibration-gated.
23. Mutable runtime values belong to config/registry/environment owners.
24. Every V3 change must leave `main`, CI, runtime contracts and `runtime-data` mutually consistent.
25. Applicable REC work attempts public Official first; fallback requires an explicit allowed disposition.
26. Finished personal GWs are Official actual truth; planning-GW points are projections.
27. Previous Official submitted squad is default planning baseline; WC/FH/user composition overrides must target the exact planning GW.
28. Explicit user XI/C/VC/chip overrides preserve engine recommendation for comparison and may not be silently overwritten.
29. Human-facing report surfaces use natural Bahasa Indonesia; raw enums remain machine/audit state.
30. Required report checkpoints are explicit, persisted and auditable; missed due checkpoints surface as missed.
31. Tactical-role/system evidence must distinguish evidence from inference. `FPL_POSITION_SHAPE` is not a claim of true tactical formation.
32. REC-41 tactical/system evidence remains advisory-only and may not mutate xMins or xPts without a later calibrated model opt-in.
33. Stale artifacts may never be presented as fresh merely to meet a latency target.
34. Network/source refresh latency and warm-serving latency are measured separately.
35. The 7 execution domains must cover all 21 background capabilities exactly once and may not become alternate business owners.
36. Runtime and report-time competitive-load governance must use one canonical policy; duplicated policy files are forbidden.
37. Version-stamped commits must not drift from `src/version.py`; release metadata surfaces must stay synchronized.
38. Accidental placeholder/probe files are prohibited from protected release branches.

## Current health contract
| Area | Requirement | State |
| --- | --- | --- |
| Gate0 | 16/16 PASS | V3.39 production proven |
| DSS | 50 / 16 / 8 ACTIVE | V3.39 production proven |
| FAST refresh | <10s | V3.39 published 5.388s |
| Validated warm serving | <1000ms hard ceiling, 500ms target | V3.39 candidate CI median 9.022ms, max 165.394ms |
| Runtime publication | rolling parentless snapshot | V3.39 published |
| Official-first | closed explicit matrix | production |
| Architecture ownership | 21 capabilities mapped exactly once into 7 domains | production guard |
| Competitive-load policy | one canonical runtime/report-time config | V3.39 production |
| Repository hygiene | no accidental placeholder/probe files | V3.39 production CI guard |
| Predictive calibration | settled frozen forecasts | MONITOR |
| Price calibration | realized Official movement | MONITOR |
| Auth private precision | optional/fail-soft | MONITOR |
| Personal GW context | actual history + labelled planning xPts | production REC-39 |
| Natural report + checkpoints | 04:30 / 12:30 / 21:30 WIB | production REC-40 |
| Tactical role/system evidence | evidence-only, no xMins/xPts adjustment | production REC-41 |

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
REC-40 made natural Bahasa Indonesia the primary human-facing surface and persisted 04:30/12:30/21:30 checkpoint completeness.

### V3.24 Tactical Role & System Evidence
REC-41 is production-published. Observed player attacking-role profiles and team `FPL_POSITION_SHAPE` are carried through the Player Feature Contract while Official identity/FPL position remains authority. The evidence remains **ADVISORY_ONLY**, with no direct xMins or xPts adjustment.

### V3.25 Architecture Consolidation + Sub-Second Warm Serving
REC-42 applies the V4.9.6 one-owner/shared-primitive idea with V5 bounded-context and performance principles. DSS/Extension/Enhancement registry ownership is aligned to active implementations, legacy projection/fixture/optimizer ownership drift is fenced, a no-duplicate CI gate is added, REC-41 forced feature refresh is closed after runtime publication, and a fail-closed validated warm-serving lane is introduced. PR #106 feature CI run `33171209718` passed architecture, no-duplicate ownership, **221 tests**, FULL **12.406s**, FAST **5.484s**, and instant-serving benchmark **0.206 / 0.226 / 3.041 ms min/median/max** across five runs. Football formulas were unchanged.

### V3.39 Claude QA Stabilization
Independent QA/QC confirmed REC-01 and REC-02 genuinely active, but found release-metadata drift, a duplicated competitive-load policy, and repeated accidental placeholder/probe commits. V3.39 consolidates runtime/report-time load governance into one canonical config without dropping deadline-day, press-conference, competition-load or double-count rules, adds repository hygiene protection, aligns release metadata with code lineage, and retains the existing 21-capability/7-domain equivalence guard rather than creating another orchestration layer.

Production evidence:
- PR **#146** merged to `main` at code commit `8c4d62d42683d6191a42dc3b778101885195322c`.
- Candidate CI run `33238691899`: compile PASS, architecture PASS, no-duplicate ownership PASS, **304 tests PASS in 1.59s**.
- Composite release acceptance PASS: FULL **8.427s**, FAST **4.642s**, material decision equivalence PASS.
- Unified interactive serving benchmark: **9.022ms median / 165.394ms max**, below the 1s preferred target.
- Merged-main CI run `33238768506`: PASS.
- Production runtime run `33238768480`: PASS, rolling `runtime-data` publication PASS, production Definition of Done PASS.
- Published runtime manifest: engine **3.39.0**, schema **49**, FAST **5.388s**, Gate0/DSS/report contracts GREEN.
- No football scoring/projection formula, Official authority or user-decision authority was intentionally changed by this stabilization batch.
- Predictive accuracy is still not claimed; REC-04 remains MONITOR pending genuinely settled forecast samples.

## REC-01 through REC-42 canonical status
The Claude QA follow-up numbering `REC-36` through `REC-39` is external-review notation and must not overwrite the canonical V3 REC IDs below.

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
| REC-41 | Tactical Role & System Evidence Contract | **DONE PROD** |
| REC-42 | Architecture Consolidation + No-Duplicate Guard + Sub-Second Warm Serving | **CANDIDATE** |

## REC-42 V3.25 candidate evidence (historical baseline)
- PR: **#106**.
- Feature CI run `33171209718`: compile PASS, existing architecture PASS, new no-duplicate ownership gate PASS, **221 tests PASS**.
- Composite FULL+FAST acceptance PASS.
- FULL: **12.406s** under 45s target.
- FAST: **5.484s** under 10s SLO, down from the previous published V3.24 FAST runtime of **7.624s**.
- `advanced_stats` FAST reuse: **15.742ms** after closing the completed REC-41 migration fence, instead of rebuilding the feature stack every run.
- Validated warm-serving benchmark, five repetitions: **min 0.206ms / median 0.226ms / max 3.041ms**, hard ceiling **1000ms**.
- This evidence is historical V3.25 candidate evidence and is not relabelled as V3.39 acceptance evidence.
- Schema remains **49**.
- No football formula, Official authority, or user-decision authority change.

## Architecture consolidation rules
1. One authoritative owner per business responsibility.
2. Shared primitives are consumed by DSS/Extensions/Enhancements instead of being recomputed.
3. Enhancements are cross-cutting aggregation layers, not new business authorities.
4. Gate0 validates legality but may not become a second optimizer/rules engine.
5. Compatibility and legacy implementations may not be active runtime owners.
6. Multi-writer artifacts must be explicitly declared as staged artifacts with one final owner.
7. New Official-FPL network fetches outside declared owners/exceptions fail CI.
8. Duplicate DSS/Extension/Enhancement/Gate0 IDs fail CI.
9. Warm serving may use only fresh, complete, contract-valid materialized artifacts.
10. Source/model refresh remains separate and may not be hidden behind stale data to claim sub-second latency.
11. Execution domains are orchestration boundaries only; all 21 background capabilities must be assigned exactly once.
12. Runtime/report-time competitive-load policy duplication is forbidden.

## Calibration / operational monitors that must remain yellow
| Monitor | Why |
| --- | --- |
| REC-04 settled prediction validation | Needs genuine GWs frozen pre-deadline and later settled. |
| REC-07 confidence calibration | Confidence distribution needs realized outcomes. |
| REC-22 price direction/timing | Needs actual Official price movements. |
| REC-23 private precision | Unpublished draft requires authorized private access. |
| REC-26 model actionability | Requires enough settled validation evidence. |
| REC-33 FULL latency | Provider/network variance remains operational. |
| REC-41 tactical evidence maturity | Early-season role/shape samples are still too small for xMins/xPts opt-in. |

## Remaining P1 intelligence/performance roadmap
1. **Rotation / competition intelligence**: convert competition depth and manager rotation evidence into bounded xMins inputs only after evidence contract exists.
2. **Set-piece / penalty hierarchy**: combine Official set-piece notes and observed evidence with succession/confidence semantics.
3. **International duty / travel / congestion**: call-up, minutes, travel burden and recovery risk as explicit xMins context.
4. **Settled calibration + model drift**: evaluate frozen forecasts and detect degradation before dynamic weighting.
5. **Challenger settled scorecard + dynamic evidence weighting**: challenger sources earn influence only through settled evidence.
6. **Refresh hot-path consolidation**: prediction remains the largest deterministic compute block; reduce process/IO overhead without changing formula ownership or freshness semantics.
7. **Official-fetch consolidation**: remove transitional non-snapshot Official network exceptions when equivalent snapshot/reconciliation ownership is available.

Advanced blank/double simulation, long-horizon chip optimization, full EO/rival intelligence and production-grade ML remain better suited to V4/V5 unless a clear V3 production need emerges.

## Composite release checklist
1. Branch from current production `main`.
2. Keep mutable policy in config/registry/environment owners.
3. Synchronize `src/version.py`, README, Master Task and Implementation Status whenever a version-stamped release lineage changes; schema changes only when the schema contract changes.
4. Compile + architecture + no-duplicate ownership + full deterministic tests PASS.
5. Update Official-first coverage for any canonical REC touching FPL facts.
6. Composite FULL contracts/resource guard PASS.
7. FAST after FULL remains <10s.
8. Validated warm-serving benchmark remains <1000ms.
9. Merge only when CI GREEN and change attributable.
10. Confirm `runtime-data` publication for runtime-impacting changes.
11. Verify Gate0 16/16, DSS 50/16/8, framework GREEN and Decision Engine HEALTHY.
12. Keep Master Task, Implementation Status, version metadata and README consistent with evidence.
13. Verify canonical competitive-load policy has no duplicate legacy config.
14. Verify repository hygiene guard finds no placeholder/probe artifacts.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation and required production evidence agree. A file existing, source reachability, or an edited status label is not proof. Predictive accuracy, confidence quality, price accuracy and any decision influence from tactical evidence require genuine realized samples.

## Execution order from here
1. Keep V3.39 production stable; do not add new capability merely because review items are closed.
2. Continue REC-04 settled prediction collection and evaluate genuinely frozen forecasts as GW samples settle.
3. Keep REC-07, REC-22, REC-23, REC-26, REC-33 and REC-41 maturity monitors yellow until evidence supports promotion.
4. Any future version-stamped change must update `src/version.py` and release metadata surfaces in the same release flow.
5. Preserve one canonical competitive-load policy and the 21-capability/7-domain equivalence gate.
6. Do not treat runtime GREEN as proof of predictive accuracy.
