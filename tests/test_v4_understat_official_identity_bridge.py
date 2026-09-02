from __future__ import annotations

import pytest

from src.intelligence.understat_tactical import normalize_player_evidence
from src.services.enrichment_service import _official_player_row
from src.sources.understat import _normalize_ajax_payload


def _snapshot_meta() -> dict:
    return {
        "source": "bootstrap-static.elements",
        "source_snapshot_id": "snapshot",
        "fetched_at": "2026-09-02T00:00:00+00:00",
        "observed_at": "2026-09-02T00:00:00+00:00",
        "freshness": "FRESH",
    }


def _policy() -> dict:
    return {
        "sample_size": {
            "low_confidence_matches_below": 3,
            "mature_matches_at_least": 5,
            "small_sample_shrinkage_prior_matches": 5,
        },
        "identity": {
            "fuzzy_minimum_confidence": 0.94,
            "ambiguity_margin": 0.03,
        },
    }


def test_official_identity_keeps_web_name_and_full_identity_variants():
    player = {
        "id": 7,
        "web_name": "Saka",
        "first_name": "Bukayo",
        "second_name": "Saka",
        "team": 1,
        "element_type": 3,
        "now_cost": 95,
        "selected_by_percent": "10.0",
        "status": "a",
        "minutes": 180,
    }
    row = _official_player_row(player, {1: "Arsenal"}, {3: "MID"}, _snapshot_meta())
    assert row["element_id"] == 7
    assert row["name"] == "Saka"
    assert row["web_name"] == "Saka"
    assert row["full_name"] == "Bukayo Saka"
    assert row["name_variants"] == ["Bukayo Saka", "Saka"]
    assert row["source"] == "bootstrap-static.elements"


def test_understat_join_uses_full_official_identity_without_player_aliases():
    official = {
        "element": 7,
        "element_id": 7,
        "name": "Bukayo Saka",
        "team": "Arsenal",
        "team_id": 1,
        "position": "MID",
        "minutes": 180,
    }
    raw = {
        "embedded": {
            "playersData": [
                {
                    "id": "501",
                    "player_name": "Bukayo Saka",
                    "team_title": "Arsenal",
                    "position": "M",
                    "games": "2",
                    "time": "180",
                    "xG": "1.0",
                    "xA": "0.5",
                    "xGChain": "1.6",
                    "xGBuildup": "0.4",
                    "shots": "6",
                    "key_passes": "4",
                }
            ]
        }
    }
    mapped, unresolved = normalize_player_evidence(raw, [official], _policy())
    assert unresolved == []
    assert mapped["7"]["mapping"]["state"] == "RESOLVED"
    assert mapped["7"]["understat_player_id"] == "501"
    assert mapped["7"]["mapping"]["method"] == "TEAM_AND_NORMALIZED_NAME_EXACT"


def test_understat_xhr_team_representation_aliases_are_team_only():
    payload = {
        "teams": {
            "1": {"id": "1", "title": "Coventry City", "history": []},
            "2": {"id": "2", "title": "Hull City", "history": []},
            "3": {"id": "3", "title": "Ipswich Town", "history": []},
            "4": {"id": "4", "title": "Nottingham Forest", "history": []},
        },
        "players": [
            {"id": "10", "player_name": "Example Player", "team_title": "Hull City"},
        ],
        "dates": [],
    }
    normalized = _normalize_ajax_payload(payload)
    assert normalized["teamsData"]["1"]["title"] == "Coventry"
    assert normalized["teamsData"]["2"]["title"] == "Hull"
    assert normalized["teamsData"]["3"]["title"] == "Ipswich"
    assert normalized["teamsData"]["4"]["title"] == "Nott'm Forest"
    assert normalized["playersData"][0]["team_title"] == "Hull"
    assert normalized["playersData"][0]["player_name"] == "Example Player"
    assert normalized["playersData"][0]["source_team_title"] == "Hull City"


def test_full_official_crosswalk_classifies_source_absent_without_fake_match():
    official = [
        {
            "element": 7,
            "element_id": 7,
            "name": "Bukayo Saka",
            "full_name": "Bukayo Saka",
            "web_name": "Saka",
            "second_name": "Saka",
            "name_variants": ["Bukayo Saka", "Saka"],
            "team": "Arsenal",
            "team_id": 1,
            "position": "MID",
            "minutes": 180,
        },
        {
            "element": 8,
            "element_id": 8,
            "name": "New Player",
            "full_name": "New Player",
            "web_name": "New Player",
            "second_name": "Player",
            "name_variants": ["New Player", "Player"],
            "team": "Arsenal",
            "team_id": 1,
            "position": "MID",
            "minutes": 0,
        },
    ]
    raw = {
        "embedded": {
            "playersData": [
                {
                    "id": "501",
                    "player_name": "Bukayo Saka",
                    "team_title": "Arsenal",
                    "position": "M",
                    "games": "2",
                    "time": "180",
                    "xG": "1.0",
                    "xA": "0.5",
                    "xGChain": "1.6",
                    "xGBuildup": "0.4",
                }
            ]
        }
    }
    mapped, unresolved = normalize_player_evidence(raw, official, _policy())
    assert unresolved == []
    assert len(mapped) == len(official)
    assert mapped["7"]["mapping"]["state"] == "RESOLVED"
    assert mapped["8"]["mapping"]["state"] == "SOURCE_ABSENT_CURRENT_SEASON"
    assert mapped["8"].get("understat_player_id") is None


@pytest.mark.parametrize(
    ("element", "official_name", "web_name", "second_name", "official_team", "official_position", "source_name", "source_team", "source_position", "expected_method"),
    [
        (102, "Yehor Yarmoliuk", "Yarmoliuk", "Yarmoliuk", "Brentford", "MID", "Yehor Yarmolyuk", "Brentford", "M", "TEAM_SCOPED_NEAR_TOKEN_IDENTITY"),
        (211, "Yéremy Pino Santos", "Yeremy", "Pino Santos", "Crystal Palace", "MID", "Yeremi Pino", "Crystal Palace", "M F", "TEAM_SCOPED_NEAR_TOKEN_IDENTITY"),
        (295, "Oli McBurnie", "McBurnie", "McBurnie", "Hull City", "FWD", "Oliver McBurnie", "Hull", "F", "TEAM_SCOPED_UNIQUE_SURNAME_IDENTITY"),
        (592, "Abdoul Ouattara", "Ouattara", "Ouattara", "Ipswich Town", "MID", "Guemissongui Ouattara", "Ipswich", "M", "TEAM_SCOPED_UNIQUE_SURNAME_IDENTITY"),
        (350, "Alisson Becker", "A.Becker", "Becker", "Liverpool", "GK", "Alisson", "Liverpool", "GK", "TEAM_SCOPED_MONONYM_EXACT"),
        (474, "Jair Paula da Cunha Filho", "Jair Cunha", "Paula da Cunha Filho", "Nott'm Forest", "DEF", "Jair", "Nott'm Forest", "D", "TEAM_SCOPED_MONONYM_EXACT"),
    ],
)
def test_generic_identity_resolver_handles_live_cross_source_name_shapes(
    element,
    official_name,
    web_name,
    second_name,
    official_team,
    official_position,
    source_name,
    source_team,
    source_position,
    expected_method,
):
    official = {
        "element": element,
        "element_id": element,
        "name": official_name,
        "full_name": official_name,
        "web_name": web_name,
        "second_name": second_name,
        "name_variants": [official_name, web_name, second_name],
        "team": official_team,
        "team_id": 1,
        "position": official_position,
        "minutes": 180,
    }
    raw = {
        "embedded": {
            "playersData": [
                {
                    "id": str(10000 + element),
                    "player_name": source_name,
                    "team_title": source_team,
                    "position": source_position,
                    "games": "2",
                    "time": "180",
                    "xG": "0.2",
                    "xA": "0.2",
                    "xGChain": "0.6",
                    "xGBuildup": "0.3",
                }
            ]
        }
    }
    mapped, unresolved = normalize_player_evidence(raw, [official], _policy())
    assert unresolved == []
    assert mapped[str(element)]["mapping"]["state"] == "RESOLVED"
    assert mapped[str(element)]["mapping"]["method"] == expected_method
