"""Regression contracts for bounded P1 section-evidence repair.

All fixtures are synthetic; no private team payload or live FPL state is used.
"""
from src.engines.v12_report_orchestration import (
    _render_deep_visible_contract_lines,
    _render_package_frontier_lines,
)


def _synthetic_s14(*, mc_route="route-A", checkpoint_paths=500_000,
                   route_ids=None, mean_delta=-2.25):
    route_ids = ["HOLD", "route-A"] if route_ids is None else route_ids
    return {
        "selected_route_id": "HOLD",
        "package_routes": [
            {"route": "HOLD", "action_verdict": "WAIT"},
            {"route": "route-A", "action_verdict": "WAIT", "moves": {}},
        ],
        "monte_carlo": {
            "execution_state": "EXECUTED",
            "actual_paths": 500_000,
            "selected_route_id": mc_route,
            "route_ids": route_ids,
            "horizons": [1, 3, 5],
            "common_random_numbers": True,
            "package_integration": {"convergence_route_id": mc_route},
            "convergence_evidence": {
                "status": "PASS",
                "checkpoints": [
                    {
                        "paths": checkpoint_paths,
                        "mean_route_delta": mean_delta,
                        "p_route_gt_hold": 0.39,
                        "p10_delta": -11.0,
                        "p50_delta": -2.0,
                        "p90_delta": 8.0,
                        "expected_regret": 3.2,
                        "mean_delta_mcse": 0.027,
                    }
                ],
            },
        },
    }


def test_s14_500k_final_checkpoint_bound_to_mc_route_and_five_gw_not_hold():
    text = "\n".join(_render_package_frontier_lines(
        _synthetic_s14(), section_state="COMPLETE"
    ))
    assert "MC reference route: route-A; comparison: HOLD; horizon: 5GW" in text
    assert "Governing S14 decision: HOLD" in text
    assert "Mean delta (5GW, pts): -2.250" in text
    assert "P(MC route > HOLD): 39.00%" in text
    assert "Q10 / P50 / Q90 (5GW, pts): -11.000 / -2.000 / 8.000" in text
    assert "Expected regret (5GW, pts): 3.200" in text
    assert "Mean delta MCSE (pts): 0.0270" in text
    assert "### VERDICT\nHOLD" in text


def test_s14_fail_closed_on_missing_route_identity():
    text = "\n".join(_render_package_frontier_lines(
        _synthetic_s14(mc_route="route-absent"), section_state="COMPLETE"
    ))
    assert "MC_ROUTE_IDENTITY_UNBOUND" in text
    assert "Mean delta: UNAVAILABLE" in text
    assert "Mean delta (5GW, pts): -2.250" not in text


def test_s14_fail_closed_on_mismatched_final_checkpoint_paths():
    text = "\n".join(_render_package_frontier_lines(
        _synthetic_s14(checkpoint_paths=250_000), section_state="COMPLETE"
    ))
    assert "FINAL_500K_CHECKPOINT_NOT_VALIDATED" in text
    assert "Mean delta: UNAVAILABLE" in text


def test_s14_fail_closed_on_nonfinite_checkpoint_number():
    text = "\n".join(_render_package_frontier_lines(
        _synthetic_s14(mean_delta=float("nan")), section_state="COMPLETE"
    ))
    assert "FINAL_500K_CHECKPOINT_NOT_VALIDATED" in text
    assert "Mean delta: UNAVAILABLE" in text


def _visible(section, content):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section, content=content,
        owned_ids=set(), owned_names={}
    )
    return "\n".join(lines)


def test_s10_no_likelihood_is_explicitly_uncalibrated_not_a_probability():
    text = _visible("S10", {"rows": [
        {"name": "Alpha", "current_price": 5.5, "direction": "RISE",
         "official_or_provider_progress": 110.0,
         "freshness": "FRESH", "source_age_minutes": 0.5,
         "prediction_strength": "UNAVAILABLE",
         "date_state": "DATE_UNAVAILABLE"},
    ]})
    assert "NOT_CALIBRATED" in text
    assert "NATIVE_FIELD 0/1 populated" in text
    assert "progress is NOT a calibrated change probability" in text
    assert "Predictor status: FRESH" in text


def test_s10_preserves_native_likelihood_per_player_without_inventing_it():
    text = _visible("S10", {"rows": [
        {"name": "Alpha", "prediction_strength": "LIKELY",
         "current_price": 5.5, "direction": "RISE"},
        {"name": "Beta", "prediction_strength": None,
         "current_price": 6.0, "direction": "FALL"},
    ]})
    assert "NATIVE_FIELD 1/2 populated" in text
    assert "| Alpha |" in text and "LIKELY" in text
    assert "| Beta |" in text and "NOT_CALIBRATED" in text


def test_s02_start_provenance_and_dnp_are_visible_with_no_recomputed_pstart():
    text = _visible("S02", {"rows": [
        {"name": "Alpha", "position": "MID", "p_start": 0.8299,
         "p_dnp": 0.0905, "xmins": 71.4,
         "p_start_evidence": {
             "quality": "PRIOR_DOMINATED", "source": "V12_PLAYER_MINUTES",
             "confidence": "LOW", "signals": ["neutral_prior"],
             "signal_count": 1,
         }}
    ]})
    assert "0.8299" in text and "0.0905" in text
    assert "PRIOR_DOMINATED" in text
    assert "Pstart evidence" in text


def test_s08_distribution_tail_and_unavailable_joint_cvc_remain_honest():
    text = _visible("S08", {
        "captain_profiles": [
            {"player": "Alpha", "football_rank": 1, "expected_points": 5.6,
             "p_blank": 0.4, "p_ge_10": 0.24, "p_ge_15": 0.08,
             "q75": 9, "q90": 14, "variance": 23.0, "p_dnp": 0.1}
        ],
        "decision_state": "PREPARE",
    })
    assert "P>=15" in text and "Variance" in text and "P(DNP)" in text
    assert "Joint C/VC MC: UNAVAILABLE" in text
    assert "CAPTAIN DECISION NOT LOCKED" in text
