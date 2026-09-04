# V6 Fresh Data Platform

## Mission

V6 is the repository's dedicated fresh-data acquisition and evidence-storage layer. V6 does not make FPL decisions. It has no transfer, captaincy, chip, optimizer, xPts, xMins, Monte Carlo, or recommendation authority. Manual FPL reads V6 snapshots as its structured fresh-data layer. V3 and V4 remain decoupled from V6 until explicitly redesigned or repaired. V6 only acquires, validates, preserves, normalizes identity, tracks provenance, and publishes source health.

## Stable-core design

The active V6 universe is intentionally limited to sources that have a maintainable acquisition path. V6 does not chase nominal source count by adding anti-bot workarounds, fragile undocumented endpoints, or unnecessary paid dependencies. Sources that cannot be acquired cleanly are excluded from the active registry and are not counted as failures.

A user command `fresh V6` means one complete acquisition cycle across the full active universe. A cycle is FULL only when all **18/18 active sources** are attempted.

## Hourly lifecycle and persistence

Every cycle:

1. hydrates the previous `runtime-data-v6` last-good snapshot when available;
2. validates registry and credentials;
3. acquires all active sources with isolated source/request failure handling and bounded concurrency;
4. performs conditional revalidation when supported, so an upstream `NOT_MODIFIED` response is a successful fresh check rather than a degradation;
5. preserves last-good source data on transient failure and marks its origin truthfully;
6. normalizes Official-FPL-authoritative identities;
7. publishes source lineage, freshness, health, and the latest evidence index;
8. publishes the governed snapshot to `runtime-data-v6`;
9. retains `data/v6/` as a 14-day GitHub Actions artifact.

The scheduler runs at minute `05` every UTC hour. No upstream content change is required for a GREEN acquisition: a successful current-cycle revalidation with unchanged content remains GREEN.

## Active 18-source universe

1. Official FPL
2. Official FPL Price Predictor
3. Understat
4. StatMuse
5. Onside
6. Ben Crellin
7. Fantasy Football Fix
8. Fantasy Football Hub
9. OneFPL
10. LiveFPL
11. Fantasy Football Scout
12. StatsBomb Open Data
13. RotoWire Soccer
14. PremierLeague.com Stats
15. Football-Data.co.uk
16. API-Football / API-Sports
17. Transfermarkt
18. vaastav/Fantasy-Premier-League

## Intentionally excluded sources

These sources are outside the active V6 universe because their API/scraping mechanism is currently too difficult, access-restricted, credential-dependent, paid, or operationally fragile for the desired clean hourly contract:

- Opta / The Analyst
- FBref
- FotMob
- Sofascore
- ClubElo
- Sportmonks
- WhoScored
- ESPN Football Data
- football-data.org

Excluded sources are **not** counted as missing, AMBER, RED, or skipped. They may return only through an explicit future source-set change with a maintainable acquisition path.

`Football-Data.co.uk` is a separate source from `football-data.org` and remains active.

## Health semantics

- **GREEN**: the active source succeeded in the current acquisition cycle, including a valid conditional revalidation where content is unchanged.
- **AMBER**: an active non-critical source is partial, uses last-good cache, has a required credential not configured, or its upstream is temporarily unavailable.
- **RED**: an active critical source has no usable current or cached data.

V6 keeps acquisition time, upstream data time, content-change state, effective state, and cache origin separate. Cached data is explicitly marked and V6 never silently substitutes or fabricates values.

## Runtime database layout

```text
data/v6/
├── manifest.json
├── current/<18 active source snapshots>.json
├── normalized/canonical_players.json
├── normalized/canonical_teams.json
├── normalized/canonical_fixtures.json
├── evidence/lineage.json
├── evidence/latest_index.json
└── health/source_health.json
```

## Canonical identity

Official FPL owns canonical player (`official_fpl_element_id`), team, and fixture identities. External provider identifiers are attributes, not competing primary keys. The canonical player registry exposes external-ID slots only for the configured active source universe.

## Lineage and independence

V6 stores evidence by source and does not average provider values. `independence_group` is preserved so downstream Manual FPL can avoid double-counting correlated evidence. Official price prediction remains derived from Official FPL. The vaastav historical mirror cannot outrank current Official FPL truth.

## Credential-backed provider

The active source universe expects only `API_FOOTBALL_KEY` as an Actions secret. If it is absent, API-Football is truthfully `CONFIG_REQUIRED` / AMBER. V6 does not bypass authentication controls.

## Failure isolation and consumer rule

One active source failure cannot terminate the other 17 acquisitions. Multiple requests within a source are also isolated. Official FPL runs first because canonical identities and Official price fields depend on it. Manual FPL should read V6 snapshots rather than duplicate upstream scraping. V3 and V4 are not V6 consumers until explicitly redesigned. Model weights and decisions remain outside V6.

## Publication governance

Generated `data/v6` remains ignored on code branches. The dedicated publisher hydrates from and publishes to `runtime-data-v6`; it uses a force-add only inside that isolated runtime worktree. This keeps code branches clean while preserving persistent last-good evidence across hourly runs.
