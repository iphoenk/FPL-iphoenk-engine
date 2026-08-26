import importlib
from pathlib import Path

from src.v5.module_registry import module_specs
from src.v5.service_registry import module_owners, service_specs, validate_registry
from src.v5.services.decision import handle as decision_handle
from src.v5.services.evaluation import handle as evaluation_handle
from src.v5.services.governance import handle as governance_handle
from src.v5.services.prediction import handle as prediction_handle
from src.v5.services.truth import handle as truth_handle

ROOT = Path(__file__).resolve().parents[1]


def test_microservice_registry_is_valid_and_covers_every_module_once():
    assert validate_registry() == []
    modules = {m.name for m in module_specs()}
    owners = module_owners()
    assert set(owners) == modules
    assert len(owners) == len(modules)
    assert {"evaluation", "governance"}.issubset({s.service_id for s in service_specs()})


def test_all_registered_service_handlers_are_importable():
    for service in service_specs():
        module_name, function_name = service.handler.split(":", 1)
        handler = getattr(importlib.import_module(module_name), function_name)
        assert callable(handler), service.service_id


def test_service_ports_are_unique_and_compose_declares_all_services():
    services = service_specs()
    assert len({s.port for s in services}) == len(services)
    compose = (ROOT / "deploy/v5/docker-compose.yml").read_text(encoding="utf-8")
    for service in services:
        assert f"  {service.service_id}:" in compose
        assert f"V5_SERVICE_ID: {service.service_id}" in compose


def test_truth_context_runs_without_network_and_exposes_rules_contract():
    bootstrap = {"events": [{"id": 2, "is_current": True, "is_next": False, "finished": False, "deadline_time": "2026-08-29T10:00:00Z"}], "elements": [], "teams": []}
    context = truth_handle("context", {"bootstrap": bootstrap, "now": "2026-08-29T09:00:00Z"})
    rules = truth_handle("rules", {"bootstrap": bootstrap})
    assert context["phase"] == "PRE_DEADLINE"
    assert context["planning_gw"] == 2
    assert rules["ruleset_id"] == "FPL_2026_27"
    assert rules["goal_points"]["1"] == 10


def test_decision_service_is_not_bridge_only():
    status = decision_handle("status", {})
    assert status["status"] == "ACTIVE"
    assert status["bridge_only"] is False


def test_p0_prediction_service_owns_xmins_and_team_strength_without_v4_bridge():
    status = prediction_handle("status", {})
    assert status["status"] == "ACTIVE"
    assert status["bridge_only"] is False
    source = (ROOT / "src/v5/services/prediction.py").read_text(encoding="utf-8")
    assert "prediction_bridge" not in source
    assert "src.v5.intelligence.projection" in source


def test_evaluation_and_governance_are_independent_services():
    assert evaluation_handle("status", {})["status"] == "ACTIVE"
    assert governance_handle("status", {})["status"] == "ACTIVE"
    owners = module_owners()
    assert owners["prediction_evaluation"] == "evaluation"
    assert owners["challenger_scorecard"] == "evaluation"
    assert owners["gate0"] == "governance"
    assert owners["enhancement_layers"] == "governance"
    assert owners["framework_health"] == "governance"


def test_prediction_network_contract_is_bounded_by_service_output_design():
    source = (ROOT / "src/v5/services/prediction.py").read_text(encoding="utf-8")
    core = (ROOT / "src/v5/intelligence/projection.py").read_text(encoding="utf-8")
    assert "max_fixture_rows_per_player" in core
    assert "full_provenance_omitted" in core
    assert "rates" not in source
