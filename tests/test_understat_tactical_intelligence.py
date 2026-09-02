from __future__ import annotations

import json

from src.engines.v4_lineup_optimizer import _select_close_call
from src.engines.v4_tactical_serving import _apply_watchlist_close_call
from src.intelligence.understat_tactical import (
    build_matchups,
    normalize_player_evidence,
    normalize_team_evidence,
)
from src.sources.understat import parse_embedded_json


def _policy() -> dict:
    return {
        "rolling_windows": [1, 3, 5],
        "venue_splits": ["HOME", "AWAY"],
        "sample_size": {
            "low_confidence_matches_below": 3,
            "mature_matches_at_least": 5,
            "small_sample_shrinkage_prior_matches": 5,
        },
        "identity": {
            "fuzzy_minimum_confidence": 0.94,
            "ambiguity_margin": 0.03,
        },
        "close_call": {
            "watchlist_base_score_margin": 0.15,
            "lineup_selection_score_margin": 0.12,
            "minimum_confidence": 0.6,
            "max_start_probability_disadvantage": 0.05,
            "max_dnp_probability_disadvantage": 0.05,
        },
    }


def _history(xg: float, xga: float, deep: float, deep_allowed: float, ppda_att: float, ppda_def: float) -> list[dict]:
    rows = []
    for index in range(5):
        rows.append({
            "xG": xg,
            "xGA": xga,
            "npxG": max(0.0, xg - 0.1),
            "npxGA": max(0.0, xga - 0.1),
            "deep": deep,
            "deep_allowed": deep_allowed,
            "ppda": {"att": ppda_att, "def": ppda_def},
            "ppda_allowed": {"att": ppda_att + 30, "def": ppda_def},
            "scored": int(round(xg)),
            "missed": int(round(xga)),
            "h_a": "h" if index % 2 == 0 else "a",
        })
    return rows


def _raw() -> dict:
    return {
        "schema_valid": True,
        "source_availability": "AVAILABLE",
        "freshness": "FRESH",
        "fetched_at": "2026-09-02T00:00:00+00:00",
        "provenance": {"provider": "Understat"},
        "embedded": {
            "teamsData": {
                "1": {"id": "1", "title": "Arsenal", "history": _history(2.2, 0.6, 12, 4, 180, 24)},
                "2": {"id": "2", "title": "Chelsea", "history": _history(0.8, 2.0, 4, 12, 260, 20)},
            },
            "playersData": [
                {"id": "10", "player_name": "Saka", "team_title": "Arsenal", "games": "5", "time": "450", "xG": "3.2", "xA": "2.0", "xGChain": "5.1", "xGBuildup": "1.4", "shots": "16", "key_passes": "12", "position": "M"},
                {"id": "20", "player_name": "Palmer", "team_title": "Chelsea", "games": "5", "time": "440", "xG": "1.5", "xA": "1.2", "xGChain": "3.4", "xGBuildup": "1.0", "shots": "11", "key_passes": "9", "position": "M"},
            ],
            "datesData": [{"datetime": "2026-08-31 18:00:00", "isResult": True, "goals": {"h": "1", "a": "0"}}],
        },
    }


def _official_universe() -> list[dict]:
    return [
        {"element": 101, "element_id": 101, "name": "Saka", "team": "Arsenal", "team_id": 1, "position": "MID"},
        {"element": 202, "element_id": 202, "name": "Palmer", "team": "Chelsea", "team_id": 2, "position": "MID"},
        {"element": 303, "element_id": 303, "name": "Unmapped Player", "team": "Arsenal", "team_id": 1, "position": "DEF"},
    ]


def test_understat_embedded_parser_does_not_execute_javascript():
    teams = {"1": {"title": "Arsenal", "history": []}}
    players = [{"id": "10", "player_name": "Saka"}]
    html = (
        "<script>var teamsData = JSON.parse('" + json.dumps(teams) + "');"
        "var playersData = JSON.parse('" + json.dumps(players) + "');"
        "var datesData = JSON.parse('[]');</script>"
    )
    parsed = parse_embedded_json(html)
    assert parsed["teamsData"]["1"]["title"] == "Arsenal"
    assert parsed["playersData"][0]["player_name"] == "Saka"


def test_team_windows_mark_ppda_as_derived_and_apply_small_sample_shrinkage():
    teams = normalize_team_evidence(_raw(), _policy())
    arsenal = teams["arsenal"]
    assert set(arsenal["windows"]) >= {"last_1", "last_3", "last_5", "season_to_date", "home", "away"}
    last_one = arsenal["windows"]["last_1"]
    assert last_one["sample_state"] == "LOW_SAMPLE"
    assert last_one["shrinkage"]["applied"] is True
    assert last_one["metric_evidence"]["xg"]["evidence_type"] == "SOURCE_OBSERVED"
    assert last_one["metric_evidence"]["ppda"]["evidence_type"] == "DERIVED"
    assert last_one["metric_evidence"]["ppda"]["derivation_version"] == "understat-tactical-v1"


def test_player_mapping_is_team_scoped_and_missing_is_unknown_not_zero():
    players, unresolved = normalize_player_evidence(_raw(), _official_universe(), _policy())
    saka = players["101"]
    assert saka["mapping"]["state"] == "RESOLVED"
    assert saka["season_to_date"]["derived"]["xg_per90"]["value"] > 0
    assert saka["rolling_windows"]["last_3"]["state"] == "INSUFFICIENT_EVIDENCE"
    missing = players["303"]
    assert missing["mapping"]["state"] == "UNRESOLVED"
    assert missing["season_to_date"] is None
    assert unresolved and unresolved[0]["element"] == 303


def test_matchup_uses_multiple_signals_and_never_converts_ppda_to_xpts():
    policy = _policy()
    teams = normalize_team_evidence(_raw(), policy)
    players, _ = normalize_player_evidence(_raw(), _official_universe(), policy)
    fixtures = [{"id": 1, "event": 3, "team_h": 1, "team_a": 2, "finished": False, "kickoff_time": "2026-09-12T14:00:00Z"}]
    matchups = build_matchups(teams, players, _official_universe(), fixtures, policy)
    saka = matchups["101"]
    assert saka["state"] in {"POSITIVE", "NEUTRAL", "NEGATIVE"}
    assert saka["dimensions"]["transition_environment"]["state"] == "INSUFFICIENT_EVIDENCE"
    assert saka["guardrails"]["ppda_direct_xpts_conversion"] is False
    assert saka["guardrails"]["single_metric_authority"] is False


def test_watchlist_understat_can_only_promote_inside_governed_cutoff_margin():
    policy = _policy()
    rows = []
    for index, score in enumerate([10.0, 9.0, 8.0, 7.0, 6.0, 5.9, 5.5], start=1):
        rows.append({
            "element": index,
            "score": score,
            "xpts_5": score,
            "start_probability_5": 1.0,
            "understat_close_call": {"state": "NEUTRAL", "confidence": 0.8},
            "tactical_signal_used_for_promotion": False,
        })
    rows[5]["understat_close_call"] = {"state": "POSITIVE", "confidence": 0.9}
    rows[6]["understat_close_call"] = {"state": "POSITIVE", "confidence": 1.0}
    selected = _apply_watchlist_close_call(rows, 5, policy)
    ids = [row["element"] for row in selected]
    assert 6 in ids
    assert 5 not in ids
    assert 7 not in ids
    promoted = next(row for row in selected if row["element"] == 6)
    assert promoted["tactical_signal_used_for_promotion"] is True
    assert promoted["tactical_close_call"]["direct_xpts_mutation"] is False


def test_lineup_close_call_does_not_change_xpts_or_allow_large_jump():
    rows = [
        {"element": 1, "selection_score": 5.00, "xpts": 5.00, "start_probability": 1.0, "dnp_probability": 0.0, "understat_tactical": {"state": "NEUTRAL", "confidence": 0.9}},
        {"element": 2, "selection_score": 4.95, "xpts": 4.95, "start_probability": 1.0, "dnp_probability": 0.0, "understat_tactical": {"state": "POSITIVE", "confidence": 0.9}},
        {"element": 3, "selection_score": 4.50, "xpts": 4.50, "start_probability": 1.0, "dnp_probability": 0.0, "understat_tactical": {"state": "POSITIVE", "confidence": 1.0}},
    ]
    selected, metadata = _select_close_call(rows, 1, "selection_score", 0.12, 0.6)
    assert selected[0]["element"] == 2
    assert selected[0]["xpts"] == 4.95
    assert metadata["direct_xpts_mutation"] is False
    assert metadata["direct_xmins_mutation"] is False
    assert metadata["score_gap"] == 0.05
    assert 3 not in [row["element"] for row in selected]


def test_positive_tactics_cannot_promote_materially_worse_xmins():
    rows = [
        {"element": 1, "selection_score": 5.00, "xpts": 5.00, "start_probability": 0.90, "dnp_probability": 0.05, "understat_tactical": {"state": "NEUTRAL", "confidence": 0.8}},
        {"element": 2, "selection_score": 4.95, "xpts": 4.95, "start_probability": 0.55, "dnp_probability": 0.30, "understat_tactical": {"state": "POSITIVE", "confidence": 1.0}},
    ]
    selected, metadata = _select_close_call(
        rows, 1, "selection_score", 0.12, 0.6,
        max_start_disadvantage=0.05, max_dnp_disadvantage=0.05,
    )
    assert selected[0]["element"] == 1
    assert metadata["used"] is False
