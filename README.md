# FPL iphoenk Engine v3.19.0

Production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release
- Engine version: `3.19.0`
- Schema version: `48`
- Release metadata source of truth: `src/version.py`
- Production runtime: bounded-process V3 microservices
- Runtime state is published to `runtime-data`; `main/data/**` is historical/source-repository material only.
- Official FPL remains the only native authority. Challenger/enrichment/report-time sources may not overwrite native Official fields.
- Canonical V3 roadmap and release checklist: `MASTER_TASK_LIST_V3.md`.

## v3.19.0 Report-Time Intelligence
V3.19 separates machine-ingested sources from report-time web intelligence. Sources that are useful for decision context but inappropriate or unreliable for unattended collector access are refreshed when a scheduled or on-demand report is prepared, then compared with DSS without mutating DSS state.

Report-time source classes:
- `MODEL_CHALLENGER`: OneFPL price/transfer/captaincy/planner context. OneFPL is disabled in the automated collector and remains available through report-time web review.
- `FIXTURE_STRATEGY_EXPERT`: Ben Crellin for blank/double Gameweeks, fixture rearrangements, schedule probabilities and chip-window context. Fixture strategy does not vote on player projection.
- `PUNDIT_CONSENSUS`: FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar and Fantasy Football Scout editorial views. Current opinions are aggregated and explicitly labelled `ALIGN`, `DIVERGE`, `REVIEW_DIVERGENCE` or `NEUTRAL` against DSS.
- `COMMUNITY_SIGNAL`: Reddit r/FantasyPL eye-test, role/rotation/injury observations, captain polls and sentiment. Community signals require independent cross-check before fact promotion.
- `VERIFIED_NEWS`: Premier League/official-club factual availability, suspension, fixture confirmation and manager-quote context.

V3.19 governance:
- Official FPL remains native authority and verified facts outrank opinion/community evidence.
- report-time evidence never automatically changes DSS rankings, OWNED/WATCHLIST membership, captaincy or transfer decisions.
- pundit consensus is advisory; disagreement with DSS must be surfaced rather than hidden.
- stale pundit evidence is not counted as current consensus.
- report-time evidence requires source URL, observation time, source class, topic, subject, stance and summary.
- OneFPL automated GitHub Actions fetches are removed; no browser spoofing or access-control bypass is used.
- `decision_brief`, `deep_review_payload` and `user_report` carry report-time intelligence state. Without a fresh web review they explicitly report `REFRESH_REQUIRED` rather than implying evidence was checked.

Schema is 48 because the report serving contract adds report-time intelligence and `DEEP_REVIEW_PAYLOAD_V2`.

Production acceptance completed on 27 August 2026. PR #32 merged to `main` as `4b5f5f72146400a25c956e7628105b7680effe84`. Final PR workflow run `33028670999` passed the full regression suite, bounded microservices integration, source capability contract, production decision/report contract, 15 OWNED + 20 WATCHLIST contract, fast report-serving contract, report-time intelligence contract and runtime budget. Production push run `33028851447` then completed the collector, all production validators and validated publication to `runtime-data`. The published framework is GREEN/HEALTHY with GO allowed, Gate 0 16/16 PASS, DSS Core 50/50 ACTIVE, DSS Extensions 16/16 ACTIVE and Enhancement Layers 8/8 ACTIVE. OneFPL is DISABLED in the unattended collector with zero collector observations; the published `decision_brief` correctly emits `report_time_intelligence.status=REFRESH_REQUIRED` until the visible-report web pass is performed. The active FPL Master Monitor task is configured to perform that fresh report-time pass for every visible scheduled/on-demand/deadline report while keeping silent hourly internal checks bounded.

## v3.18.1 OneFPL Adapter Reliability Patch
V3.18.1 fixed OneFPL source-health semantics and public structured-read resilience without changing the runtime artifact schema. It established explicit evidence that unattended server-side access can be restricted. V3.19 supersedes the automated OneFPL collector path by delegating OneFPL to report-time web intelligence.

Patch changes:
- OneFPL parser contract upgraded to `onefpl-price-v2`
- source reachability probe separated from structured data retrieval
- approved public structured fallback URL was registry-owned rather than hardcoded in Python
- HTTP 401/402/403/429 on structured endpoints represented structured-access restriction
- every structured endpoint attempt recorded with URL role, HTTP status, latency and error state
- no browser/user-agent spoofing was used
- Official FPL authority, fail-soft challenger behavior and no-fabrication guarantees remained unchanged

## v3.18.0 Structured Challenger Ingestion + Architecture Hardening
V3.18.0 introduced bounded normalized challenger observations with explicit provenance and capability health. Missing challenger values remain missing or explicit safe fallback; Official FPL remains native authority.

Release changes:
- normalized challenger observations with source/capability/status/value/payload, fetched/observed timestamps, provenance, confidence, stale state, TTL and parser/schema metadata
- separate source reachability from capability-data health
- last-known-good and stale governance without treating stale data as current
- explicit cross-source disagreement state
- non-authoritative challenger context in Price Radar
- Price Radar thresholds/capacity and refresh cadence moved to config ownership
- projection and strategic horizons moved to engine configuration ownership
- DSS Core, Extension, Enhancement and Gate0 expected counts declared by their registries
- production validators consume registry/config contracts rather than duplicating mutable values
- active prediction and price service entrypoints are version-neutral
- coarse-grained service boundaries retained where shared HTTP caching or serial artifact ownership makes further process splitting counterproductive

Production acceptance completed on 26 August 2026. The published framework was GREEN/HEALTHY with GO allowed, Gate0 16/16 PASS, DSS Core 50/50 ACTIVE, DSS Extensions 16/16 ACTIVE and Enhancement Layers 8/8 ACTIVE.

## v3.17.1 Master Task Governance
V3.17.1 established `MASTER_TASK_LIST_V3.md` as the single human-readable master roadmap for the operational V3 stream.

Every V3 feature, refactor, hardening change and release-governance change must update the master task list in the same pull request. A task is not DONE merely because code exists or a registry label is green; the applicable tests, documentation, release consistency and production evidence must agree.

## v3.17 Full DSS operationalization
V3.17 converts framework-only DSS capability states into explicit runtime evidence contracts. A module is ACTIVE only when its evaluator executes and produces evidence or an explicit safe-fallback state; unavailable external signals are never fabricated.

Release acceptance requires:
- Gate 0: 16/16 PASS
- DSS Core: 50/50 ACTIVE
- DSS Extensions: 16/16 ACTIVE
- Enhancement Layers: 8/8 ACTIVE
- overall framework GREEN and `go_allowed=true`

## v3.16.1 Configuration ownership hardening
Configuration ownership:
- `src/version.py` owns engine/schema/service release metadata.
- `config/engine.json` owns mutable runtime/user settings such as team ID, polling intervals, API retry/backoff/timeout, reconstruction baseline GW, projection horizons, and report list sizes.
- `config/intelligence/price_radar.json` owns mutable Price Radar thresholds, urgency/timing policy, timezone and market-watch capacity.
- `config/intelligence/refresh_policy.json` owns normal/deadline/match refresh cadence.
- Environment variables may override explicitly supported runtime settings.
- `config/rules/registry.json` + active ruleset own FPL squad, lineup, scoring, chip, finance, and BPS rules.
- `config/v3_service_registry.json` owns service DAG/runtime orchestration settings.
- `config/sources/registry.json` owns unattended machine-source authority and adapters.
- `config/sources/report_time_registry.json` owns report-time source classes, domains, query intents, freshness and consensus policy.

## v3.16 Source Registry + Adapter Layer
V3.16 introduced dedicated source infrastructure with registry-driven authority classes, isolated adapters, parallel health probes, fail-soft challenger/enrichment sources, and LiveFPL as a first-class challenger.

Important distinction: source reachability does not automatically mean structured data ingestion. Official FPL is native authority; challenger sources are independent evidence only.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, expanded Official detail surfaces, optional authenticated read-only Official data, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, provenance/freshness, framework health, snapshot integrity, DSS-driven watchlist selection, decision-aware price monitoring, and report-time expert/community intelligence.

## Rules authority
`src/rules.py` loads the active ruleset from `config/rules/registry.json` and is the code-facing rules interface.

Regression-tested 2026/27 rules include:
- squad size/position composition and max three players per club
- legal starting formations and captain/vice constraints
- appearance points and goals: GK +10, DEF +6, MID +5, FWD +4
- assists, clean sheets, saves, penalties, cards, own goals, bonus
- defensive contribution thresholds and caps
- Wildcard, Free Hit, Triple Captain and Bench Boost rules across both season halves
- public purchase/sell-value reconstruction

Local reconstruction is an audit aid only. It must not override Official FPL native fields such as total points, bonus allocation, rank, current price, or confirmed scoring.

## Source authority
1. Direct Official FPL native fields and Official scoring
2. Authenticated Official FPL native account fields when valid and directly applicable
3. Persisted Official-FPL-derived runtime bridge on `runtime-data`
4. Official public detail/secondary surfaces and verified official team/news context
5. Structured analytics such as FPL Core Insights and vaastav
6. Registered model challengers such as LiveFPL when valid structured observations exist
7. Report-time model/strategy/pundit/community intelligence under `REPORT_TIME_SOURCE_REGISTRY_V1`

Third-party predictions and opinions are never native authority. Failed challenger/enrichment/report-time sources must fail soft and must not corrupt the Official baseline.

## Report-time intelligence
Scheduled and on-demand user reports perform a fresh web intelligence pass when applicable. The report-time registry defines which evidence to seek and its authority ceiling; it does not authorize scraping or bypassing access controls.

The synthesis sequence is:
1. Official and verified facts.
2. DSS/data-model output.
3. OneFPL/model-challenger context when available through normal report-time web access.
4. Ben Crellin fixture/schedule context.
5. Current pundit consensus and explicit comparison against DSS.
6. Reddit/community signals as leads requiring cross-check.
7. Final decision remains governed by DSS plus verified evidence, not by vote count.

## Runtime architecture
The V3 production runtime is a bounded-process microservice orchestrator driven by `config/v3_service_registry.json`.

Key properties:
- dependency-aware DAG scheduling
- bounded parallelism and service timeouts
- isolated service work directories
- shared Official HTTP cache
- fail-closed critical services
- validated artifact promotion
- runtime performance budget and metadata
- production publication to isolated `runtime-data`
- version-neutral active service entrypoints
- coarse-grained process boundaries chosen by dependency/data ownership rather than file size
- report-time web intelligence remains in the report boundary and is not a new collector microservice

## Framework governance
- Gate 0 registry: 16 hard constraint checks
- DSS Core registry: 50 modules
- DSS Extension registry: 16 modules
- Enhancement Layers registry: 8 layers
- PRE-FLIGHT and POST-FLIGHT framework health
- centralized production contract validation

Registry presence alone is not sufficient for a module to be considered operational. Runtime evidence is required for ACTIVE health.

## Watchlist contract
Operational reports use:
- OWNED: exactly 15 players from the authoritative squad baseline
- WATCHLIST: exactly 20 external players total
- maximum 5 watchlist players per position
- OWNED players are excluded from WATCHLIST
- candidates are screened through DSS, not selected only from latest-Gameweek haul

## Price Radar
Official current price and confirmed changes are authority. Engine trajectory dates remain derived estimates.

Price pressure is an overlay, not a football decision. HIGH/CRITICAL price signals should only become actionable when they intersect an owned player or DSS-approved external candidate and materially affect affordability, sell value, or a preferred multi-GW package. LiveFPL structured challenger context remains non-authoritative. OneFPL is checked at report time and compared as advisory context rather than fetched by the unattended collector.

## Authenticated Official read-only layer
Optional authenticated Official access is precision-only and may never become a dependency for the public core engine.

Allowlisted resource routes:
- `GET /api/me/`
- `GET /api/my-team/{team_id}/`
- `GET /api/entry/{team_id}/transfers-latest/`

Credential material and raw private payloads must never be persisted to public runtime artifacts.

## Collector and reporting cadence
Collector cadence and user-visible reports are separate.

Normal reports:
- 04:30 WIB Deep Review
- 12:30 WIB Midday Tactical Monitor
- 21:30 WIB Night Tactical + Price Monitor

At every scheduled report and on-demand report, report-time web intelligence is refreshed subject to availability and freshness policy. Match Mode runs approximately every 3 hours while relevant PL/FPL matches are active. Deadline review timing is handled by report governance.

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python -m src.runtime_v3.orchestrator --mode daily --stats
python -m src.engines.price_service
python -m src.engines.official_expansion
python -m src.engines.authenticated_official
python -m src.engines.report_time_intelligence
python -m src.engines.report_time_contract_validate
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
```

## Release governance
Every version-changing commit must keep these surfaces consistent:
- `src/version.py`
- runtime metadata
- `README.md`
- `IMPLEMENTATION_STATUS.json`
- `config/engine.json` schema metadata
- workflow display name
- release regression tests
- `MASTER_TASK_LIST_V3.md`

CI must fail on release metadata drift. The master task list must be updated in the same PR for every V3 change. Production-acceptance-only documentation may keep the existing engine/schema when runtime behavior and contracts are unchanged, but README and the master task list must record the acceptance evidence together.

## Historical milestones
- v3.4: reliability and native persistence
- v3.4.1: Price Radar baseline/noise filtering
- v3.5: Official 2026/27 rules compliance
- v3.5.1: isolated runtime publication
- v3.6: Official FPL P0/P1 expansion
- v3.7/v3.7.1: authenticated read-only Official layer and runtime isolation
- v3.8/v3.8.1: price trajectory and risk hotfix
- v3.10-v3.15: decision intelligence, prediction performance, lineup governance, historical priors, full DSS watchlist, and fast report serving
- v3.16: Source Registry + Adapter Layer
- v3.16.1: configuration ownership hardening
- v3.17: runtime-evidence DSS operationalization and optimizer guardrails
- v3.17.1: canonical V3 master task governance and Definition of Done
- v3.18.0: structured challenger observations, architecture/configuration hardening, and production acceptance
- v3.18.1: OneFPL adapter reachability/structured-access reliability patch
- v3.19.0: production-accepted report-time intelligence, OneFPL report-time delegation, Ben Crellin fixture strategy, pundit consensus-vs-DSS, Reddit/community governance

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
