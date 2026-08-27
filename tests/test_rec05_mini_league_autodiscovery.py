from src.engines import official_expansion as oe


def test_auto_discovery_selects_private_and_excludes_system_leagues(monkeypatch):
    monkeypatch.setattr(oe, "_mini_league_config", lambda: {"auto_discovery": {"enabled": True, "private_only": True, "max_per_kind": 5, "private_signals": ["entry_can_leave", "entry_can_admin", "entry_can_invite"]}, "classic_league_ids": [], "h2h_league_ids": [], "environment_override": {}})
    entry = {"leagues": {"classic": [
        {"id": 1, "name": "Overall", "entry_can_leave": False, "entry_can_admin": False, "entry_can_invite": False},
        {"id": 101, "name": "Private A", "entry_can_leave": True},
        {"id": 102, "name": "Private B", "entry_can_invite": True},
    ], "h2h": [{"id": 201, "name": "H2H Private", "entry_can_admin": True}]}}
    assert oe._discovered_private_league_ids("classic", entry) == ["101", "102"]
    assert oe._discovered_private_league_ids("h2h", entry) == ["201"]


def test_explicit_ids_are_kept_before_auto_discovered_ids(monkeypatch):
    monkeypatch.setattr(oe, "_mini_league_config", lambda: {"auto_discovery": {"enabled": True, "private_only": True, "max_per_kind": 5, "private_signals": ["entry_can_leave"]}, "classic_league_ids": ["999"], "h2h_league_ids": [], "environment_override": {}})
    monkeypatch.delenv("FPL_CLASSIC_LEAGUE_IDS", raising=False)
    entry = {"leagues": {"classic": [{"id": 101, "entry_can_leave": True}]}}
    assert oe._configured_league_ids("classic", entry) == ["999", "101"]


def test_discovery_is_bounded(monkeypatch):
    monkeypatch.setattr(oe, "_mini_league_config", lambda: {"auto_discovery": {"enabled": True, "private_only": True, "max_per_kind": 2, "private_signals": ["entry_can_leave"]}})
    entry = {"leagues": {"classic": [{"id": i, "entry_can_leave": True} for i in range(10, 20)]}}
    assert oe._discovered_private_league_ids("classic", entry) == ["10", "11"]
