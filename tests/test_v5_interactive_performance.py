from __future__ import annotations

import json
from time import perf_counter

from src.v5.config_cache import load_json_config
from src.v5.evaluation.owned_challenger_comparator import compare
from src.v5.persistence import read_artifact, write_artifact


def _gw(mean: float):
    return [{"gw": i + 2, "mean": mean, "std": 1.0, "fixtures": [{"home": True, "opponent": i + 1, "mean": mean, "std": 1.0}]} for i in range(5)]


def _player(element: int, position: str, cost: int, mean: float):
    return {"element": element, "name": f"P{element}", "position": position, "team_id": (element % 20) + 1, "now_cost": cost, "status": "a", "xpts_by_gw": _gw(mean), "xpts_5": mean * 5, "xmins": {"expected_minutes": 80, "start_probability": .9, "dnp_probability": .04}, "role": {"rotation_risk": .1, "competition_pressure": .1}, "projection_confidence": "HIGH"}


def test_comparator_is_bounded_and_within_budget():
    budgets = load_json_config("config/v5_performance_budgets.json")["budgets"]
    positions = ["GK", "DEF", "MID", "FWD"]
    owned = [_player(i + 1, positions[i % 4], 50 + (i % 6) * 5, 3.0 + (i % 5) * .2) for i in range(15)]
    challengers = [_player(100 + i, positions[i % 4], 50 + (i % 6) * 5, 3.4 + (i % 7) * .2) for i in range(20)]
    prediction = {"planning_gw": 2, "players": owned + challengers}
    team = {"owned_ids": [row["element"] for row in owned], "finance": {"bank": 10, "players": [{"element": row["element"], "sell_cost": row["now_cost"], "now_cost": row["now_cost"]} for row in owned]}}
    watchlist = {"status": "READY", "positions": {pos: [{"element": row["element"], "position": pos, "admission_status": "STRICT"} for row in challengers if row["position"] == pos] for pos in positions}}
    started = perf_counter()
    result = compare(prediction=prediction, team=team, watchlist=watchlist, transfer_state={"free_transfers": 2, "authoritative": True})
    elapsed_ms = (perf_counter() - started) * 1000
    assert result["pair_count"] <= int(budgets["owned_challenger_max_pairs"])
    assert elapsed_ms <= float(budgets["owned_challenger_comparator_ms"]), elapsed_ms


def test_hot_artifact_read_is_subsecond_contract(tmp_path, monkeypatch):
    import src.v5.persistence as persistence
    budgets = load_json_config("config/v5_performance_budgets.json")["budgets"]
    monkeypatch.setattr(persistence, "data_root", lambda: tmp_path)
    payload = {"schema_version": 1, "user_report": {"decision": {"state": "HOLD"}}, "owned_vs_challenger": {"pairs": [{"element": i, "classification": "WATCH_CHALLENGER"} for i in range(60)]}}
    write_artifact("latest", payload)
    started = perf_counter()
    loaded = read_artifact("latest", {})
    elapsed_ms = (perf_counter() - started) * 1000
    assert loaded == payload
    assert elapsed_ms <= float(budgets["interactive_artifact_read_ms"]), elapsed_ms
    assert float(budgets["interactive_target_seconds"]) <= 1.0
    assert float(budgets["interactive_decision_regeneration_ms"]) < 1000.0
