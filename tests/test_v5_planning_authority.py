from __future__ import annotations

import pytest

from src.v5.decision.planning_override import apply_user_lineup_override
from src.v5.squad import projection_baseline_authority


def _player(element: int, position: str) -> dict:
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": (element % 10) + 1,
        "start_probability": 0.95,
        "dnp_probability": 0.02,
        "expected_minutes": 80.0,
        "score": 1.0,
    }


def _engine_lineup() -> dict:
    players = {
        1: _player(1, "GK"),
        2: _player(2, "GK"),
        3: _player(3, "DEF"),
        4: _player(4, "DEF"),
        5: _player(5, "DEF"),
        6: _player(6, "DEF"),
        7: _player(7, "DEF"),
        8: _player(8, "MID"),
        9: _player(9, "MID"),
        10: _player(10, "MID"),
        11: _player(11, "MID"),
        12: _player(12, "MID"),
        13: _player(13, "FWD"),
        14: _player(14, "FWD"),
        15: _player(15, "FWD"),
    }
    starter_ids = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    bench_ids = [6, 7, 12, 2]
    return {
        "status": "READY",
        "planning_gw": 2,
        "formation": "3-4-3",
        "starters": [players[element] for element in starter_ids],
        "bench": [players[element] for element in bench_ids],
        "captain": players[13],
        "vice_captain": players[14],
        "captain_safe_pool": [players[13], players[14]],
        "authority": "v5_decision_lineup_optimizer",
    }


def _truth(phase: str = "PRE_DEADLINE") -> dict:
    return {
        "context": {"phase": phase},
        "chip_state": {"active_chip": "wildcard", "source": "user_lock", "legal": True},
    }


def _rules() -> dict:
    return {"lineup": {"legal_formations": ["3-4-3", "4-4-2", "4-3-3", "3-5-2", "5-3-2"]}}


def _valid_override(gw: int = 2) -> dict:
    return {
        "status": "ACTIVE",
        "gw": gw,
        "source": "USER_MANUAL_DECISION",
        "starting_xi": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        "captain": 13,
        "vice_captain": 9,
        "bench_gk": 2,
        "bench_order": [7, 12, 15],
        "active_chip": "WILDCARD",
    }


def test_targeted_squad_override_only_applies_to_exact_planning_gw() -> None:
    lock = {"wildcard_active": True, "planning_override_active": True, "target_gw": 2}
    exact = projection_baseline_authority(lock, planning_gw=2, submitted_gw=1)
    stale = projection_baseline_authority(lock, planning_gw=3, submitted_gw=2)

    assert exact["override_applied"] is True
    assert exact["stale_override_rejected"] is False
    assert stale["override_applied"] is False
    assert stale["stale_override_rejected"] is True


def test_active_squad_override_without_target_gw_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="target_gw"):
        projection_baseline_authority(
            {"wildcard_active": True, "planning_override_active": True},
            planning_gw=2,
            submitted_gw=1,
        )


def test_post_deadline_submission_reclaims_targeted_squad_authority() -> None:
    result = projection_baseline_authority(
        {"wildcard_active": True, "planning_override_active": True, "target_gw": 2},
        planning_gw=2,
        submitted_gw=2,
    )
    assert result["override_applied"] is False
    assert result["post_deadline_official_reclaims_authority"] is True


def test_explicit_user_lineup_becomes_effective_and_engine_is_preserved() -> None:
    engine = _engine_lineup()
    effective, authority = apply_user_lineup_override(
        engine,
        truth=_truth(),
        rules=_rules(),
        planning_gw=2,
        override=_valid_override(),
    )

    assert authority["active"] is True
    assert authority["engine_recommendation_preserved"] is True
    assert effective["authority"] == "user_manual_decision"
    assert effective["formation"] == "4-4-2"
    assert effective["captain"]["element"] == 13
    assert effective["vice_captain"]["element"] == 9
    assert engine["formation"] == "3-4-3"
    assert engine["vice_captain"]["element"] == 14


def test_stale_user_lineup_override_does_not_leak_into_next_gw() -> None:
    engine = _engine_lineup()
    effective, authority = apply_user_lineup_override(
        engine,
        truth=_truth(),
        rules=_rules(),
        planning_gw=3,
        override=_valid_override(gw=2),
    )
    assert authority["active"] is False
    assert authority["reason"] == "STALE_TARGET_GW"
    assert effective["authority"] == "v5_decision_lineup_optimizer"


def test_post_deadline_manual_lineup_cannot_override_official_authority() -> None:
    engine = _engine_lineup()
    effective, authority = apply_user_lineup_override(
        engine,
        truth=_truth("POST_DEADLINE"),
        rules=_rules(),
        planning_gw=2,
        override=_valid_override(),
    )
    assert authority["active"] is False
    assert authority["post_deadline_official_submission_reclaims_authority"] is True
    assert effective["authority"] == "v5_decision_lineup_optimizer"


def test_illegal_user_captain_outside_xi_fails_closed() -> None:
    override = _valid_override()
    override["captain"] = 15
    with pytest.raises(RuntimeError, match="captain and vice"):
        apply_user_lineup_override(
            _engine_lineup(),
            truth=_truth(),
            rules=_rules(),
            planning_gw=2,
            override=override,
        )
