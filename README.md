# FPL iphoenk Engine v3.22.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current accepted production release: `3.22.0` / schema `49`.
- V3.22 production acceptance is COMPLETE: accepted source commit `3f35c06f39869e594f6e1a127437a2272c0fc515`, production FAST run `33059540147`, rolling runtime-data commit `5678fcb2f4f8e5934728ff6a8b955a401a42883d`.
- Accepted FAST runtime is `6.419s` against the `<10s` target; accepted peak RSS is about 85 MB parent / 109 MB child.
- Rolling `runtime-data` publication is production-proven as a parentless current-state snapshot: 48 files / about 17.84 MB; `history.jsonl` is not published.
- Service Registry: schema `13`, production contract `v3.22-runtime-optimization-fast-under-10s`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry: `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Runtime state publishes only to `runtime-data`; new mutable runtime output is ignored from `main`.
- Canonical roadmap and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## v3.22.0 Runtime Optimization Foundation
V3.22 separates interactive decision regeneration from heavier enrichment refresh while preserving the 20-service artifact-owned architecture and schema49 serving contract.

- FAST/LIVE/FULL/DEEP execution profiles are registry-owned.
- FAST target is under 10 seconds with a temporary 45-second legacy ceiling during transition.
- Heavy but reusable `advanced_stats`, `historical_prior`, `source_layer`, and `official_detail` artifacts can be reused only when complete, contract-valid and within profile-specific freshness windows.
- REC-31 makes production validation profile-aware: `REUSED` is accepted only for a service declared reusable by the active profile and carrying artifact-validation evidence.
- REC-32 preserves only registry-owned `latest_keys`/`latest_file_keys` for reusable services through base fan-in, so a reused artifact retains the same canonical state contract without carrying unrelated stale state.
- CI, FAST runtime, and FULL/DEEP refresh are split into separate workflows; FAST cadence gate runs before dependency installation when a scheduled adaptive slot can be skipped.
- Runtime checkout is shallow (`fetch-depth: 1`) instead of full-history.
- Runtime publication is whitelist-based and production-proven as a rolling parentless current-state snapshot rather than hourly Git history as a database.
- Runtime telemetry exposes wall time, queue wait, service timing, seed/promotion bytes, temp bytes, parent/child peak RSS, and cache entries.
- `player_features.json` normalizes advanced-stat evidence and provenance but remains decision-neutral until REC-01/REC-02 explicitly opt the projection model in.
- No new microservice is introduced for this optimization foundation.

Production acceptance evidence: REC-32 CI run `33059384073` passed 150 tests, FULL integration and FAST-after-FULL at 4.602s; accepted production run `33059540147` completed FAST in 6.419s with framework GREEN, prediction quality HEALTHY, Gate0 16/16, 15 OWNED + 20 WATCHLIST and all source/report/report-time contracts PASS. The accepted runtime-data commit is a root commit with zero parents and a 48-file whitelist snapshot.

REC-33 is the next runtime optimization item: investigate FULL Refresh Source-Layer latency variance. One CI FULL run reached 55.522s because Source Layer took 45.964s. This is a background/full-refresh issue and does not block the accepted FAST <10s application path.

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
- Engine production: `3.22.0`; accepted production schema: `49`.
- Serving/runtime schema remains `49`; V3.22 changes runtime execution/publication, not the serving field contract.
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
