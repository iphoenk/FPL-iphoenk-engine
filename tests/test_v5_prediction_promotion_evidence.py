from src.v5.evaluation.decision_validation import decision_regret
from src.v5.evaluation.promotion_evidence import build
from src.v5.services.evaluation import handle


def _actual(points):
    return {element: {"element": element, "points": value} for element, value in points.items()}


def test_decision_regret_computes_best_legal_xi_and_captain_regret():
    owned = [
        {"element": 1, "position": "GK"}, {"element": 2, "position": "GK"},
        {"element": 3, "position": "DEF"}, {"element": 4, "position": "DEF"}, {"element": 5, "position": "DEF"}, {"element": 6, "position": "DEF"}, {"element": 7, "position": "DEF"},
        {"element": 8, "position": "MID"}, {"element": 9, "position": "MID"}, {"element": 10, "position": "MID"}, {"element": 11, "position": "MID"}, {"element": 12, "position": "MID"},
        {"element": 13, "position": "FWD"}, {"element": 14, "position": "FWD"}, {"element": 15, "position": "FWD"},
    ]
    selected = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    snapshot = {
        "lineup": {
            "starting_xi": [{"element": x} for x in selected],
            "owned_squad": owned,
            "captain": 8,
        },
        "comparator": {"comparisons": []},
    }
    actual = _actual({1: 2, 2: 8, 3: 2, 4: 2, 5: 2, 6: 10, 7: 1, 8: 3, 9: 4, 10: 5, 11: 6, 12: 12, 13: 4, 14: 5, 15: 6})
    metrics = decision_regret(snapshot, actual)
    assert metrics["captain_regret"]["value"] == 9.0
    assert metrics["xi_regret"]["status"] == "SETTLED"
    assert metrics["xi_regret"]["value"] > 0


def test_promotion_evidence_requires_genuine_predeadline_snapshot():
    ledger = {
        "records": {
            "3": {
                "gw": 3,
                "status": "SETTLED",
                "actual": {"players": [{"element": 1, "points": 5}]},
            }
        }
    }
    evidence = build(ledger, {"records": {}})
    assert evidence["decision_metrics"]["captain_regret"]["sample_size"] == 0
    assert evidence["flattened_metrics"]["captain_regret"] is None
    assert evidence["rows"][0]["genuine_predeadline_snapshot"] is False


def test_promotion_evidence_aggregates_settled_exact_metrics():
    owned = [
        {"element": 1, "position": "GK"},
        {"element": 2, "position": "GK"},
        {"element": 3, "position": "DEF"}, {"element": 4, "position": "DEF"}, {"element": 5, "position": "DEF"}, {"element": 6, "position": "DEF"}, {"element": 7, "position": "DEF"},
        {"element": 8, "position": "MID"}, {"element": 9, "position": "MID"}, {"element": 10, "position": "MID"}, {"element": 11, "position": "MID"}, {"element": 12, "position": "MID"},
        {"element": 13, "position": "FWD"}, {"element": 14, "position": "FWD"}, {"element": 15, "position": "FWD"},
    ]
    xi = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    snapshots = {
        "records": {
            "3": {
                "lineup": {"starting_xi": [{"element": x} for x in xi], "owned_squad": owned, "captain": 8},
                "comparator": {"comparisons": [{"player_out": 9, "player_in": 12, "exact_hit_cost": 4}]},
            }
        }
    }
    points = {1: 2, 2: 5, 3: 2, 4: 2, 5: 2, 6: 8, 7: 1, 8: 3, 9: 2, 10: 5, 11: 6, 12: 10, 13: 4, 14: 5, 15: 6}
    ledger = {"records": {"3": {"gw": 3, "status": "SETTLED", "actual": {"players": [{"element": k, "points": v} for k, v in points.items()]}}}}
    evidence = build(ledger, snapshots)
    assert evidence["decision_metrics"]["captain_regret"]["sample_size"] == 1
    assert evidence["decision_metrics"]["xi_regret"]["sample_size"] == 1
    assert evidence["decision_metrics"]["transfer_comparator_realized_net_gain"]["sample_size"] == 1
    assert evidence["flattened_metrics"]["transfer_comparator_realized_net_gain"] == 4.0


def test_evaluation_service_exposes_promotion_evidence_operation():
    out = handle("promotion_evidence", {"ledger": {"records": {}}, "decision_validation": {"records": {}}})
    assert out["model"] == "v5_prediction_promotion_evidence_v1"
    assert out["governance"]["postdeadline_reconstruction_forbidden"] is True
