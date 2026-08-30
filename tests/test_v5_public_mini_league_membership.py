from types import SimpleNamespace

from src.v5.mini_league import public_mini_league_memberships
from src.v5 import team_service


def _entry():
    return {
        "id": 42,
        "leagues": {
            "classic": [
                {"id": 314, "name": "Overall", "entry_rank": 100, "entry_last_rank": 90, "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
                {"id": 130459, "name": "Basdor", "entry_rank": 9, "entry_last_rank": 5, "entry_can_leave": True, "entry_can_admin": False, "entry_can_invite": False},
            ],
            "h2h": [
                {"id": 1798198, "name": "Basdor H2H", "entry_rank": 3, "entry_last_rank": 4, "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
            ],
        },
    }


def test_public_mini_league_memberships_match_current_production_semantics():
    out = public_mini_league_memberships(_entry())
    assert out["authority"] == "PUBLIC_OFFICIAL_ENTRY"
    assert out["entry_id"] == 42
    assert out["membership_count"] == 2
    assert out["classic_private_count"] == 1
    assert out["h2h_count"] == 1
    assert out["system_classic_excluded_count"] == 1
    by_id = {row["league_id"]: row for row in out["memberships"]}
    assert 314 not in by_id
    assert by_id[130459]["rank"] == 9
    assert by_id[130459]["rank_delta"] == -4
    assert by_id[1798198]["rank"] == 3
    assert by_id[1798198]["rank_delta"] == 1
    assert out["governance"]["prediction_mutation"] is False
    assert out["governance"]["decision_mutation"] is False


def test_public_mini_league_memberships_are_not_capped_at_five():
    classic = [
        {"id": i, "name": f"League {i}", "entry_rank": i, "entry_last_rank": i + 1, "entry_can_leave": True}
        for i in range(100, 109)
    ]
    out = public_mini_league_memberships({"id": 42, "leagues": {"classic": classic, "h2h": []}})
    assert out["classic_private_count"] == 9
    assert out["membership_count"] == 9


def test_team_truth_state_wires_public_mini_league_projection(monkeypatch):
    monkeypatch.setattr(
        team_service,
        "select_squad",
        lambda **kwargs: {"authority": "official_public", "squad": [{"element": 1}], "validation": {"passed": True}},
    )
    monkeypatch.setattr(
        team_service,
        "build_squad_ledger",
        lambda *args, **kwargs: {"market_value": 50, "sell_value": 50, "sell_value_complete": True, "exact_count": 1, "unresolved_elements": []},
    )
    identity = SimpleNamespace(players={1: {"now_cost": 50}})
    out = team_service.build_team_state(
        phase=SimpleNamespace(),
        bootstrap={},
        identity=identity,
        locked_squad=None,
        authenticated_my_team=None,
        submitted_picks=None,
        transfers=[],
        entry=_entry(),
    )
    assert out["mini_leagues"]["membership_count"] == 2
    assert out["mini_leagues"]["authority"] == "PUBLIC_OFFICIAL_ENTRY"
