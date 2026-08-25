# FPL iphoenk Engine v3.5.0

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine:
- Official FPL API authority
- a single authoritative FPL 2026/27 ruleset inside the engine
- persisted native team/event state for downstream AI monitoring
- FPL-Core-Insights advanced community stats
- vaastav historical backbone
- live score/persistence
- exact team-value logic
- leakage-safe modelling
- projection/calibration/portfolio frameworks
- provenance, freshness and snapshot-integrity metadata
- noise-resistant Price Radar

## v3.5 Official Rules Compliance
`src/rules.py` is the single source of truth for published FPL 2026/27 rules used by the engine.

Implemented and regression-tested:
- basic scoring: appearance, goals by position, assists, clean sheets, saves, penalty saves/misses, goals conceded, cards, own goals and bonus values
- goalkeeper goals = 10 points, defender = 6, midfielder = 5, forward = 4
- defensive contribution (DC) rules: defenders reach 10 CBIT for +2; midfielders/forwards reach 12 CBIRT for +2; maximum +2 DC points per match
- official scoring reconstruction helper for event-live auditing; Official `total_points` remains authority
- 2026/27 BPS deltas are persisted as rules metadata; full BPS reconstruction remains Official FPL/Opta authority when raw metrics are unavailable
- two chip sets per season: Wildcard, Free Hit, Triple Captain and Bench Boost once in each half
- first chip set expires after the GW19 deadline and is not carried over; second set applies from GW20
- only one chip can be used in a Gameweek
- Free Hit cannot be used in GW1, and a first-half Free Hit used in GW19 cannot be followed by the refreshed Free Hit in GW20
- chip ledger is derived from Official history and persisted into `data/chips.json` and `data/latest.json`
- projection scoring imports constants from the rules module instead of hardcoding scoring independently
- ruleset identity and official source URLs are persisted in the bridge for auditability
- schema version 34

Official rule references are stored in `src/rules.py` and point to PremierLeague.com pages for scoring, defensive contributions, chips and 2026/27 BPS changes.

## v3.4.1 Price Radar fix
- applies actionable filtering before persisting `top_buy_pressure` / `top_sell_pressure`
- minimum ownership threshold: 0.5%
- minimum absolute event net transfers: 5,000
- separates actionable pressure from market noise
- attaches confidence labels so tiny-ownership ratio spikes cannot dominate tactical decisions
- persists the filtered result consistently into both `data/prices.json` and `data/latest.json`
- adds regression coverage to prevent 0.0%-ownership noise from reappearing as actionable pressure

## v3.4 reliability and native persistence
- persists native Official FPL `entry`, `history`, `transfers`, and submitted `picks`
- exposes per-source provenance and fetch timestamps
- calculates per-source freshness rather than relying only on global snapshot age
- adds snapshot integrity ID for deduplication/audit
- adds native-field change log for reconciliation and conflict tracking
- keeps Official FPL native fields authoritative while treating bridge data as persisted Tier-1-derived state
- preserves fail-closed validation for structural squad errors

## v3.3 hardening foundation
- first 2026/27 goalkeeper-goal correction
- single engine/service version source in `src/version.py`
- authenticated manual `/refresh`
- one shared live poller per service process
- regression and CI gates

## P0 Production Core
Implemented:
- phase-aware FPL state
- locked pre-deadline squad authority
- exact sell-value logic
- endpoint health/retry/latency
- live FPL player stat expansion
- official 2026/27 rules compliance and chip ledger
- confirmed price deltas and filtered transfer-pressure radar
- Core Insights + vaastav sync
- leakage guard
- fail-closed validation
- persistent snapshots
- native Official entry/history/transfers/picks persistence
- provenance and per-source freshness
- snapshot integrity and change logging
- safe GitHub workflow

## P1 Intelligence
Working base:
- optional shots.csv / playermatchstats.csv ingestion
- advanced-stat CLI
- fixture model
- interpretable xMins/xPts scaffold
- FastAPI JSON endpoints
- SSE live streaming

## P2 Advanced
Framework implemented:
- Monte Carlo points scenarios
- package/portfolio legality evaluator
- MAE/Brier/Spearman calibration utilities
- model versioning hooks

P2 is deliberately not marketed as a trained production model until enough season data exists.

## Data flow
`Official FPL API -> GitHub collector/engine -> persisted data/*.json bridge -> FPL Master Monitor`

Direct ChatGPT browsing of Official team-specific endpoints is an optional cross-check only and is not required for the production data path.

## Collector / reporting cadence
The GitHub collector is the data-refresh layer. User-visible Master Monitor cadence is separate and mode-aware:
- Normal Mode: 04:30 Deep Review, 12:30 Midday Tactical Monitor, 21:30 Night Tactical + Price Monitor (WIB)
- Match Mode: approximately every 3 hours while relevant PL/FPL matches are active
- Deadline Day Mode: hourly at :30 WIB until the definitive Final Review
- After Final Review: silent except genuinely material emergency updates

## Main commands
```bash
pip install -r requirements.txt
python fpl_daily_tasks.py daily --stats
python fpl_daily_tasks.py deadline --stats
python fpl_daily_tasks.py live
python fpl_daily_tasks.py stats-sync --gw 1
python fpl_daily_tasks.py advanced-stats --gw 1 --query "Haaland"
```

## Live endpoints
- GET `/health`
- GET `/latest`
- GET `/live`
- GET `/team`
- GET `/prices`
- POST `/refresh` with header `X-FPL-Refresh-Key`
- GET `/stream` via Server-Sent Events

## Source authority
1. Official FPL API native fields and Official scoring
2. Persisted Official-FPL-derived bridge state
3. FPL-Core-Insights community enrichment
4. vaastav historical dataset
5. Understat/mirrors if explicitly enabled
6. web/news/tactical overlays outside this repository

If direct Official FPL and persisted bridge disagree on a current native field, direct current Official FPL wins and the conflict should be logged.

## Rules authority principle
The engine may reconstruct published scoring components for audit, but must not override Official FPL `total_points`, bonus allocation, rank, price or other native fields with a local reconstruction. BPS is not fully reconstructed unless all required official raw metrics are available.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions. Historical xP-like fields should be shifted or excluded unless timestamp eligibility is proven.

## Important
FPL-Core-Insights and vaastav are community-maintained enrichments, not licensed Opta feeds. GitHub Actions is persistence/archive and scheduled collection, not true streaming infrastructure.
