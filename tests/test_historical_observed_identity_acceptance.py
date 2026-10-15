from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.v6_stage1_observed_xi_identity_gate import verify_observed_xi_identity


def _source_fixture():
    teams = (1, 2)
    official = {"source_id": "official_fpl", "health": "GREEN",
                "official": {"fixtures": []}}
    part = {
        gw: {"authority": "OFFICIAL_FPL", "gw": gw,
             "coverage": {"status": "PASS", "gw_official_finalized": True},
             "players": {str(pid): {"element_id": pid, "fixtures": []}
                         for pid in range(1, 23)}}
        for gw in range(1, 7)
    }
    original = {"source_id": "fotmob", "normalization_status": "NORMALIZED",
                "record_groups": {"match_tactics": []}}
    for fid in range(1, 61):
        gw = 1 + (fid - 1) // 10
        official["official"]["fixtures"].append(
            {"id": fid, "event": gw, "team_h": teams[0],
             "team_a": teams[1], "finished": True}
        )
        sides = []
        for team, start, away in ((1, 1, False), (2, 12, True)):
            rows = []
            for eid in range(start, start + 11):
                part[gw]["players"][str(eid)]["fixtures"].append(
                    {"fixture": fid, "starts": 1, "was_home": not away}
                )
                rows.append({"source_native_player_id": eid + 1000,
                             "official_element_id": eid,
                             "identity_status": "VERIFIED_MANUAL"})
            sides.append({
                "official_team_id": team,
                "coach": {"name": "Verified manager", "source_native_id": team + 100},
                "formation": "4-2-3-1",
                "provider_starter_count": 11, "starting_xi_complete": True,
                "verified_official_starters": rows,
                "unverified_provider_starter_ids": [],
            })
        original["record_groups"]["match_tactics"].append({
            "official_fixture_id": fid,
            "fixture_join": "VERIFIED_NATIVE_TO_OFFICIAL",
            "source_snapshot_sha256": "a" * 64,
            "sides": sides,
        })
    return official, original, part


def test_full_60_fixture_1320_observed_xi_acceptance():
    official, fotmob, partitions = _source_fixture()
    result = verify_observed_xi_identity(official, fotmob, partitions)
    assert result["status"] == "PASS"
    assert result["fixture_count"] == 60
    assert result["team_fixture_count"] == 120
    assert result["source_verified_starter_observations"] == 1320
    assert result["unique_source_native_starter_players"] == 22
    assert result["historical_predeadline_source_asof"] == "NOT_ESTABLISHED"
    assert result["numeric_pstart_effect"] == "NONE"


@pytest.mark.parametrize("mutation", ("unmapped", "incorrect", "sha", "coach",
                                      "incomplete", "unfinalized", "native_collision"))
def test_incomplete_or_conflicting_fixture_remains_fail_closed(mutation):
    official, fotmob, partitions = _source_fixture()
    first = fotmob["record_groups"]["match_tactics"][0]
    if mutation == "unmapped":
        first["sides"][0]["unverified_provider_starter_ids"] = [7777]
    elif mutation == "incorrect":
        first["sides"][0]["verified_official_starters"][0]["official_element_id"] = 99
    elif mutation == "sha":
        first["source_snapshot_sha256"] = "not-a-source-sha"
    elif mutation == "coach":
        first["sides"][0]["coach"]["source_native_id"] = None
    elif mutation == "incomplete":
        first["sides"][0]["starting_xi_complete"] = False
    elif mutation == "unfinalized":
        partitions[1]["coverage"]["gw_official_finalized"] = False
    elif mutation == "native_collision":
        first["sides"][0]["verified_official_starters"][0]["source_native_player_id"] = 999
        fotmob["record_groups"]["match_tactics"][1]["sides"][0]["verified_official_starters"][1]["source_native_player_id"] = 999
    with pytest.raises(ValueError):
        verify_observed_xi_identity(official, fotmob, partitions)


def test_original_data_does_not_change_after_verification():
    official, fotmob, partitions = _source_fixture()
    prior = deepcopy((official, fotmob, partitions))
    verify_observed_xi_identity(official, fotmob, partitions)
    assert (official, fotmob, partitions) == prior
