# Evidence metadata
source: tests at PR #668 head
commit_sha: 03abbdd9e4a1f662d4bb92f588808247d8790892
timestamp_utc: 2026-09-23T13:38:47Z
status: AVAILABLE

`tests/test_lineup_distributional_optimizer.py::test_p17_primed_player_surfaces_are_exactly_output_equivalent` line 1251
`tests/test_lineup_distributional_optimizer.py::test_p17_vectorized_550_xi_kernel_is_exact_scalar_equivalent` line 1413
`tests/test_lineup_distributional_optimizer.py::test_p17_vectorized_kernel_randomized_surface_equivalence` line 1427
`tests/test_lineup_distributional_optimizer.py::test_p17_cross_route_batch_matches_scalar_one_transfer_families` line 1514
`tests/test_lineup_distributional_optimizer.py::test_p17_core14_family_kernel_matches_scalar_across_positions_and_five_gw` line 1636
`tests/test_lineup_distributional_optimizer.py::test_p17_cross_route_batch_2043_routes_five_gw_under_ten_seconds` line 1731
`tests/test_lineup_distributional_optimizer.py::test_p17_lazy_lexicographic_preserves_first_tie_and_skips_later_keys` line 1800
`tests/test_lineup_distributional_optimizer.py::test_p17_lazy_lexicographic_resolves_adversarial_ties_in_first_order` line 1821
`tests/test_lineup_distributional_optimizer.py::test_p17_rounding_boundary_is_non_vacuous_and_matches_scalar_bench` line 1844

Comparison semantics observed:
- exact structural equality: selected/best alternative/formation/close-call/alternatives in scalar-equivalence helpers;
- numeric autosub comparison includes `pytest.approx(..., abs=1e-12)` where explicitly used;
- end-to-end rounding-boundary test compares batch/scalar bench results after non-vacuous ULP-sensitive perturbation.

Boundary-case presence:
- reserve GK: AVAILABLE at lines 238 and 663.
- p=1 DNP: AVAILABLE at line 245 (`test_04_starter_dnp_triggers_autosub`).
- p=0 DNP with p=1 regular cameo: AVAILABLE at line 258 (`test_05_regular_cameo_blocks_autosub`).
- generic adversarial lexicographic tie ordering: AVAILABLE at lines 1800 and 1821.
- rounding-boundary/ULP-sensitive scalar-equivalence case: AVAILABLE at line 1844.
- dedicated named tie-captain/vice case: NOT FOUND.
- dedicated named tie-bench-order case: NOT FOUND.
