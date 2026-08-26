# FPL iphoenk Engine V4.7.2

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

## P0 Production Core
Implemented:
- phase-aware FPL state
- locked pre-deadline squad authority
- exact sell-value logic
- sell-cost-correct Wildcard affordability (owned sell cost, unowned current cost)
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
- official-ID integration of Core Insights players, shots and player-match stats
- dedicated prior-season vaastav snapshot with stable-code reconciliation
- official set-piece and penalty orders as metadata, without double-counting xG/xA
- neutral opponent-defence scoring fallback when dedicated defence splits are unavailable
- direct-evidence xMins priors with broad-position competition retained as diagnostic only
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

python -m src.engines.framework_health_audit --phase preflight --strict
python -m src.engines.v4_decision_pipeline
python -m src.engines.framework_health_audit --phase postflight --strict
python -m src.engines.v4_quality_gate

uvicorn live_service:app --host 0.0.0.0 --port 8000
```

## Live endpoints
- GET `/health`
- GET `/latest`
- GET `/live`
- GET `/team`
- GET `/prices`
- POST `/refresh`
- GET `/stream` via Server-Sent Events

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

## V4.7.1 correctness hotfix

- V4.6.4 remains the sell-cost and truthful-health correctness baseline.
- V4.7.1 removes the mechanical xMins floor and prevents broad FPL positions from suppressing nailed starters.
- Set-piece and penalty taker orders remain visible metadata but add no blanket scoring multiplier because current xG/xA already contains those events.
- Overall team strength is diagnostic-only when official defence splits are zero, preventing duplicate fixture adjustment through FDR.
- Advanced-data health reports materially distinct enrichment separately from matched records.
- Role competition, empirical set-piece shares, weak advanced enrichment and opponent-defence fallback remain truthfully `PARTIAL`.
- Remaining unrelated framework debt stays `PARTIAL`, so health may remain `AMBER` and unqualified `GO` remains blocked while governed recommendations may still be produced.

## V4.7.2 performance hotfix

- Official FPL snapshot endpoints and independent statistics sources refresh concurrently, while bootstrap remains the phase authority and no polling is added.
- GW1 purchase-price reconstruction is fetched only when the sell-cost ledger actually lacks evidence.
- Framework health reads one immutable prediction snapshot per audit and memoizes repeated operational probes within that audit only.
- WC optimization keeps beam size 6000 and the same ranking key, using packed precomputed club bits and bounded top-k selection instead of full sorting.
- Package audit preserves its frontier and beam widths, while materializing JSON payloads only for retained top packages.
- Decision equivalence is an acceptance requirement; V4.7.1 prediction formulas and V4.6.4 correctness thresholds are unchanged.
