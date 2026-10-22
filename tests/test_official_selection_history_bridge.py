from src.engines.v12_v6_official_selection_bridge import evaluate_v6_official_history_shadow


def partition(gw, *, minutes=90, starts=1, status="FINAL"):
    return {
        "authority": "OFFICIAL_FPL",
        "contract": "OFFICIAL_FPL_RETROSPECTIVE_GW_PARTITION_V1",
        "gw": gw,
        "coverage": {
            "status": "PASS", "gw_official_finalized": True,
            "fixture_identity_status": "PASS",
        },
        "original_full_history_generated_at": "2026-10-21T22:00:58.913755+00:00",
        "players": {"101": {
            "element_id": 101, "status": status,
            "fixtures": [{"element": 101, "fixture": 100 + gw,
                          "starts": starts, "minutes": minutes}],
        }},
    }


def run(parts):
    return evaluate_v6_official_history_shadow(
        {"id": 101, "element_type": 3, "team": 5, "status": "a"},
        parts, target_gw=8, evidence_cutoff_at="2026-10-22T12:00:00Z",
        target_deadline_at="2026-10-23T12:00:00Z",
    )


def test_v6_fixture_level_starts_produce_shadow_probabilities():
    result = run([partition(i) for i in range(1, 8)])
    assert result["status"] == "READY_SHADOW_UNATTESTED"
    assert result["verified_local_fixture_rows"] == 7
    assert 0 < result["probabilities"]["p_start"] < 1
    assert sum(result["probabilities"].values()) > .999
    assert result["expected_minutes"] > 0
    assert result["publication_authorized"] is False
    assert result["eligible_for_live_scoring"] is False
    assert result["source_authentication"] == "NOT_ATTESTED"


def test_v6_rotation_lowers_canonical_start_probability():
    regular = run([partition(i) for i in range(1, 8)])
    rotating = run([partition(i, minutes=0, starts=0, status="DNP") for i in range(1, 8)])
    assert rotating["probabilities"]["p_start"] < regular["probabilities"]["p_start"]


def test_v6_after_cutoff_and_blank_never_become_dnp():
    future = partition(1)
    future["original_full_history_generated_at"] = "2026-10-23T00:00:00Z"
    blank = partition(2)
    blank["players"]["101"]["status"] = "BLANK"
    result = run([future, blank, partition(3)])
    assert result["probabilities"] is None
    assert result["rejected"]["AFTER_CUTOFF"] == 1
    assert result["rejected"]["PLAYER_ABSENT_OR_BLANK"] == 1


def test_v6_provisional_and_invalid_starter_fail_closed():
    invalid = partition(1)
    invalid["players"]["101"]["fixtures"][0]["starts"] = "1"
    provisional = partition(2)
    provisional["coverage"]["gw_official_finalized"] = False
    result = run([invalid, provisional, partition(3)])
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["rejected"]["FIXTURE_SELECTION_INVALID"] == 1
    assert result["rejected"]["NOT_FINALIZED_OR_FUTURE"] == 1
