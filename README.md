# FPL iphoenk Engine V4.8.1

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

python -m src.services.orchestrator daily --stats
python -m src.services.orchestrator deadline --stats --as-of "2026-08-28T21:30:00+07:00"
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

## V4.7.3 checkpoint governance

- Checkpoint selection is registry-driven for 04.30, 12.30, 21.30, deadline review, post-final emergency watch, and matchday live monitoring.
- Snapshot freshness limits follow the active checkpoint and block recommendations when exceeded.
- `LOCKED_15` squad composition is reported separately from the still-adjustable XI, bench order, captain, and vice-captain.
- Deterministic `--as-of` runs are labelled simulations and can never authorize a live action.
- The final action is produced only after POST-FLIGHT health, while V4.7.1 predictions and V4.7.2 optimizer search widths remain unchanged.

## V4.8.1 independent process-isolated services

- Eight registry-driven services run as isolated Python processes under one fail-closed orchestrator.
- Every service publishes versioned JSON contracts that are validated before its dependants may run.
- The raw, enrichment, and latest prediction artifacts are hashed after PASS and checked after every downstream service.
- The registry contains eight independent process boundaries. `raw_snapshot` is the sole Official FPL API authority, `enrichment` consumes `snapshot.v1`, and `prediction` consumes both immutable runtime contracts without refetching official data.
- `snapshot.v1` and `enrichment.v1` live only under ignored `data/runtime/`; SHA-256 lineage binds raw input, enrichment, and the latest prediction.
- The orchestrator locks raw snapshot, enrichment, and latest prediction immediately after each service passes, then fails closed on any mutation.
- Prediction preserves every V4.8.0 operational artifact: live state, prices and price cache, source health, chips, per-GW archive, and append-only snapshot history; `latest.json` retains the complete compatibility pointer set.
- Prediction V4.7.1, optimizer V4.7.2, checkpoint governance V4.7.3, sell-cost logic, Gate 0, and registry counts remain unchanged.
- `data/service_orchestration_v4.json` provides service status, timings, contract hashes, and failure evidence.

See `docs/v4-microservices.md` for service ownership, failure semantics, and preserved invariants.
