# FPL iphoenk Engine v3.20.2

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Production baseline remains `3.20.1` / schema `48` until this candidate is production-accepted.
- Current release candidate: `3.20.2` / schema `48`.
- Candidate scope: runtime artifact contract hardening.
- Service Registry: schema `12`, contract `v3.20.2-artifact-contract-hardening-15-owned-20-watchlist`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V1`.
- Machine Source Registry: `SOURCE_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Runtime state publishes only to `runtime-data`; `main/data/**` is historical/source-repository material.
- Canonical roadmap and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## v3.20.2 Artifact Contract Hardening
V3.20.2 closes the gap between fail-soft external-source availability and fail-closed internal artifact integrity. The serving/report contract remains schema 48 and the active topology remains 20 bounded services.

### Runtime integrity changes
- Every declared `.json` artifact is parsed strictly before service success is accepted into canonical runtime state.
- Isolated-service `latest.json` sidecars are strict-JSON validated before fan-in.
- Contract-specific validation is registry-owned in `config/runtime/artifact_contracts.json` rather than hardcoded inside consumer services.
- `challenger_observations.json` must be a JSON object with `schema_version=2`, `contract=challenger_observation_v2`, and an `observations` list before it can be promoted.
- A valid empty observations list remains a legitimate fail-soft external-data state.
- Malformed JSON, wrong contract/schema, or invalid internal artifact shape becomes an artifact-integrity failure and follows the service criticality policy.
- Critical service artifact corruption fails closed. Noncritical service failure still quarantines stale owned outputs rather than allowing old evidence to masquerade as current.
- The global convenience helper `read_json()` remains fail-soft for optional reads; integrity enforcement happens at the microservice acceptance boundary where ownership is explicit.

### Schema/version decision
- Engine: `3.20.2`.
- Serving/runtime schema: `48`, unchanged because report/output structure is unchanged.
- Service Registry schema: `12`, because runtime artifact-acceptance policy changes.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V1`.

## v3.20.1 Correctness Hardening
V3.20.1 fixed verified numerical and orchestration defects without changing schema 48:
- appearance points use unconditional `P(60+)` exactly once;
- native Official `element_type` maps correctly to projection position, restoring goalkeeper save-point projection;
- package captain mean/std come from the same captain row and captain variance includes the double-score covariance term;
- promotion failures obey service criticality and noncritical stale-output quarantine;
- obsolete direct-fetch projection runner was removed from `decision_intelligence.py`;
- XI battle closeness threshold moved to config ownership.

Production acceptance for V3.20.1 completed on 27 August 2026 with framework GREEN, Decision Engine HEALTHY, GO allowed, Gate0 16/16 PASS, DSS Core 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE, 15 OWNED + 20 WATCHLIST valid, and runtime within the 45-second budget.

## v3.20.0 Architecture Hardening
V3.20.0 removed the active monolithic base collector and established artifact-owned service boundaries:
1. `official_snapshot` owns standard Official public baseline fetches.
2. `team_state` owns squad identity, finance and chip state.
3. `market_state` owns universe/current-price/market state.
4. `live_state` owns personalized live scoring state.
5. `advanced_stats` owns current enrichment sync.
6. `base_snapshot` performs deterministic base fan-in.

`src.engine` is compatibility/manual CLI only and is forbidden as an active production service entrypoint. Existing prediction, price, lineup, governance, watchlist and reporting boundaries remain coarse-grained because they still have cohesive artifact/decision ownership.

## Operational invariants
- Official FPL is the only native authority for Official fields and scoring.
- Verified official facts outrank model challengers, pundit and community evidence.
- Missing external evidence is never fabricated.
- External-source unavailability may fail soft; broken internal critical computation/artifacts fail closed.
- OWNED is exactly 15 players.
- WATCHLIST is exactly 20 external players: 5 GK + 5 DEF + 5 MID + 5 FWD, excluding OWNED.
- Gate0 must be 16/16 PASS for unqualified GO.
- DSS Core must be 50/50 ACTIVE, Extensions 16/16 ACTIVE, Enhancements 8/8 ACTIVE.
- Runtime artifacts publish to `runtime-data`, never directly to protected `main`.
- Microservice boundaries follow artifact ownership/failure semantics, not file size.
- Mutable policy belongs in config/registry/environment ownership, not scattered Python literals.

## Runtime architecture
The active runtime is a dependency-aware bounded-process microservice DAG driven by `config/v3_service_registry.json`.

Key properties:
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
- production runtime budget below 45 seconds;
- validated publication to isolated `runtime-data`.

## Configuration ownership
- `src/version.py`: engine/schema/service release metadata.
- `config/engine.json`: mutable runtime/user settings and stale windows.
- `config/runtime/collector_policy.json`: collector timezone/cadence/deadline/match windows.
- `config/runtime/artifact_contracts.json`: runtime artifact integrity and contract-specific validation.
- `config/v3_service_registry.json`: service DAG, criticality, inputs/artifacts, isolation and runtime policy.
- `config/sources/registry.json`: unattended source authority/network/ingestion policy.
- `config/sources/report_time_registry.json`: report-time OneFPL, fixture-strategy, pundit, community and verified-news policy.
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
Every visible operational report remains decision-first and includes:
- all 15 OWNED players;
- all 20 governed external WATCHLIST players;
- recommended formation;
- exact Starting XI;
- Captain and Vice-Captain;
- Bench 1, Bench 2, Bench 3 and GK Bench;
- actionable Price Radar;
- consensus-vs-DSS context where material.

Normal visible reports are 04:30, 12:30 and 21:30 WIB, with separate Match/Deadline/Final Review governance in the Master Monitor.

## Current advanced-stat aliases
Per-GW files remain archives. Active current evidence uses:
- `data/stats/shots_current.json`
- `data/stats/playermatchstats_current.json`

Active registries may not pin a fixed Gameweek for evidence intended to mean current state.

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
Every release must keep these surfaces consistent:
- `src/version.py`
- `README.md`
- `IMPLEMENTATION_STATUS.json`
- workflow display name
- `config/engine.json` schema metadata
- Service/Source/Runtime-Artifact/Report registries as applicable
- release regression tests
- `MASTER_TASK_LIST_V3.md`

A release is not production-complete merely because unit tests are GREEN. Required acceptance includes full integration, architecture/source/decision/watchlist/report/report-time contracts, runtime budget, merge, production collect, validated `runtime-data` publication, and framework GREEN/HEALTHY/GO evidence.

## Historical milestones
- V3.17: runtime-evidence DSS operationalization.
- V3.17.1: canonical Master Task governance.
- V3.18: structured challenger ingestion and configuration ownership.
- V3.19: report-time intelligence and consensus-vs-DSS.
- V3.20.0: artifact-owned microservice architecture hardening.
- V3.20.1: numerical correctness and promotion-failure hardening.
- V3.20.2: runtime artifact contract and strict JSON acceptance hardening.
