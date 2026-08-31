import importlib
from pathlib import Path

from src.v5 import service_health
from src.v5.config_cache import load_json_config
from src.v5.module_registry import module_specs
from src.v5.service_registry import get_service, module_owners, service_specs, validate_registry
from src.v5.services.evaluation import handle as evaluation_handle
from src.v5.services.governance import handle as governance_handle
from src.v5.services.prediction import handle as prediction_handle
from src.v5.services.truth import handle as truth_handle

ROOT = Path(__file__).resolve().parents[1]


def _canonical_handler(service_id: str):
    spec = get_service(service_id)
    module_name, function_name = spec.handler.split(":", 1)
    return getattr(importlib.import_module(module_name), function_name)


def test_microservice_registry_is_valid_and_covers_every_module_once():
    assert validate_registry() == []
    modules = {m.name for m in module_specs()}
    owners = module_owners()
    assert set(owners) == modules
    assert len(owners) == len(modules)
    assert {"evaluation", "governance"}.issubset({s.service_id for s in service_specs()})


def test_all_registered_service_handlers_are_importable():
    for service in service_specs():
        handler = _canonical_handler(service.service_id)
        assert callable(handler), service.service_id


def test_service_ports_are_unique_and_compose_declares_all_services():
    services = service_specs()
    assert len({s.port for s in services}) == len(services)
    compose = (ROOT / "deploy/v5/docker-compose.yml").read_text(encoding="utf-8")
    for service in services:
        assert f"  {service.service_id}:" in compose
        assert f"V5_SERVICE_ID: {service.service_id}" in compose


def test_every_service_has_green_local_readiness():
    for service in service_specs():
        health = service_health.local_service_health(service.service_id)
        assert health["ready"] is True, health
        assert health["status"] == "UP"
        assert health["owned_module_count"] == len(service.owns_modules)
        assert all(row["entrypoint_ok"] and row["config_ok"] for row in health["modules"])


def test_local_readiness_degrades_when_owned_config_breaks(monkeypatch):
    original = service_health.load_json_config

    def broken(path: str):
        if path == "config/v5_decision_registry.json":
            raise RuntimeError("synthetic config failure")
        return original(path)

    monkeypatch.setattr(service_health, "load_json_config", broken)
    health = service_health.local_service_health("decision")
    assert health["ready"] is False
    assert health["status"] == "DEGRADED"
    assert any("v5_decision_registry.json" in error for error in health["local_errors"])


def test_truth_context_runs_without_network_and_exposes_rules_contract():
    bootstrap = {"events": [{"id": 2, "is_current": True, "is_next": False, "finished": False, "deadline_time": "2026-08-29T10:00:00Z"}], "elements": [], "teams": []}
    context = truth_handle("context", {"bootstrap": bootstrap, "now": "2026-08-29T09:00:00Z"})
    rules = truth_handle("rules", {"bootstrap": bootstrap})
    assert context["phase"] == "PRE_DEADLINE"
    assert context["planning_gw"] == 2
    assert rules["ruleset_id"] == "FPL_2026_27"
    assert rules["goal_points"]["1"] == 10


def test_decision_service_is_not_bridge_only_and_uses_canonical_handler():
    spec = get_service("decision")
    decision_handle = _canonical_handler("decision")
    status = decision_handle("status", {})
    assert spec.handler == "src.v5.services.decision_tactical:handle"
    assert status["status"] == "ACTIVE"
    assert status["bridge_only"] is False
    assert "tactical_decision_consumption" in status["capabilities"]
    assert status["tactical_consumption_contract"] == "TACTICAL_DECISION_CONSUMPTION_V1"


def test_core_decision_handler_is_not_registered_as_a_second_service_authority():
    handlers = {service.service_id: service.handler for service in service_specs()}
    assert handlers["decision"] == "src.v5.services.decision_tactical:handle"
    assert "src.v5.services.decision:handle" not in handlers.values()
    assert len(handlers) == len(set(handlers.values()))


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


def test_prediction_network_contract_is_registry_driven_and_projection_core_is_transport_agnostic():
    contract = load_json_config("config/v5_prediction_service_registry.json")["network_contract"]
    source = (ROOT / "src/v5/services/prediction.py").read_text(encoding="utf-8")
    core = (ROOT / "src/v5/intelligence/projection.py").read_text(encoding="utf-8")
    fields = contract["player_fields"]
    required = contract["required_player_fields"]
    fixture_fields = contract["fixture_fields"]
    assert contract["return_full_predictions_by_default"] is False
    assert contract["full_provenance_omitted"] is True
    assert contract["fixture_count"] == 5
    assert len(fields) == len(set(fields))
    assert len(fixture_fields) == len(set(fixture_fields))
    assert set(required).issubset(set(fields))
    assert {"element", "fixtures"}.issubset(set(required))
    assert "rates" not in fields
    assert "SERVICE_CONFIG" in source
    assert "_compact_player" in source
    assert "network_fixtures" not in core
    assert "max_fixture_rows_per_player" not in core
    assert '"network_contract"' not in core


def test_prediction_compactor_enforces_registry_fields_and_fixture_bound():
    import src.v5.services.prediction as prediction_service

    contract = prediction_service._network_contract()
    player = {field: f"value:{field}" for field in contract["player_fields"]}
    player["element"] = 1
    player["rates"] = {"must_not_leak": True}
    player["fixtures"] = [
        {
            "event": i + 1,
            "xpts": 1.0,
            "lower80": 0.0,
            "upper80": 2.0,
            "xmins": {"expected_minutes": 90},
            "must_not_leak": True,
        }
        for i in range(int(contract["fixture_count"]) + 2)
    ]
    compact = prediction_service._compact_player(player, contract)
    assert set(compact) == set(contract["player_fields"])
    assert "rates" not in compact
    assert len(compact["fixtures"]) == contract["fixture_count"]
    assert all(set(row) == set(contract["fixture_fields"]) for row in compact["fixtures"])
    assert all("must_not_leak" not in row for row in compact["fixtures"])

def test_price_predictor_and_squeeze_have_exactly_one_price_service_owner():
    owners = module_owners()
    assert owners["official_price_predictor"] == "price"
    assert owners["price_trajectory"] == "price"
    assert owners["price_service"] == "price"
    assert owners["price_squeeze"] == "price"
    price = get_service("price")
    assert set(price.owns_modules).issuperset({"official_price_predictor", "price_trajectory", "price_service", "price_squeeze"})


def test_evaluation_and_watchlist_do_not_import_price_business_implementation():
    evaluation = (ROOT / "src/v5/services/evaluation.py").read_text(encoding="utf-8")
    watchlist = (ROOT / "src/v5/services/watchlist.py").read_text(encoding="utf-8")
    assert "src.v5.price_squeeze" not in evaluation
    assert "src.v5.price_squeeze" not in watchlist
    assert "src.engines.price_radar" not in evaluation
    assert "src.engines.price_radar" not in watchlist


def test_orchestrator_routes_cross_context_price_overlays_to_price_service():
    routes = (load_json_config("config/v5_orchestrator_registry.json").get("routing") or {})
    assert routes["price_bind_watchlist"] == {"service": "price", "operation": "bind_watchlist_evidence"}
    assert routes["price_annotate_comparator"] == {"service": "price", "operation": "annotate_comparator"}


def test_price_adoption_does_not_restore_v3_global_settings_module():
    assert not (ROOT / "src/settings.py").exists()
