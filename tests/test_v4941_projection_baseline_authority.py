import pytest

from src.engines.v4_decision_pipeline import effective_planning_squad


def _team(authority="OFFICIAL_SUBMITTED"):
    squad = []
    ledger = []
    for element in range(1, 16):
        position = "GK" if element <= 2 else "DEF" if element <= 7 else "MID" if element <= 12 else "FWD"
        squad.append({"element": element, "name": f"P{element}", "position": position, "purchase_cost": 50})
        ledger.append({"element": element, "purchase_cost": 50, "sell_cost": 50})
    return {
        "squad_authority": authority,
        "squad": squad,
        "team_value_ledger": ledger,
        "totals": {"itb": 5},
    }


def test_normal_gw_optimizer_uses_previous_official_squad_even_if_old_wc_flag_remains():
    configured = {"wildcard_active": True, "target_gw": 2, "authority_source": "USER_CAPTURED_WC_DRAFT"}
    latest = {"phase": {"submitted_gw": 2, "planning_gw": 3}}
    effective = effective_planning_squad(_team("OFFICIAL_SUBMITTED"), configured, latest)
    assert [row["element"] for row in effective["players"]] == list(range(1, 16))
    assert effective["baseline_gw"] == 2
    assert effective["planning_gw"] == 3
    assert effective["wildcard_active"] is False
    assert effective["planning_override_active"] is False
    assert effective["authority_source"] == "OFFICIAL_FPL_PICKS"


def test_targeted_wc_projection_preserves_user_captured_override_for_target_gw_only():
    configured = {"wildcard_active": True, "target_gw": 2, "authority_source": "USER_CAPTURED_WC_DRAFT"}
    latest = {"phase": {"submitted_gw": 1, "planning_gw": 2}}
    effective = effective_planning_squad(_team("LOCKED_PRE_DEADLINE"), configured, latest)
    assert effective["baseline_gw"] == 1
    assert effective["planning_gw"] == 2
    assert effective["wildcard_active"] is True
    assert effective["planning_override_active"] is True
    assert effective["target_gw"] == 2
    assert effective["authority_source"] == "USER_CAPTURED_WC_DRAFT"


def test_effective_team_contract_requires_price_evidence():
    team = _team()
    team["team_value_ledger"][0]["purchase_cost"] = None
    team["team_value_ledger"][0]["sell_cost"] = None
    team["squad"][0]["purchase_cost"] = None
    with pytest.raises(RuntimeError, match="lacks price evidence"):
        effective_planning_squad(team, {}, {"phase": {"submitted_gw": 2, "planning_gw": 3}})
