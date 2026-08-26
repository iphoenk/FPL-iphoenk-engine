# FPL iphoenk Engine

## v3.16 Source Registry + Adapter Layer
v3.16 separates external-source infrastructure from DSS/report logic. Official FPL remains the only native authoritative source. Third-party sources are classified as challenger or enrichment and fail independently without silently overriding Official fields.

Source configuration is registry-driven under `config/sources/registry.json`, with DSS capability mapping in `config/sources/dss_source_map.json`.

Current source classes:
- AUTHORITATIVE: Official FPL
- CHALLENGER: LiveFPL, OneFPL, Fantasy Football Fix, Fantasy Football Hub
- ENRICHMENT: FPL Core Insights, vaastav, Fantasy Football Scout, Understat, API-Football, optional Sportmonks/manual evidence streams

Important v3.16 governance:
- source reachability is not treated as ingested data
- missing third-party observations are never fabricated
- Understat shot x/y may be used only as a **box-shot-location proxy**, never labelled as actual box touches
- API-Football is optional and requires `API_FOOTBALL_KEY`; absence of the key is `CONFIG_REQUIRED`, non-blocking
- quota-limited API-Football data must use persistent gameweek/competition caching rather than hourly full refresh
- competition IDs for UCL/UEL/UECL/FA Cup/EFL Cup/Club Friendlies must be resolved from the provider at runtime rather than hardcoded from memory
- international fixtures/minutes may be API-backed, but official call-ups and travel context remain separate evidence and must not be inferred when unavailable
- Sportmonks stays disabled by default until current Premier League coverage is verified for the configured plan/token

The source layer runs as its own bounded process service after the collector, in parallel with other independent services, and emits `source_health.json` plus `source_registry_runtime.json` for downstream governance.

## Production report contract
Visible FPL reports remain decision-first and use the fast-serving artifacts produced by the Report Materializer. Every visible report must retain all 15 owned players and all 20 governed external watchlist players (5 GK, 5 DEF, 5 MID, 5 FWD). Technical/source artifacts are lazy-loaded unless they materially affect a decision.

## Runtime architecture
Production V3 uses coarse-grained, dependency-aware process microservices with shared per-run Official FPL cache, isolated service data, deterministic fan-in, and fail-closed critical governance. Generated runtime data is published to the separate `runtime-data` branch; `main/data/**` is not the current production bridge.

## Source authority principle
1. Direct Official FPL native fields and Official scoring
2. Authenticated Official FPL native account fields when valid and directly applicable
3. Persisted Official-derived production runtime state
4. Third-party challengers/enrichments according to registry role and evidence quality

Third-party predictions, tactical context, community data and source-specific metrics can strengthen or challenge internal evidence, but never silently replace a current Official native field.
