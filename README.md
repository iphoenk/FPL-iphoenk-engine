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
