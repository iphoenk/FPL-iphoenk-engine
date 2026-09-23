from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from src.engines.canonical_decision_methodology import CANONICAL_WEIGHTS
from src.engines.lineup_governance import build_lineup_decision
from src.engines.v12_lineup_optimizer import (
    LineupOptimizerError,
    _appearance_mask_probabilities,
    _best_captain_vice_pair,
    _dnp_count_distribution,
    _expected_outfield_autosub,
    _lineup_route,
    _resolve_outfield_pattern,
    _resolver_mask_table,
    _route_sort_key,
    build_player_surface,
    compare_legacy_decision,
    enumerate_legal_xi,
    evaluate_bench_order,
    evaluate_captain_vice_pairs,
    freeze_lineup_decision,
    load_config,
    optimize_bench_order,
    optimize_lineup,
    settle_lineup_decision,
)
from src.engines.v12_model_evidence import ModelEvidenceError
from src.rules import LINEUP_RULES

ROOT = Path(__file__).resolve().parents[1]
GW = 6
GENERATED = "2026-09-20T00:00:00Z"


def _pmf(meanish: float, *, blank: float = 0.10, upside: float = 0.20) -> dict[int, float]:
    blank = max(0.0, min(0.8, blank))
    upside = max(0.0, min(0.8 - blank, upside))
    middle = 1.0 - blank - upside
    low = 2
    high = max(8, int(round(meanish + 5)))
    mid = max(3, int(round((meanish - blank * low - upside * high) / max(middle, 1e-9))))
    return {0: blank, mid: middle, high: upside}


def _projection(
    element: int,
    position: str,
    *,
    meanish: float,
    p_start: float = 0.88,
    p_regular: float = 0.05,
    p_late: float = 0.02,
    p_dnp: float = 0.05,
    blank: float = 0.10,
    upside: float = 0.20,
    tactical: float = 60.0,
) -> dict:
    pmf = _pmf(meanish, blank=blank, upside=upside)
    mean = sum(points * probability for points, probability in pmf.items())
    second = sum(points * points * probability for points, probability in pmf.items())
    variance = max(0.0, second - mean * mean)
    probabilities = {str(points): probability for points, probability in pmf.items()}
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": (element % 10) + 1,
        "projection_confidence": "HIGH",
        "xmins": {
            "start_probability": p_start,
            "cameo_probability": p_regular + p_late,
            "late_cameo_probability": p_late,
            "dnp_probability": p_dnp,
            "availability": 1.0 - p_dnp,
            "expected_minutes": 90 * p_start + 18 * p_regular + 7 * p_late,
            "confidence": "HIGH",
            "xmins_distribution": {
                "distribution": "FINITE_STATE_MINUTES_MIXTURE",
                "mean": 90 * p_start + 18 * p_regular + 7 * p_late,
                "std": 15.0,
                "states": [
                    {"state": "START", "probability": p_start, "minutes_mean": 90, "minutes_std": 0},
                    {"state": "REGULAR_CAMEO", "probability": p_regular, "minutes_mean": 18, "minutes_std": 0},
                    {"state": "LATE_CAMEO", "probability": p_late, "minutes_mean": 7, "minutes_std": 0},
                    {"state": "ZERO_MINUTES", "probability": p_dnp, "minutes_mean": 0, "minutes_std": 0},
                ],
            },
        },
        "tactical_role_component": {
            "canonical_tactical_role_score": tactical,
            "confidence": 0.9,
            "canonical_component": {
                "name": "TACTICAL_ROLE",
                "weight": 0.25,
                "weighted_component_points": 0.25 * tactical,
            },
        },
        "xpts_by_gw": [
            {
                "gw": GW,
                "mean": mean,
                "std": variance ** 0.5,
                "points_variance": variance,
                "point_distribution": {
                    "model": "FINITE_STATE_CONDITIONAL_CORE_POINT_PMF_V1",
                    "distribution_completeness": "PARTIAL_BONUS_RESIDUAL",
                    "bonus_incorporation": "EXPECTATION_ONLY_NOT_STOCHASTIC",
                    "probabilities": probabilities,
                },
                "fixtures": [],
            }
        ],
    }


def _squad() -> dict:
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    means = [4.8, 3.9, 5.4, 5.2, 5.0, 4.7, 4.3, 7.4, 7.0, 6.4, 5.8, 4.6, 8.1, 6.7, 5.9]
    players = [
        _projection(
            index + 1,
            position,
            meanish=means[index],
            blank=0.08 + (index % 4) * 0.03,
            upside=0.18 + (index % 3) * 0.04,
            tactical=55 + (index % 6) * 5,
        )
        for index, position in enumerate(positions)
    ]
    return {"planning_gw": GW, "generated_at": GENERATED, "players": players}


def _surfaces(projections: dict | None = None) -> list[dict]:
    payload = projections or _squad()
    return [build_player_surface(row, GW) for row in payload["players"]]


def _direct_surface(
    element: int,
    position: str,
    *,
    mean: float,
    p_dnp: float = 0.0,
    p_cameo: float = 0.0,
    p_late: float = 0.0,
    cond_blank: float = 0.2,
    cond_ge8: float = 0.2,
    cond_ge10: float = 0.1,
) -> dict:
    p_appear = max(0.0, 1.0 - p_dnp)
    return {
        "element": element,
        "name": f"S{element}",
        "position": position,
        "team_id": element,
        "xpts_mean": mean,
        "xpts_variance": 2.0,
        "xpts_std": 2.0 ** 0.5,
        "distributional_utility": mean,
        "expected_shortfall": cond_blank,
        "expected_excess_ge_8": cond_ge8,
        "p_fpl_blank": min(1.0, p_dnp + p_appear * cond_blank),
        "p_points_ge_8": p_appear * cond_ge8,
        "p_points_ge_10": p_appear * cond_ge10,
        "states": {
            "START": 1.0 - p_dnp - p_cameo,
            "REGULAR_CAMEO": max(0.0, p_cameo - p_late),
            "LATE_CAMEO": p_late,
            "DNP": p_dnp,
            "CAMEO_BLOCKED_AUTOSUB": p_cameo,
        },
        "p_start": 1.0 - p_dnp - p_cameo,
        "p_cameo": p_cameo,
        "p_late_cameo": p_late,
        "p_dnp": p_dnp,
        "p_appearance": p_appear,
        "appearance_conditioned": {
            "expected_points": mean / p_appear if p_appear else 0.0,
            "variance": 1.0,
            "p_fpl_blank": cond_blank,
            "p_points_ge_8": cond_ge8,
            "p_points_ge_10": cond_ge10,
        },
        "tactical_role": {
            "status": "AVAILABLE",
            "score": 60.0,
            "canonical_weight": 0.25,
            "weighted_component_points": 15.0,
        },
        "distribution_status": {"status": "READY"},
        "confidence": "HIGH",
    }


def _starters_343(*, defender_dnp: float = 0.0, forward_dnp: float = 0.0) -> list[dict]:
    rows = [_direct_surface(1, "GK", mean=4.0)]
    element = 2
    for index in range(3):
        rows.append(_direct_surface(element, "DEF", mean=4.0, p_dnp=defender_dnp if index == 0 else 0.0))
        element += 1
    for _ in range(4):
        rows.append(_direct_surface(element, "MID", mean=5.0))
        element += 1
    for index in range(3):
        rows.append(_direct_surface(element, "FWD", mean=5.5, p_dnp=forward_dnp if index == 0 else 0.0))
        element += 1
    return rows


@pytest.fixture(scope="module")
def base_decision():
    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    return optimize_lineup(projections, ids, planning_gw=GW, generated_at=GENERATED)


def test_01_exact_550_legal_xi_for_standard_2_5_5_3_squad():
    legal = enumerate_legal_xi(_surfaces())
    assert len(legal) == 550


def test_02_every_enumerated_xi_has_11_starters_and_legal_formation():
    surfaces = _surfaces()
    for indices in enumerate_legal_xi(surfaces):
        rows = [surfaces[index] for index in indices]
        assert len(rows) == 11
        assert sum(row["position"] == "GK" for row in rows) == 1
        counts = {pos: sum(row["position"] == pos for row in rows) for pos in ("DEF", "MID", "FWD")}
        assert f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}" in set(LINEUP_RULES["legal_formations"])


def test_03_reserve_gk_is_separate_from_outfield_bench(base_decision):
    assert base_decision["bench"]["gk"]["position"] == "GK"
    assert len(base_decision["bench"]["order"]) == 3
    assert all(row["position"] != "GK" for row in base_decision["bench"]["order"])
    assert base_decision["bench"]["distributional_evaluation"]["reserve_gk"]["separate_from_outfield_priority"] is True


def test_04_starter_dnp_triggers_autosub():
    starters = _starters_343(defender_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "DEF", mean=4.0),
        _direct_surface(92, "MID", mean=6.0),
        _direct_surface(93, "FWD", mean=5.0),
    ]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["autosub_probability"] == pytest.approx(1.0)
    assert out["slots"][0]["substitution_probability"] == pytest.approx(1.0)


def test_05_regular_cameo_blocks_autosub():
    starters = _starters_343()
    starters[1] = _direct_surface(2, "DEF", mean=1.0, p_dnp=0.0, p_cameo=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [_direct_surface(91, "DEF", mean=6.0), _direct_surface(92, "MID", mean=5.0), _direct_surface(93, "FWD", mean=5.0)]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["autosub_probability"] == pytest.approx(0.0)
    assert out["expected_blocked_autosub_value"] > 0.0


def test_06_late_cameo_blocks_autosub():
    starters = _starters_343()
    starters[1] = _direct_surface(2, "DEF", mean=0.5, p_dnp=0.0, p_cameo=1.0, p_late=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [_direct_surface(91, "DEF", mean=6.0), _direct_surface(92, "MID", mean=5.0), _direct_surface(93, "FWD", mean=5.0)]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["autosub_probability"] == pytest.approx(0.0)
    assert out["expected_late_cameo_blocked_autosub_value"] > 0.0


def test_07_illegal_outfield_substitution_is_skipped():
    starters = _starters_343(defender_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "MID", mean=9.0),
        _direct_surface(92, "DEF", mean=4.0),
        _direct_surface(93, "FWD", mean=3.0),
    ]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["slots"][0]["substitution_probability"] == pytest.approx(0.0)
    assert out["slots"][1]["substitution_probability"] == pytest.approx(1.0)


def test_08_next_legal_bench_player_is_used():
    starters = _starters_343(defender_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "MID", mean=9.0),
        _direct_surface(92, "DEF", mean=4.0),
        _direct_surface(93, "FWD", mean=3.0),
    ]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["slots"][1]["reach_probability"] == pytest.approx(1.0)
    assert out["expected_autosub_value"] == pytest.approx(4.0)


def test_09_multiple_dnp_are_resolved_globally():
    starters = _starters_343(defender_dnp=1.0, forward_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "MID", mean=6.0),
        _direct_surface(92, "DEF", mean=4.0),
        _direct_surface(93, "FWD", mean=3.0),
    ]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["slots"][0]["substitution_probability"] == pytest.approx(1.0)
    assert out["slots"][1]["substitution_probability"] == pytest.approx(1.0)
    assert out["expected_autosub_value"] == pytest.approx(10.0)


def test_10_bench_reach_probability_respects_upstream_priority():
    starters = _starters_343(defender_dnp=0.5)
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "DEF", mean=5.0, p_dnp=0.5),
        _direct_surface(92, "DEF", mean=4.0),
        _direct_surface(93, "MID", mean=3.0),
    ]
    out = evaluate_bench_order(starters, reserve, bench)
    assert 0.0 < out["slots"][0]["reach_probability"] <= 1.0
    assert out["slots"][1]["reach_probability"] <= out["slots"][0]["reach_probability"]


def test_11_distributional_bench_order_can_differ_from_mean_sort():
    starters = _starters_343(forward_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=3.0)
    high_mean_blank = _direct_surface(91, "MID", mean=5.0, cond_blank=0.95, cond_ge8=0.0)
    lower_mean_upside = _direct_surface(92, "MID", mean=4.95, cond_blank=0.0, cond_ge8=1.0, cond_ge10=0.8)
    third = _direct_surface(93, "DEF", mean=2.0)
    best, _ = optimize_bench_order(starters, reserve, [high_mean_blank, lower_mean_upside, third])
    assert best["order"][0] == lower_mean_upside["element"]
    assert lower_mean_upside["xpts_mean"] < high_mean_blank["xpts_mean"]


def test_12_autosub_option_value_is_nonzero_when_dnp_risk_exists():
    starters = _starters_343(defender_dnp=0.4)
    out = evaluate_bench_order(
        starters,
        _direct_surface(90, "GK", mean=3.0),
        [_direct_surface(91, "DEF", mean=5.0), _direct_surface(92, "MID", mean=4.0), _direct_surface(93, "FWD", mean=4.0)],
    )
    assert out["expected_autosub_value"] > 0.0


def test_13_cameo_blocking_cost_is_nonzero_when_bench_has_value():
    starters = _starters_343()
    starters[1] = _direct_surface(2, "DEF", mean=1.0, p_dnp=0.1, p_cameo=0.5, p_late=0.2)
    out = evaluate_bench_order(
        starters,
        _direct_surface(90, "GK", mean=3.0),
        [_direct_surface(91, "DEF", mean=6.0), _direct_surface(92, "MID", mean=4.0), _direct_surface(93, "FWD", mean=4.0)],
    )
    assert out["expected_blocked_autosub_value"] > 0.0
    assert out["blocked_autosub_probability"] > 0.0


def test_14_secure_starter_can_beat_slightly_higher_mean_cameo_risk():
    projections = _squad()
    mids = [row for row in projections["players"] if row["position"] == "MID"]
    risky, secure = mids[-2], mids[-1]
    risky.update(_projection(risky["element"], "MID", meanish=5.05, p_start=0.35, p_regular=0.45, p_late=0.15, p_dnp=0.05, blank=0.65, upside=0.05))
    secure.update(_projection(secure["element"], "MID", meanish=5.00, p_start=0.94, p_regular=0.02, p_late=0.01, p_dnp=0.03, blank=0.05, upside=0.25))
    decision = optimize_lineup(projections, [row["element"] for row in projections["players"]], generated_at=GENERATED)
    xi = {row["element"] for row in decision["starting_xi"]}
    assert secure["element"] in xi or risky["element"] not in xi


def test_15_captain_dnp_triggers_vice_takeover_probability():
    starters = _starters_343()
    starters[5]["p_dnp"] = 0.20
    starters[5]["p_appearance"] = 0.80
    starters[6]["p_dnp"] = 0.10
    starters[6]["p_appearance"] = 0.90
    pairs = evaluate_captain_vice_pairs(starters)
    pair = next(row for row in pairs if row["captain_element"] == starters[5]["element"] and row["vice_element"] == starters[6]["element"])
    assert pair["vice_takeover_probability"] == pytest.approx(0.18)


def test_16_captain_regular_cameo_blocks_vice_takeover():
    captain = _direct_surface(100, "MID", mean=6.0, p_dnp=0.0, p_cameo=1.0)
    vice = _direct_surface(101, "FWD", mean=7.0)
    others = [_direct_surface(200 + i, "DEF" if i < 3 else "MID", mean=3.0) for i in range(9)]
    starters = [captain, vice] + others
    pairs = evaluate_captain_vice_pairs(starters)
    pair = next(row for row in pairs if row["captain_element"] == 100 and row["vice_element"] == 101)
    assert pair["vice_takeover_probability"] == 0.0
    assert pair["captain_cameo_blocks_vice"] is True


def test_17_captain_late_cameo_blocks_vice_takeover():
    captain = _direct_surface(100, "MID", mean=1.0, p_dnp=0.0, p_cameo=1.0, p_late=1.0)
    vice = _direct_surface(101, "FWD", mean=7.0)
    others = [_direct_surface(200 + i, "DEF" if i < 3 else "MID", mean=3.0) for i in range(9)]
    pair = next(row for row in evaluate_captain_vice_pairs([captain, vice] + others) if row["captain_element"] == 100 and row["vice_element"] == 101)
    assert pair["vice_takeover_probability"] == 0.0
    assert pair["captain_late_cameo_blocks_vice"] is True


def test_18_vice_dnp_produces_no_takeover_multiplier():
    captain = _direct_surface(100, "MID", mean=6.0, p_dnp=0.25)
    vice = _direct_surface(101, "FWD", mean=0.0, p_dnp=1.0)
    others = [_direct_surface(200 + i, "DEF" if i < 3 else "MID", mean=3.0) for i in range(9)]
    pair = next(row for row in evaluate_captain_vice_pairs([captain, vice] + others) if row["captain_element"] == 100 and row["vice_element"] == 101)
    assert pair["vice_takeover_probability"] == 0.0
    assert pair["expected_vice_takeover_value"] == 0.0


def test_19_captain_and_vice_are_evaluated_as_ordered_pairs():
    starters = _starters_343()
    pairs = evaluate_captain_vice_pairs(starters)
    assert len(pairs) == 11 * 10
    assert all(row["captain_element"] != row["vice_element"] for row in pairs)


def test_20_captain_can_differ_from_highest_mean_for_distributional_reason():
    starters = _starters_343()
    high_mean = starters[5]
    high_mean.update({"xpts_mean": 8.0, "expected_shortfall": 7.0, "expected_excess_ge_8": 0.0})
    lower_mean = starters[6]
    lower_mean.update({"xpts_mean": 7.8, "expected_shortfall": 0.0, "expected_excess_ge_8": 4.0})
    pairs = evaluate_captain_vice_pairs(starters)
    assert pairs[0]["captain_element"] == lower_mean["element"]


def test_21_xi_decision_is_not_mean_only(base_decision):
    assert base_decision["governance"]["mean_xpts_is_not_sole_objective"] is True
    assert base_decision["lineup_score"]["distributional_downside"] is not None
    assert base_decision["lineup_score"]["supportable_upside"] is not None


def test_22_uncertainty_tails_are_not_fabricated_when_pmf_missing():
    projection = _projection(999, "MID", meanish=5.0)
    projection["xpts_by_gw"][0].pop("point_distribution")
    surface = build_player_surface(projection, GW)
    assert surface["distribution_status"]["status"] == "PARTIAL_MOMENTS_ONLY"
    assert surface["p_fpl_blank"] is None
    assert surface["p_points_ge_8"] is None


def test_23_covariance_is_not_falsely_claimed(base_decision):
    assert base_decision["lineup_score"]["covariance_status"] == "COVARIANCE_NOT_MODELLED_YET"
    assert base_decision["captain"]["pair"]["covariance_status"] == "COVARIANCE_NOT_MODELLED_YET"


def test_24_p1_1_state_probabilities_are_consumed_exactly():
    projection = _projection(999, "MID", meanish=5.0, p_start=0.60, p_regular=0.20, p_late=0.10, p_dnp=0.10)
    surface = build_player_surface(projection, GW)
    assert surface["states"]["START"] == pytest.approx(0.60)
    assert surface["states"]["REGULAR_CAMEO"] == pytest.approx(0.20)
    assert surface["states"]["LATE_CAMEO"] == pytest.approx(0.10)
    assert surface["states"]["DNP"] == pytest.approx(0.10)
    assert surface["states"]["CAMEO_BLOCKED_AUTOSUB"] == pytest.approx(0.30)


def test_25_p1_3_projection_inputs_are_not_mutated_by_p1_7():
    projections = _squad()
    before = deepcopy(projections)
    optimize_lineup(projections, [row["element"] for row in projections["players"]], generated_at=GENERATED)
    assert projections == before


def test_26_p1_6_tactical_component_is_read_only_exact_25_percent():
    projection = _projection(999, "MID", meanish=5.0, tactical=72.0)
    before = deepcopy(projection["tactical_role_component"])
    surface = build_player_surface(projection, GW)
    assert surface["tactical_role"]["canonical_weight"] == 0.25
    assert surface["tactical_role"]["weighted_component_points"] == pytest.approx(18.0)
    assert projection["tactical_role_component"] == before


def test_27_global_20_25_30_25_weights_are_unchanged():
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }


def test_28_phase0_fingerprints_are_deterministic_for_same_snapshot():
    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    first = optimize_lineup(projections, ids, generated_at=GENERATED)
    second = optimize_lineup(projections, ids, generated_at="2026-09-20T00:05:00Z")
    assert first["model_evidence_binding"]["run_fingerprint"] == second["model_evidence_binding"]["run_fingerprint"]
    assert first["model_evidence_binding"]["output_fingerprint"] == second["model_evidence_binding"]["output_fingerprint"]


def test_29_predeadline_freeze_is_immutable(base_decision):
    frozen = freeze_lineup_decision(
        base_decision,
        deadline_time="2026-09-21T10:00:00Z",
        frozen_at="2026-09-20T01:00:00Z",
    )
    assert frozen["status"] == "FROZEN_AWAITING_SETTLEMENT"
    snapshot = frozen["frozen_decision_snapshot"]
    assert snapshot["captain"] == base_decision["captain"]["element"]
    assert snapshot["vice_captain"] == base_decision["vice_captain"]["element"]
    assert snapshot["selected_route_summary"] == base_decision["lineup_score"]
    assert snapshot["formation_comparison"] == base_decision["formation_comparison"]
    assert snapshot["alternatives_considered"]
    assert len(snapshot["alternatives_considered"]) == len(base_decision["alternatives"])
    first_alt = snapshot["alternatives_considered"][0]
    assert set(first_alt["xi"]) == set(base_decision["alternatives"][0]["element_ids"])
    assert first_alt["bench_order"]
    assert first_alt["captain"] is not None
    assert first_alt["vice_captain"] is not None
    with pytest.raises(ModelEvidenceError):
        freeze_lineup_decision(
            base_decision,
            deadline_time="2026-09-21T10:00:00Z",
            frozen_at="2026-09-20T02:00:00Z",
            existing_record=frozen,
        )


def test_30_postmatch_settlement_keeps_decision_error_separate(base_decision):
    frozen = freeze_lineup_decision(
        base_decision,
        deadline_time="2026-09-21T10:00:00Z",
        frozen_at="2026-09-20T01:00:00Z",
    )
    actuals = [
        {"element": row["element"], "points": 5, "minutes": 90, "goals": 0, "assists": 0, "started": True}
        for row in base_decision["squad_rows"]
    ]
    settled = settle_lineup_decision(
        frozen,
        actual_rows=actuals,
        decision_outcome_evidence={
            "selected_xi_points": 55,
            "best_legal_xi_points": 58,
            "realized_bench_order_autosub_points": 3,
            "best_legal_bench_autosub_points": 5,
            "chosen_captain_points": 5,
            "best_captain_candidate_points": 9,
            "vice_takeover_points": 0,
            "vice_counterfactual_points": 4,
            "cameo_points": 1,
            "blocked_legal_autosub_points": 6,
        },
        event_finished=True,
        settled_at="2026-09-22T12:00:00Z",
    )
    metrics = settled["decision_calibration"]["metrics"]
    assert metrics["xi_regret"]["value"] == 3.0
    assert metrics["bench_order_regret"]["value"] == 2.0
    assert metrics["captain_regret"]["value"] == 4.0
    assert metrics["vice_captain_consequence"]["value"] == -4.0
    assert metrics["cameo_block_autosub_regret"]["value"] == 5.0
    assert settled["prediction_calibration"]["overall"]["sample_size"] == 15


@pytest.mark.parametrize(
    "forbidden",
    [
        "from src.runtime_v6",
        "import src.runtime_v6",
        "from src.runtime_v3",
        "import src.runtime_v3",
    ],
)
def test_31_32_no_v6_or_runtime_v3_production_dependency(forbidden):
    text = (ROOT / "src" / "engines" / "v12_lineup_optimizer.py").read_text(encoding="utf-8").lower()
    assert forbidden not in text


def test_33_no_package_optimizer_implementation_in_p1_7_owner():
    text = (ROOT / "src" / "engines" / "v12_lineup_optimizer.py").read_text(encoding="utf-8").lower()
    assert "from src.engines.package_optimizer" not in text
    assert "import src.engines.package_optimizer" not in text


def test_34_no_monte_carlo_implementation_in_p1_7_owner():
    text = (ROOT / "src" / "engines" / "v12_lineup_optimizer.py").read_text(encoding="utf-8").lower()
    assert "from src.engines.monte_carlo" not in text
    assert "import src.engines.monte_carlo" not in text
    assert load_config()["governance"]["monte_carlo_started"] is False


def test_35_no_mini_league_overlay_in_p1_7_owner():
    text = (ROOT / "src" / "engines" / "v12_lineup_optimizer.py").read_text(encoding="utf-8").lower()
    assert "from src.engines.mini_league" not in text
    assert "import src.engines.mini_league" not in text
    assert load_config()["governance"]["mini_league_overlay_started"] is False


def test_36_production_wrapper_switches_to_v12_owner_and_keeps_legacy_oracle(monkeypatch):
    def forbidden_production_oracle(*args, **kwargs):
        raise AssertionError("legacy lineup oracle must not execute in production after acceptance")

    monkeypatch.setattr(
        "src.engines.lineup_governance._build_legacy_lineup_decision",
        forbidden_production_oracle,
    )
    projections = _squad()
    lock = {
        "authoritative_phase": "pre_deadline_locked",
        "players": [
            {"element": row["element"], "position": row["position"], "purchase_cost": 50}
            for row in projections["players"]
        ],
    }
    decision = build_lineup_decision(projections, lock, {"used": []})
    assert decision["model"] == "governed_lineup_v2"
    assert decision["native_model"] == "v12_distributional_lineup_optimizer"
    assert decision["model_owner"] == "V12_LINEUP_OPTIMIZER"
    assert decision["governance"]["production_owner"] == "V12_LINEUP_OPTIMIZER"
    assert decision["governance"]["legacy_lineup_governance_status"] == "REGRESSION_ORACLE_CI_ONLY"
    assert decision["governance"]["legacy_oracle_executed_in_production"] is False
    assert decision["migration_comparison"]["status"] == "NOT_EXECUTED_PRODUCTION_POST_ACCEPTANCE"
    assert decision["migration_comparison"]["classification"] is None
    assert decision["migration_comparison"]["unexpected_regression_count"] == 0
    assert decision["migration_comparison"]["oracle_status"] == "CI_REGRESSION_ORACLE_ONLY_AFTER_ACCEPTANCE"


def test_37_captain_safe_pool_has_distinct_captain_candidates(base_decision):
    pool = base_decision["captain_safe_pool"]
    ids = [row["element"] for row in pool]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 2
    assert all(row.get("captain_score") is not None for row in pool)


def test_38_close_call_proof_has_mandatory_distributional_deltas(base_decision):
    proof = base_decision["main_starting_xi_battle"]
    for key in (
        "selected_xi",
        "best_alternative_xi",
        "delta_expected_utility",
        "delta_mean",
        "delta_downside",
        "delta_upside",
        "delta_autosub_value",
        "delta_cameo_block_risk",
        "delta_tactical_component",
        "expected_regret_delta",
        "reversal_triggers",
    ):
        assert key in proof


def test_39_formation_comparison_is_distributional_and_label_neutral(base_decision):
    rows = base_decision["formation_comparison"]
    assert rows
    assert {row["formation"] for row in rows}.issubset(set(LINEUP_RULES["legal_formations"]))
    assert all(row.get("route_utility") is not None for row in rows)
    assert all(len(row.get("element_ids") or []) == 11 for row in rows)
    assert sum(bool(row.get("selected")) for row in rows) == 1
    selected = next(row for row in rows if row.get("selected") is True)
    assert set(selected["element_ids"]) == {
        int(row["element"]) for row in base_decision["starting_xi"]
    }


def test_40_reserve_gk_autosub_is_independent_of_outfield_priority():
    starters = _starters_343()
    starters[0] = _direct_surface(1, "GK", mean=1.0, p_dnp=1.0)
    reserve = _direct_surface(90, "GK", mean=5.0)
    bench = [_direct_surface(91, "DEF", mean=6.0), _direct_surface(92, "MID", mean=7.0), _direct_surface(93, "FWD", mean=8.0)]
    out = evaluate_bench_order(starters, reserve, bench)
    assert out["reserve_gk"]["autosub_probability"] == pytest.approx(1.0)
    assert out["reserve_gk"]["expected_autosub_value"] == pytest.approx(5.0)


def test_41_model_evidence_is_non_authoritative_and_no_raw_v6_duplication(base_decision):
    binding = base_decision["model_evidence_binding"]
    for key in (
        "input_snapshot_id",
        "model_version",
        "feature_version",
        "parameter_version",
        "calibration_version",
        "calibration_cutoff",
        "run_fingerprint",
        "output_fingerprint",
    ):
        assert binding.get(key)
    assert binding["authority"] is False
    assert binding["raw_v6_payload_duplicated"] is False


def test_42_parameter_manifest_is_p1_5_governed_and_non_autotuning():
    cfg = load_config()
    assert cfg["parameter_manifest"]
    for row in cfg["parameter_manifest"]:
        assert row["parameter_id"].startswith("P1_7_")
        assert row["version"] == cfg["parameter_version"]
        assert row["calibration_sample_size"] == 0
        assert row["calibration_confidence"] == "LOW"
        assert row["automatic_retuning"] is False


def test_43_no_named_player_or_club_special_case():
    text = (
        (ROOT / "src" / "engines" / "v12_lineup_optimizer.py").read_text(encoding="utf-8")
        + (ROOT / "config" / "intelligence" / "v12_lineup_optimizer.json").read_text(encoding="utf-8")
    ).casefold()
    for forbidden in ("barry", "kostoulas", "groß", "gross", "brighton", "arsenal"):
        assert forbidden not in text


def test_44_migration_comparator_blocks_only_real_legality_regression(base_decision):
    legacy = deepcopy(base_decision)
    comparison = compare_legacy_decision(legacy, base_decision)
    assert comparison["classification"] == "EXACT_EQUIVALENT"
    assert comparison["ownership_migration_blocked"] is False
    assert set(comparison["classification_taxonomy"]) == {
        "EXACT_EQUIVALENT",
        "DISTRIBUTIONAL_IMPROVEMENT",
        "AUTOSUB_OPTION_VALUE_IMPROVEMENT",
        "CAMEO_BLOCKING_IMPROVEMENT",
        "CAPTAIN_FALLBACK_IMPROVEMENT",
        "BUG_FIX",
        "UNEXPECTED_REGRESSION",
    }


def test_44b_migration_taxonomy_covers_distributional_bugfix_bench_and_cvc(base_decision):
    native = deepcopy(base_decision)

    legacy_distributional = deepcopy(base_decision)
    outfield_bench = (legacy_distributional.get("bench") or {}).get("order") or []
    swapped = False
    for bench_row in outfield_bench:
        for index, starter in enumerate(legacy_distributional["starting_xi"]):
            if (
                bench_row.get("position") == starter.get("position")
                and int(starter.get("element") or 0)
                not in {
                    int((legacy_distributional.get("captain") or {}).get("element") or -1),
                    int((legacy_distributional.get("vice_captain") or {}).get("element") or -1),
                }
            ):
                replacement = deepcopy(bench_row)
                displaced = deepcopy(starter)
                legacy_distributional["starting_xi"][index] = replacement
                bench_index = next(
                    i
                    for i, row in enumerate(legacy_distributional["bench"]["order"])
                    if int(row.get("element") or 0) == int(bench_row.get("element") or -1)
                )
                legacy_distributional["bench"]["order"][bench_index] = displaced
                swapped = True
                break
        if swapped:
            break
    assert swapped is True
    comparison = compare_legacy_decision(legacy_distributional, native)
    assert comparison["classification"] == "DISTRIBUTIONAL_IMPROVEMENT"

    legacy_bench = deepcopy(base_decision)
    legacy_bench["bench"]["order"] = list(reversed(legacy_bench["bench"]["order"]))
    comparison = compare_legacy_decision(legacy_bench, native)
    assert comparison["classification"] in {
        "CAMEO_BLOCKING_IMPROVEMENT",
        "AUTOSUB_OPTION_VALUE_IMPROVEMENT",
    }

    native_no_block = deepcopy(base_decision)
    native_no_block["bench"]["distributional_evaluation"]["expected_blocked_autosub_value"] = 0.0
    comparison = compare_legacy_decision(legacy_bench, native_no_block)
    assert comparison["classification"] == "AUTOSUB_OPTION_VALUE_IMPROVEMENT"

    legacy_cvc = deepcopy(base_decision)
    legacy_cvc["captain"], legacy_cvc["vice_captain"] = (
        deepcopy(legacy_cvc["vice_captain"]),
        deepcopy(legacy_cvc["captain"]),
    )
    comparison = compare_legacy_decision(legacy_cvc, native)
    assert comparison["classification"] == "CAPTAIN_FALLBACK_IMPROVEMENT"

    legacy_bug = deepcopy(base_decision)
    legacy_bug["starting_xi"] = legacy_bug["starting_xi"][:10]
    comparison = compare_legacy_decision(legacy_bug, native)
    assert comparison["classification"] == "BUG_FIX"
    assert comparison["ownership_migration_blocked"] is False


def test_45_captain_pair_takeover_formula_is_explicit():
    starters = _starters_343()
    captain, vice = starters[5], starters[6]
    captain["p_dnp"] = 0.2
    vice["p_appearance"] = 0.8
    vice["p_dnp"] = 0.2
    pair = next(row for row in evaluate_captain_vice_pairs(starters) if row["captain_element"] == captain["element"] and row["vice_element"] == vice["element"])
    assert pair["vice_takeover_probability"] == pytest.approx(0.16)
    assert pair["dependence_assumption"] == "CAPTAIN_DNP_AND_VICE_OUTCOME_INDEPENDENCE_APPROXIMATION"


def test_46_distributional_surface_preserves_p1_3_pmf_without_rewrite():
    projection = _projection(999, "MID", meanish=5.0)
    original = deepcopy(projection["xpts_by_gw"][0]["point_distribution"]["probabilities"])
    surface = build_player_surface(projection, GW)
    assert surface["point_distribution"] == {k: pytest.approx(v) for k, v in original.items()}
    assert projection["xpts_by_gw"][0]["point_distribution"]["probabilities"] == original


def test_47_lineup_route_reports_zero_covariance_variance_approximation(base_decision):
    alternative = base_decision["alternatives"][0]
    assert alternative["aggregate_variance_semantics"] == "SUM_OF_PLAYER_VARIANCES_ZERO_COVARIANCE_APPROXIMATION"
    assert alternative["uncertainty"]["covariance_status"] == "COVARIANCE_NOT_MODELLED_YET"


def test_48_global_governance_boundaries_are_explicit(base_decision):
    gov = base_decision["governance"]
    assert gov["p1_1_math_mutated"] is False
    assert gov["p1_3_math_mutated"] is False
    assert gov["p1_6_math_mutated"] is False
    assert gov["methodology_weights_20_25_30_25_unchanged"] is True
    assert gov["v6_mutated"] is False
    assert gov["monte_carlo_applied"] is False
    assert gov["package_optimizer_implemented"] is False
    assert gov["mini_league_overlay_applied"] is False


def test_48b_production_output_does_not_duplicate_player_surfaces(base_decision):
    assert "player_surfaces" not in base_decision
    assert len(base_decision["squad_rows"]) == 15
    assert load_config()["governance"]["duplicate_player_surface_payload"] is False
    assert load_config()["migration"]["production_legacy_oracle_execution"] is False


def test_49_squad_rows_publish_non_authoritative_selection_score_alias(base_decision):
    assert base_decision["squad_rows"]
    for row in base_decision["squad_rows"]:
        assert row["selection_score"] == pytest.approx(row["distributional_utility"])
        assert row["selection_score_semantics"] == "P1_7_DISTRIBUTIONAL_UTILITY_COMPATIBILITY_ALIAS"


def test_50_captain_safe_pool_always_contains_selected_captain_and_vice(base_decision):
    safe_ids = {int(row["element"]) for row in base_decision["captain_safe_pool"]}
    assert int(base_decision["captain"]["element"]) in safe_ids
    assert int(base_decision["vice_captain"]["element"]) in safe_ids


def test_51_exact_position_count_distribution_preserves_probability_and_moments():
    starters = _starters_343()
    probabilities_by_position = {"DEF": [], "MID": [], "FWD": []}
    for index, row in enumerate(starters):
        if row["position"] not in probabilities_by_position:
            continue
        row["p_dnp"] = 0.01 * (index + 1)
        probabilities_by_position[row["position"]].append(row["p_dnp"])

    distribution = _dnp_count_distribution(starters)
    assert sum(probability for _, probability in distribution) == pytest.approx(1.0)

    for position_index, position in enumerate(("DEF", "MID", "FWD")):
        expected_count = sum(probabilities_by_position[position])
        observed_count = sum(
            counts[position_index] * probability
            for counts, probability in distribution
        )
        assert observed_count == pytest.approx(expected_count)


def test_52_cached_bench_appearance_masks_remain_exact():
    probabilities = (0.91, 0.73, 0.42)
    masks = _appearance_mask_probabilities(probabilities)
    assert len(masks) == 8
    assert all(value >= 0.0 for value in masks)
    assert sum(masks) == pytest.approx(1.0)
    assert masks[0] == pytest.approx(
        (1.0 - probabilities[0])
        * (1.0 - probabilities[1])
        * (1.0 - probabilities[2])
    )
    assert masks[7] == pytest.approx(
        probabilities[0] * probabilities[1] * probabilities[2]
    )



def test_51_resolver_mask_table_is_exact_alias_of_canonical_resolver():
    start_counts = (4, 4, 2)
    dnp_counts = (2, 1, 1)
    bench_positions = ("MID", "DEF", "FWD")
    table = _resolver_mask_table(start_counts, dnp_counts, bench_positions)
    assert len(table) == 8
    for mask in range(8):
        selected, reached, _ = _resolve_outfield_pattern(
            start_counts,
            dnp_counts,
            bench_positions,
            mask,
        )
        selected_bits = sum(1 << index for index in selected)
        reached_bits = sum(1 << index for index in reached)
        assert table[mask] == (selected_bits, reached_bits)


def test_52_compact_route_scoring_matches_full_materialization_exactly():
    surfaces = _surfaces()
    legal = enumerate_legal_xi(surfaces)
    sample_indices = sorted(
        {
            0,
            1,
            len(legal) // 7,
            len(legal) // 3,
            len(legal) // 2,
            (2 * len(legal)) // 3,
            len(legal) - 2,
            len(legal) - 1,
        }
    )
    for sample_index in sample_indices:
        xi_indices = legal[sample_index]
        compact = _lineup_route(surfaces, xi_indices, compact=True)
        detailed = _lineup_route(surfaces, xi_indices, compact=False)
        assert _route_sort_key(compact) == pytest.approx(
            _route_sort_key(detailed), abs=1e-9
        )
        assert tuple(compact["_bench_order"]) == tuple(
            detailed["bench"]["order"]
        )
        assert compact["_captain_element"] == detailed["captain_vice"]["captain_element"]
        assert compact["_vice_element"] == detailed["captain_vice"]["vice_element"]


def test_53_fast_best_cvc_matches_full_ordered_pair_ranking():
    starters = _starters_343()
    full = evaluate_captain_vice_pairs(starters)[0]
    fast = _best_captain_vice_pair(starters)
    assert fast == full


def test_54_compact_route_does_not_materialize_publish_only_payload():
    surfaces = _surfaces()
    xi_indices = enumerate_legal_xi(surfaces)[0]
    compact = _lineup_route(surfaces, xi_indices, compact=True)
    assert "starters" not in compact
    assert "bench" not in compact
    assert "bench_alternatives" not in compact
    assert "captain_vice_alternatives" not in compact
    assert compact["expected_blocked_autosub_value"] is None


def test_55_post_ranking_materialization_keeps_selected_and_best_alternative_exact(base_decision):
    governance = base_decision["materialization_governance"]
    assert governance["all_legal_routes_ranked_exactly"] is True
    assert governance["selected_route_fully_materialized"] is True
    assert governance["best_alternative_fully_materialized"] is True
    assert governance["route_pruning_applied"] is False
    assert governance["route_utility_changed"] is False

    alternatives = base_decision["alternatives"]
    assert len(alternatives) >= 3
    assert alternatives[0].get("starters")
    assert alternatives[1].get("starters")
    for row in alternatives[2:]:
        assert row["publish_materialization_status"] == "EXACT_RANKED_COMPACT_SUMMARY_NO_RECOMPUTE"
        assert len(row["element_ids"]) == 11
        assert len((row.get("bench") or {}).get("order") or []) == 3
        pair = row.get("captain_vice") or {}
        assert pair.get("captain_element") is not None
        assert pair.get("vice_element") is not None
        assert row["expected_regret"] >= 0.0


def test_56_formation_comparison_uses_exact_ranked_compact_route_without_recompute(base_decision):
    rows = base_decision["formation_comparison"]
    assert rows
    assert all(row["ranking_source"] == "EXACT_COMPACT_ROUTE" for row in rows)
    assert all(
        row["cameo_blocking_cost_status"]
        in {
            "MATERIALIZED_SELECTED_OR_BEST_ALTERNATIVE",
            "NOT_REMATERIALIZED_FORMATION_SUMMARY",
        }
        for row in rows
    )


def _scalar_expected_outfield_autosub_reference(
    starters,
    bench_order,
    *,
    cameo_as_dnp=False,
    late_cameo_as_dnp=False,
    count_states=None,
):
    outfield_starters = [
        row for row in starters if row.get("position") in ("DEF", "MID", "FWD")
    ]
    start_counts = tuple(
        sum(1 for row in outfield_starters if row.get("position") == position)
        for position in ("DEF", "MID", "FWD")
    )
    bench_positions = tuple(str(row.get("position")) for row in bench_order)
    resolved = (
        list(count_states)
        if count_states is not None
        else _dnp_count_distribution(
            outfield_starters,
            cameo_as_dnp=cameo_as_dnp,
            late_cameo_as_dnp=late_cameo_as_dnp,
        )
    )
    appear = tuple(
        max(0.0, min(1.0, float(row.get("p_appearance") or 0.0)))
        for row in bench_order
    )
    mask_probabilities = _appearance_mask_probabilities(appear)
    conditioned = [
        dict(row.get("appearance_conditioned") or {})
        for row in bench_order
    ]
    expected = [
        float(row.get("expected_points") or 0.0)
        for row in conditioned
    ]
    blank = [
        None if row.get("p_fpl_blank") is None else float(row["p_fpl_blank"])
        for row in conditioned
    ]
    ge8 = [
        None if row.get("p_points_ge_8") is None else float(row["p_points_ge_8"])
        for row in conditioned
    ]
    ge10 = [
        None if row.get("p_points_ge_10") is None else float(row["p_points_ge_10"])
        for row in conditioned
    ]
    expected_points = 0.0
    autosub_probability = 0.0
    selected_prob = [0.0, 0.0, 0.0]
    reach_prob = [0.0, 0.0, 0.0]
    selected_blank = 0.0
    selected_ge8 = 0.0
    selected_ge10 = 0.0
    for dnp_counts, starter_probability in resolved:
        table = _resolver_mask_table(
            start_counts,
            dnp_counts,
            bench_positions,
        )
        for mask, bench_probability in enumerate(mask_probabilities):
            probability = starter_probability * bench_probability
            if probability <= 1e-15:
                continue
            selected_bits, reached_bits = table[mask]
            if selected_bits:
                autosub_probability += probability
            for index in range(3):
                bit = 1 << index
                if reached_bits & bit:
                    reach_prob[index] += probability
                if not (selected_bits & bit):
                    continue
                selected_prob[index] += probability
                expected_points += probability * expected[index]
                if blank[index] is not None:
                    selected_blank += probability * blank[index]
                if ge8[index] is not None:
                    selected_ge8 += probability * ge8[index]
                if ge10[index] is not None:
                    selected_ge10 += probability * ge10[index]
    return {
        "expected_points": expected_points,
        "autosub_probability": autosub_probability,
        "slot_selected_probability": selected_prob,
        "slot_reach_probability": reach_prob,
        "expected_selected_blank_probability_mass": selected_blank,
        "expected_selected_ge8_probability_mass": selected_ge8,
        "expected_selected_ge10_probability_mass": selected_ge10,
    }


@pytest.mark.parametrize(
    "cameo_as_dnp,late_cameo_as_dnp",
    [(False, False), (True, False), (False, True)],
)
def test_57_vectorized_autosub_probability_mass_matches_scalar_canonical_reference(
    cameo_as_dnp,
    late_cameo_as_dnp,
):
    starters = _starters_343(defender_dnp=0.23, forward_dnp=0.19)
    starters[2]["p_cameo"] = 0.31
    starters[2]["p_late_cameo"] = 0.11
    starters[2]["p_appearance"] = 1.0 - starters[2]["p_dnp"]
    reserve = _direct_surface(90, "GK", mean=3.0)
    bench = [
        _direct_surface(91, "MID", mean=6.2, p_dnp=0.13, cond_blank=0.22, cond_ge8=0.31, cond_ge10=0.14),
        _direct_surface(92, "DEF", mean=4.7, p_dnp=0.07, cond_blank=0.18, cond_ge8=0.24, cond_ge10=0.09),
        _direct_surface(93, "FWD", mean=5.4, p_dnp=0.21, cond_blank=0.29, cond_ge8=0.36, cond_ge10=0.19),
    ]
    del reserve
    for order in __import__("itertools").permutations(bench, 3):
        expected = _scalar_expected_outfield_autosub_reference(
            starters,
            order,
            cameo_as_dnp=cameo_as_dnp,
            late_cameo_as_dnp=late_cameo_as_dnp,
        )
        actual = _expected_outfield_autosub(
            starters,
            order,
            cameo_as_dnp=cameo_as_dnp,
            late_cameo_as_dnp=late_cameo_as_dnp,
        )
        assert actual["expected_points"] == pytest.approx(
            expected["expected_points"], abs=1e-12
        )
        assert actual["autosub_probability"] == pytest.approx(
            expected["autosub_probability"], abs=1e-12
        )
        assert actual["slot_selected_probability"] == pytest.approx(
            expected["slot_selected_probability"], abs=1e-12
        )
        assert actual["slot_reach_probability"] == pytest.approx(
            expected["slot_reach_probability"], abs=1e-12
        )
        for key in (
            "expected_selected_blank_probability_mass",
            "expected_selected_ge8_probability_mass",
            "expected_selected_ge10_probability_mass",
        ):
            assert actual[key] == pytest.approx(expected[key], abs=1e-12)


def test_58_vectorized_autosub_keeps_canonical_resolver_as_only_legality_owner():
    source = (
        ROOT / "src" / "engines" / "v12_lineup_optimizer.py"
    ).read_text(encoding="utf-8")
    function_source = source[
        source.index("def _expected_outfield_autosub("):
        source.index("def _expected_gk_autosub(")
    ]
    assert "_resolver_mask_table(" in function_source
    assert "joint_probability" in function_source
    assert "np.sum(" in function_source
    assert "route_pruning" not in function_source


def test_p17_exact_decision_core_cache_requires_full_fingerprint_match(
    monkeypatch, tmp_path
):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(tmp_path))

    calls = {"count": 0}
    original = lineup._decision_core

    def counted(players):
        calls["count"] += 1
        return original(players)

    monkeypatch.setattr(lineup, "_decision_core", counted)

    first = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    second = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )

    assert first == second
    assert calls["count"] == 1
    assert first["legal_xi_count"] == 550
    assert list(tmp_path.rglob("*.pkl"))

    changed = deepcopy(projections)
    changed["players"][0]["tactical_role_component"][
        "canonical_tactical_role_score"
    ] += 1.0
    lineup.optimize_lineup(
        changed,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    assert calls["count"] == 2


def test_p17_decision_cache_is_execution_reuse_not_model_authority(
    monkeypatch, tmp_path
):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(tmp_path))

    first = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    second = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )

    assert first["model_owner"] == "V12_LINEUP_OPTIMIZER"
    assert second["model_owner"] == "V12_LINEUP_OPTIMIZER"
    assert first["model_evidence_binding"] == second["model_evidence_binding"]
    assert first["governance"]["v6_mutated"] is False
    assert first["governance"]["methodology_weights_20_25_30_25_unchanged"] is True


def test_p17_legal_xi_templates_reuse_identical_position_signature():
    from src.engines import v12_lineup_optimizer as lineup

    lineup._legal_xi_templates.cache_clear()
    positions = (
        ["GK"] * 2
        + ["DEF"] * 5
        + ["MID"] * 5
        + ["FWD"] * 3
    )
    first_players = [
        {"element": index + 1, "position": position}
        for index, position in enumerate(positions)
    ]
    second_players = [
        {"element": index + 101, "position": position}
        for index, position in enumerate(positions)
    ]

    first = lineup.enumerate_legal_xi(first_players)
    first_info = lineup._legal_xi_templates.cache_info()
    second = lineup.enumerate_legal_xi(second_players)
    second_info = lineup._legal_xi_templates.cache_info()

    assert first == second
    assert len(first) == 550
    assert second_info.hits == first_info.hits + 1


def test_p17_primed_player_surfaces_are_exactly_output_equivalent(
    monkeypatch,
):
    from src.engines import v12_lineup_optimizer as lineup

    monkeypatch.delenv(lineup.P17_DECISION_CACHE_ENV, raising=False)
    projections = _squad()
    ids = [row["element"] for row in projections["players"]]

    lineup._P17_SURFACE_CACHE_OWNER = None
    lineup._P17_SURFACE_CACHE = {}
    scalar = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )

    proof = lineup.prime_player_surface_cache(
        projections,
        planning_gws=[GW],
        material_elements=ids,
    )
    primed = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )

    assert proof == {
        "element_count": 15,
        "gw_count": 1,
        "surface_count": 15,
    }
    assert primed == scalar


def test_p17_cache_observability_proves_hit_miss_write_and_numerical_invalidation(
    monkeypatch, tmp_path
):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(tmp_path))
    lineup.reset_p17_execution_observability()

    cold = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    warm = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    stats = lineup.p17_execution_observability()

    assert cold == warm
    assert stats["p17_cache_hits"] >= 1
    assert stats["p17_cache_misses"] >= 1
    assert stats["p17_cache_writes"] >= 1
    assert stats["p17_cache_corrupt_rejects"] == 0
    assert stats["p1_7_wall_seconds"] > 0.0
    assert stats["p1_7_cpu_seconds"] > 0.0

    changed = deepcopy(projections)
    changed["players"][0]["xpts_by_gw"][0]["mean"] += 0.125
    before_misses = stats["p17_cache_misses"]
    lineup.optimize_lineup(
        changed,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    changed_stats = lineup.p17_execution_observability()
    assert changed_stats["p17_cache_misses"] == before_misses + 1


def test_p17_corrupt_cache_is_rejected_fail_closed_and_recomputed(
    monkeypatch, tmp_path
):
    from src.engines import v12_lineup_optimizer as lineup

    projections = _squad()
    ids = [row["element"] for row in projections["players"]]
    monkeypatch.setenv(lineup.P17_DECISION_CACHE_ENV, str(tmp_path))
    first = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    cache_files = list(tmp_path.rglob("*.pkl"))
    assert len(cache_files) == 1
    cache_files[0].write_bytes(b"not-a-valid-pickle")

    lineup.reset_p17_execution_observability()
    recovered = lineup.optimize_lineup(
        projections,
        ids,
        planning_gw=GW,
        generated_at=GENERATED,
    )
    stats = lineup.p17_execution_observability()

    assert recovered == first
    assert stats["p17_cache_corrupt_rejects"] == 1
    assert stats["p17_cache_misses"] == 1
    assert stats["p17_cache_writes"] == 1


def test_v12_workflow_saves_compute_caches_even_if_downstream_acceptance_fails():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-integrated-report-runner.yml"
    ).read_text(encoding="utf-8")
    for step_name in (
        "Persist exact P1.7 decision-core cache before downstream acceptance",
        "Persist deterministic MC summary cache before downstream acceptance",
    ):
        start = workflow.index(f"- name: {step_name}")
        block = workflow[start : start + 450]
        assert "if: always() && needs.parse.outputs.report_mode == 'DEEP'" in block
        assert "actions/cache/save@v4" in block


def _p17_core_surface_rows(projections):
    from src.engines import v12_lineup_optimizer as lineup

    return [
        lineup.build_player_surface(row, GW)
        for row in projections["players"]
    ]


def _assert_fast_scalar_core_equivalent(fast, scalar):
    assert fast["legal_xi_count"] == scalar["legal_xi_count"] == 550
    assert fast["legal_formations_evaluated"] == scalar["legal_formations_evaluated"]
    assert fast["selected"] == scalar["selected"]
    assert fast["best_alternative"] == scalar["best_alternative"]
    assert fast["formation_comparison"] == scalar["formation_comparison"]
    assert fast["close_call_proof"] == scalar["close_call_proof"]
    assert fast["alternatives"] == scalar["alternatives"]
    for key in (
        "all_legal_routes_ranked_exactly",
        "selected_route_fully_materialized",
        "best_alternative_fully_materialized",
        "other_published_routes",
        "formation_comparison_source",
        "route_pruning_applied",
        "route_utility_changed",
    ):
        assert (
            fast["materialization_governance"][key]
            == scalar["materialization_governance"][key]
        )


def test_p17_vectorized_550_xi_kernel_is_exact_scalar_equivalent():
    from src.engines import v12_lineup_optimizer as lineup

    players = _p17_core_surface_rows(_squad())
    fast = lineup._decision_core(players)
    scalar = lineup._decision_core_scalar_reference(players)
    _assert_fast_scalar_core_equivalent(fast, scalar)
    assert (
        fast["materialization_governance"]["execution_kernel"]
        == "NUMPY_BATCH_EXACT_550_XI"
    )
    assert fast["materialization_governance"]["scalar_reference_preserved"] is True


def test_p17_vectorized_kernel_randomized_surface_equivalence():
    from src.engines import v12_lineup_optimizer as lineup

    base = _p17_core_surface_rows(_squad())
    for scenario in range(8):
        players = deepcopy(base)
        for index, row in enumerate(players):
            signed = ((index * 7 + scenario * 3) % 11) - 5
            delta = signed * 0.007
            row["xpts_mean"] = round(max(0.0, float(row["xpts_mean"]) + delta), 6)
            row["xpts_variance"] = round(
                max(0.0, float(row["xpts_variance"]) + abs(delta) * 0.5),
                6,
            )
            row["expected_shortfall"] = round(
                max(0.0, float(row["expected_shortfall"] or 0.0) + abs(delta) * 0.2),
                6,
            )
            row["expected_excess_ge_8"] = round(
                max(0.0, float(row["expected_excess_ge_8"] or 0.0) + max(delta, 0.0) * 0.3),
                6,
            )
            p_dnp = min(
                0.95,
                max(0.0, float(row["p_dnp"]) + signed * 0.0007),
            )
            row["p_dnp"] = round(p_dnp, 9)
            row["p_appearance"] = round(1.0 - p_dnp, 9)
            conditional = dict(row.get("appearance_conditioned") or {})
            conditional["expected_points"] = round(
                max(
                    0.0,
                    float(conditional.get("expected_points") or 0.0)
                    + delta,
                ),
                6,
            )
            row["appearance_conditioned"] = conditional
        fast = lineup._decision_core(players)
        scalar = lineup._decision_core_scalar_reference(players)
        _assert_fast_scalar_core_equivalent(fast, scalar)


def test_issue_comment_compute_cache_write_is_owner_gated():
    workflow = (
        ROOT / ".github" / "workflows" / "v12-integrated-report-runner.yml"
    ).read_text(encoding="utf-8")
    assert "github.event.comment.user.login == github.repository_owner" in workflow
    assert "ref: main" in workflow
    assert "cache-mode: write" in workflow


def _cross_route_projection_fixture(candidate_per_position: int = 4):
    projections = deepcopy(_squad())
    for row in projections["players"]:
        base = deepcopy(row["xpts_by_gw"][0])
        row["xpts_by_gw"] = [
            {**deepcopy(base), "gw": gw}
            for gw in range(GW, GW + 5)
        ]
    candidates = []
    next_element = 1001
    for position_index, position in enumerate(("GK", "DEF", "MID", "FWD")):
        for index in range(candidate_per_position):
            row = _projection(
                next_element,
                position,
                meanish=4.0 + position_index * 0.65 + (index % 17) * 0.11,
                p_start=0.82 + (index % 4) * 0.03,
                p_regular=0.06,
                p_late=0.02,
                p_dnp=max(0.01, 0.10 - (index % 4) * 0.03),
                blank=0.07 + (index % 5) * 0.02,
                upside=0.16 + (index % 4) * 0.03,
                tactical=52.0 + (index % 9) * 3.0,
            )
            base = deepcopy(row["xpts_by_gw"][0])
            row["xpts_by_gw"] = [
                {**deepcopy(base), "gw": gw}
                for gw in range(GW, GW + 5)
            ]
            candidates.append(row)
            next_element += 1
    projections["players"].extend(candidates)
    return projections, candidates


def test_p17_cross_route_batch_matches_scalar_one_transfer_families():
    from src.engines import v12_lineup_batch as batch
    from src.engines import v12_package_utility as package

    projections, candidates = _cross_route_projection_fixture(5)
    base_ids = tuple(
        sorted(row["element"] for row in projections["players"][:15])
    )
    base_by_id = {
        int(row["element"]): row
        for row in projections["players"][:15]
    }
    candidate_by_position = {
        position: [
            row for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    squads = [base_ids]
    for outgoing in (base_ids[0], base_ids[2], base_ids[7], base_ids[12]):
        position = base_by_id[outgoing]["position"]
        for incoming in candidate_by_position[position][:2]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {int(incoming["element"])}
                    )
                )
            )

    actual, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=GW,
        generated_at=GENERATED,
        batch_size=8,
    )
    assert proof["execution_kernel"] == "CROSS_ROUTE_NUMPY_EXACT_P1_7"
    assert proof["route_pruning"] is False
    assert proof["approximation"] is False
    assert proof["legal_xi_per_squad"] == 550
    assert proof["bench_permutations"] == 6

    exact_keys = (
        "status",
        "gw",
        "route_utility",
        "expected_fpl_points",
        "distributional_downside",
        "supportable_upside",
        "expected_autosub_value",
        "cameo_blocking_cost",
        "formation",
        "starting_xi",
        "bench_gk",
        "bench_order",
        "captain",
        "vice_captain",
        "captain_safe_pool_count",
        "confidence",
        "covariance_status",
    )
    scalar_rows = []
    batch_rows = []
    for squad, horizons in zip(squads, actual):
        for offset in range(5):
            expected = package._lineup_decision(
                projections,
                squad,
                gw=GW + offset,
                generated_at=GENERATED,
            )
            observed = horizons["per_gw"][offset]
            assert {
                key: observed.get(key)
                for key in exact_keys
            } == {
                key: expected.get(key)
                for key in exact_keys
            }
        scalar_rows.append(
            tuple(
                package._lineup_decision(
                    projections,
                    squad,
                    gw=GW,
                    generated_at=GENERATED,
                ).get(key)
                for key in (
                    "route_utility",
                    "expected_fpl_points",
                    "distributional_downside",
                    "supportable_upside",
                )
            )
        )
        first = horizons["per_gw"][0]
        batch_rows.append(
            tuple(
                first.get(key)
                for key in (
                    "route_utility",
                    "expected_fpl_points",
                    "distributional_downside",
                    "supportable_upside",
                )
            )
        )
    assert sorted(
        range(len(squads)),
        key=lambda index: scalar_rows[index],
        reverse=True,
    ) == sorted(
        range(len(squads)),
        key=lambda index: batch_rows[index],
        reverse=True,
    )



def test_p17_core14_family_kernel_matches_scalar_across_positions_and_five_gw():
    from src.engines import v12_lineup_batch as batch
    from src.engines import v12_package_utility as package

    projections, candidates = _cross_route_projection_fixture(20)
    owned = projections["players"][:15]
    base_ids = tuple(sorted(int(row["element"]) for row in owned))
    owned_by_id = {int(row["element"]): row for row in owned}
    candidate_by_position = {
        position: [
            row for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }

    outgoing_by_position = {}
    for element in base_ids:
        position = owned_by_id[element]["position"]
        outgoing_by_position.setdefault(position, element)
    assert set(outgoing_by_position) == {"GK", "DEF", "MID", "FWD"}

    squads = [base_ids]
    family_ranges = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        start = len(squads)
        outgoing = outgoing_by_position[position]
        for incoming in candidate_by_position[position][:16]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {int(incoming["element"])}
                    )
                )
            )
        family_ranges[position] = (start, len(squads) - 1)

    assert len(squads) == 65
    actual, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=GW,
        generated_at=GENERATED,
        batch_size=512,
    )
    assert proof["execution_kernel"] == "ROUTE_FAMILY_CORE14_AFFINE_EXACT_P1_7"
    assert proof["route_family_count"] == 4
    assert proof["route_family_core_reuse"] is True
    assert proof["candidate_affine_resolver_exact"] is True
    assert proof["route_pruning"] is False
    assert proof["approximation"] is False

    exact_keys = (
        "status",
        "gw",
        "route_utility",
        "expected_fpl_points",
        "distributional_downside",
        "supportable_upside",
        "expected_autosub_value",
        "cameo_blocking_cost",
        "formation",
        "starting_xi",
        "bench_gk",
        "bench_order",
        "captain",
        "vice_captain",
        "captain_safe_pool_count",
        "confidence",
        "covariance_status",
    )
    representative_indices = [0]
    for start, end in family_ranges.values():
        representative_indices.extend((start, end))

    for index in representative_indices:
        squad = squads[index]
        horizons = actual[index]["per_gw"]
        for offset in range(5):
            expected = package._lineup_decision(
                projections,
                squad,
                gw=GW + offset,
                generated_at=GENERATED,
            )
            observed = horizons[offset]
            assert {
                key: observed.get(key)
                for key in exact_keys
            } == {
                key: expected.get(key)
                for key in exact_keys
            }

def test_p17_cross_route_batch_2043_routes_five_gw_under_ten_seconds():
    import time

    from src.engines import v12_lineup_batch as batch

    projections, candidates = _cross_route_projection_fixture(140)
    owned = projections["players"][:15]
    base_ids = tuple(sorted(int(row["element"]) for row in owned))
    owned_by_id = {int(row["element"]): row for row in owned}
    candidates_by_position = {
        position: [
            int(row["element"])
            for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }

    squads = [base_ids]
    for outgoing in base_ids:
        position = owned_by_id[outgoing]["position"]
        for incoming in candidates_by_position[position]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {incoming}
                    )
                )
            )
            if len(squads) == 2043:
                break
        if len(squads) == 2043:
            break
    assert len(squads) == 2043
    assert len(set(squads)) == 2043

    started = time.perf_counter()
    outputs, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=GW,
        generated_at=GENERATED,
        batch_size=512,
    )
    elapsed = time.perf_counter() - started
    assert len(outputs) == 2043
    assert all(len(row["per_gw"]) == 5 for row in outputs)
    assert all(
        gw_row["status"] == "READY"
        for row in outputs
        for gw_row in row["per_gw"]
    )
    assert proof["squad_count"] == 2043
    assert proof["legal_xi_per_squad"] == 550
    assert proof["execution_kernel"] == "ROUTE_FAMILY_CORE14_AFFINE_EXACT_P1_7"
    assert proof["route_family_count"] >= 1
    assert proof["route_family_core_reuse"] is True
    assert proof["candidate_affine_resolver_exact"] is True
    assert proof["route_pruning"] is False
    assert all(
        gw_row["cameo_blocking_cost"] is not None
        and gw_row["captain_safe_pool_count"] >= 2
        for row in outputs
        for gw_row in row["per_gw"]
    )
    assert elapsed <= 10.0


def test_p17_lazy_lexicographic_preserves_first_tie_and_skips_later_keys():
    from src.engines import v12_lineup_batch as batch

    calls = {"later": 0}
    first = np.asarray(
        [
            [[3.0, 2.0, 1.0], [4.0, 3.0, 2.0]],
            [[1.0, 0.0, -1.0], [9.0, 8.0, 7.0]],
        ],
        dtype=np.float64,
    )

    def later():
        calls["later"] += 1
        raise AssertionError("unique first key must skip later keys")

    winner = batch._lexicographic_first((first, later), axis=2)
    assert winner.tolist() == [[0, 0], [0, 0]]
    assert calls["later"] == 0


def test_p17_lazy_lexicographic_resolves_adversarial_ties_in_first_order():
    from src.engines import v12_lineup_batch as batch

    first = np.asarray([[[1.0, 1.0, 0.0], [2.0, 2.0, 2.0]]])
    second = np.asarray([[[5.0, 6.0, 99.0], [7.0, 7.0, 6.0]]])
    third = np.asarray([[[0.0, 0.0, 0.0], [1.0, 2.0, 99.0]]])
    winner = batch._lexicographic_first(
        (first, lambda: second, lambda: third),
        axis=2,
    )
    assert winner.tolist() == [[1, 1]]


def test_p17_lazy_lexicographic_rejects_non_finite_ranking_keys():
    from src.engines import v12_lineup_batch as batch

    with pytest.raises(batch.LineupBatchError, match="must be finite"):
        batch._lexicographic_first(
            (np.asarray([[[1.0, np.nan]]], dtype=np.float64),),
            axis=2,
        )


def test_p17_rounding_boundary_is_non_vacuous_and_matches_scalar_bench():
    from src.engines import v12_lineup_batch as batch

    position_signature = (
        "GK",
        "GK",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "MID",
        "MID",
        "MID",
        "MID",
        "MID",
        "FWD",
        "FWD",
        "FWD",
    )
    layout = batch._family_layout(position_signature)

    # Build the adversarial condition at the ranking-key level.  One MID
    # starter is guaranteed DNP, while the target MID bench player is certain
    # to appear.  Its blank mass is exactly near a 9-decimal half boundary;
    # expected points are chosen so the resulting bench utility is near a
    # 6-decimal half boundary.
    boundary_blank = 0.1234567895
    boundary_utility = 0.9999995
    boundary_expected = (
        boundary_utility + 0.20 * boundary_blank
    )

    def near_half(value: float, decimals: int) -> bool:
        scaled = float(value) * (10.0 ** decimals)
        fraction = scaled - np.floor(scaled)
        tolerance = 64.0 * abs(float(np.spacing(scaled)))
        return abs(fraction - 0.5) <= tolerance

    raw_ranking_keys = (
        (boundary_expected - 0.20 * boundary_blank, 6),
        (boundary_blank, 9),
    )
    boundary_hits = sum(
        1
        for value, decimals in raw_ranking_keys
        if near_half(value, decimals)
    )
    assert boundary_hits > 0
    assert boundary_hits == len(raw_ranking_keys)

    surfaces = []
    for slot, position in enumerate(position_signature):
        mean = boundary_expected if slot == 7 else 0.25
        p_dnp = 1.0 if slot == 8 else 0.0
        surfaces.append(
            _direct_surface(
                slot + 1,
                position,
                mean=mean,
                p_dnp=p_dnp,
                cond_blank=boundary_blank if slot == 7 else 0.0,
                cond_ge8=0.0,
                cond_ge10=0.0,
            )
        )

    arrays = {
        "elements": np.asarray(
            [[row["element"] for row in surfaces]],
            dtype=np.int64,
        ),
        "position_codes": np.asarray(
            [[batch.POS_CODE[row["position"]] for row in surfaces]],
            dtype=np.int8,
        ),
        "p_dnp": np.asarray(
            [[row["p_dnp"] for row in surfaces]],
            dtype=np.float64,
        ),
        "p_cameo": np.asarray(
            [[row["p_cameo"] for row in surfaces]],
            dtype=np.float64,
        ),
        "p_appearance": np.asarray(
            [[row["p_appearance"] for row in surfaces]],
            dtype=np.float64,
        ),
        "xpts_mean": np.asarray(
            [[row["xpts_mean"] for row in surfaces]],
            dtype=np.float64,
        ),
        "shortfall": np.asarray(
            [[row["expected_shortfall"] for row in surfaces]],
            dtype=np.float64,
        ),
        "excess": np.asarray(
            [[row["expected_excess_ge_8"] for row in surfaces]],
            dtype=np.float64,
        ),
        "conditioned_mean": np.asarray(
            [[
                row["appearance_conditioned"]["expected_points"]
                for row in surfaces
            ]],
            dtype=np.float64,
        ),
        "conditioned_blank": np.asarray(
            [[
                row["appearance_conditioned"]["p_fpl_blank"]
                for row in surfaces
            ]],
            dtype=np.float64,
        ),
        "conditioned_ge8": np.asarray(
            [[
                row["appearance_conditioned"]["p_points_ge_8"]
                for row in surfaces
            ]],
            dtype=np.float64,
        ),
        "conditioned_ge10": np.asarray(
            [[
                row["appearance_conditioned"]["p_points_ge_10"]
                for row in surfaces
            ]],
            dtype=np.float64,
        ),
    }

    legal_index = next(
        index
        for index, row in enumerate(layout["legal"])
        if 8 in row and 7 not in row
    )
    legal_row = set(int(slot) for slot in layout["legal"][legal_index])
    bench_slots = [slot for slot in range(15) if slot not in legal_row]
    reserve_slot = next(
        slot for slot in bench_slots if position_signature[slot] == "GK"
    )
    outfield_slots = [
        slot for slot in bench_slots if position_signature[slot] != "GK"
    ]
    assert 7 in outfield_slots

    starters = [surfaces[slot] for slot in sorted(legal_row)]
    reserve_gk = surfaces[reserve_slot]
    outfield_bench = [surfaces[slot] for slot in outfield_slots]

    scalar_winner, _ = optimize_bench_order(
        starters,
        reserve_gk,
        outfield_bench,
        include_winner_blocking_counterfactual=False,
        publish_alternatives=False,
        include_winner_slots=False,
    )
    batch_result = batch._family_bench_kernel(
        layout=layout,
        arrays=arrays,
    )

    observed_order = batch_result["order_elements"][
        0,
        legal_index,
    ].tolist()
    assert observed_order == scalar_winner["order"]
    assert (
        batch_result["bench_order_utility"][0, legal_index]
        == scalar_winner["bench_order_utility"]
    )
    assert (
        batch_result["selected_blank"][0, legal_index]
        == scalar_winner[
            "expected_selected_blank_probability_mass"
        ]
    )


def test_p17_family_bench_tie_rank_memoizes_across_gw(monkeypatch):
    from src.engines import v12_lineup_batch as batch

    batch._family_bench_permutation_tie_rank_cached.cache_clear()
    signature = (
        "GK",
        "GK",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "DEF",
        "MID",
        "MID",
        "MID",
        "MID",
        "MID",
        "FWD",
        "FWD",
        "FWD",
    )
    elements = np.arange(1, 16, dtype=np.int64)[None, :]
    calls = {"count": 0}
    original = batch._bench_permutation_tie_rank

    def counted(element_rows, permutations):
        calls["count"] += 1
        return original(element_rows, permutations)

    monkeypatch.setattr(
        batch,
        "_bench_permutation_tie_rank",
        counted,
    )
    key = elements.tobytes()
    first = batch._family_bench_permutation_tie_rank_cached(
        key,
        1,
        signature,
    )
    second = batch._family_bench_permutation_tie_rank_cached(
        key,
        1,
        signature,
    )
    assert calls["count"] == 1
    assert np.array_equal(first, second)


def test_p17_captain_rounding_boundary_uses_scalar_oracle():
    from src.engines import v12_lineup_batch as batch

    signature = (
        "GK", "GK",
        "DEF", "DEF", "DEF", "DEF", "DEF",
        "MID", "MID", "MID", "MID", "MID",
        "FWD", "FWD", "FWD",
    )
    layout = batch._family_layout(signature)
    elements = np.arange(1, 16, dtype=np.int64)[None, :]

    # Pinned NumPy/Python semantics disagree at this six-decimal half
    # boundary.  The prerequisite makes the test fail loudly if that ceases
    # to be true rather than silently becoming non-adversarial.
    boundary = 0.0041205
    competitor = 0.0041206
    assert batch._near_decimal_half(
        np.asarray([boundary]),
        6,
    )[0]
    assert round(boundary, 6) != float(np.round(boundary, 6))

    xpts = np.full((1, 15), 0.001, dtype=np.float64)
    xpts[0, 7] = boundary
    xpts[0, 8] = competitor
    zeros = np.zeros_like(xpts)
    captain = batch._family_captain_kernel(
        layout=layout,
        elements=elements,
        xpts_mean=xpts,
        shortfall=zeros,
        excess=zeros,
        p_dnp=zeros,
    )
    xi_index = next(
        index
        for index, row in enumerate(layout["legal"])
        if 7 in row and 8 in row
    )
    surfaces = [
        _direct_surface(
            slot + 1,
            signature[slot],
            mean=float(xpts[0, slot]),
            p_dnp=0.0,
            cond_blank=0.0,
            cond_ge8=0.0,
            cond_ge10=0.0,
        )
        for slot in range(15)
    ]
    scalar_pair = _best_captain_vice_pair(
        [surfaces[int(slot)] for slot in layout["legal"][xi_index]]
    )
    observed_captain = int(
        elements[
            0,
            int(captain["captain_index"][0, xi_index]),
        ]
    )
    observed_vice = int(
        elements[
            0,
            int(captain["vice_index"][0, xi_index]),
        ]
    )
    assert observed_captain == scalar_pair["captain_element"]
    assert observed_vice == scalar_pair["vice_element"]
    assert (
        captain["pair_utility"][0, xi_index]
        == scalar_pair["pair_utility"]
    )


def test_p17_family_route_first_match_tie_matches_scalar_oracle():
    from src.engines import v12_lineup_batch as batch
    from src.engines import v12_package_utility as package

    projections, candidates = _cross_route_projection_fixture(20)
    tie_template = _projection(
        999999,
        "MID",
        meanish=5.0,
        p_start=1.0,
        p_regular=0.0,
        p_late=0.0,
        p_dnp=0.0,
        blank=0.10,
        upside=0.20,
        tactical=60.0,
    )
    template_xmins = deepcopy(tie_template["xmins"])
    template_tactical = deepcopy(
        tie_template["tactical_role_component"]
    )
    template_gw = deepcopy(tie_template["xpts_by_gw"][0])
    for row in projections["players"]:
        row["xmins"] = deepcopy(template_xmins)
        row["tactical_role_component"] = deepcopy(template_tactical)
        row["xpts_by_gw"] = [
            {**deepcopy(template_gw), "gw": gw}
            for gw in range(GW, GW + 5)
        ]

    owned = projections["players"][:15]
    base_ids = tuple(sorted(int(row["element"]) for row in owned))
    owned_by_id = {int(row["element"]): row for row in owned}
    candidate_by_position = {
        position: [
            int(row["element"])
            for row in candidates
            if row["position"] == position
        ]
        for position in ("GK", "DEF", "MID", "FWD")
    }
    outgoing_by_position = {}
    for element in base_ids:
        position = owned_by_id[element]["position"]
        outgoing_by_position.setdefault(position, element)

    squads = [base_ids]
    representative_indices = [0]
    for position in ("GK", "DEF", "MID", "FWD"):
        start = len(squads)
        outgoing = outgoing_by_position[position]
        for incoming in candidate_by_position[position][:16]:
            squads.append(
                tuple(
                    sorted(
                        (set(base_ids) - {outgoing})
                        | {incoming}
                    )
                )
            )
        representative_indices.extend((start, len(squads) - 1))
    assert len(squads) == 65

    actual, proof = batch.optimize_lineup_horizons_exact_batch(
        projections,
        squads,
        planning_gw=GW,
        generated_at=GENERATED,
        batch_size=512,
    )
    assert (
        proof["execution_kernel"]
        == "ROUTE_FAMILY_CORE14_AFFINE_EXACT_P1_7"
    )

    keys = (
        "route_utility",
        "expected_fpl_points",
        "distributional_downside",
        "supportable_upside",
        "formation",
        "starting_xi",
        "bench_gk",
        "bench_order",
        "captain",
        "vice_captain",
    )
    for index in representative_indices:
        for offset in range(5):
            expected = package._lineup_decision(
                projections,
                squads[index],
                gw=GW + offset,
                generated_at=GENERATED,
            )
            observed = actual[index]["per_gw"][offset]
            assert tuple(observed.get(key) for key in keys) == tuple(
                expected.get(key) for key in keys
            )
