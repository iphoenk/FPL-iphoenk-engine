from src.intelligence.understat_tactical import _map_player


def _source_mononym() -> list[dict]:
    return [{
        "understat_player_id": "source-1",
        "name": "Alex",
        "normalized_name": "alex",
        "teams": ["Test Club"],
        "normalized_teams": ["test club"],
        "position": "D",
    }]


def test_web_name_mononym_can_resolve_observed_player():
    official = {
        "team": "Test Club",
        "name": "Alex Alpha",
        "full_name": "Alex Alpha",
        "web_name": "Alex",
        "first_name": "Alex",
        "second_name": "Alpha",
        "name_variants": ["Alex Alpha", "Alex"],
        "minutes": 180,
    }
    row, confidence, method = _map_player(official, _source_mononym(), {})
    assert row is not None
    assert row["understat_player_id"] == "source-1"
    assert confidence >= 0.99
    assert method in {"TEAM_AND_NORMALIZED_NAME_EXACT", "TEAM_SCOPED_MONONYM_EXACT"}


def test_shared_first_name_is_not_an_identity_alias():
    official = {
        "team": "Test Club",
        "name": "Alex Beta",
        "full_name": "Alex Beta",
        "web_name": "Beta",
        "first_name": "Alex",
        "second_name": "Beta",
        "name_variants": ["Alex Beta", "Beta"],
        "minutes": 0,
    }
    row, confidence, method = _map_player(official, _source_mononym(), {})
    assert row is None
    assert confidence == 0.0
    assert method == "UNRESOLVED"
