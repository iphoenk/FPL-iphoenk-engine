from src.engines.v12_price_presentation_lock import (
    load_price_presentation_lock,
    validate_price_presentation_lock,
)


def test_price_presentation_lock_is_exact():
    contract = load_price_presentation_lock()
    assert validate_price_presentation_lock(contract) == []
    assert contract["section_order"] == [f"PRICE{i}" for i in range(1, 13)]


def test_price_tables_are_locked_to_human_columns():
    sections = load_price_presentation_lock()["sections"]
    assert sections["PRICE2"]["tables"][0]["columns"] == [
        "Player","Pos","Market","Sell","Direction","Progress","ETA / Status","Decision impact"
    ]
    assert "element_id" not in sections["PRICE2"]["tables"][0]["columns"]
    assert sections["PRICE8"]["tables"][0]["columns"] == [
        "Route","OUT sell","IN price","Bank before","Affordable","Bank after","FT","Hit"
    ]
    assert sections["PRICE8"]["tables"][1]["columns"] == [
        "Route","Target +0.1","OUT -0.1","Combined","Route survives","1GW","3GW","5GW","Reversal risk"
    ]


def test_price_action_board_and_source_health_shapes_are_exact():
    sections = load_price_presentation_lock()["sections"]
    action = sections["PRICE10"]["tables"][0]
    assert action["rows"] == [
        "NOW","NEXT","TRIGGER TO ACT","LATEST SAFE DECISION POINT","COST OF WAITING","ABORT / REVERSAL"
    ]
    assert sections["PRICE11"]["tables"][0]["columns"] == ["Source","Status","As of"]


def _price_rows(count, *, positions=None):
    rows = []
    positions = positions or ["MID"] * count
    for i in range(count):
        rows.append({
            "element_id": i + 1,
            "name": f"Player {i+1}",
            "player": f"Player {i+1}",
            "position": positions[i],
            "current_price": 5.0 + i / 10,
            "authenticated_sell_value": 5.0,
            "direction": "RISE",
            "predictor_direction": "RISE",
            "official_or_provider_progress": 80,
            "predictor_progress": 80,
            "eta_status": "MODEL NEXT PRICE CYCLE",
            "impact_on_our_decision": "No decision change",
            "football_relevance": 1.0,
            "squad_relevance": "CURRENT_V12_WATCHLIST",
            "affordability_relevance": "EVALUATE_WITH_ROUTE_FINANCE",
            "projected_percent": 80,
            "confidence": "HIGH",
            "our15_flag": "NO",
            "watchlist_flag": "YES",
            "evidence_timestamp": "2026-10-03T05:30:00+07:00",
            "club": "Club",
        })
    return rows


def test_price_renderer_matches_locked_columns_and_hides_machine_fields():
    from src.engines.v12_price_delivery import render_price_report, validate_price_visible_body

    contract = load_price_presentation_lock()
    titles = [contract["sections"][f"PRICE{i}"]["title"] for i in range(1, 13)]
    positions = ["GK"] * 5 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
    our15 = _price_rows(15, positions=["GK","GK"] + ["DEF"]*5 + ["MID"]*5 + ["FWD"]*3)
    watch20 = _price_rows(20, positions=positions)
    rise20 = _price_rows(20, positions=positions)
    fall20 = _price_rows(20, positions=positions)

    sections = [
        {"section_id": f"PRICE{i}", "label": titles[i-1], "state": "COMPLETE", "content": {}}
        for i in range(1, 13)
    ]
    sections[0]["content"] = {
        "action": "WAIT", "material_change": "No confirmed change",
        "affordability_changed": "NO_PROVEN_MATERIAL_CHANGE", "price_pressure": 0,
    }
    sections[1]["content"] = {
        "rows": our15, "ownership_state": "CURRENT", "source_class": "AUTHENTICATED_OFFICIAL_CURRENT_TEAM",
        "gw": 7, "observed_at": "2026-10-03T05:30:00+07:00",
    }
    sections[2]["content"] = {
        "official_changes": [{"player":"Player 1","official_delta":0.1,"current_price":5.1,"classification":"FACT"}],
        "predictor_delta_state": "AVAILABLE",
    }
    sections[3]["content"] = {"alerts": [], "route_rows": []}
    sections[4]["content"] = {"rows": watch20}
    sections[5]["content"] = {"rows": rise20}
    sections[6]["content"] = {"rows": fall20}
    sections[7]["content"] = {"routes": []}
    sections[8]["content"] = {
        "league_name": "ICON+", "expected_manager_count":58, "collected_manager_count":58,
        "current_rank":7, "current_points":344, "evidence_freshness":"2026-10-03T05:30:00+07:00",
        "price_route_impact":"No supported route", "mini_league_consequence":"No change", "exposure_rows":[],
    }
    sections[9]["content"] = {
        "NOW":"WAIT", "NEXT":"Reassess", "TRIGGER TO ACT":"Football edge + route",
        "LATEST SAFE DECISION POINT":"Next checkpoint", "COST OF WAITING":"No proven cost",
        "ABORT / REVERSAL":"Abort if edge deteriorates",
    }
    sections[10]["content"] = {
        "official_timestamp":"2026-10-03T05:30:00+07:00",
        "predictor_timestamp":"2026-10-03T05:29:00+07:00", "personal_timestamp":"2026-10-03T05:28:00+07:00",
        "personal_status":"CURRENT", "mini_league_timestamp":"2026-10-03T05:27:00+07:00",
        "mini_league_status":"COMPLETE", "core_logical_slot":"2026-10-03T04:30:00+07:00",
        "predictor_health":"PASS",
    }
    sections[11]["content"] = {
        "action":"WAIT", "key_price_risk":"No material risk", "affordability_threatened":False,
        "football_edge_justifies_action":False, "next_checkpoint":"Next checkpoint",
        "final_judgement":"Do not force a transfer for price movement alone.",
    }
    report = {
        "planning_gw":7, "action":"WAIT", "sections":sections,
        "current15":{"supportable":True,"rows":our15},
        "watchlist20":{"state":"COMPLETE","rows":watch20,"universe_evaluated":667},
        "rise20":{"state":"COMPLETE","rows":rise20},
        "fall20":{"state":"COMPLETE","rows":fall20},
    }
    body = render_price_report(report)
    assert validate_price_visible_body(body, report=report) == []
    assert "| Player | Pos | Market | Sell | Direction | Progress | ETA / Status | Decision impact |" in body
    assert "| Route | OUT sell | IN price | Bank before | Affordable | Bank after | FT | Hit |" not in body
    assert "| Field | Current call |" in body
    assert "element_id" not in body
    assert "user_summary" not in body
    assert "core_run_id" not in body
    assert "runtime_snapshot" not in body
