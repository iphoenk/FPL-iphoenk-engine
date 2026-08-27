# FPL iphoenk Engine V3 Master Task List

Canonical status: ACTIVE  
Canonical roadmap owner: V3 operational stream  
Current production release: **V3.22.0**  
Current production schema: **49**  
Production acceptance: **COMPLETE**  
FAST decision target: **<10 seconds**  
Active microservices: **20**

This file is the single human-readable roadmap for the operational V3 stream. Git history preserves detailed historical release notes; this file represents the **current canonical state**.

## Status legend
- **DONE PROD**: implemented, tested, merged and production-proven when runtime-impacting.
- **DONE FUNCTIONAL**: implementation is complete and does not require separate runtime activation.
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

## Current production health contract
| Area | Requirement | Current policy |
| --- | --- | --- |
| Gate0 | 16/16 PASS | required for GO |
| DSS | Core50 / Ext16 / Enh8 ACTIVE | required |
| Decision engine | HEALTHY | required |
| FAST runtime | <10s target | production SLO |
| Runtime publication | rolling parentless snapshot | required |
| Runtime source | `runtime-data` | authoritative current-state branch |
| Authenticated Official | optional/read-only/fail-soft | MONITOR |
| Predictive calibration | settled frozen forecasts only | MONITOR |
| Price calibration | realized price-change samples only | MONITOR |
| Report-time web evidence | READY/PENDING separate from engine health | required semantics |

## REC-01 through REC-35 canonical status
| REC | Work item | Status | Current evidence / disposition |
| --- | --- | --- | --- |
| REC-01 | Player-specific Defensive Contribution | **DONE PROD** | PR #63; DEF CBIT=10, MID/FWD CBIRT=12, GK ineligible; player evidence + shrinkage + Poisson threshold probability; 177 tests; FULL 12.073s; FAST 6.060s. |
| REC-02 | Robust early-season attacking rates | **DONE PROD** | PR #65; adaptive evidence-minute xG/xA shrinkage, bounded extreme observations, breakout relaxation; isolated from REC-01. |
| REC-03 | Mini-league-aware captain risk mode | **DEFERRED** | Do not equate trailing with indiscriminate variance seeking; wait for enough rival/objective and settled evidence. |
| REC-04 | Settled prediction validation | **MONITOR** | Freeze/settlement/evaluation lifecycle implemented; genuine settled GWs must accumulate naturally. |
| REC-05 | Mini-league tracking | **DONE PROD** | PR #59 basic tracker + PR #69 private-league auto-discovery; bounded rank/gap/trend history; no full rival spy. |
| REC-06 | Report transparency | **DONE PROD** | All 15 OWNED expose current-GW xPts, uncertainty, xMins/start probability, selection score and lineup/choice state. |
| REC-07 | Confidence calibration | **MONITOR** | Early-season conservative guard active; HIGH confidence is never forced without evidence. |
| REC-08 | Authenticated 3xx handling | **DONE PROD** | PR #54; redirects explicitly rejected, never followed or persisted. |
| REC-09a | Git/runtime-data hygiene | **DONE PROD** | PR #62 cold-start proof; mutable `data/**` removed from `main`; FULL rebuild and FAST continuation validated. |
| REC-09b | Rewrite whole Git history | **DEFERRED / NOT REQUIRED** | Rolling runtime snapshot removed the operational need for ancestry rewrite. |
| REC-10 | Delete `src/engine.py` | **DEFERRED** | Retained as compatibility facade until usage reaches zero. |
| REC-11 | Composite release acceptance | **DONE PROD** | PR #61; compile/architecture/tests plus fail-closed FULL→contracts→resource guard→FAST→SLO acceptance. |
| REC-12 | Runtime acceptance vs predictive validation terminology | **DONE FUNCTIONAL** | Runtime production acceptance and predictive accuracy/evidence are explicitly separate claims. |
| REC-13 | Version-neutral test ownership | **DONE PROD** | PR #71; active runtime tests use domain-owned names; new version-stamped test modules are prohibited. |
| REC-14 | Reduce 20 services to ~8 | **REJECTED AS WRITTEN** | 20-service architecture achieves FAST <10s; boundary changes require profiler/ownership evidence, not a numeric target. |
| REC-15 | Runtime SLO + profiler | **DONE PROD** | FAST target and wall/RSS/I/O telemetry active. |
| REC-16 | FAST/LIVE/FULL/DEEP profiles | **DONE PROD** | Profile-specific bounded execution/reuse active. |
| REC-17 | Remove `official_detail` from FAST blocking path | **DONE PROD CORE** | Fresh complete artifact can be safely reused; no longer dominant FAST cost. |
| REC-18 | Source/weather freshness reuse | **DONE PROD CORE** | TTL-aware reuse active; weather layer strengthened by REC-33. |
| REC-19 | Persistent runtime reuse/cache | **DONE PROD CORE** | Cross-run artifact reuse active; additional transport optimization only if profiler justifies it. |
| REC-20 | Player Feature Contract | **DONE PROD + CONSUMED** | Normalized feature artifact is production active and intentionally consumed by REC-01. |
| REC-21 | DSS evidence maturity semantics | **DONE PROD** | PR #55; NATIVE/DERIVED/PROXY/SAFE_FALLBACK/UNAVAILABLE independent of ACTIVE/UNRESOLVED. |
| REC-22 | Price predictor health/calibration | **MONITOR** | PR #57; bounded calibration active; direction/timing accuracy remains WARMUP until realized price changes accumulate. |
| REC-23 | Authenticated Official bootstrap/hardening | **MONITOR** | Engineering/security is production active; private precision remains optional and disabled without credentials. |
| REC-24 | Runtime manifest/publication hygiene | **DONE PROD** | Manifest, provenance, whitelist and rolling runtime-data publication production-proven. |
| REC-25 | Final-report evidence readiness | **DONE PROD** | PR #56; ENGINE_READY is separate from FINAL_REPORT_EVIDENCE_READY/PENDING. |
| REC-26 | Model-derived Actionability Gate | **MONITOR** | PR #56; FACT/CONSTRAINT remains actionable; MODEL_DERIVED remains advisory until calibration eligibility is met. |
| REC-27 | Mini-League Strategy State microservice | **DEFERRED / CONDITIONAL** | No extra service until REC-05 genuinely grows into EO/rival attack-protect strategy ownership. |
| REC-28 | Split CI / FAST / FULL-DEEP workflows | **DONE PROD** | Workload/cadence separated without per-service workflow explosion. |
| REC-29 | Rolling runtime snapshot + shallow checkout | **DONE PROD** | Parentless rolling publication, whitelist and shallow fetch proven. |
| REC-30 | Runtime resource budget guard | **DONE PROD** | Wall/RSS/resource regression guard active. |
| REC-31 | Profile-aware REUSED validation | **DONE PROD** | Only declared, complete and contract-valid reused services are accepted. |
| REC-32 | Reused latest-state carry-forward | **DONE PROD** | Registry-owned canonical state survives base fan-in while unrelated stale state is not copied. |
| REC-33 | FULL Source-Layer latency variance | **DONE ENGINEERING / MONITOR** | PR #52; weather refresh uses confidence-aware freshness + max 4 provider workers; CI FULL improved from 55.5s outlier to 17.068s, Source Layer 3.043s; scheduled FULL latency remains monitored. |
| REC-34 | Player-feature contract migration fence | **DONE PROD** | PR #66 one-shot invalidation regenerated stale pre-REC-01 artifact; PR #67 restored normal 21,600s advanced-stats reuse TTL after successful publication. |
| REC-35 | Compact projection diagnostics | **DONE PROD** | PR #70 removes duplicated per-fixture DC provenance without formula/decision change; latest production snapshot 18.50MB, FAST 5.802s, RSS 87.5/114.8MB. |

## Production evidence after REC-01/02 and runtime closeouts
- REC-01 PR #63: architecture PASS, service count 20, 177/177 tests PASS, FULL 12.073s, FAST-after-FULL 6.060s.
- REC-01 runtime contract migration completed successfully; migration fence forced one fresh `player_features.json` publication and normal 6-hour reuse TTL was restored.
- REC-02 PR #65 merged as an isolated model change after REC-01.
- REC-35 compaction was decision-equivalent and reversed the post-REC-01/02 payload/RSS regression: current `runtime_manifest.json` reports FAST **5.802s**, parent/child RSS **87.5/114.8MB**, and runtime snapshot **18.50MB**.
- Latest `main` commit `da55f6a15909085799a9b6fcd187d01871038915` is the REC-13 merge; both V3 CI and V3 Runtime Fast completed SUCCESS.
- Runtime schema remains **49** and active service count remains **20**.

## Calibration / operational monitors that must remain yellow honestly
| Monitor | Why it cannot be forced green |
| --- | --- |
| REC-04 settled prediction validation | Needs genuine completed GWs that were frozen pre-deadline. |
| REC-07 confidence calibration | Confidence distribution must be validated against realized outcomes. |
| REC-22 price direction/timing calibration | Requires actual Official price movements after predictions. |
| REC-23 authenticated private precision | Requires an authorized production credential/session; public baseline remains fully usable without it. |
| REC-26 model actionability | Requires prediction evaluation to become dynamically eligible from settled evidence. |
| REC-33 FULL latency | Provider/network variance remains an operational metric even after engineering fix. |

## Engineering hygiene
| Task | Status |
| --- | --- |
| Config ownership / anti-hardcode | ACTIVE |
| Registry integrity | ACTIVE |
| Runtime artifact contracts | ACTIVE |
| Production/report/source/watchlist contracts | ACTIVE |
| FAST <10s + resource telemetry | ACTIVE |
| Rolling runtime-data storage hygiene | ACTIVE |
| Version-neutral active test ownership | ACTIVE |
| README / Implementation Status / Master Task synchronization | ACTIVE |

## Composite release checklist for every V3 change
1. Branch from current production `main`.
2. Keep mutable policy in its config/registry/environment owner.
3. Update version/schema only when the relevant contract changes.
4. Compile + architecture + full deterministic tests PASS.
5. Run composite FULL acceptance: source, production, watchlist, serving and report-time contracts + resource guard.
6. Run FAST after FULL and enforce <10s SLO.
7. Merge only when CI is GREEN and the change is attributable.
8. Confirm `runtime-data` publication for runtime-impacting changes.
9. Verify Gate0 16/16, DSS 50/16/8, framework GREEN and Decision Engine HEALTHY.
10. Keep Master Task, Implementation Status and README consistent with actual evidence.

## Definition of Done
A task is DONE only when implementation, deterministic tests, documentation and required production evidence agree. A file existing, a source being reachable, or a manually edited status label is not proof. Predictive accuracy, confidence quality, price accuracy and causal weather claims require genuine realized samples.

## Execution order from here
1. Keep V3.22 production GREEN and FAST <10s.
2. Accumulate settled-GW, confidence, price and weather calibration evidence without forcing status upgrades.
3. Keep authenticated Official precision optional/fail-soft until a credential is deliberately provisioned.
4. Improve remaining P1 intelligence evidence only through attributable changes that preserve Official authority and production stability.
