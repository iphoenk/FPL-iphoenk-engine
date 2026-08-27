from src.v5.official_history import (
    AUTHORITY,
    compact_submitted_picks,
    finished_gameweeks,
    reconcile_historical_submissions,
)


def _picks(gw: int, captain: int = 10) -> dict:
    return {
        "active_chip": None,
        "entry_history": {"event": gw, "points": 60 + gw, "overall_rank": 1000 - gw},
        "picks": [
            {
                "element": element,
                "position": position,
                "multiplier": 2 if element == captain else 1,
                "is_captain": element == captain,
                "is_vice_captain": element == captain + 1,
            }
            for position, element in enumerate(range(10, 25), start=1)
        ],
        "automatic_subs": [],
    }


def test_finished_gameweeks_are_sorted_and_positive():
    history = {"current": [{"event": 2}, {"event": 1}, {"event": 0}, {"event": 2}]}
    assert finished_gameweeks(history) == [1, 2]


def test_compact_submitted_picks_keeps_decision_relevant_public_fields_only():
    payload = _picks(1)
    payload["picks"][0]["purchase_price"] = 99
    compact = compact_submitted_picks(payload)
    assert compact["entry_history"]["event"] == 1
    assert compact["picks"][0]["element"] == 10
    assert compact["picks"][0]["is_captain"] is True
    assert "purchase_price" not in compact["picks"][0]


def test_reconciliation_is_public_post_deadline_and_proxy_is_decision_neutral():
    history = {
        "current": [
            {"event": 1, "points": 61, "overall_rank": 999},
            {"event": 2, "points": 62, "overall_rank": 998},
        ]
    }
    result = reconcile_historical_submissions(
        team_id=3465283,
        entry_history=history,
        picks_by_gw={1: _picks(1), 2: _picks(2)},
        max_historical_gameweeks=5,
        retrospective_proxy_gameweeks=[1],
    )
    assert result["status"] == "READY"
    assert result["authority"] == AUTHORITY
    assert result["coverage"] == {"requested": 2, "available": 2, "complete": True}
    assert result["gameweeks"]["1"]["status"] == "PUBLIC_OFFICIAL_SUBMITTED_TEAM"
    assert result["retrospective_proxy_baseline"]["gameweeks"] == [1]
    assert result["retrospective_proxy_baseline"]["use_for_predictive_accuracy"] is False
    assert result["retrospective_proxy_baseline"]["use_for_dynamic_weight"] is False
    assert result["governance"]["historical_state_never_overrides_current_pre_deadline_authority"] is True


def test_reconciliation_reports_partial_official_unavailability_without_fabrication():
    history = {"current": [{"event": 1}, {"event": 2}]}
    result = reconcile_historical_submissions(
        team_id=3465283,
        entry_history=history,
        picks_by_gw={1: _picks(1), 2: None},
        source_health={"historical_picks_gw_2": {"status": "UNAVAILABLE"}},
        max_historical_gameweeks=5,
        retrospective_proxy_gameweeks=[1],
    )
    assert result["status"] == "READY"
    assert result["coverage"] == {"requested": 2, "available": 1, "complete": False}
    assert result["gameweeks"]["2"]["status"] == "OFFICIAL_PICKS_UNAVAILABLE"
    assert "submitted" not in result["gameweeks"]["2"]
