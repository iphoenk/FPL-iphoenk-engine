from copy import deepcopy

from src.engines.live_state_service import classify_bonus_lifecycle
from src.models.official_role_evidence import attach_official_role_evidence
from src.models.official_set_piece_notes import (
    normalize_official_set_piece_notes,
    team_set_piece_note_evidence,
)


def _fixture(
    fixture_id,
    *,
    event=5,
    kickoff="2026-09-20T13:00:00Z",
    started=True,
    finished=False,
    finished_provisional=False,
):
    return {
        "id": fixture_id,
        "event": event,
        "kickoff_time": kickoff,
        "started": started,
        "finished": finished,
        "finished_provisional": finished_provisional,
    }


def test_fact1_live_bonus_is_provisional():
    got = classify_bonus_lifecycle(
        [_fixture(1)],
        5,
        {"status": [{"event": 5, "date": "2026-09-20", "bonus_added": False}]},
        event_meta={"id": 5, "finished": False, "data_checked": False},
    )
    assert got["lifecycle_state"] == "LIVE_PROVISIONAL"
    assert got["status"] == "PROVISIONAL"
    assert got["provisional"] is True
    assert got["match_state"] == "IN_PROGRESS"


def test_fact1_finished_provisional_never_implies_final_bonus():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                started=True,
                finished=True,
                finished_provisional=True,
            )
        ],
        5,
        {"status": []},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "AWAITING_BONUS_FINALIZATION"
    assert got["status"] == "PROVISIONAL"
    assert got["finished_provisional_is_final_authority"] is False


def test_fact1_final_requires_bonus_added_and_final_event_state():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                started=True,
                finished=True,
                finished_provisional=True,
            )
        ],
        5,
        {"status": [{"event": 5, "date": "2026-09-20", "bonus_added": True}]},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "FINAL"
    assert got["status"] == "FINAL"
    assert got["provisional"] is False
    assert got["match_state"] == "FINALIZED"


def test_fact1_multi_day_gw_can_be_partially_finalized_without_becoming_final():
    got = classify_bonus_lifecycle(
        [
            _fixture(
                1,
                kickoff="2026-09-19T14:00:00Z",
                started=True,
                finished=True,
                finished_provisional=True,
            ),
            _fixture(
                2,
                kickoff="2026-09-20T15:30:00Z",
                started=False,
                finished=False,
            ),
        ],
        5,
        {"status": [{"event": 5, "date": "2026-09-19", "bonus_added": True}]},
        event_meta={"id": 5, "finished": False, "data_checked": False},
    )
    assert got["lifecycle_state"] == "PARTIALLY_FINALIZED"
    assert got["status"] == "PROVISIONAL"
    assert got["bonus_finalized_dates"] == ["2026-09-19"]


def test_fact1_wrong_event_bonus_status_cannot_finalize_target_gw():
    got = classify_bonus_lifecycle(
        [_fixture(1, started=True, finished=True, finished_provisional=True)],
        5,
        {"status": [{"event": 4, "date": "2026-09-20", "bonus_added": True}]},
        event_meta={"id": 5, "finished": True, "data_checked": True},
    )
    assert got["lifecycle_state"] == "AWAITING_BONUS_FINALIZATION"


def test_fact2_placeholder_notes_are_available_but_not_actionable():
    payload = {
        "last_updated": "2026-09-10T13:57:36Z",
        "teams": [
            {
                "id": 1,
                "notes": [
                    {
                        "external_link": True,
                        "info_message": "Check back for additional notes soon",
                        "source_link": "",
                    }
                ],
            }
        ],
    }
    got = team_set_piece_note_evidence(payload, 1)
    assert got["status"] == "PLACEHOLDER_ONLY"
    assert got["actionable"] is False
    assert got["advisory_only"] is True
    assert got["direct_xmins_mutation"] is False
    assert got["direct_xpts_mutation"] is False
    assert got["direct_start_probability_mutation"] is False


def test_fact2_actionable_note_is_evidence_only_and_cannot_mutate_projection_math():
    notes = {
        "last_updated": "2026-10-01T10:00:00Z",
        "teams": [
            {
                "id": 7,
                "notes": [
                    {
                        "external_link": False,
                        "info_message": "Player A has recently taken corners.",
                        "source_link": "",
                    }
                ],
            }
        ],
    }
    projections = {
        "players": [
            {
                "element": 10,
                "xpts": 6.25,
                "xmins": {
                    "expected_minutes": 82.0,
                    "start_probability": 0.91,
                },
            }
        ]
    }
    canonical_before = deepcopy(projections["players"][0])
    summary = attach_official_role_evidence(
        projections,
        {
            "elements": [
                {
                    "id": 10,
                    "team": 7,
                    "corners_and_indirect_freekicks_order": 1,
                    "penalties_order": 2,
                }
            ]
        },
        set_piece_notes=notes,
    )
    player = projections["players"][0]
    assert player["xpts"] == canonical_before["xpts"]
    assert player["xmins"] == canonical_before["xmins"]
    assert player["official_set_piece_notes"]["status"] == "ACTIONABLE_EVIDENCE"
    assert player["official_set_piece_notes"]["advisory_only"] is True
    assert summary["direct_xpts_mutation"] is False
    assert summary["direct_xmins_mutation"] is False
    assert summary["direct_start_probability_mutation"] is False


def test_fact2_normalizer_keeps_source_and_actionability_counts():
    payload = {
        "last_updated": "2026-09-10T13:57:36Z",
        "teams": [
            {"id": 1, "notes": [{"info_message": "Check back for additional notes soon"}]},
            {"id": 2, "notes": [{"info_message": "Player B is first in line for penalties."}]},
        ],
    }
    got = normalize_official_set_piece_notes(payload)
    assert got["team_count"] == 2
    assert got["actionable_team_count"] == 1
    assert got["evidence_only"] is True
    assert got["direct_model_override_forbidden"] is True
