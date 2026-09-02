from __future__ import annotations

from src.engines import understat_tactical_consumption as consumption
from src.intelligence.understat_tactical import build_understat_tactical, normalize_player_evidence, normalize_team_evidence
from src.sources.understat import parse_embedded_json


def _policy():
    return {
        "rolling_windows": [1, 3, 5],
        "venue_splits": ["HOME", "AWAY"],
        "sample_size": {"low_confidence_matches_below": 3, "mature_matches_at_least": 5, "small_sample_shrinkage_prior_matches": 5},
        "identity": {"fuzzy_minimum_confidence": 0.94, "ambiguity_margin": 0.03},
    }


def _raw():
    history_a = [
        {"xG": 1.8, "xGA": 0.7, "deep": 10, "deep_allowed": 4, "ppda": {"att": 45, "def": 9}, "ppda_allowed": {"att": 90, "def": 10}, "h_a": "h"},
        {"xG": 1.4, "xGA": 0.9, "deep": 8, "deep_allowed": 5, "ppda": {"att": 54, "def": 9}, "ppda_allowed": {"att": 88, "def": 11}, "h_a": "a"},
        {"xG": 2.0, "xGA": 0.6, "deep": 11, "deep_allowed": 3, "ppda": {"att": 40, "def": 8}, "ppda_allowed": {"att": 95, "def": 10}, "h_a": "h"},
    ]
    history_b = [
        {"xG": 0.8, "xGA": 1.7, "deep": 4, "deep_allowed": 10, "ppda": {"att": 100, "def": 10}, "ppda_allowed": {"att": 50, "def": 10}, "h_a": "a"},
        {"xG": 0.9, "xGA": 1.5, "deep": 5, "deep_allowed": 9, "ppda": {"att": 90, "def": 9}, "ppda_allowed": {"att": 54, "def": 9}, "h_a": "h"},
        {"xG": 0.7, "xGA": 1.8, "deep": 3, "deep_allowed": 11, "ppda": {"att": 110, "def": 10}, "ppda_allowed": {"att": 48, "def": 8}, "h_a": "a"},
    ]
    return {
        "source_availability": "AVAILABLE",
        "freshness": "FRESH",
        "fetched_at": "2026-09-02T10:00:00+00:00",
        "schema_valid": True,
        "fallback": False,
        "provenance": {"provider": "Understat"},
        "embedded": {
            "teamsData": {
                "1": {"id": "1", "title": "Arsenal", "history": history_a},
                "2": {"id": "2", "title": "Chelsea", "history": history_b},
            },
            "playersData": [
                {"id": "10", "player_name": "Alpha", "team_title": "Arsenal", "position": "F", "games": 3, "time": 250, "xG": 1.5, "xA": 0.6, "xGChain": 2.8, "xGBuildup": 0.9, "shots": 8, "key_passes": 5},
                {"id": "20", "player_name": "Bravo", "team_title": "Chelsea", "position": "M", "games": 3, "time": 240, "xG": 0.5, "xA": 0.8, "xGChain": 2.0, "xGBuildup": 1.2, "shots": 4, "key_passes": 7},
            ],
            "datesData": [],
        },
    }


def _universe():
    return [
        {"element": 101, "name": "Alpha", "team": "Arsenal", "team_id": 1, "position": "FWD"},
        {"element": 102, "name": "Keeper", "team": "Arsenal", "team_id": 1, "position": "GK"},
        {"element": 201, "name": "Bravo", "team": "Chelsea", "team_id": 2, "position": "MID"},
        {"element": 202, "name": "Defender", "team": "Chelsea", "team_id": 2, "position": "DEF"},
    ]


def test_embedded_parser_never_executes_javascript():
    html = "var teamsData = JSON.parse('{\"1\":{\"title\":\"Arsenal\"}}');"
    parsed = parse_embedded_json(html)
    assert parsed["teamsData"]["1"]["title"] == "Arsenal"


def test_team_windows_ppda_and_small_sample_are_explicit():
    teams = normalize_team_evidence(_raw(), _policy())
    arsenal = teams["arsenal"]
    assert set(arsenal["windows"]) >= {"last_1", "last_3", "last_5", "season_to_date", "home", "away"}
    ppda = arsenal["windows"]["last_3"]["metric_evidence"]["ppda"]
    assert ppda["evidence_type"] == "DERIVED"
    assert "att_div_def" in ppda["derivation"]
    assert arsenal["windows"]["last_3"]["shrinkage"]["applied"] is True


def test_player_mapping_full_universe_missing_is_unknown_not_zero():
    players, unresolved = normalize_player_evidence(_raw(), _universe(), _policy())
    assert players["101"]["mapping"]["state"] == "RESOLVED"
    assert players["102"]["mapping"]["state"] == "UNRESOLVED"
    assert players["102"]["season_to_date"] is None
    assert any(row["element"] == 102 for row in unresolved)


def test_tactical_contract_covers_all_positions_without_xpts_mutation():
    snapshot = {"official": {"fixtures": [{"team_h": 1, "team_a": 2, "event": 3, "finished": False, "kickoff_time": "2026-09-05T14:00:00Z"}]}}
    payload = build_understat_tactical(_raw(), snapshot, _universe(), _policy())
    assert payload["contract"] == "UNDERSTAT_TACTICAL_INTELLIGENCE_V1"
    assert payload["health"]["official_universe_count"] == 4
    assert set(payload["player_evidence"]) == {"101", "102", "201", "202"}
    assert payload["guardrails"]["direct_xpts_mutation"] is False
    assert payload["guardrails"]["direct_xmins_mutation"] is False
    assert payload["guardrails"]["ppda_direct_xpts_conversion_forbidden"] is True


def test_ppda_alone_is_not_positive_transition_authority():
    snapshot = {"official": {"fixtures": [{"team_h": 1, "team_a": 2, "event": 3, "finished": False}]}}
    payload = build_understat_tactical(_raw(), snapshot, _universe(), _policy())
    transition = payload["tactical_matchups"]["101"]["dimensions"]["transition_environment"]
    assert transition["state"] == "INSUFFICIENT_EVIDENCE"


def test_consumption_missing_evidence_is_neutral_and_negative_is_not_positive():
    assert consumption._key({}) == (0, 0, 0, 0)
    assert consumption._key({"state": "INSUFFICIENT_EVIDENCE", "confidence": 1.0}) == (0, 0, 0, 1000)
    assert consumption._key({"state": "NEGATIVE", "confidence": 0.9})[0] == -1
    assert consumption._key({"state": "POSITIVE", "confidence": 0.9})[0] == 1


def test_intelligence_parity_contract_is_not_decision_parity():
    payload = build_understat_tactical(_raw(), {"official": {"fixtures": []}}, _universe(), _policy())
    assert payload["guardrails"]["intelligence_parity_not_decision_parity"] is True
    assert payload["guardrails"]["full_official_universe_mapping_attempted"] is True
