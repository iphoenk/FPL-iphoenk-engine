# FPL iphoenk Engine v3.25.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current release state
- Current accepted production release: `3.24.0` / schema `49`.
- Current release candidate: `3.25.0` / schema `49`, REC-42 Architecture Consolidation, No-Duplicate Ownership Guard & Sub-Second Decision Serving.
- V3.25 keeps the 20 artifact-owned background microservices and adds 2 bounded interactive microservices: `decision_hotpath` and `instant_gateway`.
- `decision_hotpath` recomputes governed XI, captain/vice, bench and package legality from fresh canonical projection artifacts without network fetches or duplicate football formulas.
- `instant_gateway` serves only fresh, validated materialized decisions and fails closed when refresh is required.
- `config/rec_registry.json` is the canonical REC set. `IMPLEMENTATION_STATUS.json`, Official-first coverage and this documentation are projections/consumers, not competing REC authorities.
- Runtime state publishes only to the rolling parentless `runtime-data` snapshot; mutable runtime output is not stored on protected `main`.
- Runtime Artifact Contract Registry: `RUNTIME_ARTIFACT_CONTRACTS_V2`.
- Machine Source Registry: `SOURCE_REGISTRY_V4`.
- Report Artifact Registry remains backward-compatible `REPORT_ARTIFACT_REGISTRY_V3`.
- Release metadata source of truth: `src/version.py`.
- Canonical roadmap and Definition of Done: `MASTER_TASK_LIST_V3.md`.

## V3.25 Architecture Consolidation + Interactive Decision Lane
REC-42 applies the V4 one-owner/no-duplicate concept and V5 bounded-context/performance principles without changing FPL scoring or prediction formulas.

- One authoritative owner per responsibility and one final owner per artifact.
- Shared evidence is a declared primitive and is reused rather than recomputed in multiple DSS/REC paths.
- DSS Core, Extensions, Enhancements, Gate0 and REC IDs are cross-registry checked for duplicate/drift.
- Legacy `src.models.projection`, `src.models.fixture` and `src.models.optimizer` may not become active runtime owners again.
- Official-FPL network access is restricted to declared owners/exceptions.
- REC is governance/change history, not a second business-capability layer.
- Background refresh and interactive decision serving are separate bounded lanes. This avoids turning the engine into a monolith while keeping user-facing recomputation fast.
- Interactive services may consume canonical projection, legality and governance primitives but may not reimplement them.
- Hard interactive end-to-end SLO is `<1000 ms`; cold source/model refresh remains measured separately and may not fake freshness to satisfy that SLO.

## V3.24 Tactical Role & System Evidence
REC-41 is production accepted and remains advisory-only. It does not directly change xMins or xPts.

- Current advanced player-match evidence is converted into observed attacking-role profiles such as attacking defender, creator, advanced runner/shooter, hybrid attacking midfielder and focal shooter.
- Team starter structure is reconstructed from Official player identity/FPL position plus observed starter rows and is explicitly labelled `FPL_POSITION_SHAPE`.
- `FPL_POSITION_SHAPE` is not presented as the club's true tactical formation. It only describes the FPL-position composition of the observed starting XI.
- Role evidence carries sample quality, confidence, evidence minutes, metrics, reason and provenance.
- Missing evidence is explicit (`UNASSESSED` / `NONE`), never guessed.
- Official FPL identity, team and position remain authoritative. Advanced role/system evidence is enrichment only.
- REC-41 remains `ADVISORY_ONLY`: `xmins_adjustment_enabled=false`, `xpts_rate_adjustment_enabled=false`, and projections explicitly report `rec41_tactical_adjustment_applied=false`.
- Evidence is published through the existing `PLAYER_FEATURE_CONTRACT_V1` and projection artifact, avoiding a parallel feature bus.

## V3.23.1 Report Completeness + Natural Presentation
REC-40 is production accepted. Natural Bahasa Indonesia is the primary human-facing presentation, while raw states such as `HOLD`, `LOCK`, `LEAN`, `OPEN` and `REVIEW` remain audit/API state. Required checkpoints are explicit at 04:30, 12:30 and 21:30 WIB, checkpoint completion is persisted, and missed due checkpoints are surfaced explicitly.

## V3.23 Personal Gameweek Context + Decision Authority
- Finished GWs use public Official FPL submitted picks/history as immutable actual truth, including actual GW points, chip, bench points, captain/vice and submitted squad.
- Historical actuals are never reconstructed or relabelled as old forecasts when no genuine pre-deadline forecast was frozen.
- Planning-GW points are labelled estimated xPts, never actual score.
- Normal planning baseline is the previous Official submitted squad.
- WC/FH/user-locked composition may replace the planning baseline only for the exact target GW; stale overrides are rejected and post-deadline Official picks reclaim authority.
- Explicit user XI/C/VC/chip overrides may become effective while preserving the engine recommendation for comparison; the engine may warn but may not silently overwrite the user decision.

## Official FPL authority and Official-first contract
Official FPL is the only native authority for Official fields and scoring. External sources remain enrichment/challenger evidence and may never overwrite Official-native truth.

`config/rec_registry.json` owns the canonical REC set. `config/sources/official_first_coverage.json` must contain exactly the same REC IDs and an explicit Official disposition for every REC. REC-42 is `NOT_APPLICABLE` because it is architecture/runtime governance rather than an FPL data capability.

Fallback/proxy evidence is allowed only after an explicit disposition:
- `OFFICIAL_UNAVAILABLE`
- `FIELD_NOT_EXPOSED`
- `PRIVATE_AUTH_REQUIRED`
- `OFFICIAL_NOT_APPLICABLE`, only when the REC genuinely does not depend on Official data

Broad/expensive Official expansion belongs to FULL refresh; FAST may reuse only fresh, complete and contract-valid Official artifacts.

## Prediction and decision governance
- REC-01 player-specific Defensive Contribution and REC-02 robust early-season attacking rates are production active.
- `player_features.json` is the normalized feature/provenance bus; Official-native fields remain authoritative.
- REC-41 tactical/system evidence is visible in that feature bus but intentionally has no direct decision adjustment yet.
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
- Background FAST refresh and interactive decision latency are separate SLOs.
- Interactive governed decision regeneration and validated gateway each have a hard `<1s` ceiling.
- Service boundaries follow bounded-context ownership/failure semantics, not a target service count.
- Runtime/report readiness and model evidence readiness are separate states.
- Weather remains advisory and may not directly mutate xPts/XI/C/VC/transfers/watchlist/packages without calibrated governance.
- Human-facing report language must not make raw machine state the primary narrative.
- Required scheduled report checkpoints must be auditable and missed checkpoints explicit.

See `MASTER_TASK_LIST_V3.md` for authoritative production/candidate state, calibration monitors, deferred work and release checklist.
