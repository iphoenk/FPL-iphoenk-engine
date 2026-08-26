# FPL iphoenk Engine v3.16.0

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, expanded Official detail surfaces, an optional authenticated read-only Official layer, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, provenance/freshness, snapshot integrity and a decision-aware Price Radar.

## Current release
- Engine version: `3.16.0`
- Schema version: `45`
- Release metadata source of truth: `src/version.py`
- Production runtime: bounded-process V3 microservices
- Generated runtime state is published to `runtime-data`; `main/data/**` is historical/source-repository material only.

## v3.8.1 Price-risk hotfix
v3.8.1 hardens the new trajectory model after the first production snapshot:
- current Official progress determines which threshold is actually at risk once progress is materially positive/negative
- a player near a fall threshold is no longer mislabelled as a rise merely because the latest hourly rate has turned slightly positive during recovery
- constant-rate ETA is suppressed when movement is away from the currently threatened threshold
- Official signed likelihood ordinals are preserved conservatively; undocumented intermediate codes are not translated into invented Official wording
- observed `+/-5` threshold-crossing codes are labelled very-likely, while intermediate levels remain neutral `RISE/DROP_SIGNAL_LEVEL_n`

## v3.8 Price Trajectory Radar
v3.8 upgrades Price Radar from event net-transfer pressure into a trajectory engine built around the new Official FPL 2026/27 price-change fields.

Official bootstrap fields consumed when present:
- `price_change_percent`: current Official progress towards the next rise/fall threshold
- `price_change_hourly_rate`: Official hourly movement; the observed 2026/27 payload is stored in hundredths of a percentage point, so the engine also exposes a normalised `%/hour` value
- `price_change_projections`: Official projected progress and likelihood for upcoming price-change deadlines
- `price_change_locked_until`
- `price_change_calibrating`

Derived trajectory features:
- predicted change deadline/date
- Official movement per hour
- observed progress velocity between persisted collector snapshots
- acceleration/deceleration and reversal detection
- constant-rate trajectory ETA when the Official projection does not itself cross the threshold
- rise/fall risk and LOW/MEDIUM/HIGH/CRITICAL urgency
- top rise-risk and fall-risk lists
- up to 50 market watch candidates for intersection with the DSS-approved external watchlist
- alert candidates for owned players and DSS-approved external candidates

Important authority rule: Official current progress is native Official FPL information. A future projection remains a prediction, even when supplied by FPL. `TRAJECTORY_RATE` dates are explicitly derived estimates and must never be presented as confirmed changes.

### Official projection health guard
Early 2026/27 observations showed cases where Official offset-0 projected progress stayed equal to current progress despite material hourly movement. v3.8 detects this as `SUSPECT_STATIC_OFFSET0` rather than silently treating it as a trustworthy future forecast. The engine can then expose its trajectory estimate alongside the Official current progress. This is a guard, not an attempt to override Official current progress.

### Persisted state and confirmed-change fix
The collector hydrates `price_cache.json` and `price_trajectory.json` from the authoritative `runtime-data` branch before generating a new snapshot. This matters because `main/data/**` is historical only. Without hydration, a fresh runner could compare prices against stale source-repository state rather than the immediately previous production snapshot.

New runtime outputs:
- `data/price_trajectory.json`
- `data/price_alerts.json`
- enriched `data/prices.json`
- enriched `price_summary` in `data/latest.json`

Price alert semantics are intentionally conservative: price pressure is an overlay, not a football decision. Consumers should notify only when a HIGH/CRITICAL signal intersects an owned player or a DSS-approved external watchlist candidate and the move is decision-relevant for affordability, sell value or a preferred multi-GW package.

Historical schema at v3.8: 37.

## v3.7.1 Runtime publication isolation
Generated `data/**` is published from a separate detached Git worktree to `runtime-data`. Production triggers share one concurrency queue and runtime publication retries against the newest runtime head. The protected `main` branch remains untouched by generated-data writes.

## v3.7 Authenticated Official read-only layer
Authenticated Official FPL is an optional precision layer, never a dependency for the public core engine.

Allowlisted resource routes are exactly:
- `GET /api/me/`
- `GET /api/my-team/{team_id}/`
- `GET /api/entry/{team_id}/transfers-latest/`

Security policy:
- GET-only authenticated resource client; no generic write/transfer/team mutation API
- `/api/me/` must verify the configured entry ID before account-native state is trusted
- credential material is never written to `data/**`, runtime-data, logs, exceptions or artifacts
- raw authenticated JSON is never persisted publicly
- public collection continues if auth is disabled, missing, expired or rejected
- authenticated failure is a separate optional-layer state, not Official public core failure
- secrets are not exposed to pull-request jobs

Supported auth modes:
- `disabled` (default)
- `session_cookie` via `FPL_SESSION_B64`
- `bearer_token` via `FPL_ACCESS_TOKEN`
- `refresh_token` via `FPL_REFRESH_TOKEN` plus the configured current OIDC token URL/client ID and optional client secret

Persisted safe output is `data/auth.json` plus `authenticated_official` in `latest.json`: auth health, verified entry, exact squad purchase/selling prices when available, safe finance summary, chip summary, private-draft integrity fingerprint/count and transfers-latest availability/count. Raw private payloads are not published.

If mobile credential bootstrap remains unavailable, nothing else breaks. The engine continues with public Official FPL plus purchase/sell-value reconstruction.

## v3.6 Official FPL P0/P1 expansion
P0:
- selective `element-summary/{id}/` for all 15 owned players plus screened candidates, capped by `FPL_ELEMENT_SUMMARY_MAX` (default 40)
- Official `team/set-piece-notes/`
- richer `event/{gw}/live/`
- fixture-stat reconciliation from Official fixtures

P1:
- season and latest-GW Dream Team
- optional Classic mini-league standings via `FPL_CLASSIC_LEAGUE_IDS`
- optional H2H standings via `FPL_H2H_LEAGUE_IDS`
- public entry cup state when available
- optional/secondary surfaces fail soft and remain separate from core Official health

Outputs include `data/official_detail.json`, `official_detail_summary` and `official_health_panel` in `latest.json`.

## v3.5.1 Runtime publishing + cadence hardening
The source branch `main` remains protected. Generated collector data is published to `runtime-data`.

Runtime bridge architecture:
`Official FPL API -> tested collector from main -> validation gate -> runtime-data -> FPL Master Monitor`

Authoritative persisted runtime bridge:
`https://raw.githubusercontent.com/iphoenk/FPL-iphoenk-engine/runtime-data/data/latest.json`

Collector cadence:
- primary hourly slot `:55`
- adaptive deadline/match redundancy `:15`
- manual/source-code push runs immediately
- pull requests test but never publish runtime data

`main/data/**` is historical/source-repository material only. Runtime consumers must use `runtime-data/data/**`.

## v3.5 Official Rules Compliance
`src/rules.py` is the single source of truth for published FPL 2026/27 rules used by the engine.

Regression-tested rules include:
- appearance 1/2 points
- goals: GK +10, DEF +6, MID +5, FWD +4
- assists +3; clean sheets GK/DEF +4 and MID +1
- saves, penalty saves/misses, goals conceded, cards, own goals and bonus
- defensive contribution: DEF 10 CBIT = +2; MID/FWD 12 CBIRT = +2; capped +2 per match
- published 2026/27 BPS deltas with Official-first BPS authority
- Wildcard, Free Hit, Triple Captain and Bench Boost rules across both season halves
- Official-history-driven chip ledger

## v3.4.1 Price Radar baseline
- transfer-momentum noise filter: ownership >=0.5% and absolute event net transfers >=5,000
- actionable pressure separated from tiny-denominator market noise
- confidence labels and regression coverage

v3.8 keeps this filter for transfer-momentum ranking, while evaluating Official price progress separately so an exact Official progress signal is not discarded merely because ownership is low.

## v3.4 reliability and native persistence
- persists Official entry/history/transfers/submitted picks
- per-source provenance/freshness
- snapshot integrity ID and native change log
- fail-closed structural validation

## Collector / reporting cadence
Collector cadence and user-visible reporting are deliberately separate.

Master Monitor reports:
- Normal Mode: 04:30 Deep Review, 12:30 Midday Tactical Monitor, 21:30 Night Tactical + Price Monitor WIB
- Match Mode: approximately every 3 hours while relevant PL/FPL matches are active
- Deadline Day: hourly at :30 WIB until definitive Final Review
- After Final Review: silent except genuinely material emergency updates

All three normal reports must include Price Radar for owned players and the DSS external watchlist by GK/DEF/MID/FWD. Price changes occur at 00:00 Europe/London, so the WIB conversion is DST-aware rather than hardcoded. The 04:30 report is a late-cycle risk checkpoint when the UK is on BST, 12:30 updates trajectory/affordability, and 21:30 emphasises the next overnight risk window.

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python -m src.engines.price_radar
python -m src.engines.official_expansion
python -m src.engines.authenticated_official
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
```

## Source authority
1. Direct Official FPL native fields and Official scoring
2. Authenticated Official FPL native account fields when valid and directly applicable
3. Persisted Official-FPL-derived runtime bridge on `runtime-data`
4. Official public detail/secondary surfaces
5. FPL-Core-Insights community enrichment
6. vaastav historical dataset
7. other mirrors only if explicitly enabled
8. web/news/tactical overlays

For Price Radar specifically:
- Official current price and confirmed price changes are native authority
- Official `price_change_percent` is native current threshold progress
- Official future projections are Official predictions, not guarantees
- engine trajectory dates/acceleration are derived estimates and are labelled as such
- third-party predictors can be used as independent challengers, not as native authority

## Rules authority principle
Local reconstruction is an audit aid only. It must not override Official FPL `total_points`, bonus allocation, rank, current price or other native fields. BPS is not fully reconstructed without all required raw Official metrics.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
