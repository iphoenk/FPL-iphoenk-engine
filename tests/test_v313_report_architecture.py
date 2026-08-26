import json

from src.engines import report_architecture as r


def _projection(element, name, *, mean=6.0, std=2.0, start=0.92, dnp=0.03, xmins=82.0, role=False):
    row = {
        "element": element,
        "name": name,
        "position": "MID",
        "projection_confidence": "HIGH",
        "xmins": {
            "start_probability": start,
            "bench_probability": max(0.0, 1.0 - start - dnp),
            "dnp_probability": dnp,
            "expected_minutes": xmins,
        },
        "xpts_by_gw": [{"gw": 2, "mean": mean, "std": std, "fixtures": [{"event": 2}]}],
    }
    if role:
        row["penalty_role"] = "first_choice"
    return row


def test_captain_ranking_is_not_auto_lock_without_role_evidence():
    lineup = {
        "planning_gw": 2,
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "captain_safe_pool": [
            {"element": 1, "captain_score": 6.2},
            {"element": 2, "captain_score": 5.0},
        ],
    }
    projections = {"planning_gw": 2, "players": [_projection(1, "A"), _projection(2, "B", mean=5.0)]}
    out = r._captaincy_section(lineup, projections)
    assert out["decision"] != "LOCK"
    assert out["model"]["checks"]["role_evidence"] is False


def test_captain_can_lock_when_strict_evidence_passes():
    lineup = {
        "planning_gw": 2,
        "captain": {"element": 1},
        "vice_captain": {"element": 2},
        "captain_safe_pool": [
            {"element": 1, "captain_score": 6.5},
            {"element": 2, "captain_score": 5.0},
        ],
    }
    projections = {"planning_gw": 2, "players": [_projection(1, "A", role=True), _projection(2, "B", mean=5.0, role=True)]}
    out = r._captaincy_section(lineup, projections)
    assert out["decision"] == "LOCK"
    assert out["confidence"] == "HIGH"


def test_lineup_battle_remains_open_when_margin_is_close():
    lineup = {
        "formation": "3-4-3",
        "starting_xi": [],
        "main_starting_xi_battle": {
            "status": "CLOSE",
            "margin": 0.13,
            "starter_side": [{"name": "A"}],
            "bench_side": [{"name": "B"}],
            "alternative_formation": "4-4-2",
        },
    }
    out = r._lineup_section(lineup, {"initial_report": False, "changed": []}, True)
    assert out["decision"] == "OPEN"
    assert out["model"]["confidence"] == "LOW"
    assert out["model"]["battle"]["starter"] == "A"
    assert out["model"]["battle"]["challenger"] == "B"


def test_price_radar_filters_external_market_noise_until_full_dss_watchlist():
    alerts = {
        "alerts": [
            {"element": 1, "name": "Owned", "owned": True, "risk_direction": "FALL", "urgency": "CRITICAL", "official_progress_pct": -95, "official_projection_health": "SUSPECT_STATIC_OFFSET0"},
            {"element": 2, "name": "External", "owned": False, "risk_direction": "RISE", "urgency": "CRITICAL", "official_progress_pct": 98},
        ]
    }
    team = {"team_value_ledger": [{"element": 1}]}
    out = r._price_section(alerts, team, {})
    assert [x["name"] for x in out["owned"]] == ["Owned"]
    assert out["external_watchlist"] == []
    assert out["external_status"] == "INSUFFICIENT_EVIDENCE"
    assert "SUSPECT_STATIC_OFFSET0" not in json.dumps(out)


def test_watchlist_refuses_ranking_without_full_dss_contract():
    out = r._watchlist_section({"positions": {"MID": [{"element": 99, "name": "Haul"}]}})
    assert out["status"] == "INSUFFICIENT_EVIDENCE"
    assert out["positions"]["MID"] == []


def test_stable_delta_is_compact_and_action_board_is_bounded():
    current = {
        "squad": "HOLD",
        "starting_xi": [1, 2],
        "formation": "3-4-3",
        "captain": 1,
        "vice_captain": 2,
        "chip": None,
        "price": [],
        "critical_health": {"overall": "GREEN", "critical_failed": [], "prediction_quality": "HEALTHY"},
    }
    delta = r._changes(current, {"state": current})
    assert delta["material_change"] is False
    user = {
        "decision": {"squad": "HOLD"},
        "starting_xi": {"decision": "OPEN", "model": {"battle": {"starter": "A", "challenger": "B"}}},
        "captaincy": {"decision": "OPEN", "facts": {"model_candidate": "C"}, "reason": "need evidence"},
        "chip": {"decision": "HOLD"},
        "price_radar": {"owned": [{"name": f"P{i}", "action": "HOLD", "direction": "RISE", "urgency": "HIGH"} for i in range(20)]},
        "external_watchlist": {"status": "INSUFFICIENT_EVIDENCE"},
    }
    assert len(r._action_board(user)) <= 8
