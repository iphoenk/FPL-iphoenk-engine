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
from src.models import projection_components as legacy
from src.models.historical_projection import build as build_projection

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = json.loads(
    (ROOT / "tests" / "fixtures" / "player_events_golden.json").read_text(
        encoding="utf-8"
    )
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
    assert out["aggregate"]["quantiles"] is None


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
    assert "package_optimizer" not in source
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
