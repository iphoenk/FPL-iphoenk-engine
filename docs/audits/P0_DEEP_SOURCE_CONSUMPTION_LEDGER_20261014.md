# P0 DEEP source-consumption ledger audit

Audit date: 14 October 2026. Status: CODE CANDIDATE, NOT PRODUCTION ACCEPTANCE.

## Production source observation

At the inspected V6 `runtime-data-v6` branch (source `effective_at=2026-10-14T15:35:54Z`): Understat has 436 player records, 424 verified Official FPL player identities; FotMob has 380 verified fixture identities and 20 verified team identities. These are input-source counts, not historical-as-of admissions and not DEEP-consumed counts. A source observed after the report cutoff remains excluded.

## Trust boundary and new ledger

`build_retrospective_context` retains the existing strict as-of, source GREEN + NORMALIZED, exact player identity, exact official fixture identity and GW1-GW6 match scope gates. In addition to existing `verified_join_count` and `verified_match_count`, it now provides:

- `source_records`: normalized V6 records before filtering.
- `verified_source_identity_rows`: source-native verified identity count, independent of report cutoff.
- `eligible_verified_rows`: identity-verified records with a source effective timestamp no later than the report occurrence.
- `historical_scope_rows` (FotMob): source fixtures within GW1-GW6, with separately counted out-of-scope rows.
- `consumed_rows`: real matching retrospective player or fixture rows attached to the report, **not** P(start) / xPts arithmetic influence.
- `source_gate`, `source_effective_at`, `report_cutoff_at`, `rejected_reasons`: inspectable reasons for rejection.

Advisory season aggregates are not reallocated to fake per-match historical values, FotMob full-time observations do not finalize Official FPL points, RotoWire identities are not promoted, and published GW7 frozen forecasts remain unmodified.

## Verification

Four deterministic tests cover: verified/eligible/consumed separation; temporal cutoff rejecting already-verified records; mapped source identities absent from the current Official player universe; duplicate or out-of-scope FotMob fixtures. Full mandatory V12 governance requires all 54 required test files and exactly 1,408 original test IDs, without reducing prior coverage.

## Production acceptance outstanding

CI success alone cannot prove `DEEP_CONSUMED>0`, historical source as-of, settled GW7 prospective calibration, scheduler natural 12/12, OIDC HTTP 200, PRICE full private readback or native ChatGPT host acknowledgment. Verify the next actual DEEP occurrence through immutable private receipt and source-to-report lineage. Keep independent gate statuses until then.

Change timestamp: 2026-10-14T23:04:00+07:00
Documentation sync: UPDATED
Documentation timestamp: 2026-10-14T23:04:00+07:00
