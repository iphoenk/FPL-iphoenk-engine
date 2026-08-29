from __future__ import annotations

from copy import deepcopy

from src.v5.evaluation.core import evaluate
from src.v5.evaluation.prediction_settlement import settlement_targets
from src.v5.services import ingestion


def _forecast() -> dict:
    return {
        "generated_at": "2026-08-28T17:00:00Z",
        "players": [
            {
                "element": 1,
                "name": "Player One",
                "position": "DEF",
                "xpts": 5.0,
                "xpts_std": 2.0,
                "xmins": 80.0,
                "start_probability": 0.9,
                "clean_sheet_probability": 0.4,
            }
        ],
    }


def _ledger() -> dict:
    return {
        "schema_version": 1,
        "records": {
            "2": {
                "gw": 2,
                "deadline_time": "2026-08-28T17:30:00Z",
                "frozen_forecast": _forecast(),
                "frozen_at": "2026-08-28T17:30:01Z",
                "status": "FROZEN_AWAITING_SETTLEMENT",
            }
        },
    }


def _bootstrap() -> dict:
    return {
        "events": [
            {"id": 2, "finished": True},
            {"id": 3, "finished": False},
        ]
    }


def _actual() -> dict:
    return {
        "elements": [
            {
                "id": 1,
                "stats": {
                    "total_points": 7,
                    "minutes": 90,
                    "starts": 1,
                    "clean_sheets": 1,
                },
            }
        ]
    }


def _context(scoring_gw: int = 3) -> dict:
    return {
        "planning_gw": 3,
        "scoring_gw": scoring_gw,
        "deadline_time": "2099-09-04T17:30:00Z",
    }


def test_finished_frozen_gw_becomes_historical_settlement_target_after_scoring_advances():
    plan = settlement_targets(
        _ledger(),
        _bootstrap(),
        scoring_gw=3,
        current_event_live_available=True,
    )
    assert plan["gameweeks"] == [2]
    assert plan["count"] == 1
    assert plan["governance"]["network_owner"] == "ingestion"
    assert plan["governance"]["settlement_owner"] == "evaluation"


def test_current_event_live_is_deduplicated_from_historical_target():
    plan = settlement_targets(
        _ledger(),
        _bootstrap(),
        scoring_gw=2,
        current_event_live_available=True,
    )
    assert plan["gameweeks"] == []


def test_historical_finished_event_live_settles_after_scoring_context_advances():
    ledger = _ledger()
    frozen_before = deepcopy(ledger["records"]["2"]["frozen_forecast"])
    result = evaluate(
        {"planning_gw": 3, "players": []},
        _context(scoring_gw=3),
        _bootstrap(),
        None,
        ledger,
        event_live_by_gw={"2": _actual()},
        settlement_health={
            "requested_gameweeks": [2],
            "health_by_gw": {"2": {"status": "LIVE"}},
        },
    )
    record = result["ledger"]["records"]["2"]
    assert record["status"] == "SETTLED"
    assert record["frozen_forecast"] == frozen_before
    assert record["settlement_provenance"]["source"] == "HISTORICAL_FINISHED_EVENT_LIVE"
    assert record["settlement_provenance"]["postdeadline_prediction_reconstruction"] is False
    assert result["accuracy"]["overall"]["sample_size"] == 1
    assert result["accuracy"]["settled_gameweeks"] == [2]
    assert result["accuracy"]["settlement_source_health"]["historical_event_live_fetched"] == 1
    assert result["accuracy"]["temporal_guard"]["status"] == "PASS"


def test_missing_historical_event_live_leaves_finished_record_pending_without_fake_sample():
    result = evaluate(
        {"planning_gw": 3, "players": []},
        _context(scoring_gw=3),
        _bootstrap(),
        None,
        _ledger(),
        event_live_by_gw={},
        settlement_health={
            "requested_gameweeks": [2],
            "health_by_gw": {"2": {"status": "FAILED"}},
        },
    )
    record = result["ledger"]["records"]["2"]
    assert record["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert "actual" not in record
    assert result["accuracy"]["overall"]["sample_size"] == 0
    assert result["accuracy"]["settlement_source_health"]["missing_historical_actuals_fail_neutral"] is True


def test_current_scoring_event_live_still_settles_without_historical_fetch():
    result = evaluate(
        {"planning_gw": 3, "players": []},
        _context(scoring_gw=2),
        _bootstrap(),
        _actual(),
        _ledger(),
    )
    record = result["ledger"]["records"]["2"]
    assert record["status"] == "SETTLED"
    assert record["settlement_provenance"]["source"] == "CURRENT_SCORING_EVENT_LIVE"


def test_ingestion_deduplicates_historical_settlement_gameweeks(monkeypatch):
    captured = {}

    def fake_fetch_many(specs):
        captured["specs"] = specs
        payloads = {name: _actual() for name in specs}
        health = {name: {"status": "LIVE"} for name in specs}
        return payloads, health

    monkeypatch.setattr(ingestion, "fetch_many", fake_fetch_many)
    result = ingestion.handle(
        "collect_settlement_live",
        {"team_id": 1, "gameweeks": [2, 2, "3", 3, None, -1]},
    )
    assert result["requested_gameweeks"] == [2, 3]
    assert result["request_count"] == 2
    assert result["fetched_gameweeks"] == [2, 3]
    assert set(captured["specs"]) == {"event_live_gw_2", "event_live_gw_3"}
    assert captured["specs"]["event_live_gw_2"].route == "event_live"
    assert captured["specs"]["event_live_gw_2"].params == {"event": 2}
