# FPL iphoenk Engine v3.7.1

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, expanded public Official FPL detail surfaces, an optional authenticated read-only Official layer, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, provenance/freshness, snapshot integrity and a noise-resistant Price Radar.

## v3.7.1 Runtime publication isolation
v3.7.1 hardens the `runtime-data` publisher after a production run correctly generated and validated a v3.7 snapshot but Git refused to switch the dirty collector worktree from `main` to `runtime-data`.

Fixes and tuning:
- generated `data/**` is copied first, then published from a separate detached Git worktree
- the collector worktree never switches away from `main` while generated files are dirty
- all non-PR production triggers share one concurrency queue, preventing push/schedule/manual runs from racing each other during runtime publication
- PR runs retain branch-scoped cancellation so stale CI attempts can still be cancelled
- runtime publish retries up to three times against the newest `runtime-data` head if an external race occurs
- `main` branch protection remains untouched
- schema remains 36

## v3.7 Authenticated Official read-only layer
Authenticated Official FPL is an optional precision layer, never a dependency for the public core engine.

Supported resource endpoints are deliberately allowlisted to exactly three GET routes:
- `GET /api/me/`
- `GET /api/my-team/{team_id}/`
- `GET /api/entry/{team_id}/transfers-latest/`

Security policy:
- the authenticated resource client exposes GET only; there is no generic method or transfer/team-write API
- `/api/me/` must verify the configured entry ID before any team-specific authenticated state is trusted
- credential material is never written to `data/**`, runtime-data, logs, exceptions or artifacts
- raw authenticated JSON is never persisted publicly
- the public collector remains operational when auth is disabled, missing, expired or rejected
- authenticated failure is reported as a separate optional-layer state, not as Official public core failure
- secrets are injected only into the authenticated overlay step and are not made available to pull-request jobs

Supported auth modes:
- `disabled` (default)
- `session_cookie`: base64-encoded filtered FPL/Premier League Cookie header in `FPL_SESSION_B64`
- `bearer_token`: short-lived access token in `FPL_ACCESS_TOKEN`
- `refresh_token`: refresh token in `FPL_REFRESH_TOKEN`; requires configured `FPL_OIDC_TOKEN_URL` and `FPL_OIDC_CLIENT_ID`, plus optional `FPL_OIDC_CLIENT_SECRET`

Recommended secret configuration:
- `FPL_AUTH_MODE`
- one credential matching the chosen mode
- for refresh-token mode, the OIDC token URL/client ID required by the current Premier League identity flow

Do not put credentials in README, repository files, `runtime-data`, chat messages or workflow logs. A GitHub Environment Secret such as `fpl-readonly` is preferred when practical; repository Actions secrets are supported by the workflow without changing source code.

Persisted safe output is `data/auth.json` plus `authenticated_official` in `latest.json`. It contains only:
- auth health/state and endpoint health without credential/header values
- verified entry ID
- exact purchase/selling prices only for players already in the authoritative squad state
- safe finance summary such as bank/value when Official authenticated data exposes it
- chip-state summary
- current-draft count, a one-way fingerprint and whether it matches the authoritative squad, without publishing the raw private draft
- count/availability summary for `transfers-latest`, not the raw transfer payload

Possible states include `DISABLED`, `VALID`, `EXPIRED_OR_REJECTED`, `ENTRY_MISMATCH`, `PARTIAL`, `MISCONFIGURED` and `UNAVAILABLE`.

If mobile credential bootstrap remains unavailable, nothing else breaks. The engine continues using public Official FPL plus the existing purchase/sell-value reconstruction. Authenticated data simply upgrades selected fields when a valid credential is present.

Schema version: 36.

## v3.6 Official FPL P0/P1 expansion
The collector exploits more of the public Official FPL surface before relying on external data.

P0 implemented:
- selective `element-summary/{id}/` collection for all 15 owned players plus actionable Price Radar candidates and top Official performers, capped by `FPL_ELEMENT_SUMMARY_MAX` (default 40)
- Official `team/set-piece-notes/` collection with fail-soft health status
- richer `event/{gw}/live/` persistence including minutes, goals, assists, clean sheets, goals conceded, own goals, penalties, cards, saves, bonus, BPS, total points and defensive contribution when present
- fixture-stat reconciliation from Official `fixtures/`

P1 implemented:
- season and latest-GW Official Dream Team surfaces
- optional Classic mini-league standings via `FPL_CLASSIC_LEAGUE_IDS`
- optional H2H standings via `FPL_H2H_LEAGUE_IDS`
- public entry cup state when available
- optional/secondary surfaces fail soft and remain separate from core Official health

Outputs:
- `data/official_detail.json`
- `official_detail_summary` and `official_health_panel` in `data/latest.json`

Important load-control rule: the engine does not fetch element-summary for the full player universe every hour. Universal screening remains bootstrap-first and detail fetches are selective.

## v3.5.1 Runtime publishing + cadence hardening
The source branch `main` remains protected. Generated collector data is published to `runtime-data` rather than pushed directly to `main`.

Runtime bridge architecture:
`Official FPL API -> tested collector from main -> validation gate -> runtime-data branch -> FPL Master Monitor`

Authoritative persisted runtime bridge:
`https://raw.githubusercontent.com/iphoenk/FPL-iphoenk-engine/runtime-data/data/latest.json`

Key hardening:
- generated `data/**` is published to the dedicated `runtime-data` branch
- `latest.json` receives `runtime_publish.branch`, `source_commit` and `published_at`
- primary collector at `:55`; adaptive deadline/match redundancy at `:15`
- pull requests run tests but never publish runtime data
- push/manual runs collect immediately

`main/data/**` is historical/source-repository material only. Runtime consumers must use `runtime-data/data/**`.

## v3.5 Official Rules Compliance
`src/rules.py` is the single source of truth for published FPL 2026/27 rules used by the engine.

Implemented and regression-tested:
- appearance scoring: 1 point below 60 minutes, 2 points at 60+ minutes
- goals: GK +10, DEF +6, MID +5, FWD +4
- assists +3; clean sheets GK/DEF +4 and MID +1
- goalkeeper saves +1 per three, penalty save +5
- penalty miss -2, every two goals conceded by GK/DEF -1, yellow -1, red -3, own goal -2
- defensive contribution points: DEF 10 CBIT = +2; MID/FWD 12 CBIRT = +2; capped at +2 per match
- published 2026/27 BPS deltas and Official-first BPS authority
- chip rules for Wildcard, Free Hit, Triple Captain and Bench Boost in both season halves
- chip ledger derived from Official history and persisted to `data/chips.json` and `data/latest.json`

## v3.4.1 Price Radar fix
- actionable threshold: ownership >=0.5% and absolute event net transfers >=5,000
- separates actionable pressure from market noise
- adds confidence labels and regression coverage

## v3.4 reliability and native persistence
- persists Official `entry`, `history`, `transfers`, and submitted `picks`
- per-source provenance/freshness
- snapshot integrity ID and native change log
- fail-closed structural validation

## Collector / reporting cadence
Collector cadence and user-visible reporting are deliberately separate.

Collector:
- primary hourly scheduled slot: `:55`
- adaptive deadline/match redundancy slot: `:15`
- manual and source-code push runs: immediate collection

Master Monitor user-visible reports:
- Normal Mode: 04:30 Deep Review, 12:30 Midday Tactical Monitor, 21:30 Night Tactical + Price Monitor WIB
- Match Mode: approximately every 3 hours while relevant PL/FPL matches are active
- Deadline Day: hourly at :30 WIB until definitive Final Review
- After Final Review: silent except genuinely material emergency updates

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python -m src.engines.official_expansion
python -m src.engines.authenticated_official
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
```

## Source authority
1. Direct Official FPL native fields and Official scoring
2. Authenticated Official FPL native account fields when valid and directly applicable
3. Persisted Official-FPL-derived runtime bridge on `runtime-data`
4. Official FPL public detail/secondary surfaces such as element-summary and set-piece notes
5. FPL-Core-Insights community enrichment
6. vaastav historical dataset
7. other mirrors only if explicitly enabled
8. web/news/tactical overlays

Direct Official native fields win conflicts with persisted/derived state. Authenticated account-native fields win reconstructed equivalents such as sell price when auth is verified for the expected entry.

## Rules authority principle
Local reconstruction is an audit aid only. It must not override Official FPL `total_points`, bonus allocation, rank, price or other native fields. BPS is not fully reconstructed without all required raw official metrics.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
