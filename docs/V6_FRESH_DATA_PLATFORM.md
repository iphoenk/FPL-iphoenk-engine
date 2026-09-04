# V6 Fresh Data Platform

## Mission

V6 is the repository's dedicated fresh-data acquisition and evidence-storage layer. V6 does not make FPL decisions. It has no transfer, captaincy, chip, optimizer, xPts, xMins, Monte Carlo, or recommendation authority. Consumers such as V3, V4, reporting, price models, or later engines may read V6 snapshots, but V6 itself only acquires, validates, preserves, normalizes identity, tracks provenance, and publishes source health.

## Hourly lifecycle

Every cycle checks all configured sources: validate registry/credentials, acquire, validate, preserve last-good data on failure, normalize Official-FPL-authoritative identities, publish lineage, classify health, publish to `runtime-data-v6`, and retain the generated `data/v6/` tree as a 14-day GitHub Actions artifact. The scheduler runs at minute `05` every UTC hour. No upstream change is a successful check and remains GREEN.

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

- GREEN: current acquisition cycle succeeded. Content can be changed or unchanged.
- AMBER: partial source, last-good cache, credential not configured, or non-critical upstream unavailable.
- RED: critical source has no usable current or cached data.

Fields keep `checked_at`, `availability`, `effective_state`, `changed`, and `data_origin` separate. Cached data is always marked `LAST_GOOD_CACHE`; V6 never silently substitutes or fabricates values.

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

## Canonical identity

Official FPL owns canonical player (`official_fpl_element_id`), team, and fixture identities. External provider identifiers are attributes, not competing primary keys. The player registry exposes external-ID slots for all configured sources.

## Lineage

V6 stores sources separately and never averages them. `opta_the_analyst`, `fbref`, and `whoscored` share the `opta_family` independence group so consumers do not count correlated retrieval paths as independent confirmations. Official price prediction remains derived from Official FPL; vaastav history cannot outrank current Official truth.

## Credential-backed providers

Expected Actions secrets are `SPORTMONKS_API_TOKEN`, `API_FOOTBALL_KEY`, and `FOOTBALL_DATA_ORG_TOKEN`. Missing credentials produce `CONFIG_REQUIRED` / AMBER with no auth bypass.

## Failure isolation and consumer rule

One source failure cannot terminate the other 26 acquisitions. Official FPL runs first because canonical identities and Official price fields depend on it. V3/V4/other consumers should read V6 snapshots rather than duplicate upstream scraping unless an intentional emergency fallback is invoked; model weights remain the consumer's responsibility.
