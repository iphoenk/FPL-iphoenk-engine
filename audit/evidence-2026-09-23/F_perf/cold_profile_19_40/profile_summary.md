# V12 Controlled Cold Profile

This artifact is measurement-only. V6 is read-only and no compute cache is restored or persisted for this run.

## Stage wall-clock

| Stage | Status | Seconds |
|---|---:|---:|
| P1_2_PACKAGE_UTILITY | PASS | 1224.645000 |
| P1_1_P1_3_FULL_UNIVERSE | PASS | 157.234000 |
| V12_ANALYTICS_FOUNDATION | PASS | 46.116000 |
| P1_4_MONTE_CARLO | PASS | 39.880000 |
| P1_2B_FUNDED_PACKAGE_UTILITY | PASS | 5.995000 |
| P1_2B_PACKAGE_COMBINE | PASS | 5.249000 |
| P1_8_MINI_LEAGUE_OVERLAY | PASS | 1.548000 |
| P1_4_PACKAGE_BINDING | PASS | 1.220000 |
| P1_6_TACTICAL_ROLE | PASS | 1.142000 |
| P1_8_MINI_LEAGUE_BINDING | PASS | 0.832000 |
| P1_2_STAGE3_DECISION_BINDING | PASS | 0.772000 |
| P1_7_LINEUP | PASS | 0.496000 |
| S16B_POST_MATCH_GW1_NOW | PASS | 0.302000 |
| V6_OFFICIAL_FACTS | PASS | 0.159000 |
| P1_2A_PACKAGE_SEARCH | PASS | 0.108000 |
| P1_2_STAGE3_DECISION_CLOSURE | PASS | 0.084000 |
| TEAM_STRENGTH | PASS | 0.078000 |
| WATCHLIST20 | PASS | 0.068000 |
| P1_2_MATERIAL_FUNDING_LEGS | PASS | 0.047000 |
| P1_4_MATERIAL_ROUTE_SELECTION | PASS | 0.040000 |
| OFFICIAL_FPL_PREDICTOR_RISE20 | PASS | 0.033000 |
| OFFICIAL_FPL_PREDICTOR_FALL20 | PASS | 0.031000 |
| P1_2A_FUNDED_PACKAGE_SEARCH | PASS | 0.004000 |
| OFFICIAL_ROLE_EVIDENCE | PASS | 0.003000 |
| P1_8_MINI_LEAGUE_SNAPSHOT | PASS | 0.003000 |
| OUR15_PRICE_RADAR | PASS | 0.002000 |
| PERSONAL_EVIDENCE_RECONCILIATION | PASS | 0.001000 |
| OUR15_IDENTITY | PASS | 0.001000 |
| V6_REPORT_PREFETCH_BINDING | PASS | 0.000000 |
| ALL15_MATERIALIZATION | PASS | 0.000000 |
| TRANSFER_FINANCE_CONTEXT | PASS | 0.000000 |

## V12_ANALYTICS_FOUNDATION / FOUNDATION

Profile status: **AVAILABLE**

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| <lambda> | v12_integrated_report_runner.py:2305 | 0.004367 | 46.115132 | 1 |
| load_v6_analytics_foundation | v12_analytics_foundation.py:346 | 0.039555 | 46.110758 | 1 |
| build_hierarchical_priors | v12_stage1_analytics.py:150 | 0.352628 | 32.175554 | 1 |
| _sufficient | v12_stage1_analytics.py:134 | 11.861200 | 31.425002 | 8004 |
| walk_forward_validate | v12_stage1_analytics.py:475 | 3.957821 | 13.602081 | 1 |
| _f | v12_stage1_analytics.py:19 | 6.613999 | 8.664607 | 25887500 |
| <method 'get' of 'dict' objects> | ~:0 | 6.715120 | 6.715120 | 40663702 |
| <built-in method builtins.max> | ~:0 | 5.520602 | 5.525584 | 25917724 |
| <built-in method builtins.sum> | ~:0 | 0.406846 | 4.337237 | 30565 |
| _clamp | v12_stage1_analytics.py:34 | 1.584195 | 3.866519 | 5719641 |
| _rate90 | v12_stage1_analytics.py:43 | 0.025148 | 3.649831 | 10096 |
| _position | v12_stage1_analytics.py:38 | 1.526598 | 2.057080 | 4096613 |
| <built-in method math.isfinite> | ~:0 | 2.050609 | 2.050609 | 25887500 |
| <genexpr> | v12_stage1_analytics.py:50 | 0.756056 | 1.696372 | 1343776 |
| _i | v12_stage1_analytics.py:27 | 1.684933 | 1.684933 | 9080323 |
| <genexpr> | v12_stage1_analytics.py:56 | 0.715645 | 1.656544 | 1333036 |
| <built-in method builtins.min> | ~:0 | 1.164943 | 1.164943 | 5722167 |
| <method 'upper' of 'str' objects> | ~:0 | 0.533006 | 0.533006 | 4113075 |
| <genexpr> | v12_stage1_analytics.py:548 | 0.346913 | 0.519776 | 1317625 |
| distribution_selection_matrix | v12_stage1_analytics.py:290 | 0.037063 | 0.100699 | 1 |
| _select_match_source | v12_analytics_foundation.py:135 | 0.000013 | 0.071655 | 1 |
| _match_source_candidate | v12_analytics_foundation.py:79 | 0.005372 | 0.071642 | 2 |
| _read_json | v12_analytics_foundation.py:24 | 0.000041 | 0.056890 | 5 |
| loads | __init__.py:299 | 0.000017 | 0.050499 | 5 |
| decode | decoder.py:333 | 0.000045 | 0.050479 | 5 |

_Cumulative time is inclusive. Child-process internals are not captured by parent cProfile._

## P1_1_P1_3_FULL_UNIVERSE / STAGE2

Profile status: **AVAILABLE**

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| _stage2_projection_with_cache | v12_integrated_report_runner.py:2316 | 0.000046 | 157.231907 | 1 |
| load_or_build_stage2_projections | v12_stage2_derived_cache.py:107 | 0.000112 | 157.231834 | 1 |
| <lambda> | v12_integrated_report_runner.py:2334 | 0.002554 | 156.042486 | 1 |
| build | historical_projection.py:35 | 0.842579 | 156.039930 | 1 |
| project_stage2_fixture | historical_projection.py:489 | 0.208974 | 120.462708 | 10005 |
| enhance_fixture_projection | v12_position_probability_components.py:1258 | 6.738379 | 91.650262 | 10005 |
| project_player_fixture | v12_player_events.py:1254 | 2.165377 | 28.520580 | 10005 |
| _convolve_integer_pmf | v12_player_events.py:873 | 18.771092 | 23.284959 | 85623 |
| _build_joint_predictive_surface | v12_player_events.py:970 | 5.129901 | 21.800106 | 10005 |
| <method 'get' of 'dict' objects> | ~:0 | 17.375750 | 17.375750 | 120651671 |
| _gk_save_pmf_from_model | v12_position_probability_components.py:357 | 6.966520 | 16.375375 | 12870 |
| <built-in method builtins.sum> | ~:0 | 3.847127 | 14.366188 | 3098626 |
| deepcopy | copy.py:118 | 7.117759 | 13.975598 | 8816592 |
| _deepcopy_dict | copy.py:217 | 2.276558 | 13.937244 | 430215 |
| build_contextual_dynamics | v12_contextual_dynamics.py:2222 | 0.238391 | 13.807376 | 10005 |
| _apply_conditional_bonus | v12_position_probability_components.py:998 | 2.395556 | 13.419644 | 10005 |
| build_player_trajectory | v12_contextual_dynamics.py:312 | 1.038366 | 12.386391 | 10005 |
| _conditional_bonus_pmf | v12_position_probability_components.py:968 | 5.471736 | 10.420148 | 383568 |
| convolve_point_distributions | v12_position_probability_components.py:636 | 0.806059 | 10.042458 | 13340 |
| _joint_goal_assist_point_surface | v12_player_events.py:807 | 1.657367 | 9.792806 | 229350 |
| _apply_bernoulli_reward | v12_player_events.py:905 | 5.880001 | 8.315599 | 448695 |
| _compound_poisson_point_pmf | v12_player_events.py:753 | 5.172131 | 6.474222 | 229350 |
| _posterior_recent_rate | v12_contextual_dynamics.py:236 | 0.264512 | 5.984913 | 70035 |
| estimate_xmins | v12_player_minutes.py:763 | 0.015094 | 5.514552 | 22621 |
| estimate_player_minutes | v12_player_minutes.py:654 | 0.633812 | 5.499459 | 22621 |

_Cumulative time is inclusive. Child-process internals are not captured by parent cProfile._

## P1_2B_PACKAGE_COMBINE / PACKAGE_COMBINE

Profile status: **AVAILABLE**

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| <lambda> | v12_integrated_report_runner.py:2751 | 0.000030 | 5.248703 | 1 |
| combine_package_utility_surfaces | v12_package_utility.py:1791 | 0.033734 | 5.248673 | 1 |
| deepcopy | copy.py:118 | 2.531549 | 5.189661 | 3132034 |
| _deepcopy_dict | copy.py:217 | 0.799321 | 5.184423 | 183974 |
| _deepcopy_list | copy.py:191 | 0.186138 | 3.820756 | 77675 |
| <method 'get' of 'dict' objects> | ~:0 | 0.905320 | 0.905320 | 6298834 |
| <built-in method builtins.id> | ~:0 | 0.349744 | 0.349744 | 3657378 |
| _deepcopy_atomic | copy.py:172 | 0.195899 | 0.195899 | 2870385 |
| _keep_alive | copy.py:231 | 0.113102 | 0.178967 | 261649 |
| <method 'append' of 'list' objects> | ~:0 | 0.086229 | 0.086229 | 672602 |
| <method 'items' of 'dict' objects> | ~:0 | 0.030734 | 0.030734 | 183974 |
| _qualifies_change | v12_package_utility.py:695 | 0.003676 | 0.007090 | 2043 |
| <built-in method builtins.isinstance> | ~:0 | 0.002219 | 0.006903 | 6138 |
| __instancecheck__ | typing.py:1221 | 0.000988 | 0.005509 | 2044 |
| __subclasscheck__ | typing.py:1492 | 0.001239 | 0.004521 | 2044 |
| _frontier | v12_package_utility.py:610 | 0.001516 | 0.004506 | 1 |
| <built-in method builtins.all> | ~:0 | 0.000357 | 0.002617 | 2043 |
| <genexpr> | v12_package_utility.py:614 | 0.001389 | 0.002616 | 4088 |
| <built-in method builtins.issubclass> | ~:0 | 0.001097 | 0.002456 | 2044 |
| <built-in method builtins.sorted> | ~:0 | 0.000202 | 0.001678 | 1 |
| <genexpr> | v12_package_utility.py:1914 | 0.000892 | 0.001476 | 2044 |
| __subclasscheck__ | <frozen abc>:121 | 0.000524 | 0.001359 | 2044 |
| <built-in method builtins.any> | ~:0 | 0.000395 | 0.001262 | 2043 |
| <genexpr> | v12_package_utility.py:700 | 0.000858 | 0.001244 | 4084 |
| <built-in method _abc._abc_subclasscheck> | ~:0 | 0.000835 | 0.000835 | 2044 |

_Cumulative time is inclusive. Child-process internals are not captured by parent cProfile._

## P1_4_MONTE_CARLO / MONTE_CARLO

Profile status: **AVAILABLE**

| Function | File | Internal s | Cumulative s | Calls |
|---|---|---:|---:|---:|
| <lambda> | v12_integrated_report_runner.py:2793 | 0.001620 | 39.875287 | 1 |
| run_package_monte_carlo | v12_monte_carlo.py:3234 | 0.005523 | 29.027408 | 1 |
| run_correlated_monte_carlo | v12_monte_carlo.py:2833 | 0.001669 | 29.012272 | 1 |
| _chain_from_iterable_of_lists | process.py:630 | 0.000138 | 20.831653 | 5 |
| _simulate_route_arrays | v12_monte_carlo.py:2522 | 0.000892 | 20.815484 | 1 |
| _simulate_route_arrays_parallel | v12_monte_carlo.py:2409 | 0.024271 | 20.814587 | 1 |
| __exit__ | _base.py:646 | 0.000008 | 20.750010 | 1 |
| shutdown | process.py:856 | 0.000194 | 20.750002 | 1 |
| join | threading.py:1117 | 0.000034 | 20.749711 | 2 |
| _wait_for_tstate_lock | threading.py:1155 | 0.000115 | 20.749641 | 2 |
| <method 'acquire' of '_thread.lock' objects> | ~:0 | 0.000674 | 20.714951 | 50 |
| _bootstrap | threading.py:1018 | 0.000023 | 20.714724 | 2 |
| _bootstrap_inner | threading.py:1058 | 0.000028 | 20.714697 | 2 |
| run | process.py:339 | 0.000049 | 20.714581 | 1 |
| join_executor_internals | process.py:568 | 0.000007 | 20.714532 | 1 |
| _join_executor_internals | process.py:572 | 0.000050 | 20.714523 | 1 |
| __call__ | util.py:208 | 0.000085 | 20.647528 | 6 |
| join_thread | queues.py:147 | 0.000013 | 20.647467 | 1 |
| _finalize_join | queues.py:214 | 0.000038 | 20.647317 | 1 |
| wait_result_broken_or_wakeup | process.py:414 | 0.000103 | 20.644212 | 6 |
| wait | connection.py:1122 | 0.000225 | 20.509666 | 17 |
| select | selectors.py:402 | 0.000121 | 20.508851 | 17 |
| <method 'poll' of 'select.poll' objects> | ~:0 | 20.508698 | 20.508698 | 17 |
| result_iterator | _base.py:612 | 0.000090 | 20.460019 | 5 |
| dumps | __init__.py:183 | 0.000072 | 14.864398 | 13 |

_Cumulative time is inclusive. Child-process internals are not captured by parent cProfile._
