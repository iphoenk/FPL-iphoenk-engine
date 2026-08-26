import json
import time
from pathlib import Path

from src.models.projection import project_points
from src.rules import GOAL_POINTS, POSITION_TO_ELEMENT_TYPE

ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_architecture_principles_are_mandatory():
    cfg = _load("config/v5_architecture_principles.json")
    assert cfg["principles"]["avoid_hardcode"]["required"] is True
    assert cfg["principles"]["modular_authority"]["required"] is True
    assert cfg["principles"]["microservices"]["required"] is True
    assert cfg["principles"]["microservices"]["architecture"] == "BOUNDED_CONTEXT_MICROSERVICES"
    assert cfg["principles"]["performance_first"]["required"] is True


def test_projection_uses_rules_authority_for_goal_points():
    assert GOAL_POINTS[POSITION_TO_ELEMENT_TYPE["GK"]] == 10


def test_projection_microbenchmark_within_bootstrap_budget():
    budgets = _load("config/v5_performance_budgets.json")["budgets"]
    player = {
        "status": "a",
        "chance_of_playing_next_round": 100,
        "minutes": 90,
        "starts": 1,
        "element_type": 3,
    }
    advanced = {"xg_per90": 0.3, "xa_per90": 0.2}
    start = time.perf_counter()
    for _ in range(100):
        project_points(player, advanced, 3.0)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms <= budgets["projection_100_players_ms"], elapsed_ms
