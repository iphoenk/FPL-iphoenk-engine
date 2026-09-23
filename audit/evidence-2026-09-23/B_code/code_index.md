# Evidence metadata
source: GitHub source at PR #668 head
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: AVAILABLE


`src/engines/v12_lineup_batch.py:2402-2629` optimize_lineup_horizons_exact_batch
`src/engines/v12_lineup_optimizer.py:3038-3238` optimize_lineup (scalar/public P1.7 entry)
`src/engines/v12_package_utility.py:613-681` _frontier
`src/engines/v12_package_utility.py:964-1203` _materialize_route_lineups
`src/engines/v12_package_utility.py:1206-1495` evaluate_packages
`src/engines/v12_package_utility.py:1500-1607` derive_bounded_future_frontier
`src/engines/v12_package_utility.py:1639-1762` select_stage3_material_mc_routes
`src/engines/v12_package_utility.py:1766-1805` select_material_funding_legs
`src/engines/v12_package_utility.py:1808-1936` combine_package_utility_surfaces
`src/engines/v12_player_minutes.py:1-776` Stage2 P1.1 module
`src/engines/v12_player_events.py:1-1821` Stage2 P1.3 module
`src/models/v12_analytics_foundation.py:346-690` Foundation load_v6_analytics_foundation
`src/engines/v12_monte_carlo.py:2833-3231` P1.4 run_correlated_monte_carlo
`src/engines/v12_stage2_derived_cache.py:79-104,107-213` Stage2 fingerprint/cache
`src/engines/v12_lineup_optimizer.py:1621-1699` P1.7 decision-core fingerprint/cache
`src/engines/v12_monte_carlo.py:940-1028,2909-2927` MC seed/cache fingerprint
