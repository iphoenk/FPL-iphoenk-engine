from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.v12_model_evidence import (
    build_model_run_binding,
    prediction_calibration_metrics,
)
from src.engines.v12_player_events import (
    aggregate_gameweek,
    build_posterior_rates,
    load_event_config,
    project_player_fixture,
)
from src.engines.v12_player_minutes import estimate_player_minutes
from src.engines.v12_position_probability_components import (
    _gk_save_pmf_from_model,
    _gk_sot_save_model,
    _set_piece_process,
    build_dynamic_matchup_vector,
    convolve_point_distributions,
    estimate_live_threshold_probability,
    scoreline_clean_sheet_probabilities,
    select_count_distribution,
    select_scoreline_model,
)
from src.models import projection_components as legacy
from src.models.historical_projection import build as build_projection

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads(
    (ROOT / "tests" / "fixtures" / "player_events_golden.json").read_text(
        encoding="utf-8"
    )
)
P13B_GOLDEN = json.loads(
    (
        ROOT
        / "tests"
        / "fixtures"
        / "player_events_p1_3b_golden.json"
    ).read_text(encoding="utf-8")
)


def _case(name: str):
    return next(row for row in GOLDEN["cases"] if row["name"] == name)


def _rates(case):
    cfg = load_event_config()
    return build_posterior_rates(
        case["player"],
        position_prior=cfg["position_priors"][case["position"]],
        feature=case.get("feature") or {},
    )


def _project(case, *, binding=None, calibration=None):
    return project_player_fixture(
        case["player"],
        case["xmins"],
        case["matchup"],
        home=True,
        rates=_rates(case),
        league_baseline=GOLDEN["league_baseline"],
        model_evidence_binding=binding,
        calibration_summary=calibration,
    )


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda row: row["name"])
def test_A1_frozen_donor_numerical_baseline(case, monkeypatch):
    monkeypatch.setattr(
        legacy,
        "_team_strength_baseline",
        lambda: dict(GOLDEN["league_baseline"]),
    )
    cfg = legacy.load_projection_config()
    position_prior = cfg["position_priors"][case["position"]]
    xg90, _, _ = legacy.robust_attack_rate(
        case["player"],
        "expected_goals",
        position_prior["xg90"],
        cfg["early_season_robust_rates"],
    )
    xa90, _, _ = legacy.robust_attack_rate(
        case["player"],
        "expected_assists",
        position_prior["xa90"],
        cfg["early_season_robust_rates"],
    )
    bonus90, _ = legacy._blended_rate(
        case["player"],
        "bonus",
        position_prior["bonus90"],
        cfg["rate_shrinkage_minutes"],
    )
    saves90, _ = legacy._blended_rate(
        case["player"],
        "saves",
        position_prior["saves90"],
        cfg["rate_shrinkage_minutes"],
    )
    dc = legacy.defensive_contribution_rate_bundle(
        case["player"],
        case.get("feature") or {},
        position_prior["dc90"],
        cfg["rate_shrinkage_minutes"],
    )
    rates = {
        "xg90": xg90,
        "xa90": xa90,
        "bonus90": bonus90,
        "saves90": saves90,
        **dc,
    }
    old = legacy._project_fixture(
        {**case["player"], "position": case["position"]},
        case["xmins"],
        {
            "event": 5,
            "team_h": 1,
            "team_a": 2,
            "home_expected_goals": case["matchup"]["team_expected_goals"],
            "away_expected_goals": 1.0,
            "home_clean_sheet_probability": case["matchup"][
                "clean_sheet_probability"
            ],
            "away_clean_sheet_probability": 0.2,
        },
        True,
        rates,
        bool(case.get("small_sample")),
    )
    expected = case["donor_expected"]
    assert xg90 == pytest.approx(expected["xG90"], abs=1e-6)
    assert xa90 == pytest.approx(expected["xA90"], abs=1e-6)
    assert bonus90 == pytest.approx(expected["bonus90"], abs=1e-6)
    assert saves90 == pytest.approx(expected["saves90"], abs=1e-6)
    assert dc["dc_count90"] == pytest.approx(
        expected["DefCon_rate"], abs=1e-6
    )
    assert old["mean"] == pytest.approx(expected["legacy_mean"], abs=0.001)
    assert old["std"] == pytest.approx(expected["legacy_std"], abs=0.001)
    assert old["clean_sheet_probability"] == pytest.approx(
        expected["clean_sheet_probability"], abs=1e-6
    )


def test_A3_DNP_zero_minutes_produces_zero_player_events():
    out = _project(_case("dnp_zero_minutes"))
    assert out["minutes"]["PDNP"] == 1.0
    assert out["aggregate"]["expected_fpl_points"] == 0.0
    assert out["events"]["goals"]["expected_count"] == 0.0
    assert out["events"]["assists"]["expected_count"] == 0.0
    assert out["events"]["defcon"]["expected_fpl_points"] == 0.0
    assert out["events"]["saves"]["expected_fpl_points"] == 0.0
    assert out["events"]["bonus"]["expected_fpl_points"] == 0.0


def test_A3_start_has_more_opportunity_than_cameo_and_late_cameo():
    case = _case("nailed_attacking_mid")
    out = _project(case)
    rows = {
        row["state"]: row
        for row in out["events"]["goals"]["state_conditional"]
    }
    assert rows["START"]["goal_mean"] > rows["REGULAR_CAMEO"]["goal_mean"]
    assert rows["REGULAR_CAMEO"]["goal_mean"] > rows["LATE_CAMEO"]["goal_mean"]


def test_A3_weighted_state_expectations_reconcile_and_variance_is_nonnegative():
    out = _project(_case("uncertain_rotation_mid"))
    rec = out["reconciliation"]
    assert rec["mean_delta"] == pytest.approx(0.0, abs=1e-9)
    assert out["aggregate"]["points_variance"] >= 0.0
    assert out["aggregate"]["points_std"] >= 0.0
    assert out["aggregate"]["canonical_gaussian"] is False
    assert set(out["aggregate"]["quantiles"]) >= {"P10", "P25", "P50", "P75", "P90"}


def test_A4_low_sample_shrinks_to_prior_and_winsorizes_extreme_rate():
    case = _case("low_sample_attacker")
    rates = _rates(case)
    goal = rates["goal"]
    assert goal["winsorized"] is True
    assert goal["observed_rate90"] > goal["bounded_observed_rate90"]
    assert goal["posterior_rate90"] < goal["bounded_observed_rate90"]
    assert goal["shrinkage"] > 0.5
    assert goal["confidence"] == "LOW"


def test_A4_missing_observation_is_not_fabricated_and_historical_prior_is_explicit():
    cfg = load_event_config()
    player = {
        "id": 90,
        "element_type": 3,
        "minutes": 0,
        "expected_goals": None,
        "expected_assists": None,
        "bonus": None,
        "saves": None,
    }
    rates = build_posterior_rates(
        player,
        position_prior=cfg["position_priors"]["MID"],
        historical={
            "attacking_prior_weight": 0.5,
            "xg90": 0.40,
            "xa90": 0.30,
        },
    )
    assert rates["goal"]["observed_rate90"] is None
    assert rates["assist"]["observed_rate90"] is None
    assert rates["goal"]["prior_source"] == "historical_player_prior+position_prior"
    assert rates["historical_attacking_prior_weight"] == 0.5


def test_A5_goal_and_assist_are_state_conditional_poisson_mixtures():
    out = _project(_case("creative_mid"))
    goal = out["events"]["goals"]
    assist = out["events"]["assists"]
    assert goal["distribution"] == "STATE_CONDITIONAL_POISSON_MIXTURE"
    assert assist["distribution"] == "STATE_CONDITIONAL_POISSON_MIXTURE"
    assert 0.0 <= goal["P_at_least_1"] <= 1.0
    assert 0.0 <= assist["P_at_least_1"] <= 1.0
    assert goal["expected_count"] >= 0.0
    assert assist["expected_count"] >= 0.0
    assert out["assumptions"]["cross_player_correlation"] == "NOT_MODELLED_YET"
    assert out["assumptions"]["p1_4_capability_claimed"] is False


def test_A6_clean_sheet_respects_position_and_minutes_threshold():
    defender = _project(_case("strong_cs_def"))
    forward_case = dict(_case("high_xg_fwd"))
    forward = _project(forward_case)
    cameo_case = dict(_case("strong_cs_def"))
    cameo_case["xmins"] = {
        "start_probability": 0.0,
        "bench_probability": 1.0,
        "cameo_probability": 1.0,
        "late_cameo_probability": 0.0,
        "dnp_probability": 0.0,
        "expected_minutes": 20.0,
        "starter_minutes_if_start": 0.0,
        "minutes_std": 0.0,
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {"state": "START", "probability": 0.0, "minutes_mean": 80, "minutes_std": 8},
                {"state": "CAMEO", "probability": 1.0, "minutes_mean": 20, "minutes_std": 4},
                {"state": "LATE_CAMEO", "probability": 0.0, "minutes_mean": 8, "minutes_std": 3},
                {"state": "ZERO_MINUTES", "probability": 0.0, "minutes_mean": 0, "minutes_std": 0},
            ],
        },
    }
    cameo = _project(cameo_case)
    assert defender["events"]["clean_sheet"]["expected_fpl_points"] > 0.0
    assert forward["events"]["clean_sheet"]["expected_fpl_points"] == 0.0
    assert cameo["events"]["clean_sheet"]["expected_fpl_points"] == 0.0


def test_A7_defcon_is_probabilistic_and_rises_with_rate_and_minutes():
    high = _project(_case("defcon_heavy_def"))
    low = _project(_case("subthreshold_defcon_def"))
    assert 0.0 < low["events"]["defcon"]["P_threshold"] < 1.0
    assert high["events"]["defcon"]["P_threshold"] > low["events"]["defcon"]["P_threshold"]
    assert high["events"]["defcon"]["expected_fpl_points"] > low["events"]["defcon"]["expected_fpl_points"]


def test_A8_gk_save_process_is_uncertain_not_saves_divided_by_three():
    out = _project(_case("save_heavy_gk"))
    saves = out["events"]["saves"]
    assert saves["eligible"] is True
    assert saves["expected_count"] > 0.0
    assert saves["points_variance"] > 0.0
    deterministic_false_floor = saves["expected_count"] / 3.0
    assert saves["expected_fpl_points"] != pytest.approx(
        deterministic_false_floor, abs=1e-4
    )


def test_A9_bonus_is_residual_expectation_and_counted_once():
    out = _project(_case("nailed_attacking_mid"))
    bonus = out["events"]["bonus"]
    assert bonus["classification"] == "RESIDUAL_EXPECTATION_COMPONENT"
    assert bonus["independent_stochastic_process"] is False
    assert out["reconciliation"]["bonus_counted_once"] is True
    assert out["reconciliation"]["mean_delta"] == pytest.approx(0.0, abs=1e-9)


def test_A12_good_bad_fixture_adjustment_uses_established_strength_only():
    good = _project(_case("good_fixture_attacker"))
    bad = _project(_case("bad_fixture_attacker"))
    assert good["fixture_attack_multiplier"] > bad["fixture_attack_multiplier"]
    assert good["events"]["goals"]["expected_count"] > bad["events"]["goals"]["expected_count"]
    assert good["assumptions"]["p1_6_tactical_scorer_applied"] is False


def test_A13_multi_fixture_gw_keeps_fixture_identity_and_states_dependency_assumption():
    a = _project(_case("dgw_fixture_a"))
    case_b = dict(_case("dgw_fixture_a"))
    case_b["matchup"] = {
        **case_b["matchup"],
        "fixture": 514,
        "team_expected_goals": 1.1,
        "clean_sheet_probability": 0.31,
    }
    b = _project(case_b)
    gw = aggregate_gameweek([a, b], gw=5)
    assert len(gw["fixtures"]) == 2
    assert a["identity"]["fixture"] != b["identity"]["fixture"]
    assert gw["mean"] == pytest.approx(a["mean"] + b["mean"], abs=0.002)
    assert gw["dependency_assumption"] == "ZERO_CROSS_FIXTURE_COVARIANCE_NOT_MODELLED_YET"


def _binding(snapshot="snap-a", model="events-1", calibration="cal-1"):
    return {
        **build_model_run_binding(
            input_snapshot_id=snapshot,
            factual_snapshot_timestamps={
                "official_fpl": "2026-09-19T12:00:00Z"
            },
            factual_artifact_fingerprints={"official_fpl": "a" * 64},
            deterministic_factual_inputs={"ref": "runtime-data-v6/official_fpl"},
            model_version=model,
            feature_version="player-features-1",
            parameter_version="p1.3-player-events-v1",
            parameters={"config": "player_events.json"},
            calibration_version=calibration,
            calibration_cutoff="2026-09-19T11:00:00Z",
            calibration_parameters={"mode": "diagnostic_only"},
            generated_at="2026-09-19T12:15:00Z",
            planning_gw=5,
            canonical_v12_revision="c" * 64,
        ),
        "authority": False,
        "evidence_only": True,
    }


def test_A14_model_evidence_fingerprints_are_bound_without_raw_v6_duplication():
    a = _project(_case("nailed_attacking_mid"), binding=_binding())
    b = _project(
        _case("nailed_attacking_mid"), binding=_binding(snapshot="snap-b")
    )
    assert a["model_evidence"]["authority"] is False
    assert a["model_evidence"]["raw_v6_payload_persisted"] is False
    assert a["model_evidence"]["output_fingerprint"]
    assert a["model_evidence"]["run_fingerprint"] != b["model_evidence"]["run_fingerprint"]


def test_A15_calibration_hooks_include_event_metrics_without_retuning():
    forecasts = [
        {
            "element": 1,
            "position": "DEF",
            "xpts": 6.0,
            "xmins": 80.0,
            "start_probability": 0.9,
            "dnp_probability": 0.05,
            "clean_sheet_probability": 0.4,
            "goal_probability": 0.25,
            "assist_probability": 0.20,
            "defcon_probability": 0.60,
            "expected_saves": 0.0,
            "xpts_interval": [2.0, 10.0],
        }
    ]
    actuals = [
        {
            "element": 1,
            "points": 8.0,
            "minutes": 90.0,
            "started": 1,
            "dnp": 0,
            "clean_sheet": 1,
            "goals": 1,
            "assists": 0,
            "defcon_hit": 1,
            "saves": 0,
        }
    ]
    metrics = prediction_calibration_metrics(forecasts, actuals)["overall"]
    for key in (
        "xpts_mae",
        "xpts_rmse",
        "goal_brier",
        "assist_brier",
        "clean_sheet_brier",
        "defcon_brier",
        "save_mae",
        "predictive_interval_coverage",
    ):
        assert key in metrics
    out = _project(
        _case("nailed_attacking_mid"),
        calibration={"prediction_sample_size": 1, "overall": metrics},
    )
    assert out["calibration_hook"]["automatic_retuning"] is False
    assert "attacking_return_brier" in out["calibration_hook"]["metrics"]
    assert "fpl_blank_brier" in out["calibration_hook"]["metrics"]
    assert "point_tail_brier" in out["calibration_hook"]["metrics"]
    assert "p10_p90_coverage" in out["calibration_hook"]["metrics"]


def test_A17_historical_projection_switches_to_v12_native_event_owner():
    source = (ROOT / "src" / "models" / "historical_projection.py").read_text(
        encoding="utf-8"
    )
    assert "from src.engines.v12_player_events import" in source
    assert "src.models.projection_components" not in source
    assert "_project_fixture" not in source


def test_A18_no_v6_runtime_v3_monte_carlo_covariance_or_p16_dependency():
    source = (ROOT / "src" / "engines" / "v12_player_events.py").read_text(
        encoding="utf-8"
    )
    assert "src.runtime_v6" not in source
    assert "runtime_v3" not in source
    assert "from src.engines.package_optimizer" not in source
    assert "import src.engines.package_optimizer" not in source
    assert "package_optimizer(" not in source
    assert "simulate_objective" not in source
    assert "tactical_role_context" not in source
    assert '"monte_carlo_applied": true' not in source.lower()
    assert '"cross_player_correlation": "modelled' not in source.lower()
    assert "20/25/30/25" in source or "methodology_weights_20_25_30_25_unchanged" in source


def test_A18_P11_output_integrates_directly_and_is_deterministic():
    player = {
        "id": 99,
        "element_type": 3,
        "team": 1,
        "starts": 4,
        "minutes": 330,
        "status": "a",
        "chance_of_playing_next_round": 100,
        "expected_goals": 1.2,
        "expected_assists": 1.5,
        "bonus": 4,
        "saves": 0,
    }
    minutes = estimate_player_minutes(
        player, {"team_matches_played": 5, "prior_start_probability": 0.8}
    )
    cfg = load_event_config()
    rates = build_posterior_rates(
        player, position_prior=cfg["position_priors"]["MID"]
    )
    matchup = {
        "event": 5,
        "fixture": 999,
        "team_h": 1,
        "team_a": 2,
        "team_expected_goals": 1.4,
        "clean_sheet_probability": 0.3,
    }
    a = project_player_fixture(
        player,
        minutes,
        matchup,
        home=True,
        rates=rates,
        league_baseline={"home_goals": 1.3, "away_goals": 1.3},
    )
    b = project_player_fixture(
        player,
        minutes,
        matchup,
        home=True,
        rates=rates,
        league_baseline={"home_goals": 1.3, "away_goals": 1.3},
    )
    assert a == b
    assert a["minutes"]["finite_state_distribution_reference"].startswith("P1.1")


def test_A18_full_projection_path_preserves_legacy_compatibility_fields():
    bootstrap = {
        "teams": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
        "elements": [
            {
                "id": 1,
                "web_name": "P1",
                "team": 1,
                "element_type": 3,
                "now_cost": 70,
                "status": "a",
                "selected_by_percent": "10",
                "starts": 4,
                "minutes": 330,
                "chance_of_playing_next_round": 100,
                "expected_goals": 1.2,
                "expected_assists": 1.5,
                "bonus": 4,
                "saves": 0,
            }
        ],
    }
    strength = {
        "baseline": {"home_goals": 1.3, "away_goals": 1.3},
        "teams": [{"team_id": 1, "matches_played": 5}, {"team_id": 2, "matches_played": 5}],
        "matchups": [
            {
                "event": 5,
                "kickoff_time": "2026-09-20T12:00:00Z",
                "team_h": 1,
                "team_a": 2,
                "home_expected_goals": 1.4,
                "away_expected_goals": 1.0,
                "home_clean_sheet_probability": 0.35,
                "away_clean_sheet_probability": 0.22,
            }
        ],
    }
    out = build_projection(
        bootstrap,
        strength,
        planning_gw=5,
        prior_payload={"model": "prior", "season": "2025/26", "players": {}},
        horizon=15,
    )
    player = out["players"][0]
    fixture = player["xpts_by_gw"][0]["fixtures"][0]
    assert out["event_model_owner"] == "V12_PLAYER_EVENTS"
    assert {"mean", "std", "components"} <= fixture.keys()
    assert fixture["aggregate"]["canonical_gaussian"] is False
    assert out["governance"]["monte_carlo_applied"] is False



def _p13b_minutes(profile: str) -> dict:
    profiles = {
        "SECURE_90": [
            ("START", 0.96, 86.0, 4.0),
            ("REGULAR_CAMEO", 0.02, 18.0, 5.0),
            ("LATE_CAMEO", 0.01, 7.0, 2.0),
            ("ZERO_MINUTES", 0.01, 0.0, 0.0),
        ],
        "CAMEO_HEAVY": [
            ("START", 0.15, 70.0, 10.0),
            ("REGULAR_CAMEO", 0.55, 22.0, 6.0),
            ("LATE_CAMEO", 0.20, 8.0, 3.0),
            ("ZERO_MINUTES", 0.10, 0.0, 0.0),
        ],
        "ROTATION": [
            ("START", 0.45, 70.0, 12.0),
            ("REGULAR_CAMEO", 0.25, 20.0, 7.0),
            ("LATE_CAMEO", 0.15, 8.0, 3.0),
            ("ZERO_MINUTES", 0.15, 0.0, 0.0),
        ],
    }
    states = profiles[profile]
    mean = sum(probability * minutes for _, probability, minutes, _ in states)
    return {
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {
                    "state": state,
                    "probability": probability,
                    "minutes_mean": minutes,
                    "minutes_std": std,
                }
                for state, probability, minutes, std in states
            ],
        },
        "expected_minutes": mean,
    }


def _p13b_synthetic_projection(name: str):
    row = next(
        scenario
        for scenario in P13B_GOLDEN["scenarios"]
        if scenario["name"] == name
    )
    player = {
        "id": 7000 + P13B_GOLDEN["scenarios"].index(row),
        "element_type": row["element_type"],
        "position": row["position"],
        "minutes": row["season_minutes"],
        "expected_goals": row["expected_goals"],
        "expected_assists": row["expected_assists"],
        "bonus": row["bonus"],
        "saves": row["saves"],
    }
    feature = {}
    if row.get("dc_reconstructed_per90") is not None:
        feature = {
            "advanced_current": {
                "minutes": row["season_minutes"],
                "dc_reconstructed_per90": row["dc_reconstructed_per90"],
                "sample_quality": "ESTABLISHED",
            }
        }
    cfg = load_event_config()
    rates = build_posterior_rates(
        player,
        position_prior=cfg["position_priors"][row["position"]],
        feature=feature,
    )
    matchup = {
        "event": 5,
        "fixture": 9700 + P13B_GOLDEN["scenarios"].index(row),
        "team_h": 1,
        "team_a": 2,
        "opponent": 2,
        "team_expected_goals": row["team_expected_goals"],
        "clean_sheet_probability": row["clean_sheet_probability"],
    }
    return project_player_fixture(
        player,
        _p13b_minutes(row["minutes_profile"]),
        matchup,
        home=True,
        rates=rates,
        league_baseline={"home_goals": 1.3, "away_goals": 1.3},
    )


def test_B01_probability_surface_reconciles_joint_attacking_return():
    out = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    probs = out["event_probabilities"]
    assert 0.0 <= probs["p_goal_return"] <= 1.0
    assert 0.0 <= probs["p_assist_return"] <= 1.0
    assert probs["p_attacking_return"] == pytest.approx(
        1.0 - probs["p_no_attacking_return"], abs=2e-9
    )
    assert probs["p_goal_and_assist"] <= min(
        probs["p_goal_return"], probs["p_assist_return"]
    ) + 1e-9
    assert probs["p_total_ga_ge_1"] == probs["p_attacking_return"]
    assert probs["p_total_ga_ge_2"] >= probs["p_total_ga_ge_3"]


def test_B01b_config_governance_does_not_claim_goal_assist_independence():
    governance = load_event_config()["governance"]
    assert governance["conditional_event_independence_except_shared_minutes"] is False
    assert "GOAL_ASSIST_JOINT" in governance["conditional_factorization_semantics"]


def test_B02_goal_assist_dependence_is_explicit_and_not_silent_independence():
    out = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    probs = out["event_probabilities"]
    independence = 1.0 - (
        1.0 - probs["p_goal_return"]
    ) * (1.0 - probs["p_assist_return"])
    assert out["dependence"]["goal_assist_model"] == "BIVARIATE_POISSON_SHARED_COMPONENT_V1"
    assert out["dependence"]["dependence_parameter"] > 0.0
    assert out["dependence"]["calibration_status"] == "LOW_CONFIDENCE_CONSERVATIVE"
    assert out["dependence"]["calibration_sample_size"] == 0
    assert out["dependence"]["assumptions"]["silent_independence"] is False
    assert probs["p_attacking_return"] < independence


def test_B03_point_pmf_is_normalized_nonnegative_and_deterministic():
    a = _p13b_synthetic_projection("high_xg_low_xa_striker")
    b = _p13b_synthetic_projection("high_xg_low_xa_striker")
    pmf = a["point_distribution"]
    values = list(pmf["probabilities"].values())
    assert sum(values) == pytest.approx(1.0, abs=1e-9)
    assert pmf["sum_probability"] == pytest.approx(1.0, abs=1e-9)
    assert all(value >= 0.0 for value in values)
    assert a == b


def test_B04_pmf_mean_reconciles_to_existing_expectation_plus_bonus_residual():
    out = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    rec = out["reconciliation"]["p1_3b"]
    assert abs(rec["mean_delta"]) <= rec["mean_tolerance"]
    assert rec["pmf_plus_bonus_expected_total"] == pytest.approx(
        out["aggregate"]["expected_fpl_points"], abs=rec["mean_tolerance"]
    )


def test_B05_published_variance_is_pmf_variance_and_bonus_limit_is_truthful():
    out = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    pmf = out["point_distribution"]
    rec = out["reconciliation"]["p1_3b"]
    assert out["aggregate"]["points_variance"] == pytest.approx(
        pmf["variance"], abs=1e-6
    )
    assert rec["variance_reconciled_to_published"] is True
    assert rec["bonus_variance_modelled"] is False
    assert pmf["distribution_completeness"] == "PARTIAL_BONUS_RESIDUAL"
    assert pmf["bonus_incorporation"] == "EXPECTATION_ONLY_NOT_STOCHASTIC"


def test_B06_tail_probabilities_and_quantiles_are_monotonic():
    out = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    tails = out["point_distribution"]["tails"]
    assert tails["ge_5"] >= tails["ge_8"] >= tails["ge_10"] >= tails["ge_12"] >= tails["ge_15"]
    assert all(0.0 <= value <= 1.0 for value in tails.values())
    q = out["point_distribution"]["quantiles"]
    assert q["P10"] <= q["P25"] <= q["P50"] <= q["P75"] <= q["P90"] <= q["P95"]


def test_B07_fpl_blank_is_not_no_attacking_return():
    out = _p13b_synthetic_projection("defender_cs_defcon_route")
    assert out["point_distribution"]["blank_threshold"] == load_event_config()["point_distribution"]["blank"]["threshold"]
    assert out["point_distribution"]["p_fpl_blank"] != pytest.approx(
        out["event_probabilities"]["p_no_attacking_return"], abs=1e-6
    )
    assert "core stochastic" in out["point_distribution"]["blank_definition"].lower()


def test_B08_dnp_is_exact_zero_point_state_and_blank():
    out = _project(_case("dnp_zero_minutes"))
    pmf = out["point_distribution"]
    assert pmf["support"] == [0]
    assert pmf["probabilities"] == {"0": 1.0}
    assert pmf["p_fpl_blank"] == 1.0
    assert out["event_probabilities"]["p_no_attacking_return"] == 1.0


def _fixed_minutes(minutes: float) -> dict:
    return {
        "xmins_distribution": {
            "distribution": "FINITE_STATE_MINUTES_MIXTURE",
            "states": [
                {"state": "START", "probability": 1.0, "minutes_mean": minutes, "minutes_std": 0.0},
                {"state": "REGULAR_CAMEO", "probability": 0.0, "minutes_mean": 20.0, "minutes_std": 0.0},
                {"state": "LATE_CAMEO", "probability": 0.0, "minutes_mean": 8.0, "minutes_std": 0.0},
                {"state": "ZERO_MINUTES", "probability": 0.0, "minutes_mean": 0.0, "minutes_std": 0.0},
            ],
        }
    }


def _fixed_rates(goal_rate: float = 0.4, assist_rate: float = 0.2, *, dc=None, saves=0.0):
    return {
        "goal": {"posterior_rate90": goal_rate},
        "assist": {"posterior_rate90": assist_rate},
        "bonus": {"posterior_rate90": 0.0},
        "saves": {"posterior_rate90": saves, "confidence": "HIGH"},
        "defcon": dc or {
            "eligible": False,
            "threshold": None,
            "points": 0.0,
            "posterior_count_rate90": 0.0,
        },
    }


def test_B09_cameo_and_60_minute_clean_sheet_qualification_are_consistent():
    player = {"id": 8801, "element_type": 2, "position": "DEF"}
    matchup = {
        "event": 5,
        "fixture": 8801,
        "team_h": 1,
        "team_a": 2,
        "team_expected_goals": 1.3,
        "clean_sheet_probability": 0.6,
    }
    at_59 = project_player_fixture(
        player,
        _fixed_minutes(59.0),
        matchup,
        home=True,
        rates=_fixed_rates(0.0, 0.0),
        league_baseline={"home_goals": 1.3, "away_goals": 1.3},
    )
    at_60 = project_player_fixture(
        player,
        _fixed_minutes(60.0),
        matchup,
        home=True,
        rates=_fixed_rates(0.0, 0.0),
        league_baseline={"home_goals": 1.3, "away_goals": 1.3},
    )
    assert at_59["events"]["clean_sheet"]["P_points_awarded"] == 0.0
    assert at_60["events"]["clean_sheet"]["P_points_awarded"] == pytest.approx(0.6)
    assert at_60["point_distribution"]["p_fpl_blank"] < at_59["point_distribution"]["p_fpl_blank"]


def test_B10_goal_scoring_points_remain_position_rule_compliant():
    matchup = {
        "event": 5,
        "fixture": 8810,
        "team_h": 1,
        "team_a": 2,
        "team_expected_goals": 1.3,
        "clean_sheet_probability": 0.0,
    }
    outputs = {}
    for position, element_type in (("DEF", 2), ("MID", 3), ("FWD", 4)):
        outputs[position] = project_player_fixture(
            {"id": 8810 + element_type, "element_type": element_type, "position": position},
            _fixed_minutes(90.0),
            matchup,
            home=True,
            rates=_fixed_rates(0.6, 0.0),
            league_baseline={"home_goals": 1.3, "away_goals": 1.3},
        )
    assert outputs["DEF"]["point_distribution"]["expected_points"] > outputs["MID"]["point_distribution"]["expected_points"] > outputs["FWD"]["point_distribution"]["expected_points"]


def test_B11_defcon_threshold_remains_position_rule_compliant():
    defender = _p13b_synthetic_projection("defender_cs_defcon_route")
    assert defender["events"]["defcon"]["eligible"] is True
    assert defender["events"]["defcon"]["threshold"] == 10
    assert 0.0 <= defender["events"]["defcon"]["P_threshold"] <= 1.0


def test_B12_parameter_uncertainty_is_truthfully_partial_without_monte_carlo():
    out = _p13b_synthetic_projection("high_rate_small_sample_shrinkage")
    assert out["parameter_uncertainty"]["status"] == "PARTIAL"
    assert out["parameter_uncertainty"]["posterior_rate_uncertainty"] == "SHRINKAGE_POINT_ESTIMATE_ONLY"
    assert out["assumptions"]["monte_carlo_applied"] is False


def test_B13_golden_scenarios_cover_all_required_general_archetypes():
    assert P13B_GOLDEN["historical_claim"] is False
    assert {row["name"] for row in P13B_GOLDEN["scenarios"]} == {
        "high_xg_low_xa_striker",
        "balanced_goal_assist_attacker",
        "high_assist_low_goal_creator",
        "low_minute_high_rate_cameo",
        "secure_90_low_event_player",
        "defender_cs_defcon_route",
        "goalkeeper_save_heavy",
        "penalty_taker_generic",
        "set_piece_creator_generic",
        "high_rate_small_sample_shrinkage",
    }


def test_B14_golden_directional_behavior_is_sensible_without_named_players():
    striker = _p13b_synthetic_projection("high_xg_low_xa_striker")
    creator = _p13b_synthetic_projection("high_assist_low_goal_creator")
    balanced = _p13b_synthetic_projection("balanced_goal_assist_attacker")
    low_event = _p13b_synthetic_projection("secure_90_low_event_player")
    cameo = _p13b_synthetic_projection("low_minute_high_rate_cameo")
    secure = _p13b_synthetic_projection("high_xg_low_xa_striker")
    gk = _p13b_synthetic_projection("goalkeeper_save_heavy")
    small = _p13b_synthetic_projection("high_rate_small_sample_shrinkage")

    assert striker["event_probabilities"]["p_goal_return"] > creator["event_probabilities"]["p_goal_return"]
    assert creator["event_probabilities"]["p_assist_return"] > striker["event_probabilities"]["p_assist_return"]
    assert balanced["event_probabilities"]["p_attacking_return"] > low_event["event_probabilities"]["p_attacking_return"]
    assert cameo["minutes"]["xMins"] < secure["minutes"]["xMins"]
    assert gk["events"]["saves"]["expected_count"] > 0.0
    assert small["events"]["goals"]["posterior"]["shrinkage"] > 0.5


def test_B15_calibration_metrics_cover_return_blank_tails_and_quantile_coverage():
    forecasts = [
        {
            "element": 1,
            "position": "MID",
            "xpts": 6.0,
            "xmins": 80.0,
            "start_probability": 0.9,
            "dnp_probability": 0.05,
            "p_attacking_return": 0.55,
            "p_fpl_blank": 0.30,
            "blank_threshold": 2,
            "point_tails": {
                "ge_5": 0.50,
                "ge_8": 0.25,
                "ge_10": 0.15,
                "ge_12": 0.08,
                "ge_15": 0.03,
            },
            "point_quantiles": {"P10": 1, "P90": 12},
        }
    ]
    actuals = [
        {
            "element": 1,
            "points": 8,
            "minutes": 90,
            "started": 1,
            "dnp": 0,
            "goals": 1,
            "assists": 0,
        }
    ]
    metrics = prediction_calibration_metrics(forecasts, actuals)["overall"]
    assert metrics["attacking_return_sample_size"] == 1
    assert metrics["fpl_blank_sample_size"] == 1
    assert metrics["point_tail_sample_size"]["ge_8"] == 1
    assert metrics["p10_p90_sample_size"] == 1


def test_B16_no_named_player_legacy_v6_optimizer_or_mc_dependency():
    source = (
        ROOT / "src" / "engines" / "v12_player_events.py"
    ).read_text(encoding="utf-8").casefold()
    for forbidden in ("barry", "kostoulas", "groß", "gross", "brighton", "arsenal"):
        assert forbidden not in source
    for forbidden in (
        "from src.runtime_v6",
        "import src.runtime_v6",
        "from src.runtime_v3",
        "import src.runtime_v3",
        "from src.runtime_v4",
        "import src.runtime_v4",
        "from src.runtime_v5",
        "import src.runtime_v5",
        "from src.engines.package_optimizer",
        "import src.engines.package_optimizer",
        "from src.engines.monte_carlo",
        "import src.engines.monte_carlo",
        "from src.engines.mini_league",
        "import src.engines.mini_league",
    ):
        assert forbidden not in source


def test_B17_p1_6_formula_contract_is_not_mutated_by_p1_3b():
    tactical_cfg = json.loads(
        (
            ROOT
            / "config"
            / "intelligence"
            / "tactical_role_canonical.json"
        ).read_text(encoding="utf-8")
    )
    event_cfg = load_event_config()
    assert tactical_cfg["parameter_version"] == "p1.6-contextual-role-v2"
    assert event_cfg["governance"]["p1_6_formula_mutated"] is False
    assert "v12_tactical_role" not in (
        ROOT / "src" / "engines" / "v12_player_events.py"
    ).read_text(encoding="utf-8")


def test_B18_key_pass_audit_does_not_create_duplicate_feature():
    cfg = load_event_config()
    audit = cfg["key_pass_semantics_audit"]
    assert audit["canonical_creation_metric"] == "chances_created"
    assert audit["status"] == "NO_DISTINCT_CANONICAL_KEY_PASS_FIELD"
    assert audit["p1_6_formula_changed"] is False
    features = (
        ROOT / "src" / "engines" / "player_features.py"
    ).read_text(encoding="utf-8")
    assert '"chances_created"' in features
    assert '"key_passes"' not in features


def test_B19_multi_gw_contract_keeps_1_3_5_and_does_not_fake_tails():
    cfg = load_event_config()
    assert {1, 3, 5}.issubset(set(cfg["published_horizons"]))
    a = _project(_case("dgw_fixture_a"))
    case_b = dict(_case("dgw_fixture_a"))
    case_b["matchup"] = {
        **case_b["matchup"],
        "fixture": 9914,
        "team_expected_goals": 1.1,
    }
    b = _project(case_b)
    gw = aggregate_gameweek([a, b], gw=5)
    assert gw["distribution_aggregation_status"] == "PARTIAL_CROSS_FIXTURE_DEPENDENCE_NOT_MODELLED"
    assert gw["tail_aggregation_status"].startswith("PARTIAL")
    assert gw["event_probabilities"] is None
    assert gw["point_distribution"] is None


def test_B20_no_genuine_settled_history_is_not_reconstructed_from_hindsight():
    state = json.loads(
        (
            ROOT
            / "control"
            / "fpl_master_v12"
            / "FPL_MASTER_STATE_V12.json"
        ).read_text(encoding="utf-8")
    )
    evidence = state["model_evidence"]
    assert evidence["records"] == {}
    registry = evidence["p1_3b_parameter_registry"]
    assert registry["settled_predeadline_sample_size"] == 0
    assert registry["dependence_status"] == "LOW_CONFIDENCE_CONSERVATIVE"
    assert registry["hindsight_reconstruction_forbidden"] is True



def test_C1_stage2_count_family_selects_overdispersion():
    model = select_count_distribution(
        [0, 0, 0, 1, 1, 2, 3, 12],
        3.5,
        thresholds=(3, 6, 9),
        label="TEST_COUNT",
    )
    assert model["family"] == "NEGATIVE_BINOMIAL"
    assert 0.0 <= model["threshold_probabilities"]["3"] <= 1.0
    assert model["posterior_predictive"]["replicated_variance"] > 0.0


def test_C2_stage2_dynamic_fdr_is_position_specific_and_mechanistic():
    matchup = {
        "home_expected_goals": 2.0,
        "away_expected_goals": 0.9,
        "home_clean_sheet_probability": 0.42,
        "official_fdr_home": 3,
    }
    context = {
        "opponent_high_line": 0.8,
        "opponent_fullback_vulnerability": 0.7,
        "opponent_pressure": 0.8,
    }
    winger = build_dynamic_matchup_vector(
        position="MID",
        role="LW WINGER",
        matchup=matchup,
        home=True,
        current_context=context,
    )
    centre_back = build_dynamic_matchup_vector(
        position="DEF",
        role="CB",
        matchup=matchup,
        home=True,
        current_context=context,
    )
    assert set(winger["vector"]) == {
        "goal",
        "creation",
        "attack",
        "clean_sheet",
        "defcon",
        "save",
        "set_piece",
        "aerial",
        "transition",
        "minutes",
        "bonus",
    }
    assert winger["vector"]["goal"]["multiplier"] != centre_back["vector"]["goal"]["multiplier"]
    assert winger["football_mechanism_interactions"]
    assert winger["official_fdr"]["applied_as_final_matchup"] is False
    assert winger["arbitrary_final_point_bonus"] is False


def test_C3_stage2_scoreline_family_is_selected_by_settled_sample():
    fixtures = [
        {"team_h_score": h, "team_a_score": a}
        for h, a in [
            (1, 0), (0, 0), (2, 1), (1, 1), (3, 1),
            (0, 1), (2, 0), (1, 2), (0, 0), (2, 2),
        ]
    ]
    selection = select_scoreline_model(fixtures)
    assert selection["selected"] in {
        "POISSON", "DIXON_COLES", "BIVARIATE_POISSON"
    }
    assert selection["sample_size"] == len(fixtures)
    cs = scoreline_clean_sheet_probabilities(selection, 1.6, 1.1)
    assert 0.0 <= cs["home_clean_sheet_probability"] <= 1.0
    assert 0.0 <= cs["away_clean_sheet_probability"] <= 1.0


def test_C4_stage2_horizon_distribution_is_true_convolution():
    one = {
        "probabilities": {"2": 0.5, "6": 0.5}
    }
    two = {
        "probabilities": {"1": 0.25, "5": 0.75}
    }
    out = convolve_point_distributions([one, two])
    assert out is not None
    assert out["status"] == "READY_COMPLETE_CONDITIONAL_PMF"
    assert abs(out["sum_probability"] - 1.0) < 1e-9
    assert set(out["support"]) == {3, 7, 11}
    assert out["expected_points"] == pytest.approx(8.0)



def test_C5_stage2_gk_is_sot_then_conditional_save_model():
    rows = [
        {"minutes": 90, "saves": 4, "goals_conceded": 1},
        {"minutes": 90, "saves": 2, "goals_conceded": 2},
        {"minutes": 90, "saves": 6, "goals_conceded": 0},
        {"minutes": 90, "saves": 1, "goals_conceded": 3},
        {"minutes": 90, "saves": 5, "goals_conceded": 1},
    ]
    model = _gk_sot_save_model(
        rows,
        xmins=82.0,
        opponent_volume_multiplier=1.10,
        fallback_save_rate90=3.0,
    )
    assert model["model"] == "GK_SOT_THEN_CONDITIONAL_SAVE_V1"
    assert model["sot_count_model"]["family"] in {
        "POISSON", "NEGATIVE_BINOMIAL"
    }
    assert model["conditional_save_model"]["family"] in {
        "BINOMIAL", "BETA_BINOMIAL"
    }
    assert model["empirical"]["save_percentage"] is not None
    assert model["empirical"]["psxg_xgot"] is None
    assert model["empirical"]["psxg_xgot_status"].startswith("UNAVAILABLE")
    pmf = _gk_save_pmf_from_model(
        model, model["projected_sot_mean"]
    )
    assert abs(sum(pmf.values()) - 1.0) < 1e-9
    assert sum(prob for saves, prob in pmf.items() if saves >= 3) > 0.0


def test_C6_stage2_set_piece_chain_is_probabilistic_not_hardcoded():
    process = _set_piece_process(
        {
            "set_piece_event_rate_per_match": 0.55,
            "set_piece_taker_share": 0.70,
            "set_piece_target_share": 0.30,
            "set_piece_shot_given_involved": 0.45,
            "set_piece_goal_given_shot": 0.20,
        },
        {"lambda_set_piece90": 0.05},
    )
    assert process["status"] == "AVAILABLE_COMPLETE_COMPONENT_CHAIN"
    assert process["P_goal_chain"] is not None
    assert process["P_goal_chain"] > 0.0
    assert process["taker_uncertainty_probabilistic"] is True
    assert process["hardcoded_taker"] is False


def test_C7_stage2_live_threshold_does_not_force_erlang():
    no_timing = estimate_live_threshold_probability(
        current_count=7,
        minute=65,
        threshold=10,
        projected_full_match_mean=11.0,
    )
    assert no_timing["selected_model"] == "CONDITIONAL_COUNT_PROCESS"
    assert no_timing["survival_family_forced"] is False
    assert 0.0 <= no_timing["probability"] <= 1.0

    justified = estimate_live_threshold_probability(
        current_count=7,
        minute=65,
        threshold=10,
        projected_full_match_mean=11.0,
        interarrival_minutes=[1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0, 34.0],
    )
    assert (
        justified["selected_model"]
        == "ERLANG_FROM_EMPIRICAL_EXPONENTIAL_INTERARRIVALS"
    )
    assert justified["erlang_selected_only_if_empirically_justified"] is True


def test_C8_stage2_dynamic_fdr_exposes_governed_tactical_inputs():
    out = build_dynamic_matchup_vector(
        position="FWD",
        role="CENTRAL STRIKER",
        matchup={
            "home_expected_goals": 1.8,
            "home_clean_sheet_probability": 0.35,
            "official_fdr_home": 3,
        },
        home=True,
        current_context={
            "own_team_tactical_state": {
                "nominal_formation": {
                    "state": "OBSERVED_DISTRIBUTION"
                }
            },
            "opponent_team_tactical_state": {
                "press_block": {"state": "UNAVAILABLE"}
            },
            "player_availability": {"available_signal": True},
            "expected_personnel": {"opponent_cb": None},
            "venue": "HOME",
        },
    )
    evidence = out["tactical_input_evidence"]
    assert evidence["own_coach_formation_style"] is not None
    assert evidence["opponent_coach_formation_style"] is not None
    assert evidence["venue"] == "HOME"
    assert evidence["missing_evidence_is_explicit_not_neutral"] is True
