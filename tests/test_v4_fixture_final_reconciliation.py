from datetime import datetime, timezone

from src.services.raw_snapshot_service import detect_phase


NOW = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)


def _bootstrap(*, current_finished: bool = False, deadline: str = "2026-08-28T17:30:00Z") -> dict:
    return {
        "events": [
            {"id": 1, "finished": True, "is_current": False, "is_next": False, "deadline_time": "2026-08-21T17:30:00Z"},
            {"id": 2, "finished": current_finished, "is_current": True, "is_next": False, "deadline_time": deadline},
            {"id": 3, "finished": False, "is_current": False, "is_next": True, "deadline_time": "2026-09-04T17:30:00Z"},
        ]
    }


def _fixtures(*states: dict) -> list[dict]:
    return [
        {
            "id": index + 100,
            "event": 2,
            "kickoff_time": "2026-08-30T13:00:00Z",
            "started": state.get("started", True),
            "finished": state.get("finished", False),
            "finished_provisional": state.get("finished_provisional", False),
        }
        for index, state in enumerate(states)
    ]


def test_bootstrap_finished_remains_primary_completion_authority() -> None:
    phase = detect_phase(
        _bootstrap(current_finished=True),
        _fixtures({"finished": True}, {"finished": True}),
        NOW,
    )
    assert phase["last_finished_gw"] == 2
    assert phase["last_finished_gw_source"] == "BOOTSTRAP_EVENT_FINISHED"
    assert phase["fixture_finalized_current_gw"] is False


def test_all_official_current_gw_fixtures_can_close_bootstrap_lag() -> None:
    phase = detect_phase(
        _bootstrap(),
        _fixtures({"finished": True}, {"finished": True}),
        NOW,
    )
    assert phase["bootstrap_last_finished_gw"] == 1
    assert phase["last_finished_gw"] == 2
    assert phase["last_finished_gw_source"] == "OFFICIAL_FIXTURE_FINALITY"
    assert phase["fixture_finalized_current_gw"] is True
    assert phase["fixture_finality_candidate_count"] == 2


def test_one_unfinished_fixture_cannot_promote_finished_gw() -> None:
    phase = detect_phase(
        _bootstrap(),
        _fixtures({"finished": True}, {"finished": False}),
        NOW,
    )
    assert phase["last_finished_gw"] == 1
    assert phase["last_finished_gw_source"] == "BOOTSTRAP_EVENT_FINISHED"
    assert phase["fixture_finalized_current_gw"] is False


def test_finished_provisional_never_counts_as_final() -> None:
    phase = detect_phase(
        _bootstrap(),
        _fixtures(
            {"finished": False, "finished_provisional": True},
            {"finished": False, "finished_provisional": True},
        ),
        NOW,
    )
    assert phase["last_finished_gw"] == 1
    assert phase["fixture_finalized_current_gw"] is False


def test_fixture_finality_never_preempts_future_deadline() -> None:
    phase = detect_phase(
        _bootstrap(deadline="2026-09-01T17:30:00Z"),
        _fixtures({"finished": True}, {"finished": True}),
        NOW,
    )
    assert phase["last_finished_gw"] == 1
    assert phase["fixture_finalized_current_gw"] is False


def test_empty_fixture_set_cannot_promote_finished_gw() -> None:
    phase = detect_phase(_bootstrap(), [], NOW)
    assert phase["last_finished_gw"] == 1
    assert phase["fixture_finalized_current_gw"] is False
