# FPL iphoenk Engine v3.3

A production-oriented personal FPL data platform.

## Design goal
Combine:
- Official FPL API authority
- FPL-Core-Insights advanced community stats
- vaastav historical backbone
- live score/persistence
- exact team-value logic
- leakage-safe modelling
- projection/calibration/portfolio frameworks

## v3.3 hardening
- 2026/27 scoring compliance: goalkeeper goals are worth 10 points in projections
- single engine/service version source in `src/version.py`
- authenticated manual `/refresh` using `FPL_REFRESH_API_KEY`
- one shared live poller for all SSE clients instead of one Official FPL polling loop per client
- regression coverage for goalkeeper goal scoring

## P0 Production Core
Implemented:
- phase-aware FPL state
- locked pre-deadline squad authority
- exact sell-value logic
- endpoint health/retry/latency
- live FPL player stat expansion
- price deltas and momentum
- Core Insights + vaastav sync
- leakage guard
- fail-closed validation
- persistent snapshots
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
uvicorn live_service:app --host 0.0.0.0 --port 8000
```

## Live endpoints
- GET `/health`
- GET `/latest`
- GET `/live`
- GET `/team`
- GET `/prices`
- POST `/refresh` with header `X-FPL-Refresh-Key`
- GET `/stream` via Server-Sent Events

`/refresh` is disabled with HTTP 503 when `FPL_REFRESH_API_KEY` is not configured. The background poller is shared by all `/stream` clients, so additional subscribers do not multiply Official FPL API polling.

## Source authority
1. Official FPL API
2. FPL-Core-Insights community enrichment
3. vaastav historical dataset
4. Understat/mirrors if explicitly enabled
5. web/news/tactical overlays outside this repository

## Leakage guard
Post-match and post-GW fields must not be used to reconstruct pre-deadline same-GW predictions.
Historical xP-like fields should be shifted or excluded unless timestamp eligibility is proven.

## Important
FPL-Core-Insights and vaastav are community-maintained. They are useful enrichments, not licensed Opta feeds.

GitHub Actions is persistence/archive, not true streaming infrastructure. Deploy `live_service.py` to an always-on host for near-live polling.
