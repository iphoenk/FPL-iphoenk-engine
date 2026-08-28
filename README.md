# FPL iphoenk Engine v3.24.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current accepted production release: `3.23.1` / schema `49`.
- Current release candidate: `3.24.0` / schema `49`, REC-41 Tactical Role & System Evidence Contract.
- REC-41 feature acceptance on PR #89 run `33129623527` passed compile, architecture, **208 deterministic tests**, composite FULL/FAST acceptance, FULL 17.020s and FAST **4.711s**.
- REC-41 remains candidate until final release CI, merge to `main`, and merged-main `runtime-data` publication succeed.
- Active architecture remains 20 artifact-owned microservices; REC-41 adds no service and no new runtime artifact.
- Runtime state publishes only to the rolling parentless `runtime-data` snapshot; mutable runtime output is not stored on protected `main`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry remains backward-compatible `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Canonical roadmap, REC status and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## V3.24 Tactical Role & System Evidence
REC-41 adds evidence before model influence. It does not change xMins or xPts in this release.

- Current advanced player-match evidence is converted into observed attacking-role profiles such as attacking defender, creator, advanced runner/shooter, hybrid attacking midfielder and focal shooter.
- Team starter structure is reconstructed from Official player identity/FPL position plus observed starter rows and is explicitly labelled `FPL_POSITION_SHAPE`.
- `FPL_POSITION_SHAPE` is **not** presented as the club's true tactical formation. It only describes the FPL-position composition of the observed starting XI.
- Role evidence carries sample quality, confidence, evidence minutes, metrics, reason and provenance.
- System evidence carries dominant observed FPL-position shape, consistency, valid-match count and confidence.
- Missing evidence is explicit (`UNASSESSED` / `NONE`), never guessed.
- Official FPL identity, team and position remain authoritative. Advanced role/system evidence is enrichment only.
- REC-41 is `ADVISORY_ONLY`: `xmins_adjustment_enabled=false`, `xpts_rate_adjustment_enabled=false`, and projections explicitly report `rec41_tactical_adjustment_applied=false`.
- Evidence is published through the existing `PLAYER_FEATURE_CONTRACT_V1` and existing projection artifact, avoiding a parallel feature bus.
- A future model opt-in requires a separate calibrated change after sufficient multi-match evidence exists.

## V3.23.1 Report Completeness + Natural Presentation
REC-40 is production accepted. Natural Bahasa Indonesia is the primary human-facing presentation, while raw states such as `HOLD`, `LOCK`, `LEAN`, `OPEN` and `REVIEW` remain audit/API state. Required checkpoints are explicit at 04:30, 12:30 and 21:30 WIB, checkpoint completion is persisted, and missed due checkpoints are surfaced explicitly. Production FAST proof is 6.326s from run `33091398202`.

## V3.23 Personal Gameweek Context + Decision Authority
- Finished GWs use public Official FPL submitted picks/history as immutable actual truth, including actual GW points, chip, bench points, captain/vice and submitted squad.
- Historical actuals are never reconstructed or relabelled as old forecasts when no genuine pre-deadline forecast was frozen.
- Planning-GW points are labelled estimated xPts, never actual score.
- Normal planning baseline is the previous Official submitted squad.
- WC/FH/user-locked composition may replace the planning baseline only for the exact target GW; stale overrides are rejected and post-deadline Official picks reclaim authority.
- Explicit user XI/C/VC/chip overrides may become effective while preserving the engine recommendation for comparison; the engine may warn but may not silently overwrite the user decision.

## Official FPL authority and Official-first contract
Official FPL is the only native authority for Official fields and scoring. External sources remain enrichment/challenger evidence and may never overwrite Official-native truth.

`config/sources/official_first_coverage.json` is the explicit REC coverage matrix. The V3.24 candidate extends it through REC-41, producing 42 disposition entries because REC-09a and REC-09b are separate. REC-41 is `PUBLIC_FIRST_WITH_ENRICHMENT`: Official identity, FPL position and fixture context remain authoritative; tactical role and observed FPL-position-shape evidence are enrichment-only and advisory until a separately calibrated model opt-in.

Fallback/proxy evidence is allowed only after an explicit disposition:
- `OFFICIAL_UNAVAILABLE`
- `FIELD_NOT_EXPOSED`
- `PRIVATE_AUTH_REQUIRED`
- `OFFICIAL_NOT_APPLICABLE`, only when the REC genuinely does not depend on Official data

Broad/expensive Official expansion belongs to FULL refresh; FAST may reuse only fresh, complete and contract-valid Official artifacts, preserving the `<10s` decision path.

## Prediction and decision governance
- REC-01 player-specific Defensive Contribution and REC-02 robust early-season attacking rates are production active.
- `player_features.json` is the normalized feature/provenance bus; Official-native fields remain authoritative.
- REC-41 tactical/system evidence is visible in that feature bus but intentionally has no decision adjustment yet.
- All 15 OWNED expose current-GW xPts, uncertainty, xMins/start probability, selection score and lineup/choice state.
- Prediction formula correctness and predictive accuracy are separate claims. Accuracy requires genuinely frozen pre-deadline forecasts settled against Official realized outcomes.
- Early-season confidence and model-derived actionability remain calibration-gated.
- Price prediction remains calibration-gated; Official realized price/ownership/transfer movement is settlement authority.
- `ENGINE_READY` does not imply final report-time web evidence is already refreshed.

## Runtime and source invariants
- Gate0 must remain 16/16 PASS for unqualified GO.
- DSS Core 50/50, Extensions 16/16 and Enhancements 8/8 must remain ACTIVE.
- OWNED is exactly 15 authoritative players.
- WATCHLIST is exactly 20 external players, exactly 5 per position and excludes OWNED.
- Critical internal artifact failure is fail-closed; optional external-source unavailability is fail-soft.
- Missing evidence is explicit and is never fabricated to keep health GREEN.
- Numerical formulas affecting decisions require deterministic regression tests.
- FAST decision regeneration targets <10s.
- Service boundaries follow ownership/failure semantics, not a target service count.
- Runtime/report readiness and model evidence readiness are separate states.
- Weather remains advisory and may not directly mutate xPts/XI/C/VC/transfers/watchlist/packages without calibrated governance.
- Human-facing report language must not make raw machine state the primary narrative.
- Required scheduled report checkpoints must be auditable and missed checkpoints explicit.
- Tactical role/system evidence must remain advisory in V3.24.0; no xMins/xPts mutation is permitted without a later calibrated REC.

See `MASTER_TASK_LIST_V3.md` for authoritative production/candidate status, calibration monitors, deferred work and release checklist.
