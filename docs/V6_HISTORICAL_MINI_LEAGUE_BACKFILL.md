# V6 Historical Mini-League Backfill

## Purpose

V6 backfills Official FPL facts for managers who belong to a configured priority mini-league at the time the backfill is run. The first production target is the configured `ICON+ League` classic league.

This capability is factual data acquisition, normalization, reconciliation, caching, and mechanical aggregation only. It does not produce FPL decisions, predictions, xPts, xMins, tactical scores, Bayesian recommendations, Monte Carlo results, transfer/captain/chip/formation recommendations, or WAIT/PREPARE/ACT classifications.

## Governed control path

Historical backfill reuses issue #431 and the existing `/v6-report-prefetch` control plane, owner authorization, `runtime-data-v6`, and the existing V6 publisher. It has no cron and no independent publisher.

Example:

```text
/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league reason=icon_plus_history_backfill
```

`gw_from` and `gw_to` are inclusive. Historical mode accepts completed Official FPL GWs and the current GW only after its Official deadline. A reversed range, GW 0, current pre-deadline GW, or future GW fails closed. `scope` must be exactly `mini_league`.

A governed force retry is available:

```text
/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league force=true reason=icon_plus_history_force_retry
```

## League resolution

The executable configuration does not contain the numeric ICON+ league ID. The service reads the V6 consumer context, discovers the user's current Official FPL league memberships, and resolves the priority league by configured `name + kind`.

If the configured priority league is missing or ambiguous, backfill fails closed. The manager count is derived from the fully paginated current standings and is never assumed to be 58.

## Cohort semantics

Historical output is explicitly labeled `CURRENT_COHORT_HISTORY`.

This means historical FPL records for managers who are members of the resolved priority-league cohort now. Current membership does not prove membership in an earlier GW. Unless Official FPL provides separate authoritative historical league-membership evidence, every manager/GW record uses:

- `current_cohort_member: true`
- `membership_at_gw_status: UNKNOWN`
- `membership_evidence: CURRENT_STANDINGS_COHORT_ONLY`
- `historical_membership_confirmed: null`

The service must never describe the current cohort as the exact historical league membership of GW1/GW2/etc without authoritative evidence.

## Historical rank semantics

Official entry history may expose manager GW points, cumulative points, and overall rank, but it does not establish a historical mini-league standings table for the current cohort.

Therefore V6 publishes `reconstructed_current_cohort_rank` when it can mechanically rank current cohort members by historical cumulative points. The field is labeled `RECONSTRUCTED_CURRENT_COHORT_ONLY`. `official_historical_league_rank` remains null unless a future Official endpoint provides authoritative historical league standings.

## Acquisition and cache

For every requested eligible GW and every currently resolved cohort manager, V6 acquires Official submitted picks and records entry ID, exact 15 submitted players, squad position, starting XI/bench order, captain, vice captain, multiplier, active chip, and Official entry-history points/cumulative points where available.

Completed-GW submitted picks are immutable cache candidates. Current post-deadline submitted picks are also factual and cache-reusable, but current-GW points remain provisional and are labeled live rather than final. Current-GW entry history is refreshed while that GW remains unfinished.

The canonical cache identity is `season + gw + league_id + entry_id` and each cached record has a deterministic digest. Reusable records report origins including:

- `LIVE_FETCHED_HISTORICAL_GW`
- `IMMUTABLE_HISTORICAL_CACHE_REUSED`
- `LIVE_FETCHED_CURRENT_GW_POST_DEADLINE`
- `POST_DEADLINE_CURRENT_GW_SUBMITTED_PICKS_CACHE_REUSED`

Digest mismatch, corruption, force retry, manager-set change for a new manager, or unresolved cached facts cause a refetch.

### Strict Official absence

Current cohort membership does not imply that the same FPL entry had an Official record in every earlier GW. For a completed GW, V6 may explicitly exclude a current-cohort entry from the eligible denominator only when all of these facts are simultaneously true:

1. Official submitted-picks for that entry/GW returns HTTP 404.
2. Official entry-history is available.
3. The requested GW has no Official history row.
4. The first Official entry-history row starts in a later GW.

The record remains present and `UNAVAILABLE`; it is not deleted or fabricated. It is marked with `official_availability_status=OFFICIAL_GW_RECORD_NOT_AVAILABLE`, `official_exclusion_reason=BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW`, the first Official history GW, and provenance from both Official endpoints.

This is only an Official FPL availability fact. It does not prove or infer historical league membership. Strict completed-GW Official absences are immutable cache candidates after digest validation.

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

Per player, exposure includes Official element ID, current canonical name/position/club labels, owners, ownership percentage, starts, captain count, vice count, bench count, multiplier sum, effective ownership, denominator, final points for completed GWs or live points for the current unfinished GW, and multiplier-adjusted cohort contribution.

The Official element ID is the primary identity. Current bootstrap club/position labels are explicitly marked as current canonical identity. V6 does not silently assert that those labels are a historical club snapshot when Official historical endpoints do not provide one.

## Longitudinal factual aggregates

V6 mechanically publishes player adoption/drop/retention counts, captain gains/drops, bench-to-start/start-to-bench counts, manager points and cumulative points by GW, captain/chip history, squad/XI overlap vs the previous GW, player changes, captain changes, XI changes, bench-order changes, pairwise cohort overlap, and player/captain concentration.

These are descriptive facts. V6 does not label managers or players as aggressive, conservative, template, differential, danger, shield, buy, sell, good, or bad.

## Reconciliation

For each manager/GW where Official data is available, V6 reconciles submitted picks with entry history and checks exact pick count, one captain, one vice captain, captain multiplier domain, chip state, and points/history availability.

The designated captain is not required to have multiplier >=2. Official submitted picks can legitimately show the designated captain at multiplier 0 when that player did not play. V6 therefore accepts designated-captain multiplier values that are mechanically valid in Official submitted picks rather than treating a no-show as corruption.

Missing values remain null/unavailable rather than being fabricated.

## Completeness and health

Each GW publishes both raw current-cohort coverage and eligible coverage after any strict Official absences. Important fields include:

- `expected_manager_count` / `current_cohort_manager_count`
- `eligible_manager_count`
- `officially_excluded_manager_count`
- `officially_excluded_entry_ids`
- `official_exclusion_reason_counts`
- `submitted_picks_available_count`
- `submitted_picks_missing_count`
- `unresolved_submitted_picks_missing_count`
- `coverage_percent` for the full current cohort
- `eligible_coverage_percent` after strict Official exclusions
- `failed_entry_ids`
- `complete_with_explicit_official_exclusions`

Raw coverage is never rewritten to 100% merely because an exclusion is known. For example, 50 records from a current cohort of 58 remain raw coverage 86.2069%; if the other eight satisfy the strict Official absence policy, eligible coverage may be 100% and the GW can be complete with explicit exclusions.

Backfill status is factual:

- `GREEN`: every requested GW has complete eligible coverage and reconciliation, with any missing current-cohort records explained by strict Official exclusions or an explicitly optional current-GW history condition.
- `AMBER`: unresolved manager/GW gaps remain but the dataset is factually useful.
- `RED`: acquisition/control/integrity failure makes the requested backfill unusable.

Silent gaps are never GREEN.

## Recovery

A normal rerun is idempotent and primarily reuses immutable submitted-picks facts and strict completed-GW Official absences. Use `force=true` only for governed corruption recovery, identity correction, or when Official evidence is known to have changed.

## Downstream contract

Manual FPL / FPL Master Monitor may consume these canonical facts to build Bayesian behavior models, rival/captain/ownership/chip models, Monte Carlo simulation, expected rank swing, P(top3), P(#1), and 3-5 GW decision analysis.

Those calculations remain outside V6. Downstream consumers should not need to scrape Official FPL again for historical facts already published by V6.
