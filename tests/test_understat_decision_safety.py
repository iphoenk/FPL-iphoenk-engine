from __future__ import annotations

from copy import deepcopy

from src.engines.v4_tactical_serving import _apply_watchlist_close_call
from src.intelligence.understat_package_context import augment_package_tactical_context


def test_watchlist_positive_tactics_cannot_erase_start_security():
    policy = {
        "close_call": {
            "watchlist_base_score_margin": 0.15,
            "minimum_confidence": 0.6,
            "max_start_probability_disadvantage": 0.05,
            "max_dnp_probability_disadvantage": 0.05,
        }
    }
    rows = [
        {"element": 1, "score": 5.00, "xpts_5": 5.0, "start_probability_5": 0.90, "dnp_probability_5": 0.05, "understat_close_call": {"state": "NEUTRAL", "confidence": 0.8}},
        {"element": 2, "score": 4.95, "xpts_5": 4.95, "start_probability_5": 0.55, "dnp_probability_5": 0.30, "understat_close_call": {"state": "POSITIVE", "confidence": 1.0}},
    ]
    selected = _apply_watchlist_close_call(rows, 1, policy)
    assert selected[0]["element"] == 1


def test_package_understat_context_is_annotation_only_and_preserves_decision():
    challenger = {
        "multi_transfer_packages": [
            {
                "out": [{"element": 1}],
                "in": [{"element": 2}],
                "decision": "REVIEW_NOW",
                "hit_context": {"hit_cost": 4},
                "net_projected_gain": 2.0,
            }
        ]
    }
    predictions = {
        "players": [
            {"element": 1, "fixtures": [{"xmins": {"start_probability": 0.9, "expected_minutes": 80, "dnp_probability": 0.05}}]},
            {"element": 2, "fixtures": [{"xmins": {"start_probability": 0.85, "expected_minutes": 75, "dnp_probability": 0.08}}]},
        ]
    }
    understat = {
        "health": {"status": "AVAILABLE"},
        "source": {"freshness": "FRESH"},
        "tactical_matchups": {
            "1": {"state": "NEUTRAL", "confidence": 0.8},
            "2": {"state": "POSITIVE", "confidence": 0.9},
        },
    }
    before = deepcopy(challenger)
    out = augment_package_tactical_context(challenger, predictions=predictions, understat=understat)
    package = out["multi_transfer_packages"][0]
    assert package["decision"] == before["multi_transfer_packages"][0]["decision"]
    assert package["hit_context"] == before["multi_transfer_packages"][0]["hit_context"]
    assert package["net_projected_gain"] == before["multi_transfer_packages"][0]["net_projected_gain"]
    assert package["understat_decision_invariant"]["unchanged"] is True
    assert package["understat_tactical_context"]["tactical_alone_authorizes_hit"] is False
    assert out["understat_package_intelligence"]["decision_authority"] is False
