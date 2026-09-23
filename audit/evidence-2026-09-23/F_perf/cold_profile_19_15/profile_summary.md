# V12 Controlled Cold Profile

This artifact is measurement-only. V6 is read-only and no compute cache is restored or persisted for this run.

## Stage wall-clock

| Stage | Status | Seconds |
|---|---:|---:|
| P1_2_PACKAGE_UTILITY | PASS | 1764.217000 |
| P1_1_P1_3_FULL_UNIVERSE | PASS | 164.619000 |
| V12_ANALYTICS_FOUNDATION | PASS | 49.945000 |
| P1_4_MONTE_CARLO | PASS | 39.891000 |
| P1_2B_FUNDED_PACKAGE_UTILITY | PASS | 6.194000 |
| P1_2B_PACKAGE_COMBINE | PASS | 5.243000 |
| P1_8_MINI_LEAGUE_BINDING | PASS | 4.265000 |
| P1_2_STAGE3_DECISION_BINDING | PASS | 3.884000 |
| P1_8_MINI_LEAGUE_OVERLAY | PASS | 3.347000 |
| P1_4_PACKAGE_BINDING | PASS | 3.276000 |
| P1_6_TACTICAL_ROLE | PASS | 3.256000 |
| S16B_POST_MATCH_GW1_NOW | PASS | 1.001000 |
| P1_7_LINEUP | PASS | 0.943000 |
| P1_2A_PACKAGE_SEARCH | PASS | 0.420000 |
| P1_2_STAGE3_DECISION_CLOSURE | PASS | 0.256000 |
| WATCHLIST20 | PASS | 0.234000 |
| TEAM_STRENGTH | PASS | 0.200000 |
| V6_OFFICIAL_FACTS | PASS | 0.182000 |
| P1_2_MATERIAL_FUNDING_LEGS | PASS | 0.147000 |
| P1_4_MATERIAL_ROUTE_SELECTION | PASS | 0.135000 |
| OFFICIAL_FPL_PREDICTOR_RISE20 | PASS | 0.077000 |
| OFFICIAL_FPL_PREDICTOR_FALL20 | PASS | 0.074000 |
| P1_8_MINI_LEAGUE_SNAPSHOT | PASS | 0.013000 |
| P1_2A_FUNDED_PACKAGE_SEARCH | PASS | 0.012000 |
| OFFICIAL_ROLE_EVIDENCE | PASS | 0.008000 |
| OUR15_PRICE_RADAR | PASS | 0.005000 |
| PERSONAL_EVIDENCE_RECONCILIATION | PASS | 0.002000 |
| OUR15_IDENTITY | PASS | 0.002000 |
| V6_REPORT_PREFETCH_BINDING | PASS | 0.001000 |
| ALL15_MATERIALIZATION | PASS | 0.000000 |
| TRANSFER_FINANCE_CONTEXT | PASS | 0.000000 |

## FOUNDATION

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| load_v6_analytics_foundation | v12_analytics_foundation.py:346 | 0.039446 | 49.940048 | 1 |
| _select_match_source | v12_analytics_foundation.py:135 | 0.000018 | 0.085428 | 1 |
| _match_source_candidate | v12_analytics_foundation.py:79 | 0.005041 | 0.085409 | 2 |
| _read_json | v12_analytics_foundation.py:24 | 0.000045 | 0.049314 | 5 |
| _feature_status | v12_analytics_foundation.py:55 | 0.000051 | 0.029941 | 22 |
| <genexpr> | v12_analytics_foundation.py:61 | 0.013576 | 0.024107 | 70224 |
| _row_is_joinable | v12_analytics_foundation.py:44 | 0.009744 | 0.015346 | 3801 |
| _supplemental_player_evidence | v12_analytics_foundation.py:179 | 0.005356 | 0.015268 | 1 |
| ensure | v12_analytics_foundation.py:194 | 0.000444 | 0.000548 | 438 |
| _latest_completed_gw | v12_analytics_foundation.py:32 | 0.000035 | 0.000197 | 1 |
| <module> | v12_analytics_foundation.py:1 | 0.000020 | 0.000058 | 1 |
| require_match_foundation | v12_analytics_foundation.py:693 | 0.000010 | 0.000011 | 1 |
| AnalyticsFoundationError | v12_analytics_foundation.py:20 | 0.000001 | 0.000001 | 1 |

_Cumulative time is inclusive; nested cumulative rows must not be added together._

## STAGE2

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| load_or_build_stage2_projections | v12_stage2_derived_cache.py:107 | 0.000118 | 164.618583 | 1 |
| build | historical_projection.py:35 | 0.968097 | 163.170863 | 1 |
| project_stage2_fixture | historical_projection.py:489 | 0.250948 | 125.401306 | 10005 |
| enhance_fixture_projection | v12_position_probability_components.py:1258 | 6.790178 | 95.070513 | 10005 |
| build_hierarchical_priors | v12_stage1_analytics.py:150 | 0.398261 | 35.227547 | 1 |
| _sufficient | v12_stage1_analytics.py:134 | 12.254624 | 34.376239 | 8004 |
| project_player_fixture | v12_player_events.py:1254 | 2.338803 | 29.985633 | 10005 |
| _convolve_integer_pmf | v12_player_events.py:873 | 19.786964 | 24.691611 | 85623 |
| _build_joint_predictive_surface | v12_player_events.py:970 | 5.250060 | 22.809213 | 10005 |
| _gk_save_pmf_from_model | v12_position_probability_components.py:357 | 7.072091 | 16.638538 | 12870 |
| build_contextual_dynamics | v12_contextual_dynamics.py:2222 | 0.267755 | 14.527805 | 10005 |
| walk_forward_validate | v12_stage1_analytics.py:475 | 4.285766 | 14.366547 | 1 |
| _apply_conditional_bonus | v12_position_probability_components.py:998 | 2.434392 | 14.091053 | 10005 |
| build_player_trajectory | v12_contextual_dynamics.py:312 | 1.200725 | 13.671662 | 10602 |
| _conditional_bonus_pmf | v12_position_probability_components.py:968 | 5.885246 | 11.030875 | 383568 |
| convolve_point_distributions | v12_position_probability_components.py:636 | 0.884015 | 10.564068 | 13340 |
| _joint_goal_assist_point_surface | v12_player_events.py:807 | 1.745500 | 10.461992 | 229350 |
| _apply_bernoulli_reward | v12_player_events.py:905 | 6.220570 | 8.810740 | 448695 |
| _f | v12_stage1_analytics.py:19 | 6.739153 | 8.776135 | 25908722 |
| _compound_poisson_point_pmf | v12_player_events.py:753 | 5.277925 | 6.928955 | 229350 |

_Cumulative time is inclusive; nested cumulative rows must not be added together._

## PACKAGE_COMBINE

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| evaluate_packages | v12_package_utility.py:1196 | 0.079310 | 1770.400627 | 2 |
| _materialize_route_lineups | v12_package_utility.py:961 | 0.009342 | 1750.501576 | 2 |
| _model_evidence_binding | v12_package_utility.py:748 | 0.004385 | 12.440193 | 2 |
| combine_package_utility_surfaces | v12_package_utility.py:1791 | 0.029603 | 5.242937 | 1 |
| derive_bounded_future_frontier | v12_package_utility.py:1483 | 3.073253 | 4.255512 | 2 |
| attach_stage3_decision | v12_package_utility.py:2520 | 0.004543 | 3.883873 | 1 |
| _cumulative_lineup_horizons | v12_package_utility.py:198 | 0.002862 | 1.433342 | 1 |
| _lineup_decision | v12_package_utility.py:127 | 0.000371 | 1.430316 | 5 |
| <lambda> | v12_package_utility.py:1561 | 0.199087 | 0.317293 | 356908 |
| _football_horizon_delta | v12_package_utility.py:1593 | 0.071906 | 0.315585 | 18381 |
| select_stage3_material_mc_routes | v12_package_utility.py:1622 | 0.028669 | 0.271728 | 2 |
| finalize_stage3_decision | v12_package_utility.py:2013 | 0.032742 | 0.254506 | 1 |
| _f | v12_package_utility.py:61 | 0.137132 | 0.177370 | 508439 |
| select_material_funding_legs | v12_package_utility.py:1749 | 0.004099 | 0.146420 | 1 |
| _route_net_horizons | v12_package_utility.py:448 | 0.046191 | 0.100263 | 2044 |
| _structural_impact | v12_package_utility.py:565 | 0.008710 | 0.080420 | 2044 |
| sensitivity_for_route | v12_package_utility.py:2063 | 0.032740 | 0.067904 | 2043 |
| <genexpr> | v12_package_utility.py:1616 | 0.026598 | 0.060586 | 73524 |
| _lineup_impact | v12_package_utility.py:526 | 0.028860 | 0.058057 | 2044 |
| <genexpr> | v12_package_utility.py:1617 | 0.025626 | 0.054221 | 73524 |

_Cumulative time is inclusive; nested cumulative rows must not be added together._

## MONTE_CARLO

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| run_package_monte_carlo | v12_monte_carlo.py:3234 | 0.006207 | 28.784991 | 1 |
| run_correlated_monte_carlo | v12_monte_carlo.py:2833 | 0.001469 | 28.770840 | 1 |
| _simulate_route_arrays | v12_monte_carlo.py:2522 | 0.000757 | 20.712792 | 1 |
| _simulate_route_arrays_parallel | v12_monte_carlo.py:2409 | 0.022025 | 20.712031 | 1 |
| canonical_package_seed | v12_monte_carlo.py:940 | 0.000037 | 5.474484 | 1 |
| attach_monte_carlo_to_package_utility | v12_monte_carlo.py:3287 | 0.006338 | 3.276197 | 1 |
| _pair_metrics | v12_monte_carlo.py:2645 | 0.069255 | 1.984435 | 84 |
| _route_metrics | v12_monte_carlo.py:2586 | 0.025803 | 0.516217 | 24 |
| <module> | v12_monte_carlo.py:1 | 0.000140 | 0.290895 | 1 |
| _quantiles | v12_monte_carlo.py:2575 | 0.000216 | 0.284162 | 24 |
| _convergence | v12_monte_carlo.py:2722 | 0.002097 | 0.038481 | 1 |
| _expected_regret | v12_monte_carlo.py:2708 | 0.014754 | 0.033939 | 3 |
| _merge_parallel_sampling_diagnostics | v12_monte_carlo.py:2239 | 0.001832 | 0.019522 | 1 |
| package_route_definitions | v12_monte_carlo.py:876 | 0.000559 | 0.013454 | 2 |
| _route_rows_from_package | v12_monte_carlo.py:801 | 0.003502 | 0.012543 | 2 |
| <genexpr> | v12_monte_carlo.py:2316 | 0.003019 | 0.004726 | 4950 |
| <genexpr> | v12_monte_carlo.py:2284 | 0.002717 | 0.004248 | 4400 |
| _simulation_route_signature | v12_monte_carlo.py:889 | 0.000476 | 0.000856 | 2 |
| _material_player_ids | v12_monte_carlo.py:1169 | 0.000310 | 0.000742 | 1 |
| _save_mc_summary_cache | v12_monte_carlo.py:1000 | 0.000038 | 0.000732 | 1 |

_Cumulative time is inclusive; nested cumulative rows must not be added together._
