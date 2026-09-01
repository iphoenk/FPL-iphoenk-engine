from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.lineup_governance import build_lineup_decision, build_package_decision
from src.engines.tactical_decision_consumption import apply_lineup_overlay


def _projection(element: int, position: str, mean: float = 5.0) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "element_type": {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position],
        "team_id": (element % 8) + 1,
        "now_cost": 50,
        "projection_confidence": "MEDIUM",
        "xmins": {
            "start_probability": 0.90,
            "bench_probability": 0.08,
            "dnp_probability": 0.02,
            "expected_minutes": 78.0,
            "availability": 1.0,
        },
        "xpts_by_gw": [{"gw": 3, "mean": mean, "std": 1.5, "fixtures": []}],
        "tactical_matchup": {
            "status": "PARTIAL",
            "evidence_confidence": "LOW",
            "player_return_routes": [],
            "opponent_vulnerabilities": [],
            "highlights": [],
        },
    }


def _fixtures() -> tuple[dict, dict, dict]:
    positions = {
        1: "GK", 2: "GK",
        3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF", 7: "DEF",
        8: "MID", 9: "MID", 10: "MID", 11: "MID", 12: "MID", 16: "MID",
        13: "FWD", 14: "FWD", 15: "FWD",
    }
    projections = {
        "planning_gw": 3,
        "players": [_projection(element, position, 5.0 + element / 100.0) for element, position in positions.items()],
    }
    lock = {
        "authoritative_phase": "pre_deadline_wc",
        "planning_override_active": True,
        "target_gw": 3,
        "wildcard_active": True,
        "players": [{"element": element, "position": positions[element], "purchase_cost": 50} for element in range(1, 16)],
    }
    resolved_ids = list(range(1, 12)) + [13, 14, 15, 16]
    team = {
        "squad_authority": "OFFICIAL_SUBMITTED",
        "projection_baseline": {
            "override_requested": True,
            "override_applied": False,
            "effective_authority": "OFFICIAL_SUBMITTED",
            "capture_rejection_reason": "INVALID_CAPTURE_EVIDENCE",
        },
        "squad": [{"element": element} for element in resolved_ids],
        "team_value_ledger": [{"element": element, "sell_cost": 50} for element in resolved_ids],
    }
    return projections, lock, team


def _package_optimizer() -> dict:
    hold = {"id": "HOLD", "legal": True, "score": {"valid": True}, "changes": 0, "outs": [], "ins": []}
    challenger = {"id": "1:8->99", "legal": True, "score": {"valid": True}, "changes": 1, "outs": [], "ins": []}
    return {"status": "READY", "hold": hold, "packages": [challenger, hold]}


def test_rejected_capture_cannot_leak_raw_lock_into_lineup_chip_or_package():
    projections, lock, team = _fixtures()
    lineup = build_lineup_decision(projections, lock, {"used": []}, team=team)
    lineup_ids = {int(row["element"]) for row in lineup["squad_rows"]}
    team_ids = {int(row["element"]) for row in team["squad"]}

    assert lineup_ids == team_ids
    assert 16 in lineup_ids and 12 not in lineup_ids
    assert lineup["squad_authority"] == "OFFICIAL_SUBMITTED"
    assert lineup["governance"]["team_state_authority_consumed"] is True
    assert lineup["governance"]["legacy_lock_fixture_fallback"] is False
    assert lineup["governance"]["rejected_user_lock_context_suppressed"] is True
    assert lineup["chip_context"]["active_chip"] is None

    package = build_package_decision(_package_optimizer(), projections, lock, team)
    assert package["manual_authority_override"] is False
    assert package["governance"]["team_state_authority_consumed"] is True
    assert package["governance"]["rejected_user_lock_cannot_freeze_package"] is True


def test_valid_wc_capture_preserves_existing_freeze_and_chip_semantics():
    projections, lock, team = _fixtures()
    team = deepcopy(team)
    team["squad_authority"] = "LOCKED_PRE_DEADLINE"
    team["projection_baseline"].update({
        "override_applied": True,
        "effective_authority": "LOCKED_PRE_DEADLINE",
        "capture_rejection_reason": None,
    })
    team["squad"] = deepcopy(lock["players"])
    team["team_value_ledger"] = [{"element": row["element"], "sell_cost": 50} for row in lock["players"]]

    lineup = build_lineup_decision(projections, lock, {"used": []}, team=team)
    package = build_package_decision(_package_optimizer(), projections, lock, team)

    assert lineup["chip_context"]["active_chip"] == "wildcard"
    assert lineup["governance"]["raw_user_lock_context_consumed"] is True
    assert package["manual_authority_override"] is True
    assert package["selected_package_id"] == "HOLD"


def test_valid_predeadline_transfer_capture_does_not_gain_new_freeze_semantics():
    projections, lock, team = _fixtures()
    lock = deepcopy(lock)
    lock["authoritative_phase"] = "pre_deadline_transfer"
    lock["wildcard_active"] = False
    team = deepcopy(team)
    team["squad_authority"] = "LOCKED_PRE_DEADLINE"
    team["projection_baseline"].update({
        "override_applied": True,
        "effective_authority": "LOCKED_PRE_DEADLINE",
        "capture_rejection_reason": None,
    })
    team["squad"] = deepcopy(lock["players"])
    team["team_value_ledger"] = [{"element": row["element"], "sell_cost": 50} for row in lock["players"]]

    package = build_package_decision(_package_optimizer(), projections, lock, team)

    assert package["manual_authority_override"] is False


def test_team_state_ledger_drift_fails_closed_before_decision():
    projections, lock, team = _fixtures()
    team = deepcopy(team)
    team["team_value_ledger"][-1]["element"] = 12

    with pytest.raises(RuntimeError, match="canonical team squad and value ledger diverged"):
        build_lineup_decision(projections, lock, {"used": []}, team=team)


def _tactical_projection(element: int, edge: bool = False) -> dict:
    return {
        "element": element,
        "name": f"T{element}",
        "tactical_matchup": {
            "status": "READY" if edge else "PARTIAL",
            "evidence_confidence": "MEDIUM" if edge else "LOW",
            "player_return_routes": ["box_pressure"] if edge else [],
            "opponent_vulnerabilities": ["box_pressure"] if edge else [],
            "highlights": ["material tactical edge"] if edge else [],
        },
    }


def _tactical_squad_row(element: int, position: str, captain_score: float = 5.0) -> dict:
    return {
        "element": element,
        "name": f"T{element}",
        "position": position,
        "selection_score": 4.0,
        "captain_score": captain_score,
        "vice_score": captain_score,
        "bench_score": 4.0,
        "start_probability": 0.90,
        "dnp_probability": 0.02,
        "lower80": 1.0,
        "upper80": 8.0,
        "score_decomposition": {"raw_xpts": 5.0},
        "attack_ceiling_proxy": 2.0,
        "focality_proxy": 0.5,
    }


def test_tactical_overlay_preserves_metadata_and_reconciles_selected_row():
    positions = {
        1: "GK", 15: "GK",
        2: "DEF", 3: "DEF", 4: "DEF", 5: "DEF", 6: "DEF",
        7: "MID", 8: "MID", 9: "MID", 10: "MID", 11: "MID",
        12: "FWD", 13: "FWD", 14: "FWD",
    }
    squad = [_tactical_squad_row(e, positions[e], captain_score=(10.0 if e == 12 else 9.8 if e == 13 else 5.0)) for e in range(1, 16)]
    base_ids = [1, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14]
    alt_ids = [1, 2, 3, 5, 7, 8, 9, 10, 12, 13, 14]
    base_risk = {"adjustment": -0.05, "governance": {"bounded_decision_adjustment_only": True}}
    alt_risk = {"adjustment": -0.04, "governance": {"bounded_decision_adjustment_only": True}}
    lineup = {
        "formation": "3-4-3",
        "squad_rows": squad,
        "starting_xi": [next(row for row in squad if row["element"] == e) for e in base_ids],
        "captain": {"element": 12, "name": "T12"},
        "vice_captain": {"element": 13, "name": "T13"},
        "captain_safe_pool": [],
        "bench": {"gk": {"element": 15}, "order": [{"element": 5}, {"element": 6}, {"element": 11}], "close_battles": []},
        "lineup_score": {"robust": 50.0, "base_robust": 50.05, "xpts_mean": 55.0, "xpts_std": 8.0, "risk_adjustment": base_risk},
        "alternatives": [
            {"formation": "3-4-3", "score": 50.0, "decision_score": 50.0, "base_score": 50.05, "risk_adjustment": base_risk, "xpts_mean": 55.0, "xpts_std": 8.0, "element_ids": base_ids},
            {"formation": "3-4-3", "score": 49.95, "decision_score": 49.95, "base_score": 49.99, "risk_adjustment": alt_risk, "xpts_mean": 54.95, "xpts_std": 8.0, "element_ids": alt_ids},
        ],
        "formation_comparison": [
            {"formation": "3-4-3", "selected": True},
            {"formation": "3-4-3", "selected": False},
        ],
        "main_starting_xi_battle": {"status": "CLOSE", "margin": 0.05},
        "chip_context": {"single_chip_rule_respected": True},
        "governance": {"team_state_authority_consumed": True, "legacy_lock_fixture_fallback": False},
    }
    projections = {"players": [_tactical_projection(e, edge=(e == 5 or e == 13)) for e in range(1, 16)]}

    result = apply_lineup_overlay(lineup, projections, persist=False)
    selected = [row for row in result["formation_comparison"] if row.get("selected") is True]

    assert 5 in {row["element"] for row in result["starting_xi"]}
    assert len(selected) == 1
    assert selected[0]["formation"] == result["formation"]
    assert result["lineup_score"]["base_robust"] == 49.99
    assert result["lineup_score"]["risk_adjustment"] == alt_risk
    assert "close_battles" in result["bench"]
    assert "score_decomposition" in result["captain"]
    assert "vice_score" in result["vice_captain"]
    assert result["governance"]["tactical_overlay_preserves_decision_transparency"] is True
    assert result["governance"]["formation_comparison_reconciled_to_final_xi"] is True
