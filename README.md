# FPL iphoenk Engine v3.21.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current production release: `3.21.0` / schema `49`.
- Production acceptance: COMPLETE on 27 August 2026.
- Production source commit: `da2be79045c0eb1015b75697eb24b030ffaa4abe`.
- Production workflow run: `33047071671` (`FPL iphoenk collector v3.21.0 microservices`) completed through validated `runtime-data` publication.
- Service Registry: schema `13`, contract `v3.21-weather-report-transparency-15-owned-20-watchlist`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry: `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Runtime state publishes only to `runtime-data`; `main/data/**` is historical/source-repository material.
- Canonical roadmap and Definition of Done: `MASTER_TASK_LIST_V3.md`.

Production acceptance evidence for V3.21.0/schema49 includes full unit/regression and architecture checks, bounded 20-service integration, source/decision/watchlist/report/report-time contracts, production collect, validated `runtime-data` publication, 15 OWNED + 20 WATCHLIST contract, weather coverage 10/10 fixtures with zero unresolved venue identity, governed selection transparency for all 15 OWNED, and runtime wall time 16.606s against the 45s budget.

## v3.21.0 Weather Intelligence + Report Transparency
V3.21 adds weather as a governed optional enrichment and makes the visible report expose the model evidence needed to audit lineup decisions quickly.

### Weather Intelligence
- Open-Meteo is registered as a noncritical `ENRICHMENT`, not an authority or model challenger.
- Weather runs inside the existing Source Layer. No 21st microservice is created.
- Official fixture ownership remains in `official_snapshot`; weather code consumes the already-fetched snapshot and never refetches standard Official FPL fixtures.
- Premier League venue identity/coordinates are owned by `config/venues/premier_league_2026_27.json` and validated against Official team ID + name so stale-season mappings fail soft instead of being silently reused.
- Forecast URL, timeout, fields, horizon, retention, freshness, confidence and severity thresholds are owned by `config/intelligence/weather_context.json`.
- `fixture_weather.json` retains bounded observations per fixture and identifies the closest retained observation to kickoff for later anomaly review.
- Weather tracks temperature, precipitation probability, precipitation amount/intensity, wind speed, wind gusts and weather code. Rain probability is never treated as rainfall intensity.
- Weather is observational/advisory only in V3.21. It may not directly change xPts, Starting XI, captaincy, transfer decisions, watchlist membership or package rankings.
- Post-match weather may be surfaced only as `POSSIBLE_CONTRIBUTING_FACTOR` when temporally relevant. A causal weather claim requires future calibrated evidence and must consider opponent strength, tactics, game state/red cards, injury, rotation, role, venue and sample noise.
- `fixture_weather.json` has a registry-owned runtime artifact contract and valid empty forecast windows remain fail-soft.

### Report transparency
Every serving payload now exposes for all 15 OWNED players:
- current-Gameweek `xpts_gw`;
- `xpts_std` uncertainty;
- governed `selection_score`;
- `lineup_status` = START/BENCH;
- `choice_state` = OPEN for players involved in a governed close choice, otherwise CURRENT;
- existing xMins/start probability and model-confidence information.

The report therefore no longer requires a reader to inspect a raw lineup artifact to understand why a goalkeeper or another player was selected. Close goalkeeper choices can expose both goalkeepers as OPEN while still providing one current starter recommendation.

### Confidence calibration guard
Early-season conservative confidence is allowed, but it is now auditable. `config/intelligence/prediction_evaluation.json` owns the review rule. Before GW5, zero HIGH-confidence owned players is labelled `EARLY_SEASON_CONSERVATIVE`; at GW5 or later, if the configured minimum HIGH count is still not reached, reports expose `CALIBRATION_REVIEW_REQUIRED`. The engine does not manufacture HIGH confidence merely to satisfy the guard.

### Settled prediction validation
V3 already freezes the final pre-deadline forecast and settles it against finished-event actuals using points MAE/RMSE, xMins MAE, starter Brier, clean-sheet Brier and Spearman correlation. V3.21 exposes the settled-sample state in every serving report and explicitly states that formula/test correctness is not evidence of predictive accuracy. Predictive accuracy claims require settled frozen forecasts.

### Schema/version decision
- Engine: `3.21.0`.
- Serving/runtime schema: `49`, because all primary report-serving payloads gain required owned xPts/selection/choice-state, model-validation and weather-context fields.
- Service Registry: schema `13`.
- Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry: `REPORT_ARTIFACT_REGISTRY_V3`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Active microservice count remains `20`.

## v3.20.2 Artifact Contract Hardening
V3.20.2 closed the gap between fail-soft external-source availability and fail-closed internal artifact integrity. Every declared JSON artifact is parsed strictly before acceptance; contract-specific validation is registry-owned; valid empty external observations remain fail-soft; malformed/wrong-contract critical artifacts fail closed; noncritical failures quarantine stale outputs.

V3.20.2 production acceptance completed on 27 August 2026 with framework GREEN, Decision Engine HEALTHY, GO allowed, Gate0 16/16 PASS, DSS Core 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE and runtime safely below the 45-second budget.

## v3.20.1 Correctness Hardening
V3.20.1 fixed verified numerical/orchestration defects: unconditional 60-minute appearance probability, Official `element_type` goalkeeper save-route projection, captain mean/std identity and double-score variance, promotion-failure criticality/stale-output quarantine, removal of obsolete direct-fetch projection runner and config-owned XI battle threshold.

## v3.20.0 Architecture Hardening
V3.20.0 removed the active monolithic base collector and established artifact-owned service boundaries:
1. `official_snapshot` owns standard Official public baseline fetches.
2. `team_state` owns squad identity, finance and chip state.
3. `market_state` owns universe/current-price/market state.
4. `live_state` owns personalized live scoring state.
5. `advanced_stats` owns current enrichment sync.
6. `base_snapshot` performs deterministic base fan-in.

`src.engine` is compatibility/manual CLI only and is forbidden as an active production service entrypoint. Prediction, price, lineup, governance, watchlist and reporting remain coarse-grained because their artifact/decision ownership is cohesive.

## Operational invariants
- Official FPL is the only native authority for Official fields and scoring.
- Verified official facts outrank model challengers, pundit/community and weather context.
- Missing external evidence is never fabricated.
- External-source unavailability may fail soft; broken internal critical computation/artifacts fail closed.
- OWNED is exactly 15 players.
- WATCHLIST is exactly 20 external players: 5 GK + 5 DEF + 5 MID + 5 FWD, excluding OWNED.
- Gate0 must be 16/16 PASS for unqualified GO.
- DSS Core must be 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE.
- Runtime artifacts publish to `runtime-data`, never directly to protected `main`.
- Microservice boundaries follow artifact ownership/failure semantics, not file size.
- Mutable policy belongs in config/registry/environment ownership, not scattered Python literals.
- Weather is context, not decision authority.
- Formula correctness and predictive accuracy are separate claims.

## Runtime architecture
The active runtime is a dependency-aware bounded-process microservice DAG driven by `config/v3_service_registry.json`.

Key properties:
- exactly 20 active services for V3.21;
- generic root-service scheduling;
- bounded parallelism and per-service timeouts;
- isolated service workspaces where appropriate;
- one standard Official snapshot owner plus shared HTTP cache;
- declared inputs/artifacts and deterministic fan-in;
- strict declared-JSON artifact validation before acceptance;
- registry-owned specialized artifact contracts;
- fail-closed critical services and fail-soft optional external evidence;
- stale-output quarantine for noncritical failures;
- ephemeral `official_snapshot.json` removed before publication;
- weather enrichment remains inside Source Layer;
- production runtime budget below 45 seconds;
- validated publication to isolated `runtime-data`.

## Configuration ownership
- `src/version.py`: engine/schema/service release metadata.
- `config/engine.json`: mutable runtime/user settings and stale windows.
- `config/runtime/collector_policy.json`: collector timezone/cadence/deadline/match windows.
- `config/runtime/artifact_contracts.json`: runtime artifact integrity and contract-specific validation.
- `config/v3_service_registry.json`: service DAG, criticality, inputs/artifacts, isolation and runtime policy.
- `config/sources/registry.json`: unattended source authority/network/ingestion policy including Open-Meteo capability ownership.
- `config/sources/report_time_registry.json`: report-time OneFPL, fixture-strategy, pundit, community and verified-news policy.
- `config/venues/premier_league_2026_27.json`: venue identity and coordinates.
- `config/intelligence/weather_context.json`: weather endpoint/fields/freshness/severity/attribution policy.
- `config/rules/registry.json` + active ruleset: FPL legality/scoring/chips/finance.
- `config/intelligence/*.json`: xMins, projections, optimizer, lineup, price, reporting and calibration policy.
- `config/report_artifact_registry.json`: fast/deep serving artifact contract.

## Report-time intelligence
Visible reports perform fresh report-time review where applicable:
- OneFPL as `MODEL_CHALLENGER`;
- Ben Crellin as `FIXTURE_STRATEGY_EXPERT`;
- FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar and FFScout editorial as `PUNDIT_CONSENSUS`;
- Reddit/community as cross-check-required `COMMUNITY_SIGNAL`;
- Premier League/official-club sources as `VERIFIED_NEWS`.

Pundit consensus is compared with DSS using `ALIGN`, `DIVERGE`, `REVIEW_DIVERGENCE` or `NEUTRAL`. Consensus never silently mutates DSS decisions.

## Reporting contract
Every visible operational report includes:
- all 15 OWNED with current-GW xPts, uncertainty, selection score, lineup status and choice state;
- all 20 governed external WATCHLIST players;
- recommended formation;
- exact Starting XI;
- Captain and Vice-Captain;
- Bench 1, Bench 2, Bench 3 and GK Bench;
- actionable Price Radar;
- current confidence-calibration/settled-prediction status;
- material weather context when present;
- consensus-vs-DSS context where material.

Normal visible reports are 04:30, 12:30 and 21:30 WIB, with separate Match/Deadline/Final Review governance in the Master Monitor.

## Current advanced-stat aliases
Per-GW files remain archives. Active current evidence uses `data/stats/shots_current.json` and `data/stats/playermatchstats_current.json`. Active registries may not pin a fixed Gameweek for evidence intended to mean current state.

## Main commands
```bash
pip install -r requirements.txt
python -m src.engines.architecture_contract_validate
python -m src.runtime_v3.orchestrator --mode daily --stats
python -m src.runtime_v3.orchestrator --mode daily --stats --deep-stats
python -m src.engines.source_contract_validate
python -m src.engines.production_contract_validate
python -m src.engines.watchlist_contract_validate
python -m src.engines.report_serving_validate
python -m src.engines.report_time_contract_validate
python -m pytest -q
```

## Release governance
Every release must keep `src/version.py`, README, IMPLEMENTATION_STATUS, workflow name, engine schema, Service/Source/Runtime-Artifact/Report registries, release tests and `MASTER_TASK_LIST_V3.md` consistent. A release is not production-complete merely because unit tests are GREEN. Acceptance requires full integration, architecture/source/decision/watchlist/report/report-time contracts, runtime budget, merge, production collect, validated `runtime-data` publication and framework GREEN/HEALTHY/GO evidence.

## Historical milestones
- V3.17: runtime-evidence DSS operationalization.
- V3.17.1: canonical Master Task governance.
- V3.18: structured challenger ingestion and configuration ownership.
- V3.19: report-time intelligence and consensus-vs-DSS.
- V3.20.0: artifact-owned microservice architecture hardening.
- V3.20.1: numerical correctness and promotion-failure hardening.
- V3.20.2: runtime artifact contract and strict JSON acceptance hardening.
- V3.21.0: weather intelligence, all-15 xPts/selection transparency, confidence calibration guard and settled-validation visibility; production accepted 27 August 2026.
