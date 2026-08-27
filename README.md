# FPL iphoenk Engine v3.22.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current accepted production release: `3.22.0` / schema `49`.
- V3.22 production acceptance is COMPLETE and the interactive FAST target remains `<10s`.
- Active architecture remains 20 artifact-owned microservices.
- Runtime state publishes only to the rolling parentless `runtime-data` snapshot; mutable runtime output is not stored on protected `main`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry: `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Canonical roadmap, REC status and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## Official FPL authority and REC-38 Official-first contract
Official FPL is the only native authority for Official fields and scoring. External sources remain enrichment/challenger evidence and may never overwrite Official-native truth.

REC-38 adds `config/sources/official_first_coverage.json`, an explicit coverage matrix for every recommendation from REC-01 through REC-38, with REC-09a and REC-09b tracked separately. For every REC touching native or potentially native FPL facts, the matrix declares the Official endpoint families that must be considered first. Public Official data is preferred before authenticated private state when public data can answer the question.

Fallback/proxy evidence is allowed only after an explicit disposition:
- `OFFICIAL_UNAVAILABLE`
- `FIELD_NOT_EXPOSED`
- `PRIVATE_AUTH_REQUIRED`
- `OFFICIAL_NOT_APPLICABLE`, only when the REC genuinely does not depend on Official data

The source contract validates the coverage matrix. Broad/expensive Official expansion belongs to FULL refresh; FAST may reuse only fresh, complete and contract-valid Official artifacts, preserving the `<10s` decision path.

## REC-36 and REC-37 historical Official reconciliation
REC-36 uses public Official entry history and historical picks as the authority for post-deadline submitted teams. GW1 can therefore be reconstructed as a retrospective Official baseline without private credentials. It is deliberately labelled retrospective proxy evidence and cannot be counted as a verified pre-deadline forecast for predictive accuracy or dynamic model weighting.

REC-37 completed the one-shot migration of those historical fields into production `runtime-data`, then restored the normal 3,600-second FAST/LIVE `official_detail` reuse TTL.

## V3.22 Runtime Optimization Foundation
V3.22 separates interactive decision regeneration from heavier enrichment refresh while preserving the 20-service artifact-owned architecture and schema-49 serving contract.

- FAST/LIVE/FULL/DEEP execution profiles are registry-owned.
- Heavy but reusable `advanced_stats`, `historical_prior`, `source_layer`, and `official_detail` artifacts may be reused only when complete, contract-valid and within profile-specific freshness windows.
- REC-31 makes production validation profile-aware: `REUSED` is accepted only for a service declared reusable by the active profile and carrying artifact-validation evidence.
- REC-32 preserves only registry-owned `latest_keys`/`latest_file_keys` for reusable services through base fan-in.
- CI, FAST runtime and FULL/DEEP refresh are separate workflows.
- Runtime checkout is shallow and publication is whitelist-based rather than using Git history as a database.
- Runtime telemetry exposes wall time, service timing, I/O and RSS/resource evidence.
- REC-33 bounds weather refresh concurrency/freshness while retaining weather as advisory-only evidence.
- REC-34 safely migrated the player-feature contract and restored normal advanced-stats reuse TTL.
- REC-35 compacted duplicated projection diagnostics without changing formulas or decisions.

## Prediction and decision governance
- REC-01 player-specific Defensive Contribution and REC-02 robust early-season attacking rates are production active.
- `player_features.json` normalizes advanced-stat evidence and provenance while Official-native fields remain authoritative.
- All 15 OWNED players expose current-GW xPts, uncertainty, xMins/start probability, selection score and lineup/choice state.
- Prediction formula correctness and predictive accuracy are separate claims. Accuracy requires genuinely frozen pre-deadline forecasts settled against Official realized outcomes.
- Early-season confidence remains conservative until realized calibration evidence supports stronger labels.
- Price prediction remains calibration-gated; Official realized price/ownership/transfer movement is the settlement authority.
- FACT/CONSTRAINT actions may remain actionable while MODEL_DERIVED actions are gated by settled evidence.

## Weather Intelligence
Open-Meteo is a noncritical `ENRICHMENT`, never an authority or model challenger. Official fixture ownership remains in the Official snapshot and weather consumes fixture context without replacing it. Weather is observational/advisory only and may not directly change xPts, Starting XI, captaincy, transfers, watchlist membership or package rankings without future calibrated governance.

## Runtime and source invariants
- Gate0 must remain 16/16 PASS for unqualified GO.
- DSS Core 50/50, Extensions 16/16 and Enhancements 8/8 must remain ACTIVE.
- OWNED is exactly 15 authoritative players.
- WATCHLIST is exactly 20 external players, exactly 5 per position and excludes OWNED.
- Critical internal artifact failure is fail-closed; optional external-source unavailability is fail-soft.
- Missing evidence is explicit and is never fabricated to keep health GREEN.
- Numerical formulas affecting decisions require deterministic regression tests.
- Service boundaries follow ownership/failure semantics, not a target service count.
- Runtime and report readiness are separate from predictive/model evidence readiness.

See `MASTER_TASK_LIST_V3.md` for the authoritative REC-01 through REC-38 status, current monitors, production evidence and release checklist.
