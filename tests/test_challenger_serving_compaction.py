from __future__ import annotations

import json

from src.engines.report_enrichment import _comparator_user_block, _serving_battle


def test_serving_battle_keeps_decision_evidence_without_nested_payload_bloat() -> None:
    huge = {f"feature_{i}": "x" * 1000 for i in range(100)}
    raw = {
        "owned": {"element": 1, "name": "Owned", "position": "DEF", "sell_cost": 45, "official_ownership": "3.0"},
        "challenger": {"element": 2, "name": "In", "position": "DEF", "now_cost": 45, "official_ownership": "1.0"},
        "v3_edge": {"3gw": {"projected_edge": 1.0}, "5gw": {"projected_edge": 3.0}, "10_15gw": {"10": {"projected_edge": 5.0}}},
        "next_matchup": {
            "owned": {"evidence_state": "READY", **huge},
            "challenger": {"evidence_state": "READY", **huge},
        },
        "rest_congestion": {
            "owned": {"state": "NORMAL", **huge},
            "challenger": {"state": "NORMAL", **huge},
        },
        "predictor": {"challenger": {"direction": "RISE", "urgency": "HIGH", "fresh": True, **huge}},
        "structural_impact": {"affordable": True, "net_projected_gain": 3.1, "canonical_single_transfer_package": huge},
        "decision": "MATERIAL_UPGRADE",
        "reason": "material challenger edge",
        "confidence": "MEDIUM",
    }
    served = _serving_battle(raw)
    encoded = json.dumps(served)
    assert len(encoded) < 10_000
    assert "feature_99" not in encoded
    assert served["next_matchup"]["challenger"]["evidence_state"] == "READY"
    assert served["predictor"]["direction"] == "RISE"
    assert served["structural_impact"]["net_projected_gain"] == 3.1


def test_user_comparator_block_is_summary_not_second_full_decision_copy() -> None:
    payload = {
        "contract": "OWNED_CHALLENGER_DECISION_V3",
        "owner": "decision.owned_challenger_evaluation",
        "status": "READY",
        "owned_count": 15,
        "governed_watchlist_count": 20,
        "material_candidate_count": 8,
        "mandatory_review_count": 2,
        "comparison_count": 120,
        "main_transfer_battles": [{"decision": "REVIEW"}] * 10,
        "multi_transfer_alternatives": [{"replacements": 1, "robust_gain_vs_hold": 2.0}],
        "publication_validation": {"status": "PASS"},
        "decision": {"state": "REVIEW", "execution_authorized": False},
    }
    served = _comparator_user_block(payload)
    assert served["capability_status"] == "GOVERNED_DECISION"
    assert served["material_candidate_count"] == 8
    assert served["main_transfer_battle_count"] == 10
    assert "main_transfer_battles" not in served
    assert served["technical_evidence_ref"].startswith("data/dss_watchlist.json")
