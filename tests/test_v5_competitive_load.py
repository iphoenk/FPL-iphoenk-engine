from datetime import datetime, timezone

from src.v5.intelligence.competitive_load import build_competitive_load


NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)


def _bootstrap():
    return {
        "elements": [
            {"id": 1, "team": 10},
            {"id": 2, "team": 11},
        ]
    }


def _fixtures():
    return [
        {"event": 3, "team_h": 10, "team_a": 11, "kickoff_time": "2026-09-01T18:00:00Z"},
    ]


def _valid(**overrides):
    row = {
        "element": 1,
        "competition": "EFL Cup",
        "match_time": "2026-08-29T18:00:00Z",
        "verified": True,
        "verification_level": "OFFICIAL_COMPETITION",
        "source": "official competition match centre",
        "source_url": "https://example.com/match/1",
        "started": True,
        "minutes": 90,
        "extra_time_minutes": 0,
        "sub_on_minute": None,
        "sub_off_minute": None,
        "travel_context": "DOMESTIC_AWAY",
    }
    row.update(overrides)
    return row


def test_verified_non_pl_observation_is_accepted_and_audited():
    result = build_competitive_load(
        _bootstrap(),
        _fixtures(),
        planning_gw=3,
        verified_observations={"contract": "COMPETITIVE_LOAD_OBSERVATIONS_V1", "observations": [_valid()]},
        now=NOW,
    )
    assert result["external_observation_count"] == 1
    assert result["external_player_coverage"] == 1
    assert result["external_evidence_status"] == "AVAILABLE"
    assert result["observation_audit"]["accepted_rows"] == 1
    assert result["players"]["1"]["verified_non_pl_observation_count"] == 1
    assert result["players"]["1"]["non_pl_evidence_state"] == "AVAILABLE"
    assert result["governance"]["direct_xpts_mutation_forbidden"] is True
    assert result["governance"]["direct_xmins_mutation_forbidden_until_calibrated"] is True


def test_invalid_rows_fail_soft_and_cannot_change_player_load():
    rows = [
        _valid(element=999),
        _valid(competition="Premier League"),
        _valid(match_time="2026-09-01T00:00:00Z"),
        _valid(match_time="2026-07-01T00:00:00Z"),
        _valid(source_url="not-a-url"),
        _valid(verification_level="COMMUNITY_ONLY"),
    ]
    result = build_competitive_load(
        _bootstrap(),
        _fixtures(),
        planning_gw=3,
        verified_observations={"contract": "COMPETITIVE_LOAD_OBSERVATIONS_V1", "observations": rows},
        now=NOW,
    )
    audit = result["observation_audit"]
    assert result["external_observation_count"] == 0
    assert result["external_evidence_status"] == "PARTIAL_COMPETITION_COVERAGE"
    assert audit["accepted_rows"] == 0
    assert audit["stale_rows"] == 1
    assert audit["rejection_reasons"]["UNKNOWN_ELEMENT"] == 1
    assert audit["rejection_reasons"]["INVALID_OR_NATIVE_COMPETITION"] == 1
    assert audit["rejection_reasons"]["FUTURE_MATCH"] == 1
    assert audit["rejection_reasons"]["INVALID_SOURCE_URL"] == 1
    assert audit["rejection_reasons"]["INVALID_VERIFICATION_LEVEL"] == 1
    assert result["players"]["1"]["verified_non_pl_observation_count"] == 0


def test_duplicate_observation_uses_stronger_verification_precedence():
    weaker = _valid(verification_level="CROSSCHECKED_OFFICIAL", source="crosscheck")
    stronger = _valid(verification_level="OFFICIAL_CLUB", source="club official")
    result = build_competitive_load(
        _bootstrap(),
        _fixtures(),
        planning_gw=3,
        verified_observations={
            "contract": "COMPETITIVE_LOAD_OBSERVATIONS_V1",
            "observations": [weaker, stronger],
        },
        now=NOW,
    )
    assert result["external_observation_count"] == 1
    assert result["observation_audit"]["deduplicated_rows"] == 1
    assert result["observation_audit"]["verification_levels"] == {"OFFICIAL_CLUB": 1}


def test_missing_or_wrong_contract_is_fail_soft():
    missing = build_competitive_load(_bootstrap(), _fixtures(), planning_gw=3, now=NOW)
    assert missing["observation_audit"]["status"] == "NO_EXTERNAL_OBSERVATIONS"
    assert missing["external_observation_count"] == 0

    wrong = build_competitive_load(
        _bootstrap(),
        _fixtures(),
        planning_gw=3,
        verified_observations={"contract": "WRONG", "observations": [_valid()]},
        now=NOW,
    )
    assert wrong["observation_audit"]["status"] == "INVALID_CONTRACT_REJECTED"
    assert wrong["external_observation_count"] == 0
