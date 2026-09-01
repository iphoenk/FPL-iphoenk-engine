# FPL iphoenk Engine V3 Master Task List

Status: **ACTIVE production operational stream**  
Release metadata authority: `src/version.py`  
REC authority: `config/rec_registry.json`  
Topology authority: `config/runtime/execution_domains.json` + `config/v3_service_registry.json`  
Performance authority: `config/runtime/performance_slo.json`  
Current production runtime/provenance authority: `runtime-data/data/runtime_manifest.json`

This file is the **human-readable roadmap and status projection** for V3. It is not a competing machine authority. Current commit SHA, topology counts, runtime timings and SLO values must be read from the authorities above. Historical values may appear below only when explicitly labelled historical evidence.

## Status legend

- **DONE PROD**: implementation is accepted and production-proven when runtime-impacting.
- **DONE FUNCTIONAL**: implementation is complete without separate runtime activation.
- **CANDIDATE**: implemented, but final merge/publication acceptance is incomplete.
- **MONITOR**: engineering exists but genuine season/runtime evidence must accumulate before promotion.
- **DEFERRED**: intentionally postponed until dependencies justify it.
- **REJECTED**: proposal is not adopted because a better control exists.

## Non-negotiable V3 invariants

1. Official FPL is the only native authority for Official fields and scoring.
2. External, challenger, community, weather and tactical evidence may never overwrite Official-native truth.
3. Missing evidence is explicit and is never fabricated to keep health GREEN.
4. OWNED is exactly 15 authoritative players.
5. External watchlist construction remains full-universe DSS-owned and must satisfy the report-position contract.
6. Gate0 must satisfy its registry-owned complete PASS contract for unqualified GO.
7. DSS Core, Extensions and Enhancements must satisfy their registry-owned activation counts.
8. Numerical formulas affecting decisions require deterministic regression tests.
9. Runtime data publishes to `runtime-data`; mutable runtime output does not belong on `main`.
10. Runtime Git history is not a database.
11. Declared production-critical JSON artifacts are validated before acceptance/publication.
12. Critical internal integrity failure is fail-closed; optional external/private unavailability is fail-soft where explicitly declared.
13. Weather remains advisory and cannot directly mutate decisions without calibrated governance.
14. Formula correctness and predictive accuracy are separate claims; predictive accuracy requires settled frozen forecasts.
15. FAST and serving latency targets are owned only by `config/runtime/performance_slo.json`; documentation must not duplicate them as current authority.
16. User-facing validated warm serving is a separate lane from source/model refresh.
17. Service/capability boundaries follow ownership and failure semantics, not a target service count.
18. Exactly one authoritative owner exists per business responsibility; shared primitives are reused, not reimplemented.
19. Enhancement layers aggregate capabilities and may not create alternate business authority.
20. Gate0 is a validator, not an alternate rules or optimizer engine.
21. REC items are change/remediation records, not business capabilities.
22. FACT/CONSTRAINT actions may remain actionable while MODEL_DERIVED recommendations are calibration-gated.
23. Mutable values belong to config, registry, environment or runtime-evidence owners.
24. Every V3 production change must leave `main`, CI, runtime contracts and `runtime-data` mutually consistent.
25. Applicable REC work attempts public Official first; fallback requires an explicit allowed disposition.
26. Finished personal GWs are Official actual truth; planning-GW points are projections.
27. Previous Official submitted squad is the default planning baseline; WC/FH/user composition overrides must target the exact planning GW.
28. Explicit user XI/C/VC/chip overrides preserve engine recommendation for comparison and may not be silently overwritten.
29. Human-facing reports use natural Bahasa Indonesia; raw enums remain machine/audit state.
30. Required report checkpoints are explicit, persisted and auditable; missed due checkpoints surface as missed.
31. Tactical-role/system evidence must distinguish observation from inference. `FPL_POSITION_SHAPE` is not a claim of true tactical formation.
32. REC-41 tactical/system evidence may not mutate xMins or xPts without a later calibrated model opt-in.
33. Stale artifacts may never be presented as fresh merely to meet a latency target.
34. Network/source refresh latency and warm-serving latency are measured separately.
35. The compiled runtime plan must map every active background capability exactly once into registry-owned execution domains; docs may not hardcode current topology counts.
36. Runtime and report-time competitive-load governance use one canonical policy; duplicated policy files are forbidden.
37. Release metadata must remain aligned with `src/version.py`.
38. Accidental placeholder/probe files are prohibited from release branches.
39. Release-test ownership is version-neutral; version-stamped release test modules are forbidden.
40. Current production provenance comes from exact-SHA CI plus `runtime-data/data/runtime_manifest.json`; historical closeout SHAs remain lineage evidence only.
41. `src.runtime_v3.domain_orchestrator` is the canonical production scheduler. The former service-level scheduler entry in `src.runtime_v3.orchestrator` is retired and must fail closed.
42. Release acceptance must test the canonical architecture and may not reactivate a retired execution path merely for equivalence testing.
43. Current-state documentation is a projection and must point to machine authorities rather than duplicating mutable current values.

## Current engineering health contract

| Area | Requirement | Projection |
| --- | --- | --- |
| Official authority | Official-native truth cannot be overwritten | **DONE PROD** |
| Gate0 / DSS framework | registry-owned completeness and activation | **DONE PROD** |
| Canonical topology | compiled registry authority, one assignment per capability | **DONE PROD** |
| No-duplicate architecture | one owner per responsibility, shared primitives reused | **DONE PROD / REC-42** |
| Legacy scheduler | alternate executable service scheduler retired fail-closed | **DONE PROD** |
| Artifact integrity | critical decision/serving outputs structurally validated | **DONE PROD** |
| Runtime SLO | profile-specific, registry-owned, acceptance-enforced | **DONE PROD** |
| Runtime publication | isolated, whitelist, atomic, exact provenance verification | **DONE PROD** |
| Private auth boundary | optional private enrichment cannot leak private state into public runtime | **DONE PROD** |
| Natural report + checkpoints | Bahasa Indonesia + auditable scheduled checkpoints | **DONE PROD / REC-40** |
| Tactical role/system evidence | evidence-only unless later calibrated model opt-in | **DONE PROD / REC-41** |
| Predictive calibration | genuine settled frozen forecasts | **MONITOR** |
| Confidence calibration | realized outcome distribution required | **MONITOR** |
| Price direction/timing calibration | realized Official movements required | **MONITOR** |
| Authenticated private precision | optional authenticated evidence required | **MONITOR** |
| Model-derived actionability | enough settled validation evidence required | **MONITOR** |
| `main` required CI enforcement | GitHub platform branch/ruleset control | **OPEN PLATFORM CONTROL** |
| `runtime-data` write protection | GitHub platform branch/ruleset control | **OPEN PLATFORM CONTROL** |

The last two rows are platform controls, not engine-code defects. They must not be marked GREEN until GitHub actually enforces them.

## Canonical REC status projection

Canonical values come from `config/rec_registry.json`. This table is a readable projection and must remain synchronized.

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
| REC-10 | Delete `src/engine.py` compatibility facade | **DEFERRED** |
| REC-11 | Composite release acceptance | **DONE PROD** |
| REC-12 | Runtime acceptance vs predictive validation terminology | **DONE FUNCTIONAL** |
| REC-13 | Version-neutral test ownership | **DONE PROD** |
| REC-14 | Reduce services to an arbitrary target count | **REJECTED AS WRITTEN** |
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
| REC-42 | Architecture Consolidation + No-Duplicate Guard + Sub-Second Decision Serving | **DONE PROD** |

## Calibration and evidence monitors that remain yellow by design

| Monitor | Promotion evidence required |
| --- | --- |
| REC-04 settled prediction validation | finished GWs settled against genuine pre-deadline frozen forecasts |
| REC-07 confidence calibration | sufficient realized outcomes across confidence buckets |
| REC-22 price direction/timing | realized Official price movements and timing evidence |
| REC-23 private precision | authorized private Official evidence where required |
| REC-26 model actionability | enough settled model validation evidence |
| REC-33 FULL source-layer variance | repeated production observations, not a single benchmark |
| Tactical model opt-in | sufficient reliable role/system evidence and calibrated benefit |
| Weather model opt-in | repeatable predictive information after football/tactical confounders |
| Resource hard limits | genuine multi-run production baseline before numeric enforcement |

These monitors must not be promoted merely because CI is GREEN.

## Historical release anchors

Historical facts are retained for audit lineage only:

- V3.20 established architecture/source/config ownership foundations.
- V3.20.2 established strict artifact-contract hardening and promotion integrity.
- V3.21 introduced governed advisory weather context and report transparency.
- V3.22 introduced FAST/LIVE/FULL/DEEP runtime profiles and rolling runtime snapshots.
- V3.23 introduced personal Gameweek context and user-decision authority.
- V3.23.1 introduced natural Bahasa Indonesia reporting and persisted checkpoint completeness.
- V3.24 introduced REC-41 tactical role/system evidence as advisory evidence.
- V3.25 PR #106 was the historical candidate baseline for REC-42. Its old topology counts, FAST timings and serving measurements remain historical candidate evidence only.
- V3.39 stabilization/housekeeping consolidated governance, prediction freeze recovery, version-neutral tests and repository hygiene without intentionally changing football formulas.
- Later production hardening consolidated runtime topology authority, artifact integrity, domain-subprocess registry authority, atomic publication and retirement of the alternate legacy scheduler.

Historical exact SHAs, CI run IDs, topology counts and performance measurements remain available in Git history and `IMPLEMENTATION_STATUS.json`. They are not current authority.

## Architecture consolidation rules

1. One authoritative owner per business responsibility.
2. Shared primitives are consumed rather than recomputed or wrapped into duplicate layers.
3. Enhancements are cross-cutting aggregation layers, not new business authorities.
4. Gate0 validates legality but may not become a second optimizer/rules engine.
5. Compatibility and legacy implementations may not be active runtime owners.
6. Multi-writer artifacts require an explicitly declared staged/final-owner contract.
7. New Official-FPL network fetches outside declared owners/exceptions fail governance checks.
8. Duplicate DSS/Extension/Enhancement/Gate0/REC ownership fails governance checks.
9. Warm serving may consume only fresh, complete, contract-valid materialized artifacts.
10. Source/model refresh remains separate and may not be hidden behind stale state to claim latency success.
11. Execution domains are orchestration boundaries; current assignments and counts come only from the canonical topology registries.
12. Runtime/report-time competitive-load policy duplication is forbidden.
13. Version-stamped release-test modules are forbidden.
14. Release acceptance may not invoke a retired scheduler as an alternate production implementation.
15. Do not create another registry, microservice or wrapper merely to move existing authority without reducing a real risk.

## Definition of production done

A runtime-impacting change is not DONE PROD until all applicable checks are true:

1. canonical source branch is verified;
2. compile and deterministic unit/regression suite pass;
3. architecture, terminology, REC and no-duplicate ownership guards pass;
4. FULL + FAST composite release acceptance passes;
5. applicable performance/SLO consistency checks pass;
6. production decision contracts and Definition of Done pass;
7. publication whitelist materializes successfully;
8. isolated publisher performs atomic publication;
9. post-publish exact provenance and whitelist verification pass;
10. `runtime-data/data/runtime_manifest.json` identifies the exact accepted source commit.

Platform branch/ruleset enforcement is assessed separately and may remain an explicit open control until GitHub settings are actually enforced.
