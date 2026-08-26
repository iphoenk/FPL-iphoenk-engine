import importlib
from pathlib import Path

from src.v5.module_registry import module_specs
from src.v5.prediction_view import compact_prediction_view
from src.v5.service_registry import module_owners, service_specs, validate_registry
from src.v5.services.decision import handle as decision_handle
from src.v5.services.truth import handle as truth_handle

ROOT = Path(__file__).resolve().parents[1]


def test_microservice_registry_is_valid_and_covers_every_module_once():
    assert validate_registry() == []
    modules = {m.name for m in module_specs()}
    owners = module_owners()
    assert set(owners) == modules
    assert len(owners) == len(modules)


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


def test_truth_context_runs_without_network_and_uses_service_boundary():
    bootstrap = {
        "events": [
            {
                "id": 2,
                "is_current": True,
                "is_next": False,
                "finished": False,
                "deadline_time": "2026-08-29T10:00:00Z",
            }
        ],
        "elements": [],
        "teams": [],
    }
    context = truth_handle("context", {"bootstrap": bootstrap, "now": "2026-08-29T09:00:00Z"})
    assert context["phase"] == "PRE_DEADLINE"
    assert context["planning_gw"] == 2


def test_decision_service_bridge_does_not_claim_production_recommendation():
    result = decision_handle("summarize", {"truth": {}, "price": {}, "prediction": {}})
    assert result["production_recommendation"] is None
    assert result["status"] == "BRIDGE_ONLY_NO_PRODUCTION_RECOMMENDATION"


def test_prediction_network_view_is_bounded_and_omits_full_provenance():
    fixtures = [
        {
            "event": event,
            "xpts": float(event),
            "lower80": 0.0,
            "upper80": 10.0,
            "xmins": {
                "start_probability": 0.9,
                "bench_probability": 0.08,
                "dnp_probability": 0.02,
                "expected_minutes": 80,
                "p60": 0.85,
            },
            "provenance": {"large": "should-not-cross-service-boundary"},
        }
        for event in range(1, 9)
    ]
    compact = compact_prediction_view(
        {
            "schema_version": 470,
            "model_version": "test",
            "players": [
                {
                    "element": 1,
                    "name": "Test",
                    "position": "MID",
                    "stable_key": "test",
                    "xpts_3": 15.0,
                    "xpts_5": 25.0,
                    "xpts_10": 50.0,
                    "xpts_15": 75.0,
                    "mean_xpts": 5.0,
                    "uncertainty": 1.0,
                    "fixtures": fixtures,
                    "priors": {"nailed_prior": 0.9},
                }
            ],
        }
    )
    player = compact["players"][0]
    assert len(player["fixtures"]) <= 5
    assert all("provenance" not in row for row in player["fixtures"])
    assert compact["network_contract"]["full_provenance_omitted"] is True
