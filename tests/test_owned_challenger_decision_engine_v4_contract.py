from __future__ import annotations

import src.engines.owned_challenger_comparator as comp


def _proj(element: int, position: str, team_id: int, mean: float, *, start: float = 0.8, dnp: float = 0.05, cost: int = 50):
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": cost,
        "status": "a",
        "projection_confidence": "MEDIUM",
        "uncertainty": 0.2,
        "xmins": {"expected_minutes": 75, "start_probability": start, "dnp_probability": dnp},
        "xpts_by_gw": [{"gw": i + 1, "mean": mean, "std": 1.0} for i in range(15)],
        "tactical_matchup": {"evidence_state": "READY"},
        "rates": {"xg90": 0.2, "xa90": 0.2},
    }


def test_owned_screening_is_not_lowest_xpts_only():
    stable = {"element": 1, "name": "stable", "position": "MID", "projection": _proj(1, "MID", 1, 2.0, start=0.95, dnp=0.01)}
    risky = {"element": 2, "name": "risky", "position": "MID", "projection": _proj(2, "MID", 2, 2.5, start=0.45, dnp=0.30)}
    challenger = {"player_in": {"element": 9, "name": "C"}, "horizons": {"3": {"projected_edge": 0.2}, "5": {"projected_edge": 0.5}}, "finance": {"affordable": True}, "legality": {"club_limit_legal": True}, "actionability": {"level": "REVIEW"}, "state": "REVIEW", "confidence": "MEDIUM"}
    stable_pair = {**challenger, "player_out": {"element": 1}}
    risky_pair = {**challenger, "player_out": {"element": 2}}
    rows = comp._screen_owned([stable, risky], [stable_pair, risky_pair])
    assert rows[0]["element"] == 2
    assert rows[0]["ranking_basis"].endswith("xPts alone forbidden")


def test_price_threshold_never_becomes_confirmation():
    evidence = comp._price_evidence({
        "current_progress_percent": 105.0,
        "projection_offset_0_percent": 110.0,
        "evidence_state": "AVAILABLE",
        "freshness_seconds": 30,
        "model_urgency": "CRITICAL",
        "direction": "RISE",
        "confirmed_price_change": False,
    })
    assert evidence["timing_state"] == "PRICE_ACTIONABLE"
    assert evidence["confirmed_price_change"] is False
    assert evidence["threshold_crossing_is_not_confirmation"] is True


def test_stale_predictor_cannot_create_urgency():
    evidence = comp._price_evidence({"evidence_state": "STALE", "freshness_seconds": 999999, "model_urgency": "CRITICAL", "direction": "RISE"})
    assert evidence["timing_state"] == "MODEL_CONTEXT_ONLY"
    assert evidence["stale_cannot_create_urgency"] is True


def test_package_alternatives_preserve_zero_one_two_and_multi():
    payload = {"best_by_replacement_count": {
        "1": {"replacements": 1, "out": [{"element": 1}], "in": [{"element": 11}], "classification": "MATERIAL_UPGRADE"},
        "2": {"replacements": 2, "out": [{"element": 1}, {"element": 2}], "in": [{"element": 11}, {"element": 12}], "classification": "MATERIAL_UPGRADE"},
        "4": {"replacements": 4, "out": [{"element": i} for i in range(1, 5)], "in": [{"element": i} for i in range(11, 15)], "classification": "MATERIAL_UPGRADE"},
    }}
    assert [row["replacements"] for row in comp._package_alternatives(payload)] == [0, 1, 2, 4]


def test_no_player_specific_out_hardcode_in_governance(monkeypatch):
    assert comp.load_policy()["owner"] == "reporting.owned_challenger_comparator"
    source = open(comp.__file__, encoding="utf-8").read()
    for name in ("Aina", "Ødegaard", "Rogers"):
        assert name not in source
