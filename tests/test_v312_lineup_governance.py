from src.engines.lineup_governance import build_lineup_decision, build_package_decision
from src.rules import LINEUP_RULES


def _projection(element, position, mean, team_id):
    element_type = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[position]
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "element_type": element_type,
        "team_id": team_id,
        "now_cost": 50,
        "projection_confidence": "MEDIUM",
        "xmins": {
            "start_probability": 0.90,
            "bench_probability": 0.08,
            "dnp_probability": 0.02,
            "expected_minutes": 78,
        },
        "xpts_by_gw": [{"gw": 2, "mean": mean, "std": 1.5, "fixtures": []}],
    }


def _fixtures():
    positions = ["GK", "GK", "DEF", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    means = [4.8, 3.2, 5.7, 5.5, 5.3, 4.2, 3.9, 7.8, 7.1, 6.4, 5.8, 4.0, 9.5, 6.7, 6.2]
    projections = [_projection(i + 1, pos, means[i], i + 1) for i, pos in enumerate(positions)]
    lock = {
        "authoritative_phase": "pre_deadline_wc",
        "wildcard_active": True,
        "players": [{"element": i + 1, "position": pos, "purchase_cost": 50} for i, pos in enumerate(positions)],
    }
    return {"planning_gw": 2, "players": projections}, lock


def test_governed_lineup_is_legal_and_has_safe_captaincy():
    projections, lock = _fixtures()
    decision = build_lineup_decision(projections, lock, {"used": []})
    assert decision["formation"] in set(LINEUP_RULES["legal_formations"])
    assert len(decision["starting_xi"]) == 11
    assert sum(p["position"] == "GK" for p in decision["starting_xi"]) == 1
    xi_ids = {p["element"] for p in decision["starting_xi"]}
    assert decision["captain"]["element"] in xi_ids
    assert decision["vice_captain"]["element"] in xi_ids
    assert decision["captain"]["element"] != decision["vice_captain"]["element"]
    assert decision["captain"]["element"] in {p["element"] for p in decision["captain_safe_pool"]}
    assert decision["vice_captain"]["element"] in {p["element"] for p in decision["captain_safe_pool"]}
    assert decision["bench"]["gk"]["position"] == "GK"
    assert len(decision["bench"]["order"]) == 3
    assert decision["main_starting_xi_battle"]["status"] in {"CLOSE", "CLEAR", "NO_ALTERNATIVE"}
    assert decision["chip_context"]["active_chip"] == "wildcard"
    assert decision["chip_context"]["single_chip_rule_respected"] is True


def test_manual_lock_freezes_optimizer_candidate_and_revalidates_gate0():
    projections, lock = _fixtures()
    hold = {"id": "HOLD", "legal": True, "score": {"valid": True}, "changes": 0, "outs": [], "ins": []}
    challenger = {"id": "1:8->99", "legal": True, "score": {"valid": True}, "changes": 1, "outs": [], "ins": []}
    optimizer = {
        "status": "READY",
        "hold": hold,
        "packages": [challenger, hold],
    }
    decision = build_package_decision(optimizer, projections, lock, {"team_value_ledger": []})
    assert decision["optimizer_best_candidate_id"] == challenger["id"]
    assert decision["selected_package_id"] == "HOLD"
    assert decision["manual_authority_override"] is True
    assert decision["current_squad_legal"] is True
    assert decision["gate0_revalidated"] is True
    assert decision["governance"]["optimizer_is_candidate_generator_only"] is True
