# FPL iphoenk Engine v3.16.1

Production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release
- Engine version: `3.16.1`
- Schema version: `45`
- Release metadata source of truth: `src/version.py`
- Production runtime: bounded-process V3 microservices
- Runtime state is published to `runtime-data`; `main/data/**` is historical/source-repository material only.
- Official FPL remains the only native authority. Challenger/enrichment sources are fail-soft and may not overwrite native Official fields.

## v3.16.1 Configuration ownership hardening
v3.16.1 reduces mutable hardcoding without changing the production output schema.

Configuration ownership:
- `src/version.py` owns engine/schema/service release metadata.
- `config/engine.json` owns mutable runtime/user settings such as team ID, polling intervals, API retry/backoff/timeout, reconstruction baseline GW, and report list sizes.
- Environment variables may override explicitly supported runtime settings such as `FPL_TEAM_ID`, `FPL_LIVE_POLL_SECONDS`, and `FPL_TIMEOUT`.
- `config/rules/registry.json` + the active ruleset own FPL squad, lineup, scoring, chip, finance, and BPS rules.
- `config/v3_service_registry.json` owns service DAG/runtime orchestration settings.
- `config/sources/registry.json` owns source authority, capability, and adapter policy.

Hardening changes:
- removed duplicate Team ID from workflow and engine code
- squad size, position counts, position mapping, and max-per-club now come from the active ruleset
- live polling and SSE heartbeat now come from engine config
- Official API retries/backoff/timeout now come from engine config
- purchase-value reconstruction baseline and price list sizes now come from engine config
- CI regression tests reject the legacy hardcoded runtime literals and enforce release metadata consistency

## v3.16 Source Registry + Adapter Layer
V3.16 introduced a dedicated source infrastructure layer with registry-driven authority classes, isolated adapters, parallel health probes, fail-soft challenger/enrichment sources, and LiveFPL as a first-class challenger.

Important distinction: source reachability does not automatically mean structured data ingestion. `public_probe_does_not_equal_data_ingestion` remains a deliberate policy. Official FPL is native authority; challenger sources are independent evidence only.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, expanded Official detail surfaces, optional authenticated read-only Official data, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, provenance/freshness, framework health, snapshot integrity, DSS-driven watchlist selection, and decision-aware price monitoring.

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
4. Official public detail/secondary surfaces
5. Registered challenger/enrichment adapters such as LiveFPL, OneFPL, FPL-Core-Insights and vaastav according to capability and health
6. Web/news/tactical overlays

Third-party predictions are challengers, never native authority. Failed challenger/enrichment sources must fail soft and must not corrupt the Official baseline.

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
Official current price and confirmed changes are authority. Official threshold/projection fields, when available, are interpreted conservatively. Engine trajectory dates remain derived estimates.

Price pressure is an overlay, not a football decision. HIGH/CRITICAL price signals should only become actionable when they intersect an owned player or DSS-approved external candidate and materially affect affordability, sell value, or a preferred multi-GW package.

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

Match Mode runs approximately every 3 hours while relevant PL/FPL matches are active. Deadline review timing is handled by report governance rather than by hardcoded user-facing assumptions.

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python -m src.runtime_v3.orchestrator --mode daily --stats
python -m src.engines.price_radar
python -m src.engines.official_expansion
python -m src.engines.authenticated_official
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

CI must fail on release metadata drift.

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

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
