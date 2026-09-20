from __future__ import annotations

import ast
from functools import lru_cache
import math
from pathlib import Path

import numpy as np
import pytest

from src.engines.canonical_decision_methodology import CANONICAL_WEIGHTS
from src.engines.v12_monte_carlo import (
    MonteCarloError,
    _projection_map,
    _resolve_route_chunk,
    attach_monte_carlo_to_package_utility,
    correlation_structure_diagnostic,
    crn_variance_benchmark,
    legacy_simulation_inventory,
    load_config,
    mc_invocation_policy,
    package_route_definitions,
    run_correlated_monte_carlo,
    run_package_monte_carlo,
    sample_state_minutes,
)
from src.engines.v12_monte_carlo_acceptance import (
    ACTUAL_PATHS,
    INPUT_SNAPSHOT_ID,
    SEED,
    build_acceptance_fixture,
)


@lru_cache(maxsize=1)
def _fixture():
    return build_acceptance_fixture()


@lru_cache(maxsize=1)
def _routes():
    _, package = _fixture()
    return package_route_definitions(package, route_ids=["R1"])


@lru_cache(maxsize=1)
def _diag():
    projections, _ = _fixture()
    return run_correlated_monte_carlo(
        projections,
        _routes(),
        actual_paths=60_000,
        seed=424242,
        input_snapshot_id="P1_4_DIAGNOSTIC_V1",
        canonical=False,
        horizons=(1,),
        selected_route_id="R1",
        generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"fixture": "2026-09-20T01:09:04Z"},
    )


@lru_cache(maxsize=1)
def _diag_seed2():
    projections, _ = _fixture()
    return run_correlated_monte_carlo(
        projections,
        _routes(),
        actual_paths=60_000,
        seed=424243,
        input_snapshot_id="P1_4_DIAGNOSTIC_V1",
        canonical=False,
        horizons=(1,),
        selected_route_id="R1",
        generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"fixture": "2026-09-20T01:09:04Z"},
    )


@lru_cache(maxsize=1)
def _multi():
    projections, _ = _fixture()
    return run_correlated_monte_carlo(
        projections,
        _routes(),
        actual_paths=8_000,
        seed=515151,
        input_snapshot_id="P1_4_MULTI_HORIZON_DIAGNOSTIC",
        canonical=False,
        horizons=(1, 3, 5),
        selected_route_id="R1",
        generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"fixture": "2026-09-20T01:09:04Z"},
    )


@lru_cache(maxsize=1)
def _rental():
    projections, package = _fixture()
    package = dict(package)
    package["routes"] = [dict(row) for row in package["routes"]]
    for row in package["routes"]:
        if row["route_id"] == "R1":
            row["rental"] = {"is_rental": True}
    return run_package_monte_carlo(
        projections,
        package,
        actual_paths=5_000,
        seed=616161,
        input_snapshot_id="P1_4_RENTAL_DIAGNOSTIC",
        route_ids=["R1"],
        canonical=False,
        generated_at="2026-09-20T01:09:04Z",
    )


@lru_cache(maxsize=1)
def _crn():
    projections, _ = _fixture()
    hold, change = _routes()
    return crn_variance_benchmark(
        projections,
        change,
        hold,
        seed=717171,
        replications=8,
        paths_per_replication=3000,
        horizon=1,
    )


def _player(element: int) -> dict:
    projections, _ = _fixture()
    return next(row for row in projections["players"] if row["element"] == element)


def _fixture_event(element: int, gw: int = 6) -> dict:
    p = _player(element)
    row = next(row for row in p["xpts_by_gw"] if row["gw"] == gw)
    return row["fixtures"][0]


def _manual_world(n: int = 4):
    projections, _ = _fixture()
    pmap = _projection_map(projections)
    hold = _routes()[0]["per_gw"][0]
    ids = hold["starting_xi"] + hold["bench_order"] + [hold["bench_gk"]]
    world = {
        element: {
            "points": np.ones(n, dtype=float),
            "appeared": np.ones(n, dtype=bool),
        }
        for element in ids
    }
    return pmap, hold, world


def test_01_same_seed_same_input_same_output_fingerprint():
    projections, _ = _fixture()
    one = run_correlated_monte_carlo(
        projections, _routes(), actual_paths=4000, seed=111,
        input_snapshot_id="REPRO", canonical=False, horizons=(1,),
        selected_route_id="R1", generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"fixture": "2026-09-20T01:09:04Z"},
    )
    two = run_correlated_monte_carlo(
        projections, _routes(), actual_paths=4000, seed=111,
        input_snapshot_id="REPRO", canonical=False, horizons=(1,),
        selected_route_id="R1", generated_at="2026-09-20T01:09:04Z",
        factual_snapshot_timestamps={"fixture": "2026-09-20T01:09:04Z"},
    )
    assert one["output_fingerprint"] == two["output_fingerprint"]
    assert one["metrics"] == two["metrics"]


def test_02_different_seed_changes_paths_but_aggregate_is_compatible():
    a, b = _diag(), _diag_seed2()
    assert a["output_fingerprint"] != b["output_fingerprint"]
    ma = a["metrics"]["R1"]["1"]["mean_difference_vs_hold"]
    mb = b["metrics"]["R1"]["1"]["mean_difference_vs_hold"]
    assert abs(ma - mb) < 0.20


def test_03_canonical_rejects_less_than_500k():
    projections, _ = _fixture()
    with pytest.raises(MonteCarloError):
        run_correlated_monte_carlo(
            projections, _routes(), actual_paths=499_999, seed=1,
            input_snapshot_id="BAD", canonical=True, horizons=(1,),
        )


def test_04_diagnostic_under_500k_cannot_claim_canonical():
    result = _diag()
    assert result["actual_paths"] == 60_000
    assert result["canonical_pass"] is False
    assert result["status"] == "DIAGNOSTIC"
    assert result["report_must_not_label_mc_canonical"] is True


def test_05_actual_path_count_exactly_recorded():
    assert _diag()["actual_paths"] == 60_000


def test_06_start_frequency_reconciles_p1_1():
    actual = _diag()["sampling_diagnostics"]["state_frequencies"]["9:gw6"]["START"]
    assert actual == pytest.approx(0.62, abs=0.015)


def test_07_regular_cameo_frequency_reconciles_p1_1():
    actual = _diag()["sampling_diagnostics"]["state_frequencies"]["9:gw6"]["REGULAR_CAMEO"]
    assert actual == pytest.approx(0.16, abs=0.012)


def test_08_late_cameo_frequency_reconciles_p1_1():
    actual = _diag()["sampling_diagnostics"]["state_frequencies"]["9:gw6"]["LATE_CAMEO"]
    assert actual == pytest.approx(0.12, abs=0.012)


def test_09_dnp_frequency_reconciles_p1_1():
    actual = _diag()["sampling_diagnostics"]["state_frequencies"]["9:gw6"]["ZERO_MINUTES"]
    assert actual == pytest.approx(0.10, abs=0.012)


@lru_cache(maxsize=1)
def _minute_diag():
    return sample_state_minutes(_player(9), actual_paths=80_000, seed=919191)


def test_10_state_minutes_start_semantics():
    assert _minute_diag()["minutes_mean_by_state"]["START"] == pytest.approx(78.0, abs=0.5)


def test_11_goal_marginal_recovers_p1_3_expected_process():
    target = _fixture_event(16)["events"]["goals"]["expected_count"]
    actual = _diag()["sampling_diagnostics"]["event_means"]["16:gw6"]["goals"]
    assert actual == pytest.approx(target, abs=0.02)


def test_12_assist_marginal_recovers_p1_3_expected_process():
    target = _fixture_event(16)["events"]["assists"]["expected_count"]
    actual = _diag()["sampling_diagnostics"]["event_means"]["16:gw6"]["assists"]
    assert actual == pytest.approx(target, abs=0.02)


def test_13_clean_sheet_process_reconciles():
    target = _fixture_event(3)["events"]["clean_sheet"]["upstream_probability"]
    actual = _diag()["sampling_diagnostics"]["event_means"]["3:gw6"]["clean_sheets"]
    assert actual == pytest.approx(target, abs=0.012)


def test_14_defcon_frequency_reconciles():
    target = _fixture_event(3)["events"]["defcon"]["P_threshold"]
    actual = _diag()["sampling_diagnostics"]["event_means"]["3:gw6"]["defcon_hits"]
    assert actual == pytest.approx(target, abs=0.015)


def test_15_gk_save_process_reconciles():
    target = _fixture_event(1)["events"]["saves"]["expected_count"]
    actual = _diag()["sampling_diagnostics"]["event_means"]["1:gw6"]["saves"]
    assert actual == pytest.approx(target, abs=0.05)


def test_16_shared_team_factor_produces_positive_dependence():
    diag = correlation_structure_diagnostic(seed=1616, actual_paths=80_000)
    assert diag["same_team_intensity_correlation"] > 0.99


def test_17_opponent_attack_clean_sheet_interaction_is_negative():
    diag = correlation_structure_diagnostic(seed=1717, actual_paths=80_000)
    assert diag["opponent_attack_vs_clean_sheet_correlation"] < -0.10


def test_18_unsupported_correlations_are_explicit_not_modelled():
    corr = load_config()["correlation"]
    assert corr["availability_cross_player"] == "NOT_MODELLED"
    assert corr["injury_cluster"] == "NOT_MODELLED"
    assert corr["manager_rotation_cluster"] == "NOT_MODELLED"


def test_19_correlation_model_is_versioned():
    result = _diag()
    assert result["correlation_model_version"] == "P1_4_SHARED_MATCH_TEAM_FACTORS_V1"


def test_20_hold_and_route_share_crn_world():
    result = _diag()
    assert result["common_random_numbers"] is True
    assert set(result["route_ids"]) == {"HOLD", "R1"}


def test_21_crn_expected_difference_not_biased():
    bench = _crn()
    assert bench["expected_difference_statistically_compatible"] is True


def test_22_crn_variance_benchmark_validates_benefit():
    bench = _crn()
    assert bench["variance_reduced_or_not_materially_increased"] is True
    assert bench["variance_ratio_crn_over_independent"] <= 1.05


def test_23_starter_dnp_triggers_outfield_autosub_pathwise():
    pmap, lineup, world = _manual_world()
    world[9]["appeared"][0] = False
    world[9]["points"][0] = 0.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["outfield_autosub"][0]) is True


def test_24_regular_cameo_blocks_autosub():
    pmap, lineup, world = _manual_world()
    world[9]["appeared"][0] = True
    world[9]["points"][0] = 1.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["outfield_autosub"][0]) is False


def test_25_late_cameo_blocks_autosub():
    pmap, lineup, world = _manual_world()
    world[9]["appeared"][1] = True
    world[9]["points"][1] = 1.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["outfield_autosub"][1]) is False


def test_26_reserve_gk_substitution_exact():
    pmap, lineup, world = _manual_world()
    world[1]["appeared"][0] = False
    world[1]["points"][0] = 0.0
    world[2]["appeared"][0] = True
    world[2]["points"][0] = 5.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["gk_autosub"][0]) is True


def test_27_captain_dnp_triggers_vice():
    pmap, lineup, world = _manual_world()
    cap, vice = lineup["captain"], lineup["vice_captain"]
    world[cap]["appeared"][0] = False
    world[cap]["points"][0] = 0.0
    world[vice]["appeared"][0] = True
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["captain_takeover"][0]) is True


def test_28_captain_cameo_blocks_vice():
    pmap, lineup, world = _manual_world()
    cap = lineup["captain"]
    world[cap]["appeared"][0] = True
    world[cap]["points"][0] = 1.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["captain_takeover"][0]) is False


def test_29_captain_late_cameo_blocks_vice():
    pmap, lineup, world = _manual_world()
    cap = lineup["captain"]
    world[cap]["appeared"][2] = True
    world[cap]["points"][2] = 1.0
    resolved = _resolve_route_chunk(lineup, pmap, world)
    assert bool(resolved["captain_takeover"][2]) is False


def test_30_route_economics_applied_exactly():
    row = _diag()["metrics"]["R1"]["1"]
    assert row["execution_cost_points"] == pytest.approx(0.20)
    assert row["mean_gross_points"] - row["mean_net_utility"] == pytest.approx(0.20, abs=1e-12)


def test_31_hold_always_represented():
    assert "HOLD" in _diag()["metrics"]


def test_32_quantiles_are_internally_coherent():
    row = _diag()["metrics"]["R1"]["1"]
    assert row["p10"] <= row["p25"] <= row["p50"] <= row["p75"] <= row["p90"]


def test_33_outperform_probability_in_unit_interval():
    p = _diag()["metrics"]["R1"]["1"]["p_route_gt_hold"]
    assert 0.0 <= p <= 1.0


def test_34_expected_regret_nonnegative():
    for rid in ("HOLD", "R1"):
        assert _diag()["metrics"][rid]["1"]["expected_regret"] >= 0.0


def test_35_progressive_convergence_checkpoints_emitted():
    checkpoints = _diag()["convergence_evidence"]["checkpoints"]
    assert checkpoints[0]["paths"] == 50_000
    assert checkpoints[-1]["paths"] == 60_000
    assert all("mean_delta_mcse" in row for row in checkpoints)


def test_36_acceptance_contract_requires_real_500k():
    assert ACTUAL_PATHS == 500_000
    assert SEED == 14092026
    assert INPUT_SNAPSHOT_ID == "P1_4_ACCEPTANCE_FIXTURE_V1"


def test_37_output_fingerprint_is_sha256():
    fp = _diag()["output_fingerprint"]
    assert len(fp) == 64
    int(fp, 16)


def test_38_code_existence_does_not_claim_execution():
    projections, package = _fixture()
    attached = attach_monte_carlo_to_package_utility(
        package,
        {
            "execution_state": "PARTIAL",
            "actual_paths": 10_000,
            "canonical_pass": False,
            "degradation_reason": "DIAGNOSTIC",
        },
    )
    assert attached["monte_carlo_canonical_pass"] is False


def test_39_raw_v6_payload_not_duplicated():
    evidence = _diag()["model_evidence_binding"]
    assert evidence["raw_v6_payload_duplicated"] is False
    assert _diag()["governance"]["raw_v6_payload_duplicated"] is False


def test_40_no_v6_or_runtime_v3_import_added():
    path = Path("src/engines/v12_monte_carlo.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    assert not any(name.startswith("src.runtime_v6") for name in imports)
    assert not any(name.startswith("src.runtime_v3") for name in imports)


def test_41_legacy_gaussian_remains_noncanonical():
    inventory = legacy_simulation_inventory()
    assert inventory
    assert all(row["canonical"] is False for row in inventory)
    assert all(row["classification"] in {"NEGATIVE_ORACLE", "HISTORICAL_BASELINE", "NON_CANONICAL"} for row in inventory)


def test_42_legacy_simulator_not_promoted_by_path_count():
    inventory = legacy_simulation_inventory()
    assert any("independent_normal" in row["method"] for row in inventory)


def test_43_weights_20_25_30_25_unchanged():
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }


def test_44_p1_1_read_only():
    assert load_config()["governance"]["p1_1_read_only"] is True


def test_45_p1_3_read_only():
    assert load_config()["governance"]["p1_3_read_only"] is True


def test_46_p1_6_read_only():
    assert load_config()["governance"]["p1_6_read_only"] is True


def test_47_p1_7_read_only():
    assert load_config()["governance"]["p1_7_read_only"] is True


def test_48_p1_2_read_only():
    assert load_config()["governance"]["p1_2_read_only"] is True


def test_49_mini_league_overlay_not_consumed():
    assert load_config()["governance"]["mini_league_forbidden"] is True
    assert _diag()["governance"]["mini_league_consumed"] is False


def test_50_multi_horizon_remains_separate():
    result = _multi()
    assert set(result["metrics"]["R1"]) == {"1", "3", "5"}
    assert result["horizons"] == [1, 3, 5]


def test_51_rental_exposes_2gw_without_precommitted_exit():
    result = _rental()
    assert result["horizons"] == [1, 2, 3, 5]
    assert result["package_integration"]["rental_exit_auto_assumed"] is False


def test_52_temporal_dependence_is_explicitly_limited():
    assert (
        load_config()["correlation"]["cross_gw_temporal_state"]
        == "CONDITIONALLY_INDEPENDENT_GIVEN_CURRENT_MODEL"
    )


def test_53_future_price_distribution_not_fabricated():
    assert load_config()["correlation"]["future_price_process"] == "NOT_MODELLED"


def test_54_tail_definitions_are_numeric_contracts():
    tails = _diag()["tail_definitions"]
    assert tails["downside_probability"].startswith("P(")
    assert tails["material_upside_threshold_points"] == 5.0


def test_55_rng_provenance_complete():
    result = _diag()
    assert result["seed"] == 424242
    assert result["rng_implementation"] == "numpy.random.Generator"
    assert result["rng_bit_generator"] == "PCG64"
    assert result["model_evidence_binding"]["rng_version"]


def test_56_model_evidence_is_non_authoritative():
    evidence = _diag()["model_evidence_binding"]
    assert evidence["authority"] is False
    assert len(evidence["run_fingerprint"]) == 64
    assert len(evidence["output_fingerprint"]) == 64


def test_57_invocation_policy_requires_close_route():
    _, package = _fixture()
    decision = mc_invocation_policy(package, route_id="R1")
    assert decision["status"] == "MC_REQUIRED"


def test_58_computational_cost_cannot_silently_skip_required_mc():
    _, package = _fixture()
    decision = mc_invocation_policy(package, route_id="R1")
    assert decision["computational_cost_is_not_skip_reason"] is True


def test_59_hold_route_can_be_mc_not_required():
    _, package = _fixture()
    assert mc_invocation_policy(package, route_id="HOLD")["status"] == "MC_NOT_REQUIRED"


def test_60_performance_evidence_is_recorded_without_affecting_fingerprint():
    perf = _diag()["performance"]
    assert perf["wall_seconds"] > 0.0
    assert perf["path_throughput_per_second"] > 0.0
    assert perf["wall_clock_excluded_from_output_fingerprint"] is True


def test_61_bonus_is_expectation_only_not_random_noise():
    assert (
        load_config()["correlation"]["bonus_stochastic_process"]
        == "NOT_MODELLED_EXPECTATION_ONLY_RESIDUAL"
    )


def test_62_same_team_clean_sheet_state_is_shared():
    assert (
        load_config()["correlation"]["same_team_clean_sheet_dependence"]
        == "ONE_SHARED_BERNOULLI_CLEAN_SHEET_STATE_PER_TEAM_FIXTURE"
    )


def test_63_goal_assist_dependence_consumes_p1_3_structure():
    assert (
        load_config()["correlation"]["within_player_goal_assist"]
        == "P1_3_BIVARIATE_POISSON_SHARED_COMPONENT"
    )


def test_64_diagnostic_status_never_masquerades_as_canonical():
    result = _diag()
    assert result["execution_state"] == "PARTIAL"
    assert result["canonical_pass"] is False


def test_65_hold_vs_route_paired_standard_error_is_reported():
    se = _diag()["metrics"]["R1"]["1"]["paired_difference_standard_error"]
    assert se > 0.0


def test_66_pairwise_a_vs_b_probability_is_reported():
    pair = _diag()["paired_outputs"]["HOLD__VS__R1__H1"]
    assert 0.0 <= pair["p_a_gt_b"] <= 1.0


def test_67_package_mc_keeps_transfer_economics_deterministic():
    result = _rental()
    assert result["package_integration"]["transfer_economics_deterministic"] is True
    assert result["package_integration"]["future_price_stochastic"] is False


def test_68_package_mc_fresh_lineup_reoptimization_semantics():
    result = _rental()
    assert result["package_integration"]["fresh_lineup_reoptimization_per_gw"] is True
    assert result["package_integration"]["future_transfer_reoptimization"] == "NOT_PRECOMMITTED_NOT_SIMULATED"


def test_69_invalid_executed_lt500k_attachment_fails_closed():
    _, package = _fixture()
    with pytest.raises(MonteCarloError):
        attach_monte_carlo_to_package_utility(
            package,
            {"execution_state": "EXECUTED", "actual_paths": 499_999, "canonical_pass": True},
        )


def test_70_no_nan_or_infinite_core_metrics():
    row = _diag()["metrics"]["R1"]["1"]
    numeric = [
        row["mean_gross_points"], row["mean_net_utility"], row["median"],
        row["standard_deviation"], row["p10"], row["p90"],
        row["mean_difference_vs_hold"], row["paired_difference_standard_error"],
    ]
    assert all(math.isfinite(float(value)) for value in numeric)
