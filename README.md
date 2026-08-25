# FPL iphoenk Engine v3.6.0

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine Official FPL API authority, a single authoritative FPL 2026/27 ruleset, persisted native team/event state, expanded Official FPL detail surfaces, community enrichments, live score/persistence, exact team-value logic, leakage-safe modelling, projection/calibration frameworks, provenance/freshness, snapshot integrity and a noise-resistant Price Radar.

## v3.6 Official FPL P0/P1 expansion
The collector now exploits more of the public Official FPL surface before relying on external data.

P0 implemented:
- selective `element-summary/{id}/` collection for all 15 owned players plus actionable Price Radar candidates and top Official performers, capped by `FPL_ELEMENT_SUMMARY_MAX` (default 40) to avoid brute-force API load
- Official `team/set-piece-notes/` collection with fail-soft health status
- richer `event/{gw}/live/` persistence including minutes, goals, assists, clean sheets, goals conceded, own goals, penalties, cards, saves, bonus, BPS, total points and defensive contribution when present
- fixture-stat reconciliation from Official `fixtures/`, preserving match `stats` payload for the planning/current window

P1 implemented:
- season and latest-GW Official Dream Team surfaces
- optional Classic mini-league standings via `FPL_CLASSIC_LEAGUE_IDS` (comma-separated IDs)
- optional H2H standings via `FPL_H2H_LEAGUE_IDS`
- public entry cup state via `entry/{team_id}/cup/` when available
- all optional/secondary surfaces fail soft and are separated from core Official health

Outputs:
- `data/official_detail.json` contains Official element summaries, set-piece notes, fixture stats, rich live data, Dream Team, optional league/cup data and detail health
- `data/latest.json` contains `official_detail_summary` and `official_health_panel`
- health is layered: Official core, Official detail/secondary surfaces and element-summary coverage
- schema version 35

Important load-control rule: the engine does not fetch element-summary for the full 600+ player universe each hour. Universal screening stays bootstrap-first; deeper Official detail is selective.

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
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
```

## Source authority
1. Official FPL API native fields and Official scoring
2. Persisted Official-FPL-derived runtime bridge on `runtime-data`
3. Official FPL detail/secondary surfaces such as element-summary and set-piece notes
4. FPL-Core-Insights community enrichment
5. vaastav historical dataset
6. other mirrors only if explicitly enabled
7. web/news/tactical overlays

If direct Official FPL and persisted bridge disagree on a current native field, direct Official FPL wins and the conflict is logged.

## Rules authority principle
Local reconstruction is an audit aid only. It must not override Official FPL `total_points`, bonus allocation, rank, price or other native fields. BPS is not fully reconstructed without all required raw official metrics.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
