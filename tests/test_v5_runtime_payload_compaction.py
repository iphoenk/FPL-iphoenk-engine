import json
from pathlib import Path

from src.v5.runtime_payloads import compact_payload


def _prediction(player_count: int = 100) -> dict:
    players = []
    for element in range(1, player_count + 1):
        players.append(
            {
                "element": element,
                "name": f"P{element}",
                "position": "MID",
                "team_id": (element % 20) + 1,
                "now_cost": 50,
                "current_season": {"starts": 1, "minutes": 90},
                "xmins": {"expected_minutes": 80, "start_probability": 0.9, "dnp_probability": 0.02},
                "xpts_by_gw": [
                    {
                        "gw": gw,
                        "mean": 5.0,
                        "std": 1.2,
                        "clean_sheet_probability": 0.25,
                        "fixtures": [{"huge_unused_detail": "x" * 200}],
                    }
                    for gw in range(2, 17)
                ],
                "fixtures": [{"huge_unused_detail": "y" * 400}],
                "horizons": {"5": {"mean": 25.0, "std": 3.0}},
                "role": {"unused": "z" * 200},
                "advanced": {"unused": "a" * 200},
            }
        )
    return {
        "generated_at": "2026-08-27T14:00:00+00:00",
        "planning_gw": 2,
        "horizon_gws": 15,
        "ruleset_id": "FPL_2026_27",
        "model_version": "test-model",
        "prediction_quality": {"status": "HEALTHY"},
        "capabilities": ["xmins", "projection_uncertainty"],
        "players": players,
        "team_strength": {"unused": "b" * 5000},
    }


def test_evaluation_transport_compaction_keeps_consumed_fields_and_drops_bulk():
    prediction = _prediction()
    payload = {
        "prediction": prediction,
        "context": {"planning_gw": 2, "deadline_time": "2026-08-28T17:30:00Z"},
        "bootstrap": {"events": [{"id": 2, "finished": False}], "elements": [{"unused": "x" * 5000}]},
        "ledger": {"schema_version": 2, "records": {}},
        "observations": {"observations": []},
    }
    compact = compact_payload("evaluation", "build", payload)
    row = compact["prediction"]["players"][0]
    assert row["element"] == 1
    assert row["xmins"] == {"expected_minutes": 80, "start_probability": 0.9}
    assert row["xpts_by_gw"][0]["clean_sheet_probability"] == 0.25
    assert "fixtures" not in row
    assert list(compact["bootstrap"]) == ["events"]
    assert len(json.dumps(compact)) < len(json.dumps(payload)) * 0.45


def test_decision_finalize_transport_does_not_resend_player_universe():
    prediction = _prediction()
    payload = {
        "truth": {
            "rules": {"ruleset_id": "FPL_2026_27"},
            "team": {"authority": "user_lock", "squad": [{"element": 1}]},
            "capabilities": ["rules"],
        },
        "prediction": prediction,
        "price": {"alerts": {"alerts": [{"element": 1}]}, "capabilities": ["price_radar"]},
        "evaluation": {"capabilities": ["calibration_store"], "ledger": {"unused": "x" * 1000}},
        "prepared": {"status": "READY", "packages": {}, "lineup": {}, "capabilities": []},
        "gate0_preflight": {"pass": True, "items": []},
    }
    compact = compact_payload("decision", "finalize", payload)
    assert compact["prediction"] == {
        "model_version": "test-model",
        "ruleset_id": "FPL_2026_27",
        "capabilities": ["xmins", "projection_uncertainty"],
    }
    assert compact["truth"]["team"] == {"authority": "user_lock"}
    assert compact["price"]["alerts"]["alerts"][0]["element"] == 1
    assert compact["prepared"] is payload["prepared"]
    assert len(json.dumps(compact)) < len(json.dumps(payload)) * 0.15


def test_governance_transport_keeps_gate_and_dss_inputs_only():
    prediction = _prediction()
    decision = {
        "status": "READY",
        "packages": [{"id": "HOLD", "legal": True, "affordability": {"resulting_itb": 0}}],
        "hold": {"id": "HOLD"},
        "lineup": {"status": "READY", "formation": "3-4-3", "starters": [], "bench": []},
        "dss": {"core": {}, "extensions": {}},
        "decision_trace": {"decision_type": "HOLD", "evidence": [1], "constraints_checked": [1], "ruleset_id": "FPL_2026_27", "projection_model": "test-model"},
        "capabilities": ["lineup_optimizer"],
        "candidate_pool": {"huge": "x" * 5000},
    }
    payload = {
        "truth": {"rules": {"ruleset_id": "FPL_2026_27"}, "team": {"squad": [], "validation": {}, "finance": {}, "authority": "user_lock"}, "chip_state": {}, "capabilities": ["rules"]},
        "prediction": prediction,
        "price": {"capabilities": ["price_radar"], "prices": {"huge": "y" * 5000}},
        "evaluation": {"capabilities": ["calibration_store"], "ledger": {"huge": "z" * 5000}},
        "decision": decision,
    }
    compact = compact_payload("governance", "audit", payload)
    assert "players" not in compact["prediction"]
    assert "candidate_pool" not in compact["decision"]
    assert compact["decision"]["dss"] == decision["dss"]
    assert compact["truth"]["team"]["authority"] == "user_lock"
    assert len(json.dumps(compact)) < len(json.dumps(payload)) * 0.2


def test_unknown_transport_operation_is_unchanged():
    payload = {"a": {"b": [1, 2, 3]}}
    assert compact_payload("snapshot", "read", payload) is payload


def test_payload_projection_is_registry_driven_without_operation_branches():
    registry = json.loads(Path("config/v5_payload_contract_registry.json").read_text(encoding="utf-8"))
    assert registry["contract"] == "V5_INTERNAL_PAYLOAD_PROJECTION_V1"
    assert set(registry["contracts"]) >= {"evaluation.build", "decision.finalize", "governance.audit"}

    source = Path("src/v5/runtime_payloads.py").read_text(encoding="utf-8")
    assert 'service_id == "' not in source
    assert 'operation == "' not in source
    assert "_evaluation_prediction" not in source
    assert "_decision_finalize_prediction" not in source
    assert "_governance_truth" not in source
