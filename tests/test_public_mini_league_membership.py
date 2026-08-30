from src.engines import base_snapshot_service as bs


def test_public_mini_league_memberships_include_private_classic_and_all_h2h(monkeypatch):
    monkeypatch.setattr(bs, "TEAM_ID", 42)
    official = {
        "entry": {
            "leagues": {
                "classic": [
                    {"id": 314, "name": "Overall", "entry_rank": 100, "entry_last_rank": 90, "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
                    {"id": 130459, "name": "Basdor", "entry_rank": 9, "entry_last_rank": 5, "entry_can_leave": True, "entry_can_admin": False, "entry_can_invite": False},
                ],
                "h2h": [
                    {"id": 1798198, "name": "Basdor H2H", "entry_rank": 3, "entry_last_rank": 4, "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
                ],
            }
        }
    }
    out = bs._public_mini_league_memberships(official)
    assert out["authority"] == "PUBLIC_OFFICIAL_ENTRY"
    assert out["membership_count"] == 2
    assert out["classic_private_count"] == 1
    assert out["h2h_count"] == 1
    by_id = {row["league_id"]: row for row in out["memberships"]}
    assert 314 not in by_id
    assert by_id[130459]["rank"] == 9
    assert by_id[130459]["rank_delta"] == -4
    assert by_id[1798198]["rank"] == 3
    assert by_id[1798198]["rank_delta"] == 1


def test_public_mini_league_memberships_are_unbounded_by_old_five_league_tracking_cap(monkeypatch):
    monkeypatch.setattr(bs, "TEAM_ID", 42)
    classic = [
        {"id": i, "name": f"League {i}", "entry_rank": i, "entry_last_rank": i + 1, "entry_can_leave": True}
        for i in range(100, 109)
    ]
    out = bs._public_mini_league_memberships({"entry": {"leagues": {"classic": classic, "h2h": []}}})
    assert out["classic_private_count"] == 9
    assert out["membership_count"] == 9
