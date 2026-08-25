# FPL iphoenk Engine v3.4.1

A production-oriented personal FPL data platform and persisted Official-FPL-derived bridge for the FPL Master Monitor.

## Design goal
Combine:
- Official FPL API authority
- persisted native team/event state for downstream AI monitoring
- FPL-Core-Insights advanced community stats
- vaastav historical backbone
- live score/persistence
- exact team-value logic
- leakage-safe modelling
- projection/calibration/portfolio frameworks
- provenance, freshness and snapshot-integrity metadata
- noise-resistant Price Radar

## v3.4.1 Price Radar fix
- applies actionable filtering before persisting `top_buy_pressure` / `top_sell_pressure`
- minimum ownership threshold: 0.5%
- minimum absolute event net transfers: 5,000
- separates `actionable_pressure` from `market_noise`
- attaches confidence labels so tiny-ownership ratio spikes cannot dominate tactical decisions
- persists the filtered result consistently into both `data/prices.json` and `data/latest.json`
- adds regression coverage to prevent 0.0%-ownership noise from reappearing as actionable pressure
- patch release only; schema remains 33

## v3.4 reliability and native persistence
- persists native Official FPL `entry`, `history`, `transfers`, and submitted `picks`
- exposes per-source provenance and fetch timestamps
- calculates per-source freshness rather than relying only on global snapshot age
- adds snapshot integrity ID for deduplication/audit
- adds native-field change log for reconciliation and conflict tracking
- keeps Official FPL native fields authoritative while treating bridge data as persisted Tier-1-derived state
- preserves fail-closed validation for structural squad errors
- schema version 33

## v3.3.1 data persistence foundation
- persists native Official FPL entry fields in `data/latest.json` and `data/team.json`
- includes current event, overall/event points and rank, last-deadline bank/value and transfer count
- each native entry block carries the Official API fetch timestamp

## v3.3 hardening
- 2026/27 scoring compliance: goalkeeper goals are worth 10 points in projections
- single engine/service version source in `src/version.py`
- authenticated manual `/refresh` using `FPL_REFRESH_API_KEY`
- constant-time refresh-key comparison and fail-closed manual refresh when no key is configured
- one shared live poller per service process instead of one Official FPL polling loop per SSE client
- manual refresh and background polling serialized through the same process-local lock
- SSE keep-alives plus anti-buffering/no-cache response headers
- regression coverage for all position goal values, release metadata and refresh authentication
- pull-request test gate plus snapshot version/schema assertions

## P0 Production Core
Implemented:
- phase-aware FPL state
- locked pre-deadline squad authority
- exact sell-value logic
- endpoint health/retry/latency
- live FPL player stat expansion
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
Normal production path:

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
python fpl_daily_tasks.py stats-sync --gw 1 --deep
python fpl_daily_tasks.py advanced-stats --gw 1 --query "Haaland"

export FPL_REFRESH_API_KEY="replace-with-a-long-random-secret"
export FPL_LIVE_POLL_SECONDS="60"
uvicorn live_service:app --host 0.0.0.0 --port 8000 --workers 1
```

## Live endpoints
- GET `/health`
- GET `/latest`
- GET `/live`
- GET `/team`
- GET `/prices`
- POST `/refresh` with header `X-FPL-Refresh-Key`
- GET `/stream` via Server-Sent Events

`/refresh` is disabled with HTTP 503 when `FPL_REFRESH_API_KEY` is not configured and returns HTTP 401 for an invalid key. `FPL_LIVE_POLL_SECONDS` has a 30-second safety floor.

The background poller is shared by all `/stream` clients within one service process, so additional subscribers do not multiply Official FPL API polling. The poller is process-local: multiple Uvicorn workers each create their own polling chain. Use one worker when exactly one polling chain per host is required, or use an external single scheduler/coordinator for multi-worker deployments.

## Source authority
1. Official FPL API native fields
2. Persisted Official-FPL-derived bridge state
3. FPL-Core-Insights community enrichment
4. vaastav historical dataset
5. Understat/mirrors if explicitly enabled
6. web/news/tactical overlays outside this repository

If direct Official FPL and persisted bridge disagree on a current native field, direct current Official FPL wins and the conflict should be logged.

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
Historical xP-like fields should be shifted or excluded unless timestamp eligibility is proven.

## Important
FPL-Core-Insights and vaastav are community-maintained. They are useful enrichments, not licensed Opta feeds.

GitHub Actions is persistence/archive and scheduled collection, not true streaming infrastructure. `live_service.py` remains available for near-live hosting if that is ever required, but the normal Master Monitor architecture does not require a separate public proxy service.
