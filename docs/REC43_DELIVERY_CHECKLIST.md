# REC-43 Delivery Checklist

## New modules
- `src/engines/owned_challenger_comparator.py`
- `src/engines/owned_challenger_transfer_context.py`
- `src/engines/report_comparator_overlay.py`

## New configuration
- `config/intelligence/owned_challenger_comparator.json`

## Existing modules/artifacts reused
- `projections.json` for canonical xPts, xMins, start/DNP, current tactical matchup
- `package_optimizer.json` for canonical package legality and robust gain
- `team.json` for owned sell value, ITB and planning chip override
- `dss_watchlist.json` for governed challenger admission
- `stats/playermatchstats_current.json` for emerging performance/process triggers
- `official_detail.json` for PL recent-match history
- existing price/market state through canonical published artifacts

## Overlap avoided
No new xPts, xMins, team-strength, fixture, tactical, price, watchlist-admission or legality engine is introduced. Comparator responsibility is orchestration only and belongs to the existing watchlist bounded context.

## New runtime artifact
- `data/owned_challenger_comparator.json`
- contract `OWNED_CHALLENGER_COMPARATOR_V1`
- initial status `ADVISORY_ONLY`

## Report visibility
`owned_vs_challenger` is added after normal report materialization to:
- `user_report.json`
- `decision_brief.json`
- `deep_review_payload.json`

The overlay is additive and cannot replace canonical decision, XI, captain/vice, watchlist or chip state.

## Known limitations at candidate stage
- future-GW tactical matchup remains `UNVERIFIED` until canonical tactical context materializes fixture-specific future evidence;
- cup/UEFA/international workload remains `PENDING_REPORT_TIME` until verified external/official competition evidence is available;
- normal FT/hit opportunity cost remains pending without authoritative transfer state;
- external model consensus is report-time evidence, not machine majority voting;
- `STRONG_TRANSFER` is intentionally not promoted while REC-43 is `ADVISORY_ONLY`.

## Production gate
REC-43 remains `CANDIDATE` until V3 CI is green and a fresh `runtime-data` snapshot publishes and exposes the comparator artifact.
