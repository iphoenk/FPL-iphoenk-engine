from __future__ import annotations

from src.rules import LINEUP_RULES, RULESET_ID, SQUAD_RULES
from src.v5.config_cache import load_json_config
from src.v5.decision.lineup_optimizer import optimize_lineup
from src.v5.decision.package_governance import govern_packages


def _positions() -> list[str]:
    return ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)]


def _team() -> dict:
    squad = [
        {"element": element, "name": f"P{element}", "position": position, "team_id": element}
        for element, position in enumerate(_positions(), start=1)
    ]
    return {"authority": "user_lock", "squad": squad, "owned_ids": [row["element"] for row in squad]}


def _prediction() -> dict:
    players = []
    for element, position in enumerate(_positions(), start=1):
        mean = 3.0 + element * 0.15 + (0.4 if position == "FWD" else 0.0)
        start_probability = 0.90
        dnp_probability = 0.03
        if element == 15:
            mean = 12.0
            start_probability = 0.40
            dnp_probability = 0.50
        players.append(
            {
                "element": element,
                "name": f"P{element}",
                "team_id": element,
                "position": position,
                "now_cost": 50,
                "status": "a",
                "xmins": {
                    "start_probability": start_probability,
                    "bench_probability": 0.05,
                    "dnp_probability": dnp_probability,
                    "expected_minutes": 75.0,
                },
                "xpts_by_gw": [{"gw": 2, "mean": mean, "std": 1.2}],
            }
        )
    return {
        "model_version": "synthetic-v312-parity",
        "ruleset_id": RULESET_ID,
        "planning_gw": 2,
        "players": players,
    }


def _rules() -> dict:
    return {"ruleset_id": RULESET_ID, "squad": SQUAD_RULES, "lineup": LINEUP_RULES}


def test_manual_lock_freezes_official_package_but_retains_optimizer_challenger():
    hold = {
        "id": "HOLD",
        "legal": True,
        "changes": 0,
        "score": {"valid": True, "robust_score": 100.0},
    }
    challenger = {
        "id": "1:1->101",
        "legal": True,
        "changes": 1,
        "score": {"valid": True, "robust_score": 105.0},
    }
    packages = {"status": "READY", "hold": hold, "packages": [challenger, hold]}
    truth = {"context": {"phase": "PRE_DEADLINE"}, "team": {"authority": "user_lock"}}

    governed = govern_packages(packages, truth)

    assert governed["status"] == "READY"
    assert governed["selected_package_id"] == "HOLD"
    assert governed["manual_authority_override"] is True
    assert governed["optimizer_best_challenger_id"] == "1:1->101"
    assert governed["governance"]["optimizer_is_candidate_generator_only"] is True
    assert governed["governance"]["locked_composition_frozen"] is True


def test_final_lineup_exposes_safe_captain_pool_and_xi_battle():
    lineup = optimize_lineup(_team(), _prediction(), _rules())
    policy = load_json_config("config/v5_decision_registry.json")["lineup"]
    safety = policy["captain_safety"]
    alternatives = policy["alternatives"]

    assert lineup["status"] == "READY"
    assert lineup["formation"] in LINEUP_RULES["legal_formations"]
    assert 2 <= len(lineup["captain_safe_pool"]) <= int(safety["safe_pool_size"])
    assert all(
        row["start_probability"] >= float(safety["minimum_start_probability"])
        and row["dnp_probability"] <= float(safety["maximum_dnp_probability"])
        for row in lineup["captain_safe_pool"]
    )
    assert lineup["captain"]["element"] != 15
    assert lineup["vice_captain"]["element"] != 15
    assert len(lineup["alternatives"]) <= int(alternatives["publish_top_n"])
    assert lineup["alternatives"][0]["element_ids"] == sorted(row["element"] for row in lineup["starters"])
    assert lineup["main_starting_xi_battle"]["status"] in {"CLOSE", "CLEAR", "NO_ALTERNATIVE"}
    assert lineup["performance"]["final_lineup_enumeration"] == "all_legal_xi_once"
    assert lineup["performance"]["legal_xi_candidates"] > 0
