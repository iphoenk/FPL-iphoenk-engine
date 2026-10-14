from src.runtime_v6.domains.report_plane.official_gw_history import retrospective_gw_partition


def _source(finalized=True):
    return {
        "generated_at": "2026-10-15T00:00:00Z",
        "as_of": {"historical_gws": [1, 2, 3], "planning_gw": 4},
        "universe": {"expected_players": 2},
        "coverage_gate": {
            "fixture_identity_status": "PASS",
            "finalized_historical_gws": [1, 2, 3] if finalized else [1, 2],
        },
        "players": {
            "1": {"element_id": 1, "team": 6, "position": 3,
                  "history": {"3": {"status": "FINAL", "fixtures": [
                      {"fixture": 33, "round": 3, "minutes": 90, "total_points": 6}
                  ]}}},
            "2": {"element_id": 2, "team": 6, "position": 2,
                  "history": {"3": {"status": "BLANK", "fixtures": []}}},
        },
    }


def test_gw3_official_partition_preserves_raw_match_and_blank():
    p = retrospective_gw_partition(_source(), 3)
    assert p["coverage"]["status"] == "PASS"
    assert p["coverage"]["players_with_gw_record"] == 2
    assert p["players"]["1"]["fixtures"][0]["minutes"] == 90
    assert p["players"]["2"]["status"] == "BLANK"
    assert p["players"]["2"]["fixtures"] == []
    assert p["historical_predeadline_source_asof"] == "NOT_ATTESTED"
    assert p["natural_scheduler_proof"] == "NOT_APPLICABLE"


def test_unfinalized_or_missing_gw_records_never_pretend_pass():
    unfinalized = retrospective_gw_partition(_source(finalized=False), 3)
    assert unfinalized["coverage"]["status"] == "PARTIAL"
    missing = _source()
    del missing["players"]["1"]["history"]["3"]
    out = retrospective_gw_partition(missing, 3)
    assert out["coverage"]["status"] == "PARTIAL"
    assert out["coverage"]["missing_player_ids"] == ["1"]
    assert "1" not in out["players"]


def test_unknown_gw_is_not_minted_from_other_gw():
    out = retrospective_gw_partition(_source(), 4)
    assert out["coverage"]["status"] == "PARTIAL"
    assert out["players"] == {}
