# V6 Source Contract (Generated)

> Generated from the resolved V6 registry. Do not hand-edit counts or source lists.

| Metric | Count |
|---|---:|
| Configured source definitions | 38 |
| Active scheduled sources | 22 |
| Disabled sources | 8 |
| Reference-only sources | 8 |
| Required active sources | 2 |
| Temporary source overrides | 0 |

## Active scheduled sources

- `official_fpl`
- `official_price_predictor`
- `understat`
- `opta_the_analyst`
- `statmuse`
- `onside`
- `ben_crellin`
- `onefpl`
- `livefpl`
- `ffscout`
- `fotmob`
- `statsbomb`
- `rotowire`
- `premierleague_stats`
- `espn`
- `vaastav_fpl`
- `solio_analytics`
- `check_the_chance`
- `fantasy_football_pundit`
- `wikidata`
- `open_meteo`
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

## Reference-only sources

- `fffix`: FREE_ACCOUNT_EXISTS_BUT_MACHINE_ENDPOINTS_REDIRECT_TO_LOGIN
- `ffhub`: FREE_PUBLIC_SITE_EXISTS_BUT_PREDICTIONS_ARE_AUTH_GATED
- `clubelo`: FREE_PUBLIC_REFERENCE_BUT_RUNTIME_HTTPS_CONNECT_TIMEOUT_AFTER_REPAIR_RETRY
- `bbc_team_news`: FREE_EDITORIAL_TARGETED_DEADLINE_REFERENCE
- `premier_injuries`: FREE_PUBLIC_REFERENCE_NO_DATASET_REPUBLISH
- `fpl_form`: FREE_PERSONAL_USE_REFERENCE_NO_RUNTIME_REPUBLISH
- `fpl_review_free`: FREE_MODEL_REFERENCE_NO_STABLE_MACHINE_CONTRACT
- `reep_register`: PUBLIC_NO_AUTH_RELEASE_POINTER_HTTP_404_ON_2026_09_07_REENABLE_ONLY_AFTER_STABLE_PUBLIC_DOWNLOAD_REVALIDATION

## Required active sources

- `official_fpl`
- `official_price_predictor`

## Governance

- Stable provider contracts belong in the canonical registry/additions layer.
- `source_overrides.json` is temporary repair-only and lifecycle-governed.
- Activation state comes only from `config/v6/source_activation.json`.
- V6 remains data-only; this generated document conveys acquisition configuration, not FPL intelligence.
