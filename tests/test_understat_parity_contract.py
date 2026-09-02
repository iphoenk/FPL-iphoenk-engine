from __future__ import annotations

from src.intelligence.understat_tactical import build_matchups, normalize_player_evidence, normalize_team_evidence


REQUIRED_WINDOWS = {"last_1", "last_3", "last_5", "season_to_date", "home", "away"}
REQUIRED_MATCHUP_DIMENSIONS = {
    "attacking_environment",
    "creativity_environment",
    "finishing_environment",
    "transition_environment",
    "clean_sheet_environment",
    "goalkeeper_environment",
    "set_piece_environment",
}


def _history():
    return [
        {
            "xG": 1.8,
            "xGA": 0.9,
            "npxG": 1.7,
            "npxGA": 0.8,
            "deep": 9,
            "deep_allowed": 5,
            "ppda": {"att": 200, "def": 25},
            "ppda_allowed": {"att": 250, "def": 22},
            "scored": 2,
            "missed": 1,
            "h_a": "h" if index % 2 == 0 else "a",
        }
        for index in range(5)
    ]


def _raw():
    return {
        "schema_valid": True,
        "source_availability": "AVAILABLE",
        "freshness": "FRESH",
        "fetched_at": "2026-09-02T00:00:00+00:00",
        "provenance": {"provider": "Understat"},
        "embedded": {
            "teamsData": {
                "1": {"id": "1", "title": "Arsenal", "history": _history()},
                "2": {"id": "2", "title": "Chelsea", "history": _history()},
            },
            "playersData": [
                {"id": "10", "player_name": "Saka", "team_title": "Arsenal", "games": "5", "time": "450", "xG": "3", "xA": "2", "xGChain": "5", "xGBuildup": "1.5", "shots": "15", "key_passes": "10", "position": "M"},
                {"id": "20", "player_name": "Palmer", "team_title": "Chelsea", "games": "5", "time": "445", "xG": "2.5", "xA": "1.8", "xGChain": "4.6", "xGBuildup": "1.2", "shots": "14", "key_passes": "9", "position": "M"},
            ],
            "datesData": [],
        },
    }


def _universe():
    return [
        {"element": 101, "element_id": 101, "name": "Saka", "team": "Arsenal", "team_id": 1, "position": "MID"},
        {"element": 202, "element_id": 202, "name": "Palmer", "team": "Chelsea", "team_id": 2, "position": "MID"},
    ]


def _policy():
    return {
        "rolling_windows": [1, 3, 5],
        "venue_splits": ["HOME", "AWAY"],
        "sample_size": {"low_confidence_matches_below": 3, "mature_matches_at_least": 5, "small_sample_shrinkage_prior_matches": 5},
        "identity": {"fuzzy_minimum_confidence": 0.94, "ambiguity_margin": 0.03},
    }


def test_normalized_understat_intelligence_contract_is_engine_agnostic():
    universe = _universe()
    teams = normalize_team_evidence(_raw(), _policy())
    players, unresolved = normalize_player_evidence(_raw(), universe, _policy())
    fixtures = [{"id": 1, "event": 3, "team_h": 1, "team_a": 2, "finished": False, "kickoff_time": "2026-09-12T14:00:00Z"}]
    matchups = build_matchups(teams, players, universe, fixtures, _policy())

    arsenal = teams["arsenal"]
    assert REQUIRED_WINDOWS.issubset(arsenal["windows"])
    assert arsenal["windows"]["last_1"]["metric_evidence"]["xg"]["evidence_type"] == "SOURCE_OBSERVED"
    assert arsenal["windows"]["last_1"]["metric_evidence"]["ppda"]["evidence_type"] == "DERIVED"
    assert players["101"]["mapping"]["state"] == "RESOLVED"
    assert players["202"]["mapping"]["state"] == "RESOLVED"
    assert unresolved == []
    assert REQUIRED_MATCHUP_DIMENSIONS.issubset(matchups["101"]["dimensions"])
    assert matchups["101"]["state"] in {"POSITIVE", "NEUTRAL", "NEGATIVE", "INSUFFICIENT_EVIDENCE"}
    assert matchups["101"]["guardrails"]["ppda_direct_xpts_conversion"] is False
    assert matchups["101"]["guardrails"]["single_metric_authority"] is False
