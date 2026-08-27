# FPL iphoenk Engine V5 Convergence

V5 is the Unified Decision Engine track. It does not replace V3 production until explicit manual promotion, and it does not stop V4 prediction R&D.

## Accepted production baseline

- Production version: `v3.18.1`
- Production main SHA: `02d0ce597e111e9b7d464f88479d78d462b616eb`
- Production schema: `47`
- V5 convergence release: `5.0.0-beta.3`

The baseline changed after beta.2 had accumulated validated shadow cycles. V5 acceptance accounting is deliberately version- and baseline-SHA-scoped, so those beta.2 cycles are historical evidence only and do not satisfy beta.3 promotion criteria.

## Operating tracks

- V3.x: production and scheduled-task runtime. Changes stay conservative and reliability-oriented.
- V4.x: prediction development, calibration and tuning reference.
- V5.x: bounded-context microservices convergence of V3 truth/reliability and V4 intelligence/decision capability.

## V5 architecture

1. Truth plane
   - Official FPL authority
   - authenticated read-only account overlay
   - phase-aware state
   - Official rules registry
   - finance and sell value
   - live scoring and authoritative identity

2. Intelligence plane
   - price trajectory and transfer momentum
   - xMins and starter/rotation priors
   - advanced player statistics
   - set-piece and penalty shares
   - prior-season evidence
   - dynamic opponent resistance
   - xPts and scenario distributions
   - external challenger observations without authority override

3. Governance/evaluation plane
   - Gate0 hard constraints
   - DSS core/extensions/enhancement registries
   - preflight and postflight health
   - centralized quality gates
   - calibration and regression controls
   - leakage/freshness evidence guards
   - postvalidated real-shadow accounting

4. Decision/presentation plane
   - XI and bench order
   - captain and vice-captain
   - transfers and hits
   - Wildcard/package optimization
   - chips
   - watchlist and price-risk actions
   - user report, technical appendix and on-demand full snapshot

## V3.18.1 source-contract convergence

V3.18.1 introduced a stricter challenger-source reliability contract. V5 beta.3 adopts the contract semantics without turning a challenger into an authority:

- source reachability is distinct from capability/data health
- stale observations are never silently treated as current
- challenger observations have a versioned `challenger_observation_v2` contract
- LiveFPL and OneFPL structured access is registry-owned
- OneFPL fallback endpoints and allowed hosts are registry-owned
- missing or restricted challenger data remains fail-neutral and is never fabricated
- Official FPL remains the sole native external authority

V5 keeps provider-specific runtime concerns inside the ingestion/evaluation boundaries rather than importing V3 monolithic source-manager authority into the V5 decision path.

## Single-authority invariants

V5 must have exactly one authoritative implementation for rules, player identity, squad state, finance/sell value, price decision state, projection, watchlist, decision output and reporting. Legacy implementations may remain for comparison, but two authorities must never participate in one V5 decision path.

## Current migration status

| Capability | Source baseline | V5 status |
| --- | --- | --- |
| Official rules and scoring | V3 | CONVERGED |
| Authenticated Official layer | V3 | CONVERGED |
| Phase-aware squad authority | V3 | CONVERGED |
| Finance/sell-value authority | V3 | CONVERGED |
| Price trajectory and registry-owned thresholds | V3/V5 | CONVERGED |
| V3.18.1 challenger-source reliability contract | V3.18.1 | CONVERGED IN BETA.3 |
| xMins/xPts and full DSS intelligence | V4/V5 | CONVERGED |
| Evidence to prediction to decision trace | V5 | CONVERGED |
| 50 core + 16 extension DSS strict postflight | V5 | CONVERGED |
| Watchlist 20 total / 5 per position | V5 | CONVERGED |
| Decision-first reporting and on-demand full snapshot | V5 | CONVERGED |
| Microservice topology and transport resilience | V5 | CONVERGED |
| Production baseline drift gate | V5 | REQUIRED |
| Three beta.3 postvalidated real-shadow cycles | V5 | REQUIRED, RESET TO 0/3 AFTER REBASELINE |
| Production promotion | V5 | MANUAL AND LOCKED |

## Promotion rule

A clean Unified Gate is necessary but not sufficient. Beta.3 must then complete three successful postvalidated real-shadow cycles on exactly V5.0.0-beta.3 and exactly the accepted V3.18.1 production baseline SHA. Core-only PASS, failed post-validation, older beta versions and old baseline SHAs do not count. Reaching 3/3 creates production-candidate eligibility only. Actual production promotion remains an explicit manual governance action.
