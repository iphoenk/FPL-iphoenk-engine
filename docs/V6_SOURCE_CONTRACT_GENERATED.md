# V6 Source Contract (Generated)

> Generated from the resolved V6 registry. Do not hand-edit counts or source lists.

| Metric | Count |
|---|---:|
| Configured source definitions | 38 |
| Active scheduled sources | 13 |
| Disabled sources | 9 |
| Reference-only sources | 16 |
| Required active sources | 2 |
| Temporary source overrides | 0 |

## Active scheduled sources

- `official_fpl`
- `official_price_predictor`
- `understat`
- `opta_the_analyst`
- `statmuse`
- `fotmob`
- `statsbomb`
- `rotowire`
- `premierleague_stats`
- `espn`
- `vaastav_fpl`
- `wikidata`
- `thesportsdb_v1`

## Disabled sources

- `fbref`: DROP_DUPLICATE_ACCESS_RESTRICTED
- `sofascore`: DROP_DUPLICATE_UNOFFICIAL_403
- `sportmonks`: DROP_PAID_PROVIDER
- `api_football`: DROP_PAID_PROVIDER
- `transfermarkt`: DROP_AUTOMATION_RESTRICTED
- `whoscored`: DROP_DUPLICATE_ACCESS_RESTRICTED
- `football_data_org`: DROP_PAID_BY_OWNER_DECISION
- `football_data_uk`: TEMPORARY_DISABLE_FREE_PUBLIC_PROVIDER_RUNTIME_HTTP_503_REENABLE_AFTER_STABLE_REVALIDATION
- `open_meteo`: RETIRED_CHATGPT_REPORT_TIME_WEATHER_NOT_V6_DEPENDENCY

## Reference-only sources

- `onside`: WAVE_B_MODEL_SOURCE_FPL_MASTER_ONLY
- `ben_crellin`: HUMAN_FIXTURE_ANALYSIS_FPL_MASTER_CONTEXT_ONLY
- `fffix`: WAVE_B_MODEL_SOURCE_AUTH_GATED
- `ffhub`: WAVE_B_MODEL_SOURCE_AUTH_GATED
- `onefpl`: WAVE_B_MARKET_MODEL_REFERENCE_FPL_MASTER_ONLY
- `livefpl`: WAVE_B_MARKET_MODEL_REFERENCE_FPL_MASTER_ONLY
- `ffscout`: WAVE_B_C_MODEL_EDITORIAL_SOURCE_FPL_MASTER_ONLY
- `clubelo`: FREE_PUBLIC_REFERENCE_BUT_RUNTIME_HTTPS_CONNECT_TIMEOUT_AFTER_REPAIR_RETRY
- `solio_analytics`: WAVE_B_MODEL_SOURCE_FPL_MASTER_ONLY
- `check_the_chance`: WAVE_B_MARKET_MODEL_SOURCE_FPL_MASTER_ONLY
- `fantasy_football_pundit`: WAVE_B_C_MODEL_EDITORIAL_SOURCE_FPL_MASTER_ONLY
- `bbc_team_news`: WAVE_C_EDITORIAL_TARGETED_DEADLINE_REFERENCE
- `premier_injuries`: WAVE_C_INJURY_CONTEXT_REFERENCE_NO_DATASET_REPUBLISH
- `fpl_form`: WAVE_B_MODEL_REFERENCE_NO_RUNTIME_REPUBLISH
- `fpl_review_free`: WAVE_B_MODEL_REFERENCE_NO_STABLE_MACHINE_CONTRACT
- `reep_register`: PUBLIC_NO_AUTH_RELEASE_POINTER_HTTP_404_ON_2026_09_07_REENABLE_ONLY_AFTER_STABLE_PUBLIC_DOWNLOAD_REVALIDATION

## Required active sources

- `official_fpl`
- `official_price_predictor`

## Governance

- Stable provider contracts belong in the canonical registry/additions layer.
- `source_overrides.json` is temporary repair-only and lifecycle-governed.
- Activation state comes only from `config/v6/source_activation.json`.
- V6 remains data-only; this generated document conveys acquisition configuration, not FPL intelligence.
