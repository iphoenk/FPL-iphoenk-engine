from __future__ import annotations

from copy import deepcopy

from src.engines.v4_tactical_serving import _apply_watchlist_close_call
from src.engines.v4_lineup_optimizer import optimize_lineup
from src.intelligence.understat_package_context import augment_package_tactical_context
from src.services.projected_value_market_challenger import rerank_visible_watchlist


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


def test_projected_value_rerank_forwards_explicit_understat_dependency():
    positions = ("GK", "DEF", "MID", "FWD")
    current = []
    for pos_index, position in enumerate(positions):
        for rank in range(5):
            current.append({
                "element": 10 * (pos_index + 1) + rank,
                "position": position,
                "score": 5.0 - rank * 0.1,
                "xpts_5": 5.0 - rank * 0.1,
            })
    discovery = {
        "candidates": [{
            "element": 99,
            "position": "GK",
            "mandatory_review": True,
            "identity_sanity": {
                "status": "PASS",
                "official_fact": {
                    "element": 99,
                    "name": "Explicit Understat GK",
                    "team_id": 1,
                    "team": "Test",
                    "position": "GK",
                    "now_cost": 45,
                    "ownership": 0.1,
                    "status": "a",
                },
            },
            "projected_value": {"score": 9.0, "value_per_million_5gw": 2.0},
        }],
    }
    predictions = {
        "players": [{
            "element": 99,
            "position": "GK",
            "xpts_5": 8.0,
            "xpts_15": 24.0,
            "uncertainty": 0.1,
            "fixtures": [{
                "opponent": 2,
                "xmins": {
                    "start_probability": 0.95,
                    "dnp_probability": 0.01,
                    "expected_minutes": 90,
                },
                "components": {},
            }],
            "priors": {"tactical_role": "GK"},
        }],
    }
    universe = {"players": [{"element": 99, "name": "Explicit Understat GK", "position": "GK"}]}
    understat = {
        "source": {"freshness": "FRESH"},
        "tactical_matchups": {
            "99": {"state": "POSITIVE", "confidence": 0.91, "dimensions": {"pressing": "EDGE"}},
        },
    }

    out = rerank_visible_watchlist(
        {"watchlist": current},
        discovery=discovery,
        predictions=predictions,
        universe=universe,
        external={},
        understat_data=understat,
        per_position=5,
    )

    promoted = next(row for row in out["watchlist"] if row.get("element") == 99)
    assert promoted["tactical"]["understat"]["state"] == "POSITIVE"
    assert promoted["tactical"]["understat"]["confidence"] == 0.91
    assert promoted["tactical"]["understat"]["direct_xpts_mutation"] is False
    assert promoted["tactical"]["understat"]["direct_xmins_mutation"] is False


def test_understat_lineup_guardrails_follow_positive_pass_contract():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    prediction_rows = []
    universe_rows = []
    locked_rows = []
    for index, position in enumerate(positions, start=1):
        element = 1000 + index
        xpts = 8.0 - index * 0.1
        prediction_rows.append({
            "element": element,
            "position": position,
            "fixtures": [{
                "xpts": xpts,
                "lower80": xpts - 1.0,
                "upper80": xpts + 1.0,
                "xmins": {
                    "start_probability": 0.95,
                    "bench_probability": 0.04,
                    "dnp_probability": 0.01,
                    "expected_minutes": 85,
                    "start_probability_confidence": 0.9,
                },
            }],
            "priors": {"tactical_role": position.lower()},
        })
        universe_rows.append({
            "element": element,
            "name": f"P{element}",
            "position": position,
            "team": f"T{(index % 5) + 1}",
        })
        locked_rows.append({"element": element})

    out = optimize_lineup(
        {"players": prediction_rows},
        {"players": universe_rows},
        {"players": locked_rows, "wildcard_active": False},
        tactical={},
    )

    assert out["guardrails"]["understat_no_direct_xpts_mutation"] is True
    assert out["guardrails"]["understat_no_direct_xmins_mutation"] is True
    assert "understat_direct_xpts_mutation" not in out["guardrails"]
    assert "understat_direct_xmins_mutation" not in out["guardrails"]
    assert all(out["guardrails"].values())
    assert out["understat_tactical"]["direct_xpts_mutation"] is False
    assert out["understat_tactical"]["direct_xmins_mutation"] is False
