from src.v5.squad import _capture_is_current, select_squad
from src.v5.state import Phase, authority_chain


def _bootstrap():
    elements = []
    eid = 1
    for position_type, count in ((1, 2), (2, 5), (3, 5), (4, 3)):
        for _ in range(count):
            elements.append({
                "id": eid,
                "web_name": f"P{eid}",
                "team": ((eid - 1) // 3) + 1,
                "element_type": position_type,
                "now_cost": 50,
            })
            eid += 1
    teams = [{"id": i, "name": f"T{i}"} for i in range(1, 6)]
    return {"elements": elements, "teams": teams}


def _capture(target_gw=3):
    positions = ["GK", "GK"] + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return {
        "planning_override_active": True,
        "target_gw": target_gw,
        "players": [
            {"element": i, "position": positions[i - 1], "purchase_cost": 50}
            for i in range(1, 16)
        ],
    }


def _submitted():
    return {"picks": [{"element": i} for i in range(1, 16)]}


def _authenticated():
    return {"picks": [{"element": 16 - i, "purchase_price": 50} for i in range(1, 16)]}


def test_predeadline_chain_is_capture_then_public():
    assert authority_chain(Phase.PRE_DEADLINE, "squad") == ("user_capture", "official_public")
    assert "official_authenticated" not in authority_chain(Phase.PRE_DEADLINE, "squad")


def test_current_capture_beats_authenticated_overlay_and_public_submitted():
    resolved = select_squad(
        phase=Phase.PRE_DEADLINE,
        bootstrap=_bootstrap(),
        locked_squad=_capture(3),
        authenticated_my_team=_authenticated(),
        submitted_picks=_submitted(),
        planning_gw=3,
        submitted_gw=2,
    )
    assert resolved["authority"] == "user_capture"
    assert resolved["authority_policy"]["authenticated_official_production_blocking"] is False


def test_stale_capture_falls_back_to_public_submitted():
    resolved = select_squad(
        phase=Phase.PRE_DEADLINE,
        bootstrap=_bootstrap(),
        locked_squad=_capture(2),
        authenticated_my_team=_authenticated(),
        submitted_picks=_submitted(),
        planning_gw=3,
        submitted_gw=2,
    )
    assert resolved["authority"] == "official_public"
    assert resolved["authority_policy"]["capture_current"] is False


def test_postdeadline_public_reclaims_even_when_capture_targets_same_gw():
    resolved = select_squad(
        phase=Phase.POST_DEADLINE,
        bootstrap=_bootstrap(),
        locked_squad=_capture(3),
        authenticated_my_team=_authenticated(),
        submitted_picks=_submitted(),
        planning_gw=3,
        submitted_gw=3,
    )
    assert resolved["authority"] == "official_public"


def test_capture_requires_target_scope():
    capture = _capture(3)
    capture.pop("target_gw")
    assert _capture_is_current(capture, planning_gw=3, submitted_gw=2) is False


def test_authenticated_official_is_not_squad_authority_when_no_capture():
    resolved = select_squad(
        phase=Phase.PRE_DEADLINE,
        bootstrap=_bootstrap(),
        locked_squad=None,
        authenticated_my_team=_authenticated(),
        submitted_picks=_submitted(),
        planning_gw=3,
        submitted_gw=2,
    )
    assert resolved["authority"] == "official_public"
