import pytest

from src.services.user_decision_overlay_service import build_effective_plan


def _row(element, position, xpts):
    return {"element": element, "name": f"P{element}", "position": position, "xpts": xpts}


def _engine_lineup():
    rows = {
        1: _row(1, "GK", 3.0),
        2: _row(2, "GK", 2.0),
        3: _row(3, "DEF", 4.0),
        4: _row(4, "DEF", 3.8),
        5: _row(5, "DEF", 3.6),
        6: _row(6, "DEF", 3.4),
        7: _row(7, "DEF", 3.2),
        8: _row(8, "MID", 5.0),
        9: _row(9, "MID", 4.8),
        10: _row(10, "MID", 4.6),
        11: _row(11, "MID", 4.4),
        12: _row(12, "MID", 4.2),
        13: _row(13, "FWD", 5.5),
        14: _row(14, "FWD", 5.2),
        15: _row(15, "FWD", 4.9),
    }
    starting_ids = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    starting = [rows[i] for i in starting_ids]
    return {
        "formation": "3-4-3",
        "xi_xpts": round(sum(r["xpts"] for r in starting), 2),
        "starting_xi": starting,
        "captain": rows[13],
        "vice_captain": rows[8],
        "bench": {
            "gk": rows[2],
            "order": [
                {"slot": 1, **rows[12]},
                {"slot": 2, **rows[6]},
                {"slot": 3, **rows[7]},
            ],
        },
        "chip_context": {"active_chip": "WILDCARD", "single_chip_rule_respected": True},
    }


def _team():
    return {
        "squad_authority": "LOCKED_PRE_DEADLINE",
        "squad": [{"element": i} for i in range(1, 16)],
    }


def _latest(gw=2):
    return {"phase": {"planning_gw": gw}}


def _manual():
    # User intentionally benches FWD 15 for MID 12 and changes captain.
    return {
        "gw": 2,
        "expires_after_gw": 2,
        "status": "MANUAL_DRAFT_ADJUSTABLE",
        "starting_xi": [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14],
        "captain": 8,
        "vice_captain": 13,
        "bench_gk": 2,
        "bench_order": [15, 6, 7],
        "active_chip": "WILDCARD",
        "source": "latest_user_pick_team_screenshot",
    }


def test_valid_user_override_is_effective_even_when_engine_has_higher_xpts():
    out = build_effective_plan(
        _engine_lineup(),
        _team(),
        _latest(2),
        _manual(),
        {"wildcard_active": True, "target_gw": 2},
    )
    effective = out["effective_plan"]
    assert out["status"] == "PASS"
    assert out["user_override"]["active"] is True
    assert effective["authority"] == "USER_OVERRIDE"
    assert effective["decision_authority"] == "USER"
    assert effective["formation"] == "3-5-2"
    assert effective["captain"]["element"] == 8
    assert effective["chip_context"]["active_chip"] == "WILDCARD"
    assert out["comparison"]["user_minus_engine_xpts"] < 0
    assert out["comparison"]["engine_can_warn_but_not_overwrite"] is True
    assert out["guardrails"]["engine_never_auto_overwrites_valid_user_override"] is True


def test_stale_manual_override_is_ignored_for_next_gw():
    out = build_effective_plan(
        _engine_lineup(),
        {**_team(), "squad_authority": "OFFICIAL_SUBMITTED"},
        _latest(3),
        _manual(),
        {"wildcard_active": True, "target_gw": 2},
    )
    assert out["user_override"]["active"] is False
    assert out["effective_plan"]["authority"] == "ENGINE_RECOMMENDATION"
    assert out["effective_plan"]["formation"] == "3-4-3"


def test_manual_captain_must_be_inside_user_xi():
    manual = _manual()
    manual["captain"] = 15
    with pytest.raises(RuntimeError, match="captain and vice"):
        build_effective_plan(
            _engine_lineup(),
            _team(),
            _latest(2),
            manual,
            {"wildcard_active": True, "target_gw": 2},
        )


def test_target_gw_wildcard_composition_cannot_claim_non_wc_chip():
    manual = _manual()
    manual["active_chip"] = "NONE"
    with pytest.raises(RuntimeError, match="requires WILDCARD"):
        build_effective_plan(
            _engine_lineup(),
            _team(),
            _latest(2),
            manual,
            {"wildcard_active": True, "target_gw": 2},
        )
