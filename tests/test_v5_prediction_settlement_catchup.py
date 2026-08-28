from copy import deepcopy

from src.v5.evaluation.core import evaluate


def _forecast(gw: int = 1):
    return {
        "generated_at": "2026-08-20T09:00:00+00:00",
        "players": [
            {
                "element": 10,
                "name": "P10",
                "position": "MID",
                "xpts": 5.0,
                "xpts_std": 2.0,
                "xmins": 80.0,
                "start_probability": 0.9,
                "clean_sheet_probability": 0.3,
            },
            {
                "element": 11,
                "name": "P11",
                "position": "FWD",
                "xpts": 4.0,
                "xpts_std": 2.0,
                "xmins": 70.0,
                "start_probability": 0.8,
                "clean_sheet_probability": 0.0,
            },
        ],
    }


def _ledger(gw: int = 1):
    return {
        "schema_version": 2,
        "records": {
            str(gw): {
                "gw": gw,
                "deadline_time": "2026-08-20T10:00:00+00:00",
                "frozen_forecast": _forecast(gw),
                "frozen_at": "2026-08-20T10:01:00+00:00",
                "status": "FROZEN_AWAITING_SETTLEMENT",
            }
        },
    }


def _collecting_ledger(gw: int = 1):
    return {
        "schema_version": 2,
        "records": {
            str(gw): {
                "gw": gw,
                "deadline_time": "2026-08-20T10:00:00+00:00",
                "latest_pre_deadline_forecast": _forecast(gw),
                "status": "COLLECTING",
            }
        },
    }


def _event_live(points_a=7, points_b=2):
    return {
        "elements": [
            {
                "id": 10,
                "stats": {
                    "total_points": points_a,
                    "minutes": 90,
                    "starts": 1,
                    "clean_sheets": 1,
                },
            },
            {
                "id": 11,
                "stats": {
                    "total_points": points_b,
                    "minutes": 30,
                    "starts": 0,
                    "clean_sheets": 0,
                },
            },
        ]
    }


def _bootstrap(finished=True):
    return {"events": [{"id": 1, "finished": finished}, {"id": 2, "finished": True}]}


def test_catch_up_settles_old_finished_gw_when_scoring_gw_has_advanced():
    result = evaluate(
        prediction={"planning_gw": 0},
        context={"planning_gw": 0, "scoring_gw": 2},
        bootstrap=_bootstrap(True),
        event_live=_event_live(1, 1),
        ledger=_ledger(1),
        event_live_by_gw={"1": _event_live(7, 2)},
    )
    record = result["ledger"]["records"]["1"]
    assert record["status"] == "SETTLED"
    assert record["metrics"]["sample_size"] == 2
    assert result["accuracy"]["overall"]["sample_size"] == 2
    assert result["accuracy"]["settled_gameweeks"] == [1]
    assert result["accuracy"]["settlement"]["completed_gameweeks"] == [1]
    assert result["accuracy"]["temporal_guard"]["status"] == "PASS"


def test_rollover_collecting_record_freezes_and_settles_after_planning_gw_advances():
    ledger = _collecting_ledger(1)
    predeadline = deepcopy(ledger["records"]["1"]["latest_pre_deadline_forecast"])
    result = evaluate(
        prediction={"planning_gw": 2, "players": []},
        context={"planning_gw": 2, "scoring_gw": 2, "deadline_time": "2099-08-27T10:00:00+00:00"},
        bootstrap=_bootstrap(True),
        event_live=None,
        ledger=ledger,
        event_live_by_gw={"1": _event_live(7, 2)},
    )
    record = result["ledger"]["records"]["1"]
    assert record["status"] == "SETTLED"
    assert record["frozen_forecast"] == predeadline
    assert record["metrics"]["sample_size"] == 2
    assert result["accuracy"]["overall"]["sample_size"] == 2
    assert result["accuracy"]["freeze_lifecycle"]["attempted_gameweeks"] == [1]
    assert result["accuracy"]["freeze_lifecycle"]["completed_gameweeks"] == [1]
    assert result["accuracy"]["settlement"]["completed_gameweeks"] == [1]
    assert result["accuracy"]["temporal_guard"]["status"] == "PASS"


def test_expired_collecting_record_freezes_without_actual_and_waits_for_settlement():
    result = evaluate(
        prediction={"planning_gw": 2, "players": []},
        context={"planning_gw": 2, "scoring_gw": 2, "deadline_time": "2099-08-27T10:00:00+00:00"},
        bootstrap=_bootstrap(False),
        event_live=None,
        ledger=_collecting_ledger(1),
    )
    record = result["ledger"]["records"]["1"]
    assert record["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert record["frozen_forecast"] == _forecast(1)
    assert result["accuracy"]["freeze_lifecycle"]["completed_gameweeks"] == [1]
    assert result["accuracy"]["overall"]["sample_size"] == 0


def test_single_current_event_live_remains_backward_compatible():
    result = evaluate(
        prediction={"planning_gw": 0},
        context={"planning_gw": 0, "scoring_gw": 1},
        bootstrap=_bootstrap(True),
        event_live=_event_live(6, 3),
        ledger=_ledger(1),
    )
    assert result["ledger"]["records"]["1"]["status"] == "SETTLED"
    assert result["accuracy"]["overall"]["sample_size"] == 2


def test_unfinished_gw_is_not_settled_even_when_actual_payload_is_supplied():
    result = evaluate(
        prediction={"planning_gw": 0},
        context={"planning_gw": 0, "scoring_gw": 2},
        bootstrap=_bootstrap(False),
        event_live=None,
        ledger=_ledger(1),
        event_live_by_gw={"1": _event_live()},
    )
    assert result["ledger"]["records"]["1"]["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert result["accuracy"]["overall"]["sample_size"] == 0
    assert result["accuracy"]["settlement"]["attempted_finished_gameweeks"] == []


def test_empty_actual_payload_does_not_mark_record_settled():
    result = evaluate(
        prediction={"planning_gw": 0},
        context={"planning_gw": 0, "scoring_gw": 2},
        bootstrap=_bootstrap(True),
        event_live=None,
        ledger=_ledger(1),
        event_live_by_gw={"1": {"elements": []}},
    )
    assert result["ledger"]["records"]["1"]["status"] == "FROZEN_AWAITING_SETTLEMENT"
    assert result["accuracy"]["settlement"]["missing_actual_gameweeks"] == [1]


def test_already_settled_record_is_immutable_to_later_actual_payload():
    ledger = _ledger(1)
    settled = ledger["records"]["1"]
    settled["status"] = "SETTLED"
    settled["actual"] = {
        "settled_at": "2026-08-21T10:00:00+00:00",
        "players": [
            {"element": 10, "points": 7.0, "minutes": 90.0, "started": 1, "clean_sheet": 1},
            {"element": 11, "points": 2.0, "minutes": 30.0, "started": 0, "clean_sheet": 0},
        ],
    }
    settled["metrics"] = {"sample_size": 2, "status": "SETTLED"}
    before = deepcopy(settled["actual"])
    result = evaluate(
        prediction={"planning_gw": 0},
        context={"planning_gw": 0, "scoring_gw": 2},
        bootstrap=_bootstrap(True),
        event_live=None,
        ledger=ledger,
        event_live_by_gw={"1": _event_live(99, 99)},
    )
    assert result["ledger"]["records"]["1"]["actual"] == before
    assert result["accuracy"]["settlement"]["completed_gameweeks"] == []
