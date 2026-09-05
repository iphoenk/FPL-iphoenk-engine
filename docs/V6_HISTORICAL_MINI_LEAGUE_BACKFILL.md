# V6 Historical Mini-League Backfill

## Purpose

V6 can backfill completed Official FPL gameweeks for the managers who belong to a configured priority mini-league at the time the backfill is run. The first production target is the configured `ICON+ League` classic league.

This capability is factual data acquisition, normalization, reconciliation, caching, and mechanical aggregation only. It does not produce FPL decisions, predictions, xPts, xMins, tactical scores, Bayesian recommendations, Monte Carlo results, transfer/captain/chip/formation recommendations, or WAIT/PREPARE/ACT classifications.

## Governed control path

Historical backfill reuses issue #431 and the existing `/v6-report-prefetch` control plane, owner authorization, `runtime-data-v6`, and the existing V6 publisher. It has no cron and no independent publisher.

Example:

```text
/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league reason=icon_plus_history_backfill
```

`gw_from` and `gw_to` are inclusive. Historical mode accepts finished Official FPL GWs only. A reversed range, GW 0, a current unfinished GW, or a future GW fails closed. `scope` must be exactly `mini_league`.

A governed force retry is available:

```text
/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league force=true reason=icon_plus_history_force_retry
```

## League resolution

The executable configuration does not contain the numeric ICON+ league ID. The service reads the V6 consumer context, discovers the user's current Official FPL league memberships, and resolves the priority league by configured `name + kind`.

If the configured priority league is missing or ambiguous, backfill fails closed. The manager count is derived from the fully paginated current standings and is never assumed to be 58.

## Cohort semantics

Historical output is explicitly labeled:

`CURRENT_COHORT_HISTORY`

This means: historical FPL records for managers who are members of the resolved ICON+ cohort now.

Current membership does not prove membership in an earlier GW. Unless Official FPL provides separate authoritative historical league-membership evidence, every manager/GW record uses:

- `current_cohort_member: true`
- `membership_at_gw_status: UNKNOWN`
- `membership_evidence: CURRENT_STANDINGS_COHORT_ONLY`
- `historical_membership_confirmed: null`

The service must never describe the current cohort as the exact historical ICON+ membership of GW1/GW2/etc without authoritative evidence.

## Historical rank semantics

Official entry history may expose manager GW points, cumulative points, and overall rank, but it does not establish a historical ICON+ standings table for the current cohort.

Therefore V6 publishes `reconstructed_current_cohort_rank` when it can mechanically rank current cohort members by their historical cumulative points. The field is labeled `RECONSTRUCTED_CURRENT_COHORT_ONLY`. `official_historical_league_rank` remains null unless a future Official endpoint provides authoritative historical league standings.

## Acquisition and cache

For every requested completed GW and every currently resolved cohort manager, V6 acquires Official submitted picks and records:

- entry ID
- exact 15 submitted players
- squad position
- starting XI / bench position and bench order
- captain and vice captain
- multiplier
- active chip
- Official entry-history GW points and cumulative points where available

Historical completed-GW submitted picks are immutable cache candidates. The canonical cache identity is `season + gw + league_id + entry_id` and each cached record has a deterministic digest.

A reusable historical record reports one of:

- `LIVE_FETCHED_HISTORICAL_GW`
- `IMMUTABLE_HISTORICAL_CACHE_REUSED`

Digest mismatch, corruption, force retry, manager-set change for a new manager, or unavailable cached facts cause a refetch. A rerun reuses valid manager/GW records and fetches only misses.

## Canonical output tree

```text
data/v6/
  health/
    historical_backfill.json
  mini_leagues/<resolved_league_id>/history/
    manifest.json
    managers.json
    gw_1/
      manager_picks.json
      exposure.json
      standings_or_points.json
      transitions.json
    gw_2/...
    gw_3/...
    longitudinal/
      player_ownership_history.json
      captain_history.json
      manager_history.json
      squad_overlap_history.json
      transitions.json
```

The tree is published only through the existing `runtime-data-v6` publisher. V3/V4/V5 caches and runtime branches are not read or used as fallback.

## Per-GW factual aggregates

Per player, exposure includes Official element ID, current canonical name/position/club labels, owners, ownership percentage, starts, captain count, vice count, bench count, multiplier sum, effective ownership, denominator, final points where available, and multiplier-adjusted cohort contribution.

The Official element ID is the primary identity. Current bootstrap club/position labels are explicitly marked as current canonical identity. V6 does not silently assert that those labels are a historical club snapshot when Official historical endpoints do not provide one.

## Longitudinal factual aggregates

V6 mechanically publishes player adoption/drop/retention counts, captain gains/drops, bench-to-start/start-to-bench counts, manager points and cumulative points by GW, captain/chip history, squad/XI overlap vs the previous GW, player changes, captain changes, XI changes, bench-order changes, pairwise cohort overlap, and player/captain concentration.

These are descriptive facts. V6 does not label managers or players as aggressive, conservative, template, differential, danger, shield, buy, sell, good, or bad.

## Reconciliation

For each manager/GW where Official data is available, V6 reconciles submitted picks with entry history and checks exact pick count, one captain, one vice captain, captain multiplier consistency, chip state, GW points/cumulative points availability, and progression facts. Missing values remain null/unavailable rather than being fabricated.

## Completeness and health

Each GW publishes expected manager count, collected manager count, submitted-picks available/missing count, entry-history available count, coverage percentage, completeness, and failed entry IDs.

Backfill status is factual:

- `GREEN`: every requested GW has full current-cohort submitted-picks and entry-history coverage with reconciliation checks passing.
- `AMBER`: partial manager/GW coverage exists and the dataset remains factually useful.
- `RED`: acquisition/control/integrity failure makes the requested backfill unusable.

Silent gaps are not GREEN.

## Recovery

A normal rerun is idempotent and should primarily reuse immutable submitted-picks cache. Use `force=true` only for governed corruption recovery, identity correction, or when Official evidence is known to have changed.

## Downstream contract

Manual FPL / FPL Master Monitor may consume these canonical facts to build Bayesian behavior models, rival/captain/ownership/chip models, Monte Carlo simulation, expected rank swing, P(top3), P(#1), and 3-5 GW decision analysis.

Those calculations remain outside V6. Downstream consumers should not need to scrape Official FPL again for the historical facts already published by V6.
