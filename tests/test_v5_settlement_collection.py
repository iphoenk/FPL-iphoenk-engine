from src.v5.services import ingestion
from src.v5.services.orchestrator import _unresolved_finished_settlement_gws


def test_orchestrator_requests_only_frozen_unsettled_finished_gameweeks():
    ledger = {
        "records": {
            "1": {"gw": 1, "status": "FROZEN_AWAITING_SETTLEMENT", "frozen_forecast": {"players": []}},
            "2": {"gw": 2, "status": "SETTLED", "frozen_forecast": {"players": []}},
            "3": {"gw": 3, "status": "COLLECTING", "latest_pre_deadline_forecast": {"players": []}},
            "4": {"gw": 4, "status": "FROZEN_AWAITING_SETTLEMENT", "frozen_forecast": {"players": []}},
        }
    }
    bootstrap = {
        "events": [
            {"id": 1, "finished": True},
            {"id": 2, "finished": True},
            {"id": 3, "finished": True},
            {"id": 4, "finished": False},
        ]
    }
    assert _unresolved_finished_settlement_gws(ledger, bootstrap) == [1]


def test_settlement_actual_collection_is_bounded_and_keeps_missing_unavailable(monkeypatch):
    monkeypatch.setattr(
        ingestion,
        "_historical_cfg",
        lambda: {"max_historical_gameweeks": 2},
    )

    def fake_fetch_many(specs):
        assert sorted(specs) == ["settlement_event_live_gw_3", "settlement_event_live_gw_4"]
        return (
            {
                "settlement_event_live_gw_3": {"elements": [{"id": 10, "stats": {"total_points": 5}}]},
                "settlement_event_live_gw_4": None,
            },
            {
                "settlement_event_live_gw_3": {"status": "LIVE"},
                "settlement_event_live_gw_4": {"status": "UNAVAILABLE"},
            },
        )

    monkeypatch.setattr(ingestion, "fetch_many", fake_fetch_many)
    result = ingestion._settlement_actuals([1, 2, 3, 4])
    assert result["requested_gameweeks"] == [3, 4]
    assert result["available_gameweeks"] == [3]
    assert result["unavailable_gameweeks"] == [4]
    assert list(result["event_live_by_gw"]) == ["3"]
    assert result["governance"]["evaluation_service_does_not_fetch_network"] is True


def test_settlement_collection_with_no_gameweeks_makes_no_requests(monkeypatch):
    called = False

    def fake_fetch_many(specs):
        nonlocal called
        called = True
        return {}, {}

    monkeypatch.setattr(ingestion, "fetch_many", fake_fetch_many)
    result = ingestion._settlement_actuals([])
    assert called is False
    assert result["requested_gameweeks"] == []
    assert result["event_live_by_gw"] == {}
