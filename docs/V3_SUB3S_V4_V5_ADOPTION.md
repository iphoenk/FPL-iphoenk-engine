# V3 sub-3s hardening and V4/V5 donor adoption

## Objective
Production V3 remains the authority. FAST decision runtime must be consistently at or below 3000 ms without changing football formulas, xPts/xMins semantics, XI/C/VC/bench, transfer, chip, watchlist, phase authority, or report semantics.

## Adopted from V4
- Hot-orchestrator principle: remove repeated interpreter/process startup between bounded stages.
- Keep capability order and validation; optimize execution boundary, not business logic.
- Fail closed on architecture/runtime-assurance drift.
- Treat latency targets as release gates, not observational metrics.

V3 implementation: `fast_decision` executes all eleven canonical domains sequentially inside one Python process while preserving the compiler-derived domain/capability order. FULL/deep/live retain the existing domain-process scheduler.

## Adopted from V5
- Explicit performance policy registry.
- Fail-closed degraded-mode principle: critical failure is not hidden by a silent fallback.
- Exact release/source provenance remains mandatory.
- Repeated-run performance acceptance rather than a single best-case sample.

## Deliberately not adopted
- V5 static degraded fallback payloads: V3 already has established critical/non-critical artifact ownership and stale-output quarantine; adding synthetic fallback payloads would risk semantic drift.
- V5 microservice transport layer: adds latency and operational complexity without value for the current single-repository runtime.
- V5 broad config-cache refactor: deferred until profiling proves JSON-config parsing is a material part of the remaining sub-3s budget.
- V4/V5 prediction or optimizer formulas: explicitly out of scope for this package.

## Hard gates
- FAST hard wall: 3000 ms.
- Warning: 2800 ms.
- At least three fresh-Python-process FAST runs, each <=3000 ms, in candidate CI.
- Material decision equivalence remains required by existing release acceptance.
- No fallback from partially executed coalesced FAST lane to multi-process mode.
- 11 execution domains / 21 capability owners remain canonical.
