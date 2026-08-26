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


def test_microservice_transport_resilience_is_registry_driven_and_persistence_safe():
    architecture = _load("config/v5_architecture_principles.json")["principles"]["microservices"]
    transport_path = architecture["transport_registry"]
    transport = _load(transport_path)
    requirements = set(architecture["requirements"])

    assert "registry-driven retry and circuit-breaker policy" in requirements
    assert "non-idempotent persistence operations are never automatically retried" in requirements
    assert "transport retry/circuit observability" in requirements
    assert transport["connection_pool"]["enabled"] is True
    assert transport["circuit_breaker"]["enabled"] is True
    assert transport["retry"]["policies"]["idempotent"]["max_attempts"] >= 2
    assert transport["retry"]["policies"]["non_idempotent"]["max_attempts"] == 1
    assert transport["retry"]["operation_policy"]["snapshot.write"] == "non_idempotent"
    assert transport["retry"]["operation_policy"]["snapshot.snapshot"] == "non_idempotent"

    client_source = (ROOT / "src/v5/service_client.py").read_text(encoding="utf-8")
    orchestrator_source = (ROOT / "src/v5/services/orchestrator.py").read_text(encoding="utf-8")
    assert "transport_post" in client_source
    assert "transport_attempts" in orchestrator_source
    assert "transport_circuit" in orchestrator_source


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
