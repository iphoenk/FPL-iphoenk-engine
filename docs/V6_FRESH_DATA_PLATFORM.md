# V6 Fresh Data Platform

## Mission

V6 is the repository's dedicated fresh-data acquisition and evidence-storage layer. V6 does not make FPL decisions. It has no transfer, captaincy, chip, optimizer, xPts, xMins, Monte Carlo, or recommendation authority. Consumers such as V3, V4, reporting, price models, or later engines may read V6 snapshots, but V6 itself only acquires, validates, preserves, normalizes identity, tracks provenance, and publishes source health.

## Hourly lifecycle

Every cycle checks all configured sources: hydrate the previous runtime snapshot, validate registry and credentials, acquire, conditionally revalidate unchanged upstreams, preserve last-good data on failure, normalize Official-FPL-authoritative identities, publish lineage, classify health, publish to `runtime-data-v6`, and retain the generated `data/v6/` tree as a 14-day GitHub Actions artifact. The scheduler runs at minute `05` every UTC hour.

`changed=false` or HTTP `304 Not Modified` is a successful current-cycle validation and remains GREEN. `checked_at`, `last_success_at`, `effective_state`, `data_origin`, and effective data age are kept separate.

## Performance architecture

V6 uses two bounded concurrency layers:

1. Source-level workers start all network-backed sources together, including Official FPL.
2. Request-level workers execute independent endpoints within a source concurrently.

The derived Official price-predictor adapter is the only acquisition dependency. It runs after Official FPL completes. Official FPL no longer blocks unrelated sources.

The default policy is 20 source workers and up to 4 request workers per active source, with short connect/read timeouts, bounded retries, retry backoff, and HTTP conditional revalidation using ETag / Last-Modified when the provider supports it.

This is intentionally a modular in-process acquisition service rather than 27 deployment units. Separate workflow shards or services should only be introduced when runtime telemetry proves a provider family needs a separate failure domain or substantially different resource envelope. Avoiding premature microservice fragmentation keeps V6 faster and simpler while preserving adapter isolation.

## Persistent last-good state

The GitHub Actions workflow hydrates `data/v6/` from `runtime-data-v6` before every acquisition cycle. This is required for real last-good behavior across ephemeral runners.

A failed source or request never silently erases a previously usable payload. The current attempt is preserved in `attempts`, while the effective payload explicitly reports one of:

- `CURRENT_CYCLE`
- `REVALIDATED_CACHE`
- `LAST_GOOD_CACHE`

A revalidated cache is current evidence that the upstream body has not changed. A last-good cache is degraded and remains AMBER.

## 27-source universe

1. Official FPL
2. Official FPL Price Predictor
3. Understat
4. Opta / The Analyst
5. StatMuse
6. Onside
7. Ben Crellin
8. Fantasy Football Fix
9. Fantasy Football Hub
10. OneFPL
11. LiveFPL
12. Fantasy Football Scout
13. FBref
14. FotMob
15. Sofascore
16. StatsBomb Open Data
17. RotoWire Soccer
18. PremierLeague.com Stats
19. ClubElo
20. Football-Data.co.uk
21. Sportmonks
22. API-Football / API-Sports
23. Transfermarkt
24. WhoScored
25. ESPN Football Data
26. football-data.org
27. vaastav/Fantasy-Premier-League

## Health semantics

- GREEN: current acquisition or conditional revalidation succeeded. Content may be changed or unchanged.
- AMBER: partial source, last-good cache, credential not configured, truncated text payload, or non-critical upstream degradation.
- RED: critical source has no usable current or cached data.

Health exposes source duration and effective data age so a source can be checked recently without pretending that an unrevalidated stale cache is fresh.

## Runtime database layout

```text
data/v6/
├── manifest.json
├── current/<27 source snapshots>.json
├── normalized/canonical_players.json
├── normalized/canonical_teams.json
├── normalized/canonical_fixtures.json
├── evidence/lineage.json
├── evidence/latest_index.json
└── health/source_health.json
```

The complete `data/v6/` tree is also retained as an immutable GitHub Actions artifact for each cycle.

## Canonical identity

Official FPL owns canonical player (`official_fpl_element_id`), team, and fixture identities. External provider identifiers are attributes, not competing primary keys. The player registry exposes external-ID slots for all configured sources.

## Lineage

V6 stores sources separately and never averages them. `opta_the_analyst`, `fbref`, and `whoscored` share the `opta_family` independence group so consumers do not count correlated retrieval paths as independent confirmations. Official price prediction remains derived from Official FPL; vaastav history cannot outrank current Official truth.

The price-predictor adapter inherits Official FPL freshness. A complete predictor payload derived from cached Official data is AMBER, not falsely GREEN.

## Credential-backed providers

Expected Actions secrets are `SPORTMONKS_API_TOKEN`, `API_FOOTBALL_KEY`, and `FOOTBALL_DATA_ORG_TOKEN`. Missing credentials produce `CONFIG_REQUIRED` / AMBER with no auth bypass.

## Failure isolation and consumer rule

A source failure cannot terminate the other acquisitions, and one endpoint failure cannot terminate sibling endpoints. V3/V4/other consumers should read V6 snapshots rather than duplicate upstream scraping unless an intentional emergency fallback is invoked; model weights remain the consumer's responsibility.

## Scale-out trigger

Create separate workflow shards or services only when telemetry shows one of the following:

- a source family repeatedly consumes a material share of the cycle wall-clock time;
- provider-specific rate limits require separate scheduling;
- authentication or network policy needs a separate failure domain;
- payload size or parsing needs a materially different runtime;
- one source family causes recurrent worker starvation despite bounded timeouts.

Until one of those conditions is measured, bounded in-process concurrency is the preferred production design.
