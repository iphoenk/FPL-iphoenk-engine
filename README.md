# FPL iphoenk Engine v3.23.1

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current accepted production release: `3.23.0` / schema `49`.
- Current release candidate: `3.23.1` / schema `49`, REC-40 Report Completeness + Natural Presentation.
- V3.23.1 candidate PR #85 has passed compile, architecture, 203 deterministic tests and composite FULL/FAST acceptance. Production merge and runtime publication are still required before it becomes the accepted production release.
- Candidate FULL runtime: 10.346s. Candidate FAST runtime: 3.804s, below the `<10s` target.
- Active architecture remains 20 artifact-owned microservices.
- Runtime state publishes only to the rolling parentless `runtime-data` snapshot; mutable runtime output is not stored on protected `main`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry remains backward-compatible `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Canonical roadmap, REC status and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## V3.23.1 Report Completeness + Natural Presentation
REC-40 hardens the human report surface without changing football projection formulas or adding a microservice.

- Natural Bahasa Indonesia is the primary human-facing presentation. Raw states such as `HOLD`, `LOCK`, `LEAN`, `OPEN` and `REVIEW` remain available for audit/API compatibility but are not the primary narrative.
- Required report checkpoints are explicit at 04:30, 12:30 and 21:30 WIB.
- Checkpoint completion is persisted across runs. A due checkpoint that was not completed is surfaced explicitly instead of silently appearing complete.
- `user_report.json`, `decision_brief.json` and `deep_review_payload.json` carry natural presentation and report-checkpoint metadata.
- Report-serving validation fails closed when the required presentation/checkpoint contract is missing.
- Report-time intelligence, personal gameweek context, Official authority, user override authority and existing DSS decisions are preserved.
- Schema remains 49 and active service count remains 20.
- PR #85 candidate CI run `33087549395` passed 203 tests, FULL 10.346s and FAST 3.804s. This remains candidate evidence until merged-main runtime publication succeeds.

## V3.23 Personal Gameweek Context + Decision Authority
V3.23 makes the personal-team timeline explicit without replacing the DSS as an advisory decision engine.

- Finished GWs use public Official FPL submitted picks/history as immutable actual truth, including actual GW points, chip, bench points, captain/vice and submitted squad.
- Historical actuals are never reconstructed or relabelled as old forecasts when no genuine pre-deadline forecast was frozen.
- The planning GW exposes estimated team points from current xPts together with formation, XI, bench, captain, vice-captain and active chip. Estimated points are always labelled projection, never actual score.
- Normal planning baseline is the previous Official submitted squad.
- Wildcard, Free Hit or user-locked composition may replace that planning baseline only when the override explicitly targets the current planning GW. A stale override is rejected and post-deadline Official submitted picks reclaim authority.
- Formation, XI, bench, captain, vice-captain and chip may be explicitly overridden by the user. The engine recommendation remains visible for comparison and may warn about the xPts difference, but it does not silently overwrite the user's decision.
- The manual override config is inactive by default; no user decision is invented.
- This is implemented inside existing team-state/report-serving ownership, so the active microservice count remains 20.

## Official FPL authority and Official-first contract
Official FPL is the only native authority for Official fields and scoring. External sources remain enrichment/challenger evidence and may never overwrite Official-native truth.

`config/sources/official_first_coverage.json` is the explicit coverage matrix for the REC stream. REC-39 is classified as `PUBLIC_THEN_PRIVATE_AUTH`: finished-GW truth and submitted planning baselines use public Official entry history/picks first, while unpublished current-draft precision may use optional authorized `my-team` access. Explicit user locks remain a separate user authority, not a substitute public-data source. REC-40 is `NOT_APPLICABLE` to football-data authority because it changes presentation and checkpoint scheduling only; it does not introduce a substitute data source. The source contract validates that matrix and closed fallback dispositions.

Fallback/proxy evidence is allowed only after an explicit disposition:
- `OFFICIAL_UNAVAILABLE`
- `FIELD_NOT_EXPOSED`
- `PRIVATE_AUTH_REQUIRED`
- `OFFICIAL_NOT_APPLICABLE`, only when the REC genuinely does not depend on Official data

Broad/expensive Official expansion belongs to FULL refresh; FAST may reuse only fresh, complete and contract-valid Official artifacts, preserving the `<10s` decision path.

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
- Human-facing report language must not make raw machine state the primary narrative.
- Required scheduled report checkpoints must be auditable and missed checkpoints must be explicit.

See `MASTER_TASK_LIST_V3.md` for the authoritative production/candidate status, monitors, deferred work, production evidence and release checklist.
