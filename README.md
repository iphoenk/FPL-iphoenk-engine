# FPL iphoenk Engine v3.39.0

Production-oriented personal FPL decision engine and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Current-state authority

This README is a human-readable projection, not a second source of truth. Current mutable facts must be read from their machine owners:

- release/version: `src/version.py`
- execution phases/domains: `config/runtime/execution_domains.json`
- background capability contracts: `config/v3_service_registry.json`
- runtime SLOs: `config/runtime/performance_slo.json`
- canonical REC status: `config/rec_registry.json`
- current production runtime/provenance: `runtime-data/data/runtime_manifest.json`
- historical release/projection metadata: `IMPLEMENTATION_STATUS.json`
- operational roadmap and monitor explanations: `MASTER_TASK_LIST_V3.md`
- V6 fresh-data architecture/governance: `docs/V6_FRESH_DATA_PLATFORM.md`
- V6 deterministic identity-bridge roadmap: `docs/V6_IDENTITY_BRIDGE_ROADMAP.md`
- V6 mutable runtime truth: `runtime-data-v6:data/v6/manifest.json`

Do not copy a current commit SHA, topology count, or mutable SLO into this document as an independent authority. Historical values may remain only when explicitly labelled as historical evidence.

## V6 fresh-data platform

V6 is an isolated, registry-driven, data-only acquisition and evidence-publication platform. It has no prediction, optimizer, transfer, captaincy, chip, xPts, xMins, Monte Carlo, tactical, recommendation, or decision authority. Its active source set and health must be read from V6 registry/runtime artifacts rather than inferred from static counts in this README.

V6 consumers may use a fresh, integrity-valid `runtime-data-v6` snapshot. Stale or invalid snapshots must remain visibly degraded and may only use explicitly governed minimum-scope direct fallback. See `docs/V6_FRESH_DATA_PLATFORM.md` for the architecture contract and `docs/V6_IDENTITY_BRIDGE_ROADMAP.md` for deterministic cross-source identity work.

## Production architecture

V3 uses the canonical domain pipeline:

`ACQUIRE → ENRICH → MODEL → DECISION → GOVERNANCE → PUBLISH`

Execution domains are orchestration boundaries, not alternate business owners. Capability ownership remains registry-defined and every active capability must map exactly once through the compiled runtime plan. `src.runtime_v3.registry_compiler` is the control-plane compiler authority.

The former executable service-level scheduler in `src.runtime_v3.orchestrator` is retired and fails closed. That module retains shared execution primitives only; production execution is owned by `src.runtime_v3.domain_orchestrator`.

## Runtime and publication

- FAST, LIVE, FULL and DEEP profiles are registry-owned.
- FAST and validated warm-serving SLO values are owned only by `config/runtime/performance_slo.json`.
- Correctness may not be traded for latency and stale artifacts may not be presented as fresh to satisfy an SLO.
- Mutable runtime state publishes only to the rolling parentless `runtime-data` snapshot, not to `main`.
- Publication is whitelist-based, materialized before publish, atomic, source-SHA checked, and post-publish provenance verified.
- Private authenticated state is optional enrichment and must not leak into public runtime artifacts; only governed public health/projection fields may be published.
- Current runtime performance and exact source commit are authoritative only from `runtime-data/data/runtime_manifest.json`.

## Artifact integrity

`RUNTIME_ARTIFACT_CONTRACTS_V2` owns runtime JSON integrity. Malformed JSON is an integrity failure. Production-critical decision and serving artifacts have explicit structural contracts; non-critical unknown JSON may remain `PARSE_ONLY` where flexibility is intentional.

Critical package publication requires the existing governed Gate0 invariant to be revalidated. A syntactically valid artifact is not sufficient if its decision contract is invalid.

## Official FPL authority

Official FPL is the only native authority for Official fields and scoring. External/community/challenger/weather/tactical evidence is enrichment and may never overwrite Official-native truth.

Applicable REC work attempts public Official evidence first. Fallback requires an explicit allowed disposition such as `OFFICIAL_UNAVAILABLE`, `FIELD_NOT_EXPOSED`, `PRIVATE_AUTH_REQUIRED`, or genuinely not-applicable governance scope.

Finished personal Gameweeks use Official submitted picks/history as actual truth. Planning-GW points are projections. User WC/FH/LOCK overrides must target the exact planning GW, and explicit XI/C/VC/chip overrides preserve the engine recommendation for audit comparison.

## Prediction and decision governance

- Gate0 remains the legality/governance validator, not a second optimizer or rules engine.
- DSS Core, Extensions and Enhancements must satisfy their registry-owned activation requirements before unqualified GO.
- OWNED is exactly 15 authoritative players.
- The external watchlist is produced by full DSS screening and must remain position-balanced according to the report contract.
- Numerical decision formulas require deterministic regression coverage.
- Formula correctness and predictive accuracy are separate claims. Predictive accuracy requires genuinely frozen pre-deadline forecasts settled against Official realized outcomes.
- Price timing/direction, confidence calibration, private authenticated precision, model actionability and other evidence-dependent claims remain MONITOR until genuine evidence supports promotion.

## Tactical and weather evidence

REC-41 tactical role/system evidence is production-published but evidence-driven. `FPL_POSITION_SHAPE` is not a claim of the club's true tactical formation, and missing tactical evidence is never invented.

Weather is a governed enrichment capability. Probability and intensity are distinct fields. Weather remains observational/advisory and may not directly mutate xPts, xMins, XI, captaincy, transfers, watchlist or packages without calibrated governance.

## Reporting and serving

Human-facing reports use natural Bahasa Indonesia while raw enums remain machine/audit state. Required report checkpoints are tracked and missed due checkpoints must be explicit.

Background refresh and validated warm serving are separate bounded lanes. Interactive serving consumes canonical decision artifacts; it may not reimplement projection, legality or decision formulas.

## REC governance

`config/rec_registry.json` is the canonical REC authority. REC records are change/remediation records, not business capabilities. `IMPLEMENTATION_STATUS.json`, Official-first coverage, this README and `MASTER_TASK_LIST_V3.md` are projections/consumers and may not create competing REC truth.

REC-42, Architecture Consolidation / No-Duplicate Guard / Sub-Second Decision Serving, is production accepted. Its early PR #106 measurements remain historical candidate evidence only and do not define current topology or SLO values.

## Historical release evidence

Historical PR, CI, runtime and performance values are retained in Git history and `IMPLEMENTATION_STATUS.json` for provenance. They must remain explicitly historical and must not be interpreted as current topology, current runtime performance, current SLO, or current production source commit.

V3.39 preserves the established football decision semantics while hardening source authority, prediction settlement, architecture ownership, runtime performance, artifact integrity, publication provenance and repository hygiene.

See `MASTER_TASK_LIST_V3.md` for the human-readable operational projection, monitors and deferred work.
