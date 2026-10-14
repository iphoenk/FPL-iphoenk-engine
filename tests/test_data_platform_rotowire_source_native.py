from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.source_native import build_source_native_datasets
from scripts.v6_rotowire_identity_review import build_review


HTML = """
<div class="lineup is-soccer" data-gameid="123">
  <div class="lineup__time">September 13 11:00 AM</div>
  <div class="lineup__mteam is-home"><a title="Alpha"><div class="lineup__abbr">ALP</div>Alpha</a></div>
  <div class="lineup__mteam is-visit"><a title="Beta"><div class="lineup__abbr">BET</div>Beta</a></div>
  <ul class="lineup__list is-home">
    <li class="lineup__status is-expected">Predicted Lineup</li>
    <li class="lineup__player"><div class="lineup__pos">M</div><a title="Player One" href="/soccer/player/player-one-101">One</a></li>
  </ul>
</div>
"""


def test_rotowire_source_native_dataset_is_advisory_and_never_v6_authored_prediction():
    results = {
        "rotowire": {
            "source_id": "rotowire",
            "checked_at": "2026-09-06T22:00:00+00:00",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "current_run_action": "FETCHED",
            "data": {
                "lineups": {
                    "body": HTML,
                    "sha256": "abc123",
                }
            },
        }
    }

    dataset = build_source_native_datasets(results, identity_map={})["rotowire"]

    assert dataset["normalization_status"] == "NORMALIZED"
    assert dataset["record_count"] >= 2
    assert dataset["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert dataset["model_author"] == "ROTOWIRE"
    assert dataset["v6_computation"] == "NONE"
    assert dataset["authority_ceiling"] == "ADVISORY"
    assert dataset["governance"]["decision_authority"] == "NONE"
    assert dataset["governance"]["prediction_authority"] == "NONE"
    assert dataset["governance"]["requires_primary_crosscheck_for_fact_promotion"] is True
    assert dataset["governance"]["may_override_verified_facts"] is False
    player = dataset["record_groups"]["lineups"][0]
    assert player["source_native_id"] == 101
    assert player["official_element_id"] is None
    assert player["identity_status"] == "UNMAPPED"


    # Existing test node: review may discover identity candidates but must not
    # manufacture a verified RotoWire -> Official FPL mapping or modify xMins.
    official_players = {
        "authority": "official_fpl",
        "players": [{
            "official_fpl_element_id": 226, "official_code": 17745,
            "first_name": "Jordan", "second_name": "Pickford", "team_id": 9,
        }],
    }
    official_teams = {"authority": "official_fpl", "teams": [
        {"official_fpl_team_id": 9, "name": "Everton"},
        {"official_fpl_team_id": 6, "name": "Chelsea"},
    ]}
    official_fixtures = {"authority": "official_fpl", "fixtures": [
        {"official_fpl_fixture_id": 64, "team_h": 9, "team_a": 6,
         "event": 7, "kickoff_time": "2026-10-17T11:30:00Z"},
    ]}
    rotowire = {
        "source_id": "rotowire",
        "effective_at": "2026-10-14T09:33:52Z",
        "record_groups": {
            "fixtures": [{"fixture_key": "October 17 7:30 AM ET|Everton|Chelsea",
                          "home": {"name": "Everton"}, "away": {"name": "Chelsea"}}],
            "lineups": [{
                "source_native_id": 19035, "player_name": "Jordan Pickford",
                "team_name": "Everton", "position": "GK",
                "lineup_status": "PREDICTED",
                "fixture_key": "October 17 7:30 AM ET|Everton|Chelsea",
            }],
            "availability": [],
        },
    }
    review = build_review(rotowire, official_players, official_teams, official_fixtures)
    assert review["fixture_candidate_matches"] == 1
    assert review["candidate_counts"]["IDENTITY_CANDIDATE_REVIEW"] == 1
    candidate = review["players"][0]
    assert candidate["official_fpl_element_candidate"] == 226
    assert candidate["official_fpl_code_candidate"] == 17745
    assert candidate["verification_status"] == "UNMAPPED"
    assert candidate["joinable"] is False
    assert candidate["numeric_pstart_authority"] is False
    assert review["governance"]["crosswalk_catalog_not_mutated"] is True

    # Name-only match without a verified fixture is not ready for review.
    rotowire["record_groups"]["lineups"][0]["fixture_key"] = "UNKNOWN|UNKNOWN|UNKNOWN"
    unverified = build_review(rotowire, official_players, official_teams, official_fixtures)
    assert unverified["players"][0]["review_status"] == "FIXTURE_UNVERIFIED"
    # Incorrect player name cannot silently inherit a provider-native ID bridge.
    rotowire["record_groups"]["lineups"][0]["player_name"] = "Other Pickford"
    unmatched = build_review(rotowire, official_players, official_teams, official_fixtures)
    assert unmatched["players"][0]["review_status"] == "NAME_TEAM_UNRESOLVED"


    # Frozen observed V6 snapshot: 312 provider-native IDs; only candidates,
    # never silently a live verified-crosswalk catalog.
    root = Path(__file__).resolve().parents[1]
    observed = json.loads((root / "docs/audits/P0_ROTOWIRE_IDENTITY_CANDIDATES_20261014.json").read_text())
    assert observed["unique_provider_ids"] == 312
    assert observed["candidate_counts"]["IDENTITY_CANDIDATE_REVIEW"] == 273
    assert observed["candidate_counts"]["NAME_TEAM_UNRESOLVED"] == 39
    assert observed["fixture_candidate_matches"] == 11
    assert observed["fixture_count"] == 12
    assert len({row["rotowire_native_id"] for row in observed["players"]}) == 312
    assert all(row["verification_status"] == "UNMAPPED" for row in observed["players"])
    assert all(row["joinable"] is False and row["numeric_pstart_authority"] is False
               for row in observed["players"])

    # GW-specific admission: an otherwise verified fixture belongs to one
    # GW only; a GW8 prediction must not leak into the GW7 review.
    rotowire["record_groups"]["lineups"][0]["fixture_key"] = (
        "October 17 7:30 AM ET|Everton|Chelsea"
    )
    rotowire["record_groups"]["lineups"][0]["player_name"] = "Jordan Pickford"
    rotowire["record_groups"]["fixtures"].append({
        "fixture_key": "October 23 3:00 PM ET|Everton|Chelsea",
        "home": {"name": "Everton"}, "away": {"name": "Chelsea"},
    })
    official_fixtures["fixtures"].append({
        "official_fpl_fixture_id": 82,
        "team_h": 9, "team_a": 6, "event": 8,
        "kickoff_time": "2026-10-23T19:00:00Z",
    })
    official_players["players"].append({
        "official_fpl_element_id": 228, "official_code": 44444,
        "first_name": "Michael", "second_name": "Keane", "team_id": 9,
    })
    rotowire["record_groups"]["lineups"].append({
        "source_native_id": 17514, "player_name": "Michael Keane",
        "team_name": "Everton", "position": "D", "lineup_status": "PREDICTED",
        "fixture_key": "October 23 3:00 PM ET|Everton|Chelsea",
    })
    gw7_review = build_review(
        rotowire, official_players, official_teams, official_fixtures,
        target_gw=7,
    )
    assert gw7_review["target_gw"] == 7
    assert gw7_review["fixture_candidate_matches"] == 1
    assert gw7_review["fixture_matched_other_gw"] == 1
    assert gw7_review["candidate_counts"]["IDENTITY_CANDIDATE_REVIEW"] == 1
    assert gw7_review["candidate_counts"]["MATCHED_OTHER_GW"] == 1
    assert all(row["joinable"] is False for row in gw7_review["players"])
    gw8_review = build_review(
        rotowire, official_players, official_teams, official_fixtures,
        target_gw=8,
    )
    assert gw8_review["candidate_counts"]["IDENTITY_CANDIDATE_REVIEW"] == 1
    assert gw8_review["candidate_counts"]["MATCHED_OTHER_GW"] == 1
