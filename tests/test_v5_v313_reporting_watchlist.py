from src.v5.decision.watchlist import build_watchlist
from src.v5.reporting import build_report


def _prediction():
    players = []
    for i, pos in enumerate(["GK", "DEF", "MID", "FWD"] * 3, start=1):
        players.append({
            "element": i, "name": f"P{i}", "position": pos, "team_id": i, "now_cost": 50,
            "ownership_pct": 5.0, "projection_confidence": "MEDIUM",
            "xmins": {"start_probability": 0.9, "expected_minutes": 80, "dnp_probability": 0.05},
            "role": {"confidence": 0.8},
            "current_season": {"expected_goals": 0.4, "expected_assists": 0.3},
            "historical_prior": {"minutes": 2200, "xg_per90": 0.3, "xa_per90": 0.2, "set_piece_role": "some"},
            "xpts_5": 25.0 + i / 10, "xpts_15": 70.0 + i / 10,
        })
    return {"players": players, "prediction_quality": {"status": "HEALTHY"}, "model_version": "test"}


def test_full_dss_watchlist_excludes_owned_and_caps_positions():
    team = {"team_value_ledger": [{"element": 1}]}
    result = build_watchlist(_prediction(), team)
    assert result["screening_contract"] == "FULL_DSS_SCREEN_V1"
    assert all(row["element"] != 1 for rows in result["positions"].values() for row in rows)
    assert all(len(rows) <= 5 for rows in result["positions"].values())
    assert all("dimensions" in row and "evidence" in row for rows in result["positions"].values() for row in rows)


def test_reporting_separates_user_and_technical_layers_and_delta_mode():
    prediction = _prediction()
    decision = {
        "selected_package_id": "HOLD", "selected_package": {"id": "HOLD"}, "ruleset_id": "FPL_2026_27", "model": "test",
        "decision_trace": {"confidence": "MEDIUM"},
        "lineup": {"formation": "3-4-3", "starting_xi": [{"element": i} for i in range(1, 12)], "bench": [], "captain": {"element": 3, "start_probability": .9, "expected_minutes": 80}, "vice_captain": {"element": 4}, "captain_safe_pool": [{"captain_score": 6.0}, {"captain_score": 5.0}], "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0}},
        "watchlist": build_watchlist(prediction, {"team_value_ledger": [{"element": 1}]}),
        "dss": {}, "gate0_preflight_pass": True,
    }
    payload = {"decision": decision, "truth": {"team": {"authority": "user_lock", "team_value_ledger": [{"element": 1}]}}, "prediction": prediction, "price": {}, "governance": {"overall": "GREEN", "go_allowed": True}}
    first = build_report(payload)
    assert first["user_report"]["layer"] == "USER_REPORT"
    assert first["technical_appendix"]["layer"] == "TECHNICAL_APPENDIX"
    assert first["user_report"]["report_mode"] == "FULL_DECISION"
    second = build_report({**payload, "previous_report_state": first["report_state"]})
    assert second["user_report"]["report_mode"] == "COMPACT_DELTA"
    assert second["user_report"]["changes_since_last_report"]["material_change"] is False
