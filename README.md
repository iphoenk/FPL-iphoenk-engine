# FPL iphoenk Engine v3.20.1

Production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Production baseline: `3.20.0` / schema `48` until V3.20.1 production acceptance completes.
- Release candidate: `3.20.1` / schema `48`.
- Release metadata source of truth: `src/version.py`.
- Service Registry: schema `11`, contract `v3.20-architecture-hardening-15-owned-20-watchlist`.
- Machine Source Registry: `SOURCE_REGISTRY_V3`.
- Runtime state publishes only to `runtime-data`; `main/data/**` is historical/source-repository material.
- Official FPL remains the only native authority. Challenger, enrichment and report-time sources may not overwrite Official-native fields.
- Canonical roadmap and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## v3.20.1 Correctness Hardening
V3.20.1 is a patch release for numerical correctness and runtime fault handling. It does not change the serving/report schema, the 15 OWNED + 20 WATCHLIST contract, the report-time intelligence contract, or the 20-service production topology.

### Correctness fixes
- Appearance points now use the unconditional 60-minute probability exactly once: `P(start) + P(bench appearance) + P(60+)`.
- Projection position is derived from Official `element_type` when a string position is absent, restoring the goalkeeper save-points route for native bootstrap rows.
- Package captain variance now uses the same player selected by captain mean and includes the covariance created because the captain is already present once in lineup variance. Under the independent-player baseline, the extra captain variance is `((1+w)^2 - 1) * Var(X)`.
- Artifact-promotion failures now enter the same critical/noncritical service-failure path as command failures. A noncritical failure also removes stale owned outputs and `latest.json` keys before downstream services continue.
- The obsolete direct-fetch projection runner was removed from `decision_intelligence.py`; production projection components now live under `src/models/projection_components.py`, while `decision_intelligence.py` remains package-optimizer-only.
- Starting-XI battle closeness is config-owned under `config/intelligence/lineup_governance.json` rather than hardcoded in Python.

### Review decisions that were intentionally not applied verbatim
`challenger_source_failure_does_not_block_decisions` refers to external challenger/source availability, which is normalized fail-soft before the internal challenger scorecard runs. The deterministic internal `challenger_scorecard` service remains critical because a code/artifact-integrity failure is different from an unavailable external source; silently accepting a broken internal scorecard could preserve stale evidence. V3.20.1 strengthens generic noncritical stale-output quarantine without weakening this integrity boundary.

The package optimizer and final lineup governance also remain separate. The package optimizer evaluates candidate squad packages with a raw expected-points lineup approximation inside its package objective, while final lineup governance selects the actual XI with risk-adjusted selection score, DNP penalties, captain safety and bench governance. They share legality/rules contracts but intentionally do not share one selector because their objectives differ.

### Schema decision
- Engine: `3.20.1`.
- Serving/runtime schema: `48`, unchanged because output structure and consumer contracts are unchanged.
- Service Registry schema: `11`, unchanged because the service topology and artifact contract are unchanged.
- Lineup-governance policy schema: `2`, because the mutable battle-margin threshold now has an explicit config owner.

V3.20.1 remains a release candidate until PR CI, bounded integration, merge, production collector, validated `runtime-data` publication and framework GREEN/HEALTHY/GO verification complete.

## v3.20.0 Architecture Hardening
V3.20 removes the remaining active monolithic base collector and consolidates mutable infrastructure policy under explicit registry/config ownership. The user-facing report/serving contract remains schema 48, so this is an engine architecture release without a serving-schema bump.

### Base runtime ownership
The old active `collector -> src.engine` boundary is replaced by artifact-owned services:
1. `official_snapshot`: single owner for standard Official public baseline fetches.
2. `team_state`: authoritative squad identity, purchase/sell ledger, team value and chip state.
3. `market_state`: universe, current-price cache and Official transfer-pressure baseline.
4. `live_state`: personalized submitted-picks/live-event scoring state.
5. `advanced_stats`: current enrichment sync and optional deep-stat refresh.
6. `base_snapshot`: deterministic fan-in that assembles `latest.json`, `native.json` and history without doing new network fetches or football decisions.

`src.engine` remains only as a compatibility/manual CLI facade. It is forbidden from the active production service registry.

### Why these boundaries were split
The former collector owned unrelated network, finance, market, live-scoring, statistics and snapshot responsibilities. Those domains have distinct artifacts and failure semantics, so separating them reduces coupling and clarifies ownership. Existing price, prediction, lineup, governance, watchlist, reporting and report-materializer services remain coarse-grained because they still have cohesive decision/artifact ownership. V3.20 explicitly rejects splitting services merely because a Python file is large.

### Generic DAG orchestration
`src/runtime_v3/orchestrator.py` no longer special-cases a service named `collector`. Any service with no dependency may be a root. The DAG validates unknown dependencies, self-dependencies, cycles, unsupported/inline commands and critical-service failures. Isolated services promote only declared artifacts and declared `latest.json` keys.

`official_snapshot.json` is an internal ephemeral artifact. Downstream prediction and historical-prior services consume it during the run instead of refetching the same standard Official baseline, and the orchestrator removes the snapshot before publication.

### Configuration and registry ownership
- `src/version.py`: engine/schema/service title.
- `config/engine.json`: mutable engine/user runtime settings such as team ID, retry/backoff/timeout, reconstruction baseline, horizons and stale windows.
- `config/runtime/collector_policy.json`: collector timezone, primary/adaptive/deep-stats schedules, deadline-intensive window, match window and fixture-probe policy.
- `config/sources/registry.json`: unattended source authority, network locations, source season/files, ingestion timeouts and adapters.
- `config/sources/report_time_registry.json`: report-time OneFPL/fixture-strategy/pundit/community/verified-news classes and freshness policy.
- `config/rules/registry.json` + active ruleset: FPL legality/scoring/chip/finance rules.
- `config/v3_service_registry.json`: active service DAG, process isolation, inputs/outputs, performance budget and orchestration policy.
- `config/intelligence/*.json`: projection, xMins, package, lineup, price, reporting and calibration policies.
- `config/report_artifact_registry.json`: serving artifact contract.

Legacy `config/sources.json` is removed. Source adapters are not allowed to carry a second mutable network/source policy in Python.

### Current advanced-stat aliases
Per-GW artifacts remain archives, but active current evidence uses:
- `data/stats/shots_current.json`
- `data/stats/playermatchstats_current.json`

Active Source/DSS registries may not pin `_gw1.json` or any fixed Gameweek for evidence intended to mean current state.

### Deep-stats workflow
The standalone deep-stats workflow that committed `data/**` directly to `main` is removed. Deep stats now use the same production workflow and validated `runtime-data` publication path. The cadence is owned by `config/runtime/collector_policy.json`.

### Semantic model IDs
Active model identity is independent of engine release numbering. Projection configuration uses semantic model identifiers rather than labels such as `v310` or `v313`. Historical compatibility filenames/modules may remain for backward compatibility, but they are forbidden as active service entrypoints.

### Architecture anti-regression gate
`python -m src.engines.architecture_contract_validate` is a mandatory CI/integration/production gate. It rejects, among other things:
- reintroduction of `config/sources.json`;
- an active monolithic `collector` service;
- active `src.engine`, `src.reliability_overlay` or old version-stamped service entrypoints;
- inline Python commands in the Service Registry;
- fixed-GW active source/DSS evidence paths;
- stale engine-version model IDs;
- missing collector-policy workflow schedules;
- direct workflow pushes of runtime data to `main`;
- reintroduction of the legacy deep-stats workflow;
- prediction/historical-prior services that stop consuming the shared Official snapshot;
- a second direct-fetch projection entrypoint in `decision_intelligence.py`;
- hardcoded XI battle threshold ownership;
- promotion failures bypassing service criticality handling or stale-output quarantine.

### Schema decision
- Engine: `3.20.0`.
- Serving/runtime schema: `48`, unchanged because `decision_brief`, `deep_review_payload`, 15+20 roster contract and report-time evidence contract are unchanged.
- Service Registry schema: `11`.
- Source Registry: `SOURCE_REGISTRY_V3`.

### Production acceptance evidence
V3.20.0 production acceptance completed on 27 August 2026. PR #34 merged to `main` as `edeaff7a5b1f8173392cb528f93e132836608ed5`. Production push workflow run `33032958368` passed architecture, runtime, source capability, production decision/report, full DSS watchlist, report serving, report-time intelligence and validated `runtime-data` publication. Production `runtime-data` reports engine `3.20.0` / schema `48`, framework GREEN, decision engine HEALTHY, recommendation allowed and GO allowed; Gate0 is 16/16 PASS, DSS Core 50/50 ACTIVE, DSS Extensions 16/16 ACTIVE and Enhancement Layers 8/8 ACTIVE. `SOURCE_REGISTRY_V3` is GREEN/non-blocking, OneFPL remains disabled in the unattended collector, and the ephemeral `official_snapshot.json` is not published to `runtime-data`.

## v3.19.0 Report-Time Intelligence
V3.19 separates machine-ingested sources from report-time web intelligence. Sources useful for decision context but inappropriate or unreliable for unattended collector access are refreshed when a scheduled or on-demand report is prepared, then compared with DSS without silently mutating DSS.

Report-time source classes:
- `MODEL_CHALLENGER`: OneFPL price/transfer/captaincy/planner context through normal report-time web access.
- `FIXTURE_STRATEGY_EXPERT`: Ben Crellin for blank/double Gameweeks, fixture rearrangements, schedule probabilities and chip-window context. This class does not vote on player projection.
- `PUNDIT_CONSENSUS`: FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar and Fantasy Football Scout editorial views.
- `COMMUNITY_SIGNAL`: Reddit r/FantasyPL eye-test, role/rotation/injury leads, captain polls and sentiment. Community evidence requires corroboration before fact promotion.
- `VERIFIED_NEWS`: Premier League/official-club factual availability, suspension, fixture confirmation and manager/team news.

Pundit consensus is explicitly compared with DSS as `ALIGN`, `DIVERGE`, `REVIEW_DIVERGENCE` or `NEUTRAL`; vote count is advisory and never becomes automatic DSS authority. A machine snapshot without a fresh visible-report web pass reports `REFRESH_REQUIRED` rather than pretending external evidence was checked.

V3.19.0 production acceptance completed on 27 August 2026. PR #32 merged as `4b5f5f72146400a25c956e7628105b7680effe84`; production collector and `runtime-data` publication passed; framework was GREEN/HEALTHY/GO with Gate0 16/16, Core50, Extensions16 and Enhancements8.

## v3.18 Structured Challenger and configuration hardening
V3.18 introduced normalized challenger observations, provenance/freshness, reachability-vs-capability health, TTL/LKG/stale/disagreement governance and non-authoritative Price Radar challenger context. V3.18 also established registry-owned framework expected counts, config-owned Price Radar/refresh/horizon policies and version-neutral active prediction/price service entrypoints.

V3.18.1 diagnosed OneFPL unattended-access restrictions explicitly. V3.19 then delegated OneFPL to report-time web intelligence instead of attempting access-control workarounds.

## V3 operational invariants
- Gate 0: 16/16 PASS for unqualified GO.
- DSS Core: 50/50 ACTIVE.
- DSS Extensions: 16/16 ACTIVE.
- Enhancement Layers: 8/8 ACTIVE.
- OWNED: exactly 15 authoritative players.
- WATCHLIST: exactly 20 external players, exactly 5 GK + 5 DEF + 5 MID + 5 FWD, with no OWNED overlap.
- Official FPL native fields and scoring always outrank third-party model/opinion evidence.
- Missing external observations are never fabricated.
- Critical services fail closed; optional external evidence fails soft.
- Microservice boundaries follow data/artifact ownership and failure isolation, not line count.

## Rules authority
`src/rules.py` loads the active ruleset from `config/rules/registry.json` and is the code-facing rules interface.

Regression-tested 2026/27 rules include squad composition, max three per club, legal starting formations, captain/vice constraints, appearance and position-specific scoring, assists, clean sheets, saves, penalties, cards, own goals, bonus, defensive contribution thresholds/caps, Wildcard, Free Hit, Triple Captain, Bench Boost and public purchase/sell-value reconstruction.

Local reconstruction is an audit aid only and may not override Official FPL native scoring, rank, price or confirmed fields.

## Source authority
1. Direct Official FPL native fields and scoring.
2. Authenticated Official FPL read-only account fields when valid and directly applicable.
3. Persisted Official-derived runtime bridge on `runtime-data`.
4. Verified official team/competition news and Official detail surfaces.
5. Structured analytics such as FPL Core Insights and vaastav.
6. Registered machine challengers such as LiveFPL when valid structured observations exist.
7. Report-time model/strategy/pundit/community intelligence under `REPORT_TIME_SOURCE_REGISTRY_V1`.

Third-party predictions and opinions are evidence, never native authority.

## Runtime architecture
The active production/candidate runtime is a bounded-process dependency-aware microservice orchestrator driven by `config/v3_service_registry.json`.

Key properties:
- generic root DAG scheduling;
- bounded parallelism and per-service timeout;
- isolated service work directories where appropriate;
- a shared Official HTTP cache plus a single baseline Official snapshot owner;
- declared inputs/artifacts and deterministic fan-in;
- fail-closed critical services;
- runtime performance budget and metadata;
- validated publication to isolated `runtime-data`;
- version-neutral active service entrypoints;
- report-time web intelligence remains in the report boundary rather than becoming an unattended crawler service.

## Reporting contract
Every visible operational report must remain decision-first and include all 15 OWNED plus all 20 governed external WATCHLIST players. The current Master Monitor additionally requires explicit recommended formation, exact Starting XI, Captain, Vice-Captain, Bench 1, Bench 2, Bench 3 and GK Bench on every visible report, even when unchanged.

Report-time intelligence is refreshed for visible scheduled/on-demand/deadline reports. Silent hourly internal checks remain bounded and do not perform a broad pundit/community sweep unless a material alert/deadline/emergency trigger requires it.

## Collector and report cadence
Machine collector cadence is controlled by `config/runtime/collector_policy.json` and is separate from user-visible report cadence.

Normal visible reports:
- 04:30 WIB Deep Review
- 12:30 WIB Midday Tactical Monitor
- 21:30 WIB Night Tactical + Price Monitor

Deadline/Match modes are governed separately by the Master Monitor. Deep-stat machine refresh runs through the production workflow and `runtime-data`, not through a workflow that commits runtime data to `main`.

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
python fpl_daily_tasks.py daily --stats
python fpl_daily_tasks.py deadline --stats
```

## Release governance
Every version-changing release must keep these surfaces consistent:
- `src/version.py`
- runtime metadata
- `README.md`
- `IMPLEMENTATION_STATUS.json`
- `config/engine.json` schema metadata
- workflow display name
- Service/Source/Report registries as applicable
- release regression tests
- `MASTER_TASK_LIST_V3.md`

CI must fail on release metadata or architecture ownership drift. A version is not production-complete merely because unit tests are green; merge, production collect, validated `runtime-data` publication and framework GREEN/HEALTHY/GO evidence are also required.

## Historical milestones
- v3.4-v3.9: reliability, price, rules, runtime isolation and Official expansion.
- v3.10-v3.15: decision intelligence, prediction performance, lineup governance, historical priors, full DSS watchlist and fast report serving.
- v3.16: Source Registry + Adapter Layer.
- v3.16.1: configuration ownership hardening.
- v3.17: runtime-evidence DSS operationalization and optimizer guardrails.
- v3.17.1: canonical V3 Master Task governance.
- v3.18.0: structured challenger ingestion and architecture/configuration hardening.
- v3.18.1: OneFPL unattended-access reliability diagnosis.
- v3.19.0: report-time intelligence, pundit consensus-vs-DSS and OneFPL report-time delegation.
- v3.20.0: production-accepted artifact-owned base-service decomposition, generic DAG, Source Registry V3, collector policy, current advanced-stat aliases and architecture anti-regression gate.
- v3.20.1 candidate: projection/scoring correctness, promotion fault handling, legacy projection-path cleanup and config-owned XI battle threshold; serving schema remains 48.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
