from copy import deepcopy
from datetime import datetime, timezone

from src.engines.team_state_service import (
    CANONICAL_USER_CAPTURE_AUTHORITY,
    OFFICIAL_SUBMITTED_AUTHORITY,
    projection_baseline_authority,
    validate_user_capture,
)
from src.runtime_v3.definition_of_done import _user_capture_authority_contract
from src.settings import TEAM_ID


NOW = datetime(2026, 8, 30, 16, 0, tzinfo=timezone.utc)


def _fixture():
    teams = {index: f"Club {index}" for index in range(1, 6)}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    specs = [
        (1, 1, 1),
        (2, 1, 2),
        (3, 2, 1),
        (4, 2, 2),
        (5, 2, 3),
        (6, 2, 4),
        (7, 2, 5),
        (8, 3, 1),
        (9, 3, 2),
        (10, 3, 3),
        (11, 3, 4),
        (12, 3, 5),
        (13, 4, 3),
        (14, 4, 4),
        (15, 4, 5),
    ]
    by_id = {
        element: {
            "id": element,
            "web_name": f"P{element}",
            "element_type": element_type,
            "team": team,
            "now_cost": 50 + element,
            "cost_change_start": 0,
        }
        for element, element_type, team in specs
    }
    lock = {
        "team_id": TEAM_ID,
        "locked_at": "2026-08-25T03:44:30Z",
        "planning_override_active": True,
        "target_gw": 3,
        "authority_source": "USER_CAPTURE_TEST_FIXTURE",
        "players": [
            {
                "element": element,
                "position": positions[element_type],
                "expected_web_name": f"P{element}",
                "expected_team": teams[team],
                "purchase_cost": 50 + element,
            }
            for element, element_type, team in specs
        ],
    }
    phase = {
        "planning_gw": 3,
        "submitted_gw": 2,
        "deadline_time": "2026-09-01T10:00:00Z",
    }
    return lock, phase, by_id, teams, positions


def _evaluate(lock, phase, by_id, teams, positions):
    preliminary = projection_baseline_authority(lock, phase, now=NOW)
    validation = None
    if preliminary["capture_evidence_required"]:
        validation = validate_user_capture(
            lock,
            phase,
            by_id,
            teams,
            positions,
            now=NOW,
        )
    baseline = projection_baseline_authority(
        lock,
        phase,
        capture_validation=validation,
        now=NOW,
    )
    return validation, baseline


def test_no_capture_uses_official_and_passes_authority_contract():
    _, phase, by_id, teams, positions = _fixture()
    validation, baseline = _evaluate({}, phase, by_id, teams, positions)
    assert validation is None
    assert baseline["effective_authority"] == OFFICIAL_SUBMITTED_AUTHORITY
    assert baseline["override_requested"] is False
    assert _user_capture_authority_contract(baseline)[0] is True


def test_valid_exact_gw_predeadline_capture_is_first_class_authority():
    lock, phase, by_id, teams, positions = _fixture()
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["valid"] is True
    assert validation["identity_validated"] is True
    assert validation["squad_legal"] is True
    assert validation["purchase_cost_exact_for_all"] is True
    assert baseline["effective_authority"] == CANONICAL_USER_CAPTURE_AUTHORITY
    assert baseline["override_applied"] is True
    assert baseline["stale_override_rejected"] is False
    assert baseline["capture_target_gw_matches"] is True
    assert baseline["capture_pre_deadline_phase"] is True
    assert _user_capture_authority_contract(baseline)[0] is True


def test_stale_previous_gw_capture_is_rejected_without_failing_governance():
    lock, phase, by_id, teams, positions = _fixture()
    lock["target_gw"] = 2
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation is None
    assert baseline["effective_authority"] == OFFICIAL_SUBMITTED_AUTHORITY
    assert baseline["stale_override_rejected"] is True
    assert baseline["capture_rejection_reason"] == "STALE_TARGET_GW"
    assert _user_capture_authority_contract(baseline)[0] is True


def test_wrong_future_gw_capture_is_rejected_before_it_can_apply():
    lock, phase, by_id, teams, positions = _fixture()
    lock["target_gw"] = 4
    _, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert baseline["effective_authority"] == OFFICIAL_SUBMITTED_AUTHORITY
    assert baseline["wrong_gw_override_rejected"] is True
    assert baseline["capture_rejection_reason"] == "WRONG_FUTURE_TARGET_GW"
    assert _user_capture_authority_contract(baseline)[0] is True


def test_postdeadline_official_deterministically_reclaims_authority():
    lock, phase, by_id, teams, positions = _fixture()
    phase["submitted_gw"] = 3
    _, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert baseline["effective_authority"] == OFFICIAL_SUBMITTED_AUTHORITY
    assert baseline["override_applied"] is False
    assert baseline["post_deadline_official_reclaims_authority"] is True
    assert baseline["capture_rejection_reason"] == "POST_DEADLINE_OFFICIAL_RECLAIM"
    assert _user_capture_authority_contract(baseline)[0] is True


def test_exact_gw_capture_missing_required_provenance_fails_dod():
    lock, phase, by_id, teams, positions = _fixture()
    lock.pop("authority_source")
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["valid"] is False
    assert "missing_capture_provenance" in validation["errors"]
    assert baseline["override_applied"] is False
    assert baseline["capture_rejection_reason"] == "INVALID_CAPTURE_EVIDENCE"
    assert _user_capture_authority_contract(baseline)[0] is False


def test_exact_gw_capture_missing_timestamp_fails_dod():
    lock, phase, by_id, teams, positions = _fixture()
    lock.pop("locked_at")
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["timestamp_valid"] is False
    assert baseline["override_applied"] is False
    assert _user_capture_authority_contract(baseline)[0] is False


def test_illegal_duplicate_capture_is_not_applied():
    lock, phase, by_id, teams, positions = _fixture()
    lock["players"][-1] = deepcopy(lock["players"][-2])
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["valid"] is False
    assert baseline["effective_authority"] == OFFICIAL_SUBMITTED_AUTHORITY
    assert baseline["capture_rejection_reason"] == "INVALID_CAPTURE_EVIDENCE"
    assert _user_capture_authority_contract(baseline)[0] is False


def test_more_than_three_players_from_one_club_is_rejected():
    lock, phase, by_id, teams, positions = _fixture()
    for element in (4, 5):
        by_id[element]["team"] = 1
        lock["players"][element - 1]["expected_team"] = teams[1]
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["squad_legal"] is False
    assert baseline["override_applied"] is False
    assert _user_capture_authority_contract(baseline)[0] is False


def test_unresolved_official_element_is_rejected():
    lock, phase, by_id, teams, positions = _fixture()
    lock["players"][0]["element"] = 9999
    lock["players"][0].pop("expected_web_name")
    lock["players"][0].pop("expected_team")
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["identity_validated"] is False
    assert baseline["override_applied"] is False
    assert _user_capture_authority_contract(baseline)[0] is False


def test_supplied_lineup_bench_captain_vice_and_chip_are_validated():
    lock, phase, by_id, teams, positions = _fixture()
    lock.update(
        {
            "starting_xi": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
            "bench_gk": 2,
            "bench_order": [6, 15, 7],
            "captain": 13,
            "vice_captain": 8,
            "active_chip": "triple_captain",
        }
    )
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["lineup"]["status"] == "VALID"
    assert baseline["override_applied"] is True
    assert _user_capture_authority_contract(baseline)[0] is True


def test_illegal_supplied_lineup_is_rejected():
    lock, phase, by_id, teams, positions = _fixture()
    lock.update(
        {
            "starting_xi": [1, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15],
            "bench_gk": 2,
            "bench_order": [5, 6, 7],
            "captain": 13,
            "vice_captain": 8,
        }
    )
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["lineup"]["valid"] is False
    assert "starting_xi_illegal_formation" in validation["lineup"]["errors"]
    assert baseline["override_applied"] is False
    assert _user_capture_authority_contract(baseline)[0] is False


def test_capture_finance_is_only_exact_for_explicit_purchase_costs():
    lock, phase, by_id, teams, positions = _fixture()
    lock["players"][0].pop("purchase_cost")
    validation, baseline = _evaluate(lock, phase, by_id, teams, positions)
    assert validation["valid"] is True
    assert validation["purchase_cost_rows_supplied"] == 14
    assert validation["purchase_cost_exact_for_all"] is False
    assert baseline["override_applied"] is True


def test_authority_phase_contradiction_fails_dod():
    lock, phase, by_id, teams, positions = _fixture()
    _, baseline = _evaluate(lock, phase, by_id, teams, positions)
    baseline["override_applied"] = False
    assert _user_capture_authority_contract(baseline)[0] is False
