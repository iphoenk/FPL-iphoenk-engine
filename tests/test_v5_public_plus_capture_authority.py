import pytest

from src.v5.squad import select_squad
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


def test_predeadline_chain_allows_scoped_capture_then_public():
    assert authority_chain(Phase.PRE_DEADLINE, "squad") == ("user_lock", "official_public")
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
    assert resolved["authority"] == "user_lock"
    assert resolved["projection_baseline"]["primary_authority_model"] == "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE"
    assert resolved["projection_baseline"]["override_applied"] is True
    assert resolved["projection_baseline"]["authenticated_official_is_private_enrichment_only"] is True


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
    assert resolved["projection_baseline"]["override_applied"] is False
    assert resolved["projection_baseline"]["stale_override_rejected"] is True


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
    assert resolved["projection_baseline"]["post_deadline_official_reclaims_authority"] is True


def test_active_capture_requires_exact_target_scope_and_fails_closed_without_it():
    capture = _capture(3)
    capture.pop("target_gw")
    with pytest.raises(RuntimeError, match="requires target_gw"):
        select_squad(
            phase=Phase.PRE_DEADLINE,
            bootstrap=_bootstrap(),
            locked_squad=capture,
            authenticated_my_team=_authenticated(),
            submitted_picks=_submitted(),
            planning_gw=3,
            submitted_gw=2,
        )


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
    assert resolved["projection_baseline"]["authenticated_official_is_private_enrichment_only"] is True
