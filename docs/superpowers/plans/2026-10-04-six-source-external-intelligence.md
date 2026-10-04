# FPL V12 Six-Source External Intelligence

## Goal

Add the six audited external sources using the existing V6 structured-source and report-time evidence lanes. Preserve one canonical factual plane, one football model, one optimizer, one captain authority, fail-soft retrieval, root-provenance deduplication, and the existing production/report locks.

## Current truth

- Production main: `5d983525bed54281bfa83c53b7b3dc4aa80b30ef`.
- Existing open PRs: #869, #838, #809 (do not touch #809), #780, #453.
- Existing structured challenger contract: `challenger_observation_v2` with registry-driven providers.
- Existing report-time contract: `report_time_evidence_v1` with advisory-only sources.
- FPLAnaly and FPL Analytics Dashboard are already reference-only V6 candidates; CardStats is an unvalidated V6 candidate.
- FPL Tactics, FPLRatings, and AllAboutFPL are not yet represented in the production registries.

## Safe implementation sequence

1. Extend shared normalized external evidence metadata and categorical reconciliation without introducing an external score.
2. Register FPL Tactics as an advisory structured challenger; prove deterministic identity, freshness, and non-mutation with fixture/live validation.
3. Register FPLRatings as a diagnostic challenger; keep DUE/OVER/regression signals non-decisional.
4. Register FPLAnaly with explicit official-derived versus model-native lineage; prevent official-derived outputs from counting as independent votes.
5. Register FPL Analytics Dashboard as targeted report-time distribution evidence with explicit maturity and stale/unavailable states.
6. Register AllAboutFPL as bounded current-GW editorial evidence with publication timestamp and quoted-fact root deduplication.
7. Complete CardStats admission audit and record `PROMOTE_V6=NO` unless every promotion gate is proven; keep it non-active and nonblocking when unresolved.
8. Run all relevant contract/source/report tests, then run controlled DEEP/DEADLINE/MATCH production validation and inspect the rendered report.

## Invariants to verify

- MC remains 500,000; universe/search breadth and exhaustive route semantics unchanged.
- WatchlistScore remains 20/25/30/25; no external fifth weight or voting authority.
- Official FPL and Opta root families are not double-counted.
- External failures, stale data, missing data, parser drift, and unresolved identity remain fail-soft.
- Canonical optimizer, captain frontier, S04, S14, S15/S17 separation, and S08/S18/S19 consistency remain authoritative.

## Verification evidence required before completion

- Red/green unit tests for the shared contract and each provider classification.
- Live bounded retrieval evidence for each provider or an explicit nonblocking unavailable/maturity result.
- Exact-head CI and governance checks for every repair PR.
- Fresh controlled production run with integrated computation, all QA/delivery gates, private delivery, receipt/latest advancement, and rendered-report inspection.
- Natural scheduler result distinguished from controlled validation; no premature natural-green claim.
