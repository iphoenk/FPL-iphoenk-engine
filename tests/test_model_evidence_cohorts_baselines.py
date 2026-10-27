"""E04 (remaining): cohort disclosure, baseline comparison, position/minutes cohorts and decision ranking metrics.

All additions are diagnostic and additive: no score, weight or rule changes, and nothing here selects a model.
Reuses the canonical fixtures of test_model_evidence_calibration.
"""
from __future__ import annotations

import pytest

from src.engines.v12_model_evidence import (
    aggregate_settled_ledgers,
    decision_ranking_metrics,
    freeze_prediction,
    prediction_calibration_metrics,
    settle_frozen_record,
)
from tests.test_model_evidence_calibration import _actual_rows, _binding, _forecast_rows


def _rows(n=6):
    pos = ["GKP", "DEF", "DEF", "MID", "MID", "FWD"]
    return (
        [{"element": i, "position": pos[i - 1], "xpts": float(i), "xmins": [10, 25, 45, 70, 85, 90][i - 1], "start_probability": 0.5, "dnp_probability": 0.1, "projection_confidence": "HIGH", "evidence_sample_size": 100} for i in range(1, n + 1)],
        [{"element": i, "points": float(i) + (1 if i % 2 else -1), "minutes": [0, 30, 60, 90, 90, 90][i - 1], "started": 1, "dnp": 0} for i in range(1, n + 1)],
    )


def test_cohort_disclosure_names_the_frozen_forecast_as_the_population():
    cohort = prediction_calibration_metrics(_forecast_rows(), _actual_rows())["coverage"]["cohort"]
    assert cohort["basis"] == "FROZEN_FORECAST_PLAYERS"
    assert cohort["players_outside_the_frozen_forecast_are_excluded"] is True
    assert cohort["forecast_count"] == 2 and cohort["settled_count"] == 2


def test_position_cohorts_are_reported_separately_and_sum_to_the_overall_sample():
    f, a = _rows()
    out = prediction_calibration_metrics(f, a)
    by_pos = out["by_position"]
    assert set(by_pos) == {"GKP", "DEF", "MID", "FWD"}
    assert by_pos["DEF"]["sample_size"] == 2 and by_pos["GKP"]["sample_size"] == 1
    assert sum(v["sample_size"] for v in by_pos.values()) == out["overall"]["sample_size"] == 6


def test_minutes_cohorts_use_predicted_minutes_from_the_frozen_forecast_not_actual_minutes():
    f, a = _rows()
    # Actual minutes say player 1 played 0, player 2 played 30; the cohort must follow the forecast (10 and 25 -> LOW).
    by_min = prediction_calibration_metrics(f, a)["by_minutes_cohort"]
    assert by_min["LOW_MINUTES"]["sample_size"] == 2      # xmins 10, 25
    assert by_min["MID_MINUTES"]["sample_size"] == 1      # xmins 45
    assert by_min["HIGH_MINUTES"]["sample_size"] == 3     # xmins 70, 85, 90
    assert by_min["LOW_MINUTES"]["max_predicted_minutes_exclusive"] == 30


def test_missing_position_is_unspecified_never_guessed():
    f, a = _rows()
    f[0] = {k: v for k, v in f[0].items() if k != "position"}
    assert "UNSPECIFIED" in prediction_calibration_metrics(f, a)["by_position"]


def test_baselines_absent_are_reported_as_not_provided_not_as_zero():
    out = prediction_calibration_metrics(*_rows())["baselines"]
    assert out == {"status": "NO_BASELINE_PROVIDED", "comparison_is_diagnostic_only": True}


def test_baseline_comparison_uses_the_same_players_and_declares_no_winner():
    f, a = _rows()
    for row in f:
        row["baseline_xpts"] = {"official_ep": row["xpts"] + 2.0}
    f[5]["baseline_xpts"] = {}  # one player has no official baseline: it must drop out of the baseline subset only
    base = prediction_calibration_metrics(f, a)["baselines"]["official_ep"]
    assert base["sample_size"] == 5
    assert base["xpts_mae"] == pytest.approx(1.8, abs=1e-6)  # errors 1,3,1,3,1 over players 1..5
    assert base["model_xpts_mae_same_players"] == pytest.approx(1.0, abs=1e-6)
    assert base["model_minus_baseline_mae"] == pytest.approx(-0.8, abs=1e-6)
    assert "winner" not in base and "better_model" not in base
    assert base["comparison_is_diagnostic_only"] is True


def test_non_numeric_baseline_values_are_ignored_not_coerced_to_zero():
    f, a = _rows()
    f[0]["baseline_xpts"] = {"form": "n/a"}
    f[1]["baseline_xpts"] = {"form": None}
    assert prediction_calibration_metrics(f, a)["baselines"]["status"] == "NO_BASELINE_PROVIDED"


def test_captain_ranking_metrics_cover_only_frozen_candidates():
    f, a = _rows()
    snap = {"lineup": {"captain": 6, "captain_candidates": [4, 5, 6, 99]}}  # 99 has no forecast or actual
    cap = decision_ranking_metrics(snap, f, a)["captain"]
    assert cap["sample_size"] == 3 and cap["candidates_without_data"] == [99]
    assert cap["xpts_mae"] == pytest.approx(1.0 / 1.0, abs=1e-6)  # |4-3|,|5-6|,|6-5| = 1 each
    assert cap["spearman_rank"] == pytest.approx(0.5, abs=1e-6)  # predicted ranks 1,2,3 vs realised points 3,6,5
    assert cap["chosen_captain_realized_rank"] == 2.0            # captain 6 scored 5: second best of (3,6,5)


def test_captain_ranking_needs_three_candidates_for_a_rank_statistic():
    f, a = _rows()
    cap = decision_ranking_metrics({"lineup": {"captain": 6, "captain_candidates": [5, 6]}}, f, a)["captain"]
    assert cap["sample_size"] == 2 and cap["spearman_rank"] is None
    assert cap["status"] == "INSUFFICIENT_CANDIDATES_FOR_RANK"


def test_transfer_metrics_never_invent_the_exact_hit_cost():
    f, a = _rows()
    snap = {"comparator": {"comparisons": [
        {"player_out": 1, "player_in": 4, "exact_hit_cost": None, "hit_cost_state": "UNAVAILABLE_EXACT_HIT_COST"},
        {"player_out": 2, "player_in": 5, "exact_hit_cost": None},
        {"player_out": 3, "player_in": 6, "exact_hit_cost": None},
    ]}}
    t = decision_ranking_metrics(snap, f, a)["transfer"]
    assert t["pre_hit"]["sample_size"] == 3 and t["pre_hit"]["xpts_delta_mae"] is not None
    assert t["after_hit"] == {"status": "UNAVAILABLE_EXACT_HIT_COST", "sample_size": 0}


def test_transfer_after_hit_uses_only_rows_with_a_numeric_exact_cost():
    f, a = _rows()
    snap = {"comparator": {"comparisons": [
        {"player_out": 1, "player_in": 4, "exact_hit_cost": 4},
        {"player_out": 2, "player_in": 5, "exact_hit_cost": None},
        {"player_out": 3, "player_in": 6, "exact_hit_cost": 0},
    ]}}
    t = decision_ranking_metrics(snap, f, a)["transfer"]
    assert t["after_hit"]["sample_size"] == 2 and t["pre_hit"]["sample_size"] == 3
    # rows 1 and 3: predicted 3-4=-1 vs realized 1-4=-3, and 3-0=3 vs 1-0=1 -> MAE (2+2)/2
    assert t["after_hit"]["net_delta_mae"] == pytest.approx(2.0, abs=1e-6)
    assert t["pre_hit"]["xpts_delta_mae"] == pytest.approx(2.0, abs=1e-6)
    assert t["after_hit"]["hit_cost_subtracted_from_predicted_and_realized"] is True


def test_missing_snapshot_gives_explicit_no_sample_not_zero():
    f, a = _rows()
    out = decision_ranking_metrics(None, f, a)
    assert out["captain"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE" and out["captain"]["sample_size"] == 0
    assert out["transfer"]["pre_hit"]["status"] == "NO_GENUINE_PREDEADLINE_SAMPLE"


def test_settlement_records_ranking_metrics_without_changing_existing_decision_metrics():
    f, a = _rows()
    rec = freeze_prediction(
        model_binding=_binding(), deadline_time="2026-09-19T12:00:00Z", forecast_generated_at="2026-09-19T11:50:00Z",
        frozen_at="2026-09-19T11:55:00Z", forecast_rows=f,
        decision_snapshot={"captured_at": "2026-09-19T11:50:00Z", "lineup": {"captain": 6, "captain_candidates": [4, 5, 6]}},
    )
    settled = settle_frozen_record(rec, actual_rows=a, decision_outcome_evidence={}, event_finished=True, settled_at="2026-09-20T18:00:00Z")
    assert settled["decision_ranking_calibration"]["captain"]["sample_size"] == 3
    assert "transfer_counterfactual_regret" in settled["decision_calibration"]["metrics"]


def test_aggregate_discloses_gameweek_count_and_forbids_model_selection():
    f, a = _rows()
    recs = []
    for gw in (5, 6, 7):
        rec = freeze_prediction(
            model_binding=_binding(planning_gw=gw), deadline_time="2026-09-19T12:00:00Z", forecast_generated_at="2026-09-19T11:50:00Z",
            frozen_at="2026-09-19T11:55:00Z", forecast_rows=f)
        recs.append(settle_frozen_record(rec, actual_rows=a, decision_outcome_evidence={}, event_finished=True, settled_at="2026-09-20T18:00:00Z"))
    agg = aggregate_settled_ledgers(recs)
    assert agg["gameweek_count"] == 3
    assert agg["governance"]["model_selection_from_aggregate_forbidden"] is True
    assert agg["evidence_scope"]["conclusive_model_comparison"] is False
    # Same GW settled twice counts once.
    assert aggregate_settled_ledgers([recs[0], recs[0]])["gameweek_count"] == 1
