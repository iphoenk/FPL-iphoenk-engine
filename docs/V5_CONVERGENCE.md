# FPL iphoenk Engine V5 Convergence

V5 is the Unified Decision Engine track. It does not replace V3 production yet and it does not stop V4 prediction R&D.

## Operating tracks

- V3.x: production and scheduled-task runtime. Changes stay conservative and reliability-oriented.
- V4.x: active prediction development, calibration and tuning.
- V5.x: architectural convergence of V3 truth/reliability and V4 intelligence/decision capability.

## V5 architecture

1. Truth plane
   - Official FPL authority
   - authenticated read-only account overlay
   - phase-aware state
   - Official rules registry
   - finance and sell value
   - price trajectory
   - persistence, provenance, freshness and leakage protection

2. Intelligence plane
   - xMins and starter/rotation priors
   - advanced player statistics
   - set-piece and penalty shares
   - prior-season evidence
   - dynamic opponent resistance
   - xPts and scenario distributions

3. Governance plane
   - Gate0 hard constraints
   - DSS core/extensions/enhancement registries
   - preflight and postflight health
   - centralized quality gates
   - calibration and regression controls

4. Decision plane
   - XI and bench order
   - captain and vice-captain
   - transfers and hits
   - Wildcard/package optimization
   - chips
   - watchlist and price-risk actions

## Single-authority invariants

V5 must have exactly one authoritative implementation for each of these concepts: rules, player identity, squad state, finance/sell value, projection and decision output. Legacy implementations may remain temporarily for comparison but must not both participate in one V5 decision path.

## Migration status

| Capability | Source baseline | V5 status |
| --- | --- | --- |
| V4.7 prediction codebase | V4 | BASELINE IMPORTED |
| Official rules registry | V3.9 | MIGRATED |
| Projection scoring wired to rules registry | V3.9 + V4 | MIGRATED |
| Decision/evidence contracts | V5 | IMPLEMENTED |
| Bootstrap acceptance gate | V5 | IMPLEMENTED |
| Authenticated Official layer parity | V3 | PENDING |
| Price trajectory parity | V3 | PENDING |
| Runtime-data/persistence parity | V3 | PENDING |
| Rules drift governance parity | V3.9 | PENDING |
| Finance single-authority consolidation | V3 + V4 | PENDING |
| Phase-aware authority consolidation | V3 + V4 | PENDING |
| Full V4 xMins/xPts provenance adaptation | V4 | PENDING |
| Evidence to prediction to decision trace | V5 | PENDING |
| V3 truth regression suite | V3 | PENDING |
| V4 prediction benchmark suite | V4 | PENDING |
| Production promotion | V5 | BLOCKED UNTIL ACCEPTANCE |

## Promotion rule

V5 can become production only when it proves no material regression against V3 for truth/reliability and no material regression against V4 for prediction/decision capability. Prediction calibration must be reported separately from structural health.
