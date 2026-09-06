# V6 Historical Mini-League Backfill

## Purpose

V6 historical backfill is a **data-acquisition, normalization, validation, cache, and publication** capability only. It exists to preserve Official FPL facts for the currently resolved priority mini-league cohort so downstream systems can perform their own analysis.

V6 does not own decision, prediction, optimization, tactical, transfer, captain, chip, Bayesian, Monte Carlo, rank-probability, or mini-league analytical authority.

## Control plane

Historical acquisition reuses the governed report-prefetch control plane. It has no independent cron and no second publisher.

Example request:

```text
/v6-report-prefetch report_kind=historical_backfill gw_from=1 gw_to=3 scope=mini_league reason=icon_plus_history_backfill
```

The production workflow continues to invoke:

```text
python -m src.runtime_v6.historical_backfill
```

`src.runtime_v6.historical_backfill` is now a compatibility entrypoint. The factual implementation lives in `src.runtime_v6.historical_facts`.

The publisher remains `runtime-data-v6` only.

## Cohort semantics

Historical rows use:

```text
CURRENT_COHORT_HISTORY
```

This means the manager set is the mini-league cohort resolved from current Official FPL standings at acquisition time. V6 does not infer that every current member belonged to the league in every historical GW.

Historical membership remains unknown unless Official FPL provides direct evidence for that GW.

## Eligible gameweeks

The backfill accepts:

- completed GWs;
- the current GW only after its deadline;
- no future GW;
- no current pre-deadline GW.

A current post-deadline GW is provisional. Submitted picks are factual post-deadline records, while event points are labeled live rather than final. Entry-history rows may remain unavailable until the GW completes.

## Canonical factual artifacts

For each resolved league, V6 publishes only atomic or normalized factual artifacts under:

```text
data/v6/mini_leagues/<league_id>/history/
```

Canonical layout:

```text
manifest.json
managers.json
gw_<n>/manager_picks.json
gw_<n>/event_points.json
gw_<n>/entry_history.json
longitudinal/manager_history.json
```

### `managers.json`

Contains the current Official FPL standings cohort and explicit membership semantics. Current membership is a fact. Historical membership is not inferred.

### `gw_<n>/manager_picks.json`

Contains Official submitted picks for each current-cohort manager, including the 15 submitted players, squad position, bench order, multiplier, designated captain, designated vice-captain, and active chip when Official FPL exposes it.

Completed-GW submitted picks may be reused as immutable cache records when the record digest and cache identity still validate.

### `gw_<n>/event_points.json`

Contains Official event element points only.

For completed GWs:

```text
points_semantics = FINAL_COMPLETED_GW
```

For the current post-deadline GW:

```text
points_semantics = LIVE_CURRENT_GW
```

V6 does not multiply these values by mini-league ownership, captaincy, or manager selections.

### `gw_<n>/entry_history.json`

Contains factual reconciliation between Official submitted picks and Official entry-history rows. Validation checks may include exact pick count, designated captain/vice presence, captain multiplier consistency, and chip consistency.

Official overall rank from entry history may be preserved as an upstream fact. V6 does not reconstruct mini-league rank or derive rank probability.

### `longitudinal/manager_history.json`

Contains a normalized per-manager sequence of factual GW states: submitted squad, starting XI, bench order, designated captain/vice, active chip, Official GW points, cumulative points, and Official overall rank where available.

It deliberately contains no previous-GW deltas, behavioral labels, similarity score, ownership calculation, or concentration statistic.

## Retired analytical artifacts

P0 retires the former historical analytical publication path. V6 no longer publishes canonical historical:

- ownership/EO or player exposure;
- player ownership history;
- captain concentration/history aggregates;
- transitions or ownership churn;
- pairwise squad/XI overlap;
- concentration or HHI metrics;
- reconstructed cohort rank;
- behavioral classification.

Legacy files with these meanings are removed from the runtime tree during a factual backfill run. In particular, the former paths `exposure.json`, `standings_or_points.json`, `transitions.json`, `player_ownership_history.json`, `captain_history.json`, and `squad_overlap_history.json` are not canonical V6 outputs.

Any ownership/EO, transitions, overlap, concentration, reconstructed cohort rank, rival modeling, probability, or decision analysis must be produced downstream from the atomic facts.

## Official absence handling

A missing completed-GW submitted-picks record is not automatically treated as a failure or as proof that the manager was not in the league.

V6 may classify a strict Official availability exclusion only when both are true:

1. Official submitted-picks returns HTTP 404 for that completed GW; and
2. Official entry history begins in a later GW.

That classification is an availability fact only. It does not infer historical mini-league membership.

Raw coverage and eligible coverage are reported separately so a strict Official absence cannot be hidden by denominator manipulation.

## Cache behavior

Completed-GW submitted picks are reusable only when cache identity and record digest validate. Corrupted records are fetched again. Current post-deadline submitted picks may be reused, but current-GW entry history is refreshed because Official can add that row while the GW progresses.

Entry-history cache reuse is allowed for completed requested ranges when the cached factual manager history contains every requested GW with the required Official points fields.

## Health

`data/v6/health/historical_backfill.json` mirrors the run manifest and reports factual acquisition health, including:

- expected/current-cohort manager count;
- eligible manager count;
- submitted-picks coverage;
- entry-history coverage;
- strict Official exclusions;
- cache hits/misses;
- request and retry telemetry;
- completed versus provisional current GW semantics;
- overall GREEN / AMBER / RED data-acquisition status.

GREEN means the requested factual dataset is complete under the explicit Official availability rules. It does not mean any downstream model or FPL decision is correct.

## Isolation and authority

Historical backfill reads Official FPL through V6 clients and writes V6 artifacts only. It must not retrieve runtime data from V3, V4, or V5.

The publication contract is fail-closed:

- canonical atomic facts: allowed;
- normalized facts: allowed;
- validation/control telemetry: allowed;
- deterministic identity crosswalks: allowed;
- V6-authored mini-league analytics: forbidden;
- decisions, predictions, optimization, tactical outputs, Bayesian outputs, and Monte Carlo outputs: forbidden.
