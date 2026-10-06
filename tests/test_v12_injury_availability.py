from __future__ import annotations

import pytest

from src.engines.v12_injury_availability import (
    build_availability_evidence_by_player,
    derive_gw_availability,
    normalize_injury_evidence,
)
from src.engines.v12_player_minutes import estimate_player_minutes


NOW = "2026-10-06T14:00:00Z"


def resolve(rows, *, target_gw=7, fixture=7001):
    return derive_gw_availability(
        rows,
        target_gw=target_gw,
        target_fixture_id=fixture,
        derived_at=NOW,
        evidence_cutoff_at=NOW,
    )


def test_case1_fpl_75_is_neutral_and_later_full_training_clears_concern():
    out = resolve(
        [
            {
                "source": "Official FPL",
                "source_type": "OFFICIAL_FPL",
                "observed_at": "2026-10-05T12:00:00Z",
                "evidence_type": "FPL_FLAG",
                "claim_domain": "FPL_STATUS",
                "fpl_flag": 75,
                "raw_claim": "75% chance of playing",
            },
            {
                "source": "Club",
                "source_type": "OFFICIAL_CLUB",
                "observed_at": "2026-10-06T10:00:00Z",
                "evidence_type": "FULL_TRAINING",
                "training_status": "FULL",
                "raw_claim": "trained fully with the first team",
            },
        ]
    )
    assert out["gw_availability"] == "AVAILABLE"
    flag = next(
        row
        for row in out["active_evidence"]
        if row["evidence_type"] == "FPL_FLAG"
    )
    assert flag["evidence_polarity"] == "NEUTRAL"
    assert out["model_features"]["fpl_flag_used_as_probability"] is False


def test_case2_international_withdrawal_precaution_is_not_injury_confirmation():
    out = resolve(
        [
            {
                "source": "Federation",
                "source_type": "OFFICIAL_FEDERATION",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "INTERNATIONAL_WITHDRAWAL",
                "withdrawn_from_squad": "YES",
                "normalized_claim": "PRECAUTION",
                "injury_confirmed": "UNKNOWN",
                "raw_claim": "withdrawn as a precaution",
            }
        ]
    )
    assert out["gw_availability"] == "UNKNOWN"
    claim = out["active_evidence"][0]
    assert claim["withdrawn_from_squad"] == "YES"
    assert claim["injury_confirmed"] == "UNKNOWN"
    assert claim["diagnosis_inferred"] is False


def test_case3_nothing_major_plus_returned_to_club_is_not_out():
    out = resolve(
        [
            {
                "source": "Manager",
                "source_type": "MANAGER_DIRECT",
                "observed_at": "2026-10-06T08:00:00Z",
                "evidence_type": "MANAGER_QUOTE",
                "manager_severity": "NOT_SERIOUS",
                "manager_availability_language": "ASSESS",
                "raw_claim": "nothing major, we will assess him",
            },
            {
                "source": "Federation",
                "source_type": "OFFICIAL_FEDERATION",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "RETURNED_TO_CLUB",
                "returned_to_club": "YES",
                "raw_claim": "returned to club",
            },
        ]
    )
    assert out["gw_availability"] in {"LIKELY_AVAILABLE", "DOUBT"}
    assert out["gw_availability"] != "OUT"


def test_case4_confirmed_hamstring_injury_keeps_unknown_return():
    out = resolve(
        [
            {
                "source": "Club medical",
                "source_type": "MEDICAL_STAFF_DIRECT",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "INJURY_EVENT",
                "injury_confirmed": "YES",
                "injury_mechanism": "MUSCLE",
                "body_part": "HAMSTRING",
                "club_assessment": "ASSESSING",
                "raw_claim": "hamstring injury, assessment ongoing",
            }
        ]
    )
    claim = out["active_evidence"][0]
    assert claim["injury_confirmed"] == "YES"
    assert claim["body_part"] == "HAMSTRING"
    assert claim["expected_return"] == "UNKNOWN"
    assert out["gw_availability"] == "DOUBT"


def test_case5_journalist_timeline_keeps_journalist_provenance():
    out = resolve(
        [
            {
                "source": "Club correspondent",
                "source_type": "CLUB_CORRESPONDENT",
                "source_authority": "TIER_B_REPUTABLE",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "EXPECTED_RETURN",
                "claim_domain": "RETURN_TIMELINE",
                "expected_return": "3 weeks",
                "expected_return_source": "Club correspondent",
                "expected_return_authority": "JOURNALIST",
                "raw_claim": "expected to miss around three weeks",
            }
        ]
    )
    claim = out["active_evidence"][0]
    assert claim["expected_return"] == "3 weeks"
    assert claim["expected_return_authority"] == "JOURNALIST"
    assert claim["expected_return_source"] == "Club correspondent"


def test_case6_later_89_minute_match_supersedes_availability_concern_not_history():
    out = resolve(
        [
            {
                "source": "Club",
                "source_type": "OFFICIAL_CLUB",
                "observed_at": "2026-10-03T09:00:00Z",
                "evidence_type": "INJURY_EVENT",
                "injury_confirmed": "YES",
                "body_part": "ANKLE",
                "raw_claim": "ankle injury",
            },
            {
                "source": "Official match record",
                "source_type": "OFFICIAL_MATCH_RECORD",
                "observed_at": "2026-10-06T12:00:00Z",
                "evidence_type": "MATCH_APPEARANCE",
                "match_status": "STARTED",
                "minutes": 89,
                "raw_claim": "started and played 89 minutes",
            },
        ]
    )
    assert out["gw_availability"] == "AVAILABLE"
    historical_injury = next(
        row
        for row in out["superseded_evidence"]
        if row["evidence_type"] == "INJURY_EVENT"
    )
    assert historical_injury["injury_confirmed"] == "YES"
    assert historical_injury["availability_superseded"] is True


def test_case7_planned_workload_substitution_is_not_injury():
    out = resolve(
        [
            {
                "source": "Manager",
                "source_type": "MANAGER_DIRECT",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "WORKLOAD_MANAGEMENT",
                "injury_confirmed": "NO",
                "no_injury_explicit": True,
                "normalized_claim": "WORKLOAD_NO_PHYSICAL_ISSUE",
                "raw_claim": "substitution was planned; no physical issue",
            }
        ]
    )
    assert out["gw_availability"] == "LIKELY_AVAILABLE"
    claim = out["active_evidence"][0]
    assert claim["injury_confirmed"] == "NO"
    assert claim["injury_mechanism"] == "WORKLOAD"


def test_case8_missing_body_part_stays_unknown():
    out = resolve(
        [
            {
                "source": "Club",
                "source_type": "OFFICIAL_CLUB",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "INJURY_EVENT",
                "injury_confirmed": "YES",
                "raw_claim": "an injury was confirmed",
            }
        ]
    )
    assert out["active_evidence"][0]["body_part"] == "UNKNOWN"


def test_strict_no_without_affirmative_support_downgrades_to_unknown():
    rows = normalize_injury_evidence(
        [
            {
                "source": "Report",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "OTHER",
                "injury_confirmed": "NO",
                "raw_claim": "no diagnosis was provided",
            }
        ],
        as_of=NOW,
    )
    assert rows[0]["injury_confirmed"] == "UNKNOWN"
    assert "STRICT_NO_DOWNGRADED_TO_UNKNOWN" in rows[0]["semantic_warnings"]


def test_root_republication_does_not_multiply_independent_evidence():
    root = "manager-presser-20261006"
    out = resolve(
        [
            {
                "source": "Manager",
                "source_type": "MANAGER_DIRECT",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "MANAGER_QUOTE",
                "manager_severity": "DOUBT",
                "root_claim_id": root,
                "raw_claim": "late decision",
            },
            {
                "source": "Repost",
                "source_type": "REPOST",
                "observed_at": "2026-10-06T09:05:00Z",
                "evidence_type": "MANAGER_QUOTE",
                "manager_severity": "DOUBT",
                "root_claim_id": root,
                "is_republication": True,
                "raw_claim": "late decision",
            },
        ]
    )
    assert out["observability"]["independent_root_claim_count"] == 1
    assert out["observability"]["republication_count"] == 1


def test_target_fixture_scope_prevents_international_state_overwrite():
    rows = [
        {
            "source": "Federation",
            "source_type": "OFFICIAL_FEDERATION",
            "observed_at": "2026-10-05T09:00:00Z",
            "evidence_type": "INTERNATIONAL_WITHDRAWAL",
            "availability": "OUT",
            "explicit_target_unavailable": True,
            "target_fixture_id": "INTL-1",
            "raw_claim": "unavailable for international fixture",
        },
        {
            "source": "Club",
            "source_type": "OFFICIAL_CLUB",
            "observed_at": "2026-10-06T10:00:00Z",
            "evidence_type": "FULL_TRAINING",
            "training_status": "FULL",
            "target_fixture_id": "PL-7",
            "raw_claim": "full club training",
        },
    ]
    intl = derive_gw_availability(
        rows,
        target_gw=7,
        target_fixture_id="INTL-1",
        derived_at=NOW,
        evidence_cutoff_at=NOW,
    )
    pl = derive_gw_availability(
        rows,
        target_gw=7,
        target_fixture_id="PL-7",
        derived_at=NOW,
        evidence_cutoff_at=NOW,
    )
    assert intl["gw_availability"] == "OUT"
    assert pl["gw_availability"] == "AVAILABLE"


def test_expected_return_without_provenance_is_not_promoted():
    out = resolve(
        [
            {
                "source": "Aggregator",
                "source_type": "AGGREGATOR",
                "observed_at": "2026-10-06T09:00:00Z",
                "evidence_type": "EXPECTED_RETURN",
                "expected_return": "2 weeks",
                "raw_claim": "two weeks",
            }
        ]
    )
    claim = out["active_evidence"][0]
    assert claim["expected_return"] == "UNKNOWN"
    assert "EXPECTED_RETURN_WITHOUT_PROVENANCE" in claim["semantic_warnings"]


def test_report_time_adapter_keeps_fpl_flag_neutral_and_no_diagnosis():
    bootstrap = {
        "elements": [
            {
                "id": 1,
                "web_name": "Example",
                "status": "d",
                "chance_of_playing_next_round": 75,
                "news": "Knock - 75% chance of playing",
                "news_added": "2026-10-06T10:00:00Z",
            }
        ]
    }
    claims = build_availability_evidence_by_player(
        bootstrap,
        None,
        report_timestamp=NOW,
        target_gw=7,
    )
    claim = claims[1][0]
    assert claim["evidence_type"] == "FPL_FLAG"
    assert claim["evidence_polarity"] == "NEUTRAL"
    assert claim["injury_confirmed"] == "UNKNOWN"


@pytest.mark.parametrize("flag", [25, 50, 75])
def test_fpl_flag_values_do_not_equal_pstart(flag):
    player = {
        "starts": 5,
        "minutes": 420,
        "status": "d",
        "chance_of_playing_next_round": flag,
    }
    context = {
        "team_matches_played": 6,
        "prior_start_probability": 0.85,
        "prior_evidence_minutes": 1800,
    }
    out = estimate_player_minutes(player, context)
    baseline = estimate_player_minutes(
        {**player, "chance_of_playing_next_round": 100},
        context,
    )
    assert out["start_probability"] == baseline["start_probability"]
    assert out["start_probability"] != pytest.approx(flag / 100.0, abs=1e-4)


def test_availability_confidence_does_not_directly_change_pstart():
    player = {
        "starts": 5,
        "minutes": 420,
        "status": "a",
        "chance_of_playing_next_round": 75,
    }
    base_context = {"team_matches_played": 6}
    low = estimate_player_minutes(
        player,
        {
            **base_context,
            "availability_evidence_state": {
                "gw_availability": "DOUBT",
                "gw_availability_confidence": "LOW",
                "model_features": {
                    "gw_availability": "DOUBT",
                    "explicit_out_for_target": False,
                },
            },
        },
    )
    high = estimate_player_minutes(
        player,
        {
            **base_context,
            "availability_evidence_state": {
                "gw_availability": "DOUBT",
                "gw_availability_confidence": "HIGH",
                "model_features": {
                    "gw_availability": "DOUBT",
                    "explicit_out_for_target": False,
                },
            },
        },
    )
    assert low["start_probability"] == high["start_probability"]
