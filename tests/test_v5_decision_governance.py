from __future__ import annotations

import copy
import time

from src.rules import LINEUP_RULES, RULESET_ID, SQUAD_RULES
from src.v5.config_cache import load_json_config
from src.v5.decision.dss_evaluator import evaluate_dss
from src.v5.decision.lineup_optimizer import optimize_lineup
from src.v5.governance.gate0 import audit as gate0_audit
from src.v5.services.decision import handle as decision_handle


def _positions() -> list[str]:
    return ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)]


def _truth() -> dict:
    squad = []
    ledger = []
    for element, position in enumerate(_positions(), start=1):
        row = {"element": element, "name": f"P{element}", "position": position, "team_id": element}
        squad.append(row)
        ledger.append({**row, "now_cost": 50, "purchase_cost": 50, "sell_cost": 50, "finance_source": "synthetic_exact", "finance_exact": True})
    return {
        "rules": {"ruleset_id": RULESET_ID, "squad": SQUAD_RULES, "lineup": LINEUP_RULES, "authority": "truth-service-test"},
        "team": {
            "authority": "synthetic",
            "squad": squad,
            "owned_ids": [row["element"] for row in squad],
            "validation": {"passed": True},
            "finance": {"players": ledger, "bank": 25, "market_value": 750, "sell_value": 750, "sell_value_complete": True, "exact_count": 15, "unresolved_elements": []},
        },
        "chip_state": {"active_chip": "wildcard", "active_chip_count": 1, "legal": True},
        "capabilities": ["universe_identity", "universe_price_position", "universe_registration", "availability", "manual_authority", "structural_fit", "sell_cost_affordability", "chip_context"],
    }


def _prediction() -> dict:
    players = []
    for element, position in enumerate(_positions(), start=1):
        by_gw = []
        for gw in range(2, 17):
            mean = 3.0 + element * 0.15 + (0.4 if position == "FWD" else 0.0)
            by_gw.append({"gw": gw, "mean": round(mean, 3), "std": 1.2})
        horizons = {str(h): {"mean": round(sum(row["mean"] for row in by_gw[:h]), 3), "std": round((h * 1.2**2) ** 0.5, 3)} for h in (3, 5, 10, 15)}
        players.append({
            "element": element, "name": f"P{element}", "team_id": element, "position": position, "now_cost": 50,
            "status": "a", "ownership_pct": float(element),
            "xmins": {"start_probability": 0.85 if element % 2 else 0.78, "bench_probability": 0.10, "dnp_probability": 0.05 if element % 2 else 0.12, "expected_minutes": 72.0},
            "xpts_by_gw": by_gw, "horizons": horizons,
            "xpts_3": horizons["3"]["mean"], "xpts_5": horizons["5"]["mean"], "xpts_10": horizons["10"]["mean"], "xpts_15": horizons["15"]["mean"],
            "mean_xpts": by_gw[0]["mean"], "uncertainty": by_gw[0]["std"], "projection_confidence": "MEDIUM",
        })
    return {
        "model_version": "synthetic-v5-prediction", "ruleset_id": RULESET_ID, "planning_gw": 2, "horizon_gws": 15, "players": players,
        "capabilities": ["xmins", "xmins_distribution", "small_sample_guard", "projection_uncertainty", "team_attacking_strength", "team_defensive_strength", "opponent_defence_dynamic", "clean_sheet_probability", "fixture_context", "fixture_swing", "horizon_3", "horizon_5", "horizon_10", "horizon_15", "price_value", "ownership_context", "bonus_route"],
    }


def _price() -> dict:
    return {"prices": {}, "alerts": {"alerts": []}, "capabilities": ["transfer_momentum", "price_intelligence"]}


def _evaluation() -> dict:
    return {"capabilities": ["prediction_evaluation", "calibration_store", "challenger_scorecard"], "accuracy": {"overall": {"sample_size": 0}}}


def _decision() -> dict:
    return decision_handle("build", {"truth": _truth(), "prediction": _prediction(), "price": _price(), "evaluation": _evaluation()})


def test_native_lineup_is_legal_and_governed():
    truth = _truth()
    lineup = optimize_lineup(truth["team"], _prediction(), truth["rules"])
    assert lineup["status"] == "READY"
    assert lineup["formation"] in LINEUP_RULES["legal_formations"]
    assert len(lineup["starters"]) == 11
    assert sum(row["position"] == "GK" for row in lineup["starters"]) == 1
    assert len(lineup["bench"]) == 4
    assert sum(row["position"] == "GK" for row in lineup["bench"]) == 1
    starter_ids = {row["element"] for row in lineup["starters"]}
    assert lineup["captain"]["element"] in starter_ids
    assert lineup["vice_captain"]["element"] in starter_ids
    assert lineup["captain"]["element"] != lineup["vice_captain"]["element"]


def test_package_and_final_lineup_share_single_authority():
    decision = _decision()
    assert decision["status"] == "READY"
    assert decision["governance"]["lineup_authority"] == "v5_decision_lineup_optimizer"
    assert decision["governance"].get("lineup_authority") == decision["lineup"]["authority"]


def test_full_gate0_passes_all_16_on_legal_synthetic_decision():
    gate = gate0_audit(_truth(), _decision())
    assert gate["registry_integrity"]["integrity_ok"] is True
    assert len(gate["items"]) == 16
    assert gate["counts"].get("PASS") == 16
    assert gate["pass"] is True


def test_gate0_rejects_negative_resulting_itb_and_package_revalidation():
    broken = copy.deepcopy(_decision())
    assert broken["packages"]
    broken["packages"][0]["affordability"]["resulting_itb"] = -1
    gate = gate0_audit(_truth(), broken)
    states = {row["id"]: row["status"] for row in gate["items"]}
    assert states["G0-06"] == "FAIL"
    assert states["G0-16"] == "FAIL"
    assert gate["pass"] is False


def test_gate0_rejects_illegal_chip_state():
    truth = _truth()
    truth["chip_state"] = {"active_chip": "wildcard", "active_chip_count": 2, "legal": False}
    gate = gate0_audit(truth, _decision())
    states = {row["id"]: row["status"] for row in gate["items"]}
    assert states["G0-14"] == "FAIL"


def test_dss_uses_capability_contract_and_does_not_fake_missing_modules():
    dss = evaluate_dss(_truth(), _price(), _prediction(), local_capabilities=["captaincy", "lineup_governance", "governed_optimizer"], external_capability_sources={"evaluation": _evaluation()["capabilities"]})
    core = {row["probe"]: row for row in dss["core"]["items"]}
    assert core["xmins"]["status"] == "ACTIVE"
    assert core["captaincy"]["status"] == "ACTIVE"
    assert core["tactical_role"]["status"] == "PARTIAL"
    assert dss["registry_integrity"] is True


def test_decision_trace_is_evidence_backed_and_never_auto_submits():
    decision = _decision()
    trace = decision["decision_trace"]
    assert trace["decision_type"] in {"HOLD", "TRANSFER_PACKAGE_REVIEW"}
    assert trace["evidence"]
    assert trace["constraints_checked"]
    assert trace["ruleset_id"] == RULESET_ID
    assert trace["projection_model"] == "synthetic-v5-prediction"
    assert trace["production_recommendation"] is None
    assert decision["production_recommendation"] is None


def test_decision_governance_bootstrap_performance_budgets():
    budgets = load_json_config("config/v5_performance_budgets.json")["budgets"]
    truth, prediction, price = _truth(), _prediction(), _price()
    started = time.perf_counter()
    optimize_lineup(truth["team"], prediction, truth["rules"])
    lineup_ms = (time.perf_counter() - started) * 1000.0
    assert lineup_ms <= float(budgets["decision_lineup_15_players_ms"]), lineup_ms
    started = time.perf_counter()
    evaluate_dss(truth, price, prediction, local_capabilities=["captaincy"])
    dss_ms = (time.perf_counter() - started) * 1000.0
    assert dss_ms <= float(budgets["dss_registry_audit_ms"]), dss_ms
    decision = _decision()
    started = time.perf_counter()
    gate0_audit(truth, decision)
    gate_ms = (time.perf_counter() - started) * 1000.0
    assert gate_ms <= float(budgets["gate0_full_16_ms"]), gate_ms
