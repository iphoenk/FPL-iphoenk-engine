import src.engines.challenger_discovery as discovery
import src.engines.watchlist_public_sanitize as public


def _projection(element, h5, cost, *, position="DEF", start=0.9):
    return {
        "element": element,
        "name": f"P{element}",
        "team_id": element,
        "position": position,
        "now_cost": cost,
        "status": "a",
        "ownership_pct": "1.0",
        "projection_confidence": "MEDIUM",
        "xmins": {"expected_minutes": 82.0, "start_probability": start, "dnp_probability": 0.03},
        "horizons": {
            "3": {"mean": round(h5 * 0.60, 3), "std": 1.5},
            "5": {"mean": h5, "std": 2.0},
            "10": {"mean": h5 * 2.0, "std": 3.0},
            "15": {"mean": h5 * 3.0, "std": 4.0},
        },
    }


def _official(element, cost, *, position_type=2):
    return {
        "id": element,
        "web_name": f"P{element}",
        "team": element,
        "element_type": position_type,
        "now_cost": cost,
        "selected_by_percent": "1.0",
        "status": "a",
    }


def _fixture(team):
    opponent = 99 if team != 99 else 98
    return {
        "id": team,
        "event": 3,
        "team_h": team,
        "team_a": opponent,
        "kickoff_time": "2026-09-12T14:00:00Z",
        "started": False,
        "finished": False,
    }


def test_low_price_def_with_material_value_and_fresh_market_move_is_mandatory(monkeypatch):
    players = [
        _projection(101, 18.0, 40),
        _projection(102, 14.0, 45),
        _projection(103, 13.0, 50),
        _projection(104, 12.0, 55),
    ]
    snapshot = {
        "bootstrap": {"elements": [_official(row["element"], row["now_cost"]) for row in players]},
        "fixtures": [_fixture(row["element"]) for row in players],
    }
    prices = {
        "players": [{
            "element_id": 101,
            "evidence_state": "AVAILABLE",
            "freshness_seconds": 60,
            "risk_direction": "RISE",
            "urgency": "HIGH",
            "official_progress_pct": 94.0,
            "predicted_change_deadline": "2026-09-01T06:00:00+07:00",
        }]
    }

    def fake_read(path, default=None):
        name = getattr(path, "name", "")
        return {
            "projections.json": {"players": players},
            "official_snapshot.json": snapshot,
            "prices.json": prices,
            "team.json": {"team_value_ledger": []},
        }.get(name, default if default is not None else {})

    monkeypatch.setattr(discovery, "read_json", fake_read)
    result = discovery.build()
    candidate = next(row for row in result["candidates"] if row["element"] == 101)
    assert candidate["routes"]["VALUE_MARKET_URGENCY"] is True
    assert candidate["mandatory_challenger_review"] is True
    assert candidate["projected_value"]["position_value_percentile"] >= 0.75
    assert result["mandatory_review_element_ids"] == [101]


def test_stale_predictor_cannot_create_mandatory_review(monkeypatch):
    player = _projection(101, 18.0, 40)
    snapshot = {"bootstrap": {"elements": [_official(101, 40)]}, "fixtures": [_fixture(101)]}
    prices = {
        "players": [{
            "element_id": 101,
            "evidence_state": "AVAILABLE",
            "freshness_seconds": 999999,
            "risk_direction": "RISE",
            "urgency": "CRITICAL",
        }]
    }

    def fake_read(path, default=None):
        name = getattr(path, "name", "")
        return {
            "projections.json": {"players": [player]},
            "official_snapshot.json": snapshot,
            "prices.json": prices,
            "team.json": {"team_value_ledger": []},
        }.get(name, default if default is not None else {})

    monkeypatch.setattr(discovery, "read_json", fake_read)
    result = discovery.build()
    row = result["candidates"][0]
    assert row["market"]["fresh"] is False
    assert row["mandatory_challenger_review"] is False
    assert result["mandatory_review_count"] == 0


def test_identity_team_or_position_mismatch_blocks_projection(monkeypatch):
    player = _projection(101, 18.0, 40)
    official = _official(101, 40)
    official["team"] = 55
    snapshot = {"bootstrap": {"elements": [official]}, "fixtures": [_fixture(55)]}

    def fake_read(path, default=None):
        name = getattr(path, "name", "")
        return {
            "projections.json": {"players": [player]},
            "official_snapshot.json": snapshot,
            "prices.json": {"players": []},
            "team.json": {"team_value_ledger": []},
        }.get(name, default if default is not None else {})

    monkeypatch.setattr(discovery, "read_json", fake_read)
    result = discovery.build()
    assert result["eligible_candidate_count"] == 0
    assert result["blocked_identity_count"] == 1
    assert result["blocked_identity"][0]["reason"] == "IDENTITY_MAPPING_MISMATCH"


def test_compacted_decision_preserves_publication_proof_and_actionability_reason():
    source = {
        "schema_version": 5,
        "contract": "OWNED_CHALLENGER_DECISION_V3",
        "owner": "decision.owned_challenger_evaluation",
        "capability_status": "GOVERNED_DECISION",
        "status": "READY",
        "owned_count": 15,
        "governed_watchlist_count": 20,
        "comparison_count": 1,
        "top_comparisons": [{
            "player_out": {"element": 1},
            "player_in": {"element": 2},
            "state": "REVIEW",
            "actionability": {"level": "REVIEW"},
            "reason": "evidence review required",
        }],
        "main_transfer_battles": [],
        "publication_validation": {"status": "PASS", "blockers": []},
        "decision": {"state": "REVIEW", "execution_authorized": False},
    }
    result = public._compact_decision(source)
    assert result["publication_validation"]["status"] == "PASS"
    assert result["top_comparisons"][0]["actionability"]["reason"] == "evidence review required"
    assert result["governance"]["reporting_recomputation_forbidden"] is True
