# V12 score oracle golden cases (E01)

`src/engines/v12_official_public_scoring.score_entry` is the single scoring oracle for submitted public Official FPL picks. It is not duplicated in any other runtime.

## Contract

- `gross_points`, `net_points` (gross minus the official hit), `captain_points` and `bench_raw_points` are separate numbers. Captain and bench are reported alongside gross, never netted against the hit.
- An unknown hit is `null` (`hit_verified=false`); `net_points` and `live_overall_points` are then `null`, not 0.
- `captain_points` is the effective captain's points times the multiplier they carry now (x2, or x3 with Triple Captain). If nobody carries a multiplier of 2 or more, it is `null` and `effective_captain_id` is `null`.
- `bench_raw_points` is the raw points of players with a zero multiplier. It is not a claim that the whole bench could have been fielded legally.
- A vice-captain takeover that is not yet confirmed by official data, or an unconfirmed DNP starter, is `PROVISIONAL`. The oracle never returns a final status; finality is decided by official `data_checked`, outside this function.
- Already-applied official autosub multipliers are not applied twice (idempotent for pre- and post-published picks).
- The baseline source is explicit: `OFFICIAL_PREVIOUS_GW_HISTORY`, `OFFICIAL_PUBLISHED_STANDING_DIFFERENCE` or an unverified difference, with `baseline_verified`.

## Golden fixture

`tests/fixtures/audit_20261025/score_cases.json` holds 14 synthetic cases with hand-computed expectations. The dashboard score-context tests can load the same JSON for JS/Python parity (I01); no Python runs on Vercel. Formation legality and fielded-bench regret are E02 concerns, not scoring.
