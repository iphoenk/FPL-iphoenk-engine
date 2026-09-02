from __future__ import annotations

from copy import deepcopy

from src.engines import understat_tactical_context as context
from src.intelligence import understat_tactical as tactical


POLICY = {
    "identity": {
        "normalized_exact_confidence": 0.98,
        "fuzzy_minimum_confidence": 0.94,
        "ambiguity_margin": 0.03,
    },
    "sample_size": {
        "low_confidence_matches_below": 3,
        "mature_matches_at_least": 5,
        "small_sample_shrinkage_prior_matches": 5,
    },
}


def _candidate(pid: str, name: str, team: str = "Manchester United") -> dict:
    return {
        "understat_player_id": pid,
        "name": name,
        "normalized_name": tactical._norm(name),
        "teams": [team],
        "normalized_teams": [tactical._norm(team)],
        "season_to_date": {"matches": 2, "metrics": {}, "derived": {}},
    }


def test_full_official_name_can_match_shorter_understat_identity_without_lowering_fuzzy_threshold() -> None:
    official = {
        "name": "Bruno Borges Fernandes",
        "first_name": "Bruno",
        "second_name": "Borges Fernandes",
        "web_name": "B.Fernandes",
        "name_variants": ["Bruno Borges Fernandes", "B.Fernandes", "Borges Fernandes", "Bruno"],
        "team": "Manchester United",
    }
    row, confidence, method = tactical._map_player(
        official,
        [_candidate("1", "Bruno Fernandes")],
        POLICY,
    )
    assert row is not None
    assert row["understat_player_id"] == "1"
    assert confidence == 0.985
    assert method == "TEAM_SCOPED_MULTI_TOKEN_IDENTITY_SUBSET"
    assert POLICY["identity"]["fuzzy_minimum_confidence"] == 0.94


def test_web_or_surname_variant_exact_match_is_consumed_by_core_mapper() -> None:
    official = {
        "name": "Murillo Santiago Costa dos Santos",
        "first_name": "Murillo",
        "second_name": "Santiago Costa dos Santos",
        "web_name": "Murillo",
        "name_variants": ["Murillo Santiago Costa dos Santos", "Murillo", "Santiago Costa dos Santos"],
        "team": "Nottingham Forest",
    }
    row, confidence, method = tactical._map_player(
        official,
        [_candidate("2", "Murillo", team="Nottingham Forest")],
        POLICY,
    )
    assert row is not None
    assert row["understat_player_id"] == "2"
    assert confidence == 0.98
    assert method == "TEAM_AND_IDENTITY_VARIANT_EXACT"


def test_ambiguous_multi_token_subset_fails_closed() -> None:
    official = {
        "name": "John Michael Smith",
        "first_name": "John",
        "second_name": "Michael Smith",
        "web_name": "Smith",
        "name_variants": ["John Michael Smith", "Smith", "Michael Smith", "John"],
        "team": "Example FC",
    }
    candidates = [
        _candidate("10", "John Smith", team="Example FC"),
        _candidate("11", "Michael Smith", team="Example FC"),
    ]
    row, confidence, method = tactical._map_player(official, candidates, POLICY)
    assert row is None
    assert confidence == 0.0
    assert method == "AMBIGUOUS_IDENTITY_CANDIDATES"


def test_first_name_alone_is_not_used_when_surname_exists() -> None:
    official = {
        "name": "John Different",
        "first_name": "John",
        "second_name": "Different",
        "web_name": "Different",
        "name_variants": ["John Different", "Different", "John"],
        "team": "Example FC",
    }
    row, confidence, method = tactical._map_player(
        official,
        [_candidate("12", "John", team="Example FC")],
        POLICY,
    )
    assert row is None
    assert confidence == 0.0
    assert method == "UNRESOLVED"


def test_all_official_players_receive_canonical_identity_records_even_without_source_rows() -> None:
    raw = {
        "source_availability": "AVAILABLE",
        "schema_valid": True,
        "embedded": {
            "teamsData": {},
            "playersData": [
                {"id": "1", "player_name": "Alpha", "team_title": "Example FC", "games": 2, "time": 120},
            ],
            "datesData": [],
        },
    }
    universe = [
        {
            "element": 101,
            "name": "Alpha",
            "web_name": "Alpha",
            "first_name": "Alpha",
            "second_name": "",
            "name_variants": ["Alpha"],
            "team": "Example FC",
            "team_id": 1,
            "position": "MID",
        },
        {
            "element": 102,
            "name": "Beta Player",
            "web_name": "Beta",
            "first_name": "Beta",
            "second_name": "Player",
            "name_variants": ["Beta Player", "Beta", "Player"],
            "team": "Example FC",
            "team_id": 1,
            "position": "DEF",
        },
    ]
    payload = tactical.build_understat_tactical(raw, {"official": {"fixtures": []}}, universe, POLICY)
    assert set(payload["player_evidence"]) == {"101", "102"}
    assert payload["health"]["player_mapping_count"] == 2
    assert payload["health"]["player_mapping_coverage"] == 1.0
    assert payload["health"]["canonical_identity_mapping_complete"] is True
    assert payload["player_evidence"]["102"]["canonical_identity"]["state"] == "RESOLVED"
    assert payload["player_evidence"]["102"]["mapping"]["state"] == "UNRESOLVED"
    assert payload["player_evidence"]["102"]["season_to_date"] is None
    assert payload["health"]["source_linked_mapping_count"] == 1
    assert payload["health"]["source_unlinked_official_count"] == 1


def test_source_relative_mapping_health_has_honest_separate_denominators() -> None:
    raw = {
        "embedded": {
            "playersData": [
                {"id": "1", "player_name": "Alpha"},
                {"id": "2", "player_name": "Bravo"},
                {"id": "3", "player_name": "Departed"},
            ]
        }
    }
    payload = {
        "player_evidence": {
            "101": {"understat_player_id": "1", "mapping": {"state": "RESOLVED", "method": "TEAM_AND_NORMALIZED_NAME_EXACT"}},
            "102": {"understat_player_id": "2", "mapping": {"state": "RESOLVED", "method": "TEAM_SCOPED_MULTI_TOKEN_IDENTITY_SUBSET"}},
            "103": {"mapping": {"state": "UNRESOLVED", "method": "UNRESOLVED"}},
        }
    }
    health = context._source_relative_mapping_health(raw, payload)
    assert health["source_player_count"] == 3
    assert health["source_player_mapping_count"] == 2
    assert health["source_player_mapping_coverage"] == 0.6667
    assert health["source_player_unmapped_count"] == 1
    assert health["source_relative_denominator_is_observed_understat_players"] is True
    assert health["official_universe_denominator_remains_all_fpl_players"] is True


def test_identity_v2_cache_fingerprint_changes_when_variants_change() -> None:
    raw = {"fetched_at": "2026-09-02T13:00:00+00:00", "transport_revision": "UNDERSTAT_XHR_JSON_V1"}
    fixtures = [{"id": 1, "event": 3, "team_h": 1, "team_a": 2, "kickoff_time": "2026-09-04T17:30:00Z", "finished": False}]
    universe = [{
        "element": 101,
        "name": "Bruno Borges Fernandes",
        "web_name": "B.Fernandes",
        "first_name": "Bruno",
        "second_name": "Borges Fernandes",
        "name_variants": ["Bruno Borges Fernandes", "B.Fernandes", "Borges Fernandes", "Bruno"],
        "team": "Manchester United",
        "position": "MID",
    }]
    changed = deepcopy(universe)
    changed[0]["name_variants"] = ["Bruno Fernandes", "B.Fernandes"]
    assert context.DERIVED_CACHE_REVISION == "UNDERSTAT_V3_OFFICIAL_IDENTITY_V2"
    assert context._derived_cache_fingerprint(raw, universe, fixtures) != context._derived_cache_fingerprint(raw, changed, fixtures)
