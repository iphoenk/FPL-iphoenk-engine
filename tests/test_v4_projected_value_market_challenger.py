from __future__ import annotations

from copy import deepcopy

from src.services.projected_value_market_challenger import discover


POLICY = {
    "projected_value_market_discovery": {
        "minimum_projected_value_score": 0.72,
        "minimum_value_percentile": 0.75,
        "minimum_start_probability": 0.60,
        "football_edge_minimum_score": 0.76,
        "structural_edge_minimum_5gw": 1.0,
        "market_urgencies": ["HIGH", "CRITICAL"],
        "imminent_cycles": ["NEXT_UPDATE", "PLUS_1_UPDATE"],
        "visible_watchlist_per_position": 5,
    }
}


def _prediction(element: int, x5: float, start: float = 0.90, *, position: str = "DEF") -> dict:
    return {
        "element": element,
        "position": position,
        "xpts_3": x5 * 0.60,
        "xpts_5": x5,
        "xpts_10": x5 * 2.0,
        "xpts_15": x5 * 3.0,
        "uncertainty": 0.8,
        "fixtures": [
            {
                "event": 3,
                "xpts": x5 / 5.0,
                "xmins": {"start_probability": start, "expected_minutes": 82.0, "dnp_probability": 0.04},
            }
            for _ in range(5)
        ],
    }


def _price(element: int, team: int, cost: int, *, position: str = "DEF", fresh: bool = True, urgent: bool = False) -> dict:
    return {
        "element_id": element,
        "player_name": f"P{element}",
        "team_id": team,
        "position": position,
        "now_cost": cost,
        "ownership_percent": 2.5,
        "source": "OFFICIAL_FPL",
        "freshness_state": "FRESH" if fresh else "STALE",
        "evidence_state": "AVAILABLE" if fresh else "STALE",
        "direction": "RISE" if urgent else "STABLE",
        "model_urgency": "HIGH" if urgent else "LOW",
        "predicted_change_cycle": "NEXT_UPDATE" if urgent else "NONE",
        "predicted_change_at": "2026-09-01T06:00:00+07:00" if urgent else None,
        "next_official_price_update_at": "2026-09-01T06:00:00+07:00",
        "eta_human": "9 jam",
        "confidence": "HIGH",
        "confirmed_price_change": None,
    }


def _state(*, urgent_top: bool = True, stale_top: bool = False, local_team_for_top: int = 20, price_team_for_top: int = 20):
    owned_id = 1
    candidates = [101, 102, 103, 104, 105]
    official_players = [
        {"id": owned_id, "web_name": "Owned", "team": 1, "element_type": 2, "now_cost": 50, "selected_by_percent": "10.0", "status": "a"},
    ]
    predictions = [_prediction(owned_id, 12.0)]
    universe_players = [
        {
            "element": owned_id, "element_id": owned_id, "name": "Owned", "team": "T1", "club": "T1", "team_id": 1,
            "position": "DEF", "now_cost": 50, "price": 5.0, "ownership": "10.0", "status": "a",
            "source": "bootstrap-static.elements", "source_snapshot_id": "old", "fetched_at": "2026-08-31T14:00:00+00:00",
            "observed_at": "2026-08-31T14:00:00+00:00", "freshness": "FRESH",
        }
    ]
    prices = []
    fixtures = []
    for index, element in enumerate(candidates):
        team_id = 20 + index
        cost = 45 + index
        x5 = 25.0 - index * 4.0
        official_players.append({
            "id": element, "web_name": f"P{element}", "team": team_id, "element_type": 2, "now_cost": cost,
            "selected_by_percent": "2.5", "status": "a",
        })
        predictions.append(_prediction(element, x5, 0.92 if index == 0 else 0.75))
        universe_players.append({
            "element": element, "element_id": element, "name": f"P{element}", "team": f"T{team_id}", "club": f"T{team_id}",
            "team_id": local_team_for_top if index == 0 else team_id, "position": "DEF", "now_cost": cost, "price": cost / 10.0,
            "ownership": "2.5", "status": "a", "source": "bootstrap-static.elements", "source_snapshot_id": "old",
            "fetched_at": "2026-08-31T14:00:00+00:00", "observed_at": "2026-08-31T14:00:00+00:00", "freshness": "FRESH",
        })
        prices.append(_price(
            element,
            price_team_for_top if index == 0 else team_id,
            cost,
            fresh=not (stale_top and index == 0),
            urgent=urgent_top and index == 0,
        ))
        fixtures.append({"id": 300 + index, "event": 3, "team_h": team_id, "team_a": 2, "kickoff_time": "2026-09-12T14:00:00Z"})
    raw = {
        "schema": "snapshot.v1",
        "official": {
            "bootstrap": {
                "elements": official_players,
                "teams": [{"id": idx, "name": f"T{idx}"} for idx in range(1, 30)],
                "element_types": [{"id": 2, "singular_name_short": "DEF"}],
            },
            "fixtures": fixtures,
        },
        "endpoint_health": {"bootstrap": {"status": "LIVE", "fetched_at": "2026-08-31T14:00:00+00:00"}},
    }
    team = {
        "squad": [{"element": owned_id}],
        "team_value_ledger": [{"element": owned_id, "sell_cost": 50}],
        "itb_tenths": 10,
    }
    return {"predictions": {"players": predictions}, "universe": {"players": universe_players}, "prices": {"players": prices}, "raw_snapshot": raw, "team": team}


def _row(out: dict, element: int = 101) -> dict:
    return next(row for row in out["candidates"] if row["element"] == element)


def test_synthetic_def_outside_watchlist_becomes_mandatory_review_not_buy():
    state = _state()
    out = discover(**state, policy=POLICY)
    candidate = _row(out)
    assert out["full_universe_scanned"] is True
    assert candidate["position"] == "DEF"
    assert candidate["mandatory_review"] is True
    assert "VALUE_MARKET_URGENCY" in candidate["routes"]
    assert candidate["market"]["imminent_rise"] is True
    assert candidate["projected_value"]["position_budget_aware"] is True
    assert candidate["price_signal_can_authorize_transfer"] is False
    assert candidate["element"] in out["mandatory_candidate_ids"]
    assert any(row["element"] == 1 for row in candidate["relevant_owned"])


def test_high_value_stable_price_remains_football_discoverable():
    state = _state(urgent_top=False)
    candidate = _row(discover(**state, policy=POLICY))
    assert candidate["mandatory_review"] is False
    assert candidate["market"]["imminent_rise"] is False
    assert "FOOTBALL_EDGE" in candidate["routes"]


def test_price_only_weak_football_is_rejected_as_transfer_driver():
    state = _state()
    weak = next(row for row in state["predictions"]["players"] if row["element"] == 105)
    state["prices"]["players"][-1] = _price(105, 24, 49, urgent=True)
    weak["xpts_3"] = 1.8
    weak["xpts_5"] = 3.0
    weak["xpts_10"] = 6.0
    weak["xpts_15"] = 9.0
    candidate = _row(discover(**state, policy=POLICY), 105)
    assert candidate["market"]["imminent_rise"] is True
    assert candidate["mandatory_review"] is False
    assert candidate["market_only_rejected"] is True
    assert "VALUE_MARKET_URGENCY" not in candidate["routes"]


def test_stale_predictor_cannot_create_mandatory_review():
    state = _state(stale_top=True)
    candidate = _row(discover(**state, policy=POLICY))
    assert candidate["market"]["fresh"] is False
    assert candidate["market"]["imminent_rise"] is False
    assert candidate["mandatory_review"] is False


def test_wrong_price_club_mapping_taints_and_blocks_downstream_identity():
    state = _state(price_team_for_top=19)
    candidate = _row(discover(**state, policy=POLICY))
    assert candidate["identity_sanity"]["status"] == "TAINTED_BLOCKED"
    assert candidate["identity_sanity"]["reason"] == "OFFICIAL_PRICE_IDENTITY_MISMATCH"
    assert candidate["mandatory_review"] is False


def test_fresh_official_mapping_repairs_stale_local_mapping():
    state = _state(local_team_for_top=19, price_team_for_top=20)
    candidate = _row(discover(**state, policy=POLICY))
    assert candidate["identity_sanity"]["status"] == "PASS_REPAIRED"
    repairs = candidate["identity_sanity"]["repairs"]
    assert any(row["field"] == "team_id" and row["official"] == 20 for row in repairs)
    assert candidate["team_id"] == 20
    assert candidate["mandatory_review"] is True


def test_checkpoint_reranking_is_data_driven_not_player_named():
    first = discover(**_state(), policy=POLICY)
    changed_state = _state()
    top = next(row for row in changed_state["predictions"]["players"] if row["element"] == 101)
    second = next(row for row in changed_state["predictions"]["players"] if row["element"] == 102)
    top.update({"xpts_3": 3.0, "xpts_5": 5.0, "xpts_10": 10.0, "xpts_15": 15.0})
    second.update({"xpts_3": 18.0, "xpts_5": 30.0, "xpts_10": 60.0, "xpts_15": 90.0})
    changed_state["prices"]["players"][0] = _price(101, 20, 45, urgent=False)
    changed_state["prices"]["players"][1] = _price(102, 21, 46, urgent=True)
    changed = discover(**changed_state, policy=POLICY)
    assert first["mandatory_candidate_ids"] != changed["mandatory_candidate_ids"]
    assert 102 in changed["mandatory_candidate_ids"]


def test_price_threshold_crossing_is_not_confirmed_change():
    candidate = _row(discover(**_state(), policy=POLICY))
    assert candidate["market"]["imminent_rise"] is True
    assert candidate["market"]["confirmed_price_change"] is None
