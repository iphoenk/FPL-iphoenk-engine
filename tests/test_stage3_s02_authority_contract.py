from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.v12_deep_delivery import select_personal_evidence
from src.engines.v12_stage3_acceptance import _verified_s02_public_fallback


SLOT = "2026-10-11T07:44:00+07:00"
OBSERVED = "2026-10-11T00:43:00+00:00"
TEAM = 3462711


def _public_evidence(gw=6):
    picks = []
    for i in range(1, 16):
        picks.append({
            "element_id": i,
            "squad_position": i,
            "multiplier": 1 if i <= 11 else 0,
            "captain": i == 4,
            "vice_captain": i == 10,
            "bench_order": i - 11 if i > 11 else None,
        })
    submitted = {
        "status": "AVAILABLE",
        "authority": "OFFICIAL_FPL",
        "entry_id": TEAM,
        "gw": gw,
        "generated_at": OBSERVED,
        "picks": picks,
        "lineage": {
            "authority": "OFFICIAL_FPL",
            "endpoint_class": "submitted_picks",
            "http_status": 200,
            "entry_id": TEAM,
            "gw": gw,
            "origin": "LIVE_FETCHED_CURRENT_GW",
            "payload_digest": "known-source-hash",
        },
    }
    rows = []
    for i in range(1, 16):
        position = "GK" if i <= 2 else "DEF" if i <= 7 else "MID" if i <= 12 else "FWD"
        rows.append({"element_id": i, "position": position})
    section = {
        "state": "DEGRADED",
        "degradation_reason": (
            "CURRENT15 preserved from official submitted picks but is not "
            "authenticated-current for the planning GW"
        ),
        "content": {
            "rows": rows,
            "current15_authority": {
                "source_class": "OFFICIAL_SUBMITTED_PICKS",
                "observed_at": OBSERVED,
                "applicable_gw": gw,
                "resolution_status": "PREVIOUS_GW_IDENTITY_FALLBACK",
                "auth_state": "UNAVAILABLE",
                "finance_availability": "DEGRADED",
                "stale": True,
            },
        },
    }
    return section, submitted


def _errors(section, submitted):
    return _verified_s02_public_fallback(
        section, submitted, planning_gw=7, report_slot=SLOT
    )


def test_verified_last_submitted_squad_can_be_source_degraded_without_private_finance():
    section, submitted = _public_evidence()
    assert _errors(section, submitted) == []


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("incomplete", "S02_SUBMITTED_COUNT_INVALID"),
        ("duplicate", "S02_SUBMITTED_DUPLICATE_OR_INVALID_PLAYER"),
        ("fabricated", "S02_OWNED_PLAYERS_NOT_BOUND_TO_PUBLIC_SOURCE"),
        ("wrong_positions", "S02_POSITION_DISTRIBUTION_INVALID"),
        ("captain_absent", "S02_CAPTAIN_VICE_INVALID"),
        ("bad_bench", "S02_XI_BENCH_INVALID"),
        ("wrong_source", "S02_SOURCE_CLASS_NOT_OFFICIAL_SUBMITTED"),
        ("wrong_entry", "S02_PUBLIC_TEAM_ID_MISMATCH"),
        ("wrong_gw", "S02_SOURCE_GW_MISMATCH"),
        ("missing_lineage", "S02_OFFICIAL_PROVENANCE_INVALID"),
        ("false_freshness", "S02_PUBLIC_IDENTITY_MISREPRESENTED_AS_FRESH_CURRENT"),
        ("invented_finance", "S02_PUBLIC_FINANCE_FABRICATED"),
        ("invented_current", "S02_PUBLIC_EDITABLE_AUTHORITY_FABRICATED"),
        ("missing_auth_notice", "S02_PUBLIC_AUTH_GAP_NOT_DISCLOSED"),
        ("future_observation", "S02_OBSERVATION_TIMESTAMP_INVALID"),
    ],
)
def test_s02_fallback_fails_closed_on_integrity_corruption(mutation, error):
    section, submitted = deepcopy(_public_evidence())
    authority = section["content"]["current15_authority"]
    if mutation == "incomplete":
        submitted["picks"].pop()
    elif mutation == "duplicate":
        submitted["picks"][-1]["element_id"] = 1
    elif mutation == "fabricated":
        section["content"]["rows"][-1]["element_id"] = 5555
    elif mutation == "wrong_positions":
        section["content"]["rows"][-1]["position"] = "DEF"
    elif mutation == "captain_absent":
        for pick in submitted["picks"]:
            pick["captain"] = False
    elif mutation == "bad_bench":
        submitted["picks"][0]["multiplier"] = 0
    elif mutation == "wrong_source":
        authority["source_class"] = "AUTHENTICATED_CURRENT_TEAM"
    elif mutation == "wrong_entry":
        submitted["entry_id"] = TEAM + 1
    elif mutation == "wrong_gw":
        submitted["gw"] = 4
        submitted["lineage"]["gw"] = 4
        authority["applicable_gw"] = 4
    elif mutation == "missing_lineage":
        submitted["lineage"] = {}
    elif mutation == "false_freshness":
        authority["stale"] = False
    elif mutation == "invented_finance":
        authority["finance_availability"] = "AVAILABLE"
    elif mutation == "invented_current":
        authority["resolution_status"] = "CURRENT_VALID"
    elif mutation == "missing_auth_notice":
        section["degradation_reason"] = "Internal renderer error"
    elif mutation == "future_observation":
        authority["observed_at"] = "2026-10-11T12:00:00+07:00"
    assert error in _errors(section, submitted)


def _auth_candidate(*, gw=7, entry=TEAM, observed=OBSERVED):
    return {
        "source": "PRIVATE:personal/current_team.json",
        "source_class": "AUTHENTICATED_CURRENT_TEAM",
        "gw": gw,
        "auth_state": "AUTH_AVAILABLE",
        "observed_at": observed,
        "payload": {
            "gw": gw,
            "entry_id": entry,
            "generated_at": observed,
            "auth_state": "AUTH_AVAILABLE",
            "players": [{"element_id": i} for i in range(21, 36)],
            "bank": 12,
            "free_transfers": 1,
            "lineage": {
                "authenticated": [
                    {"endpoint_class": "me", "http_status": 200, "entry_id": entry},
                    {"endpoint_class": "my_team", "http_status": 200, "entry_id": entry},
                ]
            },
        },
    }


def _public_candidate():
    section, submitted = _public_evidence()
    return {
        "source": "PRIVATE:personal/submitted_picks.json",
        "source_class": "OFFICIAL_SUBMITTED_PICKS",
        "gw": 6,
        "observed_at": OBSERVED,
        "auth_state": "PUBLIC_OFFICIAL",
        "payload": submitted,
    }


def _select(candidates):
    return select_personal_evidence(
        candidates,
        planning_gw=7,
        expected_entry_id=TEAM,
        as_of=SLOT,
    )


def test_current_authenticated_gw7_with_live_lineage_authorizes_finance():
    result = _select([_public_candidate(), _auth_candidate()])
    assert result["resolution_status"] == "CURRENT_VALID"
    assert result["source_class"] == "AUTHENTICATED_CURRENT_TEAM"
    assert result["finance_allowed"] is True
    assert result["stale"] is False


def test_http200_but_previous_gw_falls_back_to_public_with_private_finance_blocked():
    result = _select([_public_candidate(), _auth_candidate(gw=6)])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
    assert result["resolution_status"] == "PREVIOUS_GW_IDENTITY_FALLBACK"
    assert result["finance_allowed"] is False
    assert result["stale"] is True


def test_http200_but_newer_than_report_slot_falls_back_to_public():
    result = _select([
        _public_candidate(),
        _auth_candidate(observed="2026-10-11T08:01:00+07:00"),
    ])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
    assert result["finance_allowed"] is False


def test_wrong_authenticated_team_falls_back_to_official_public():
    result = _select([_public_candidate(), _auth_candidate(entry=TEAM + 1)])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"


def test_http200_without_both_live_endpoint_lineages_is_not_current_authority():
    candidate = _auth_candidate()
    candidate["payload"]["lineage"]["authenticated"].pop()
    result = _select([_public_candidate(), candidate])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"


def test_incomplete_public_squad_has_no_source_degraded_acceptance():
    section, submitted = _public_evidence()
    section["content"]["rows"].pop()
    assert "S02_SUBMITTED_COUNT_INVALID" in _errors(section, submitted)


def test_current_gw_submitted_picks_are_still_not_editable_current15():
    candidate = _public_candidate()
    candidate["gw"] = candidate["payload"]["gw"] = 7
    result = _select([candidate])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
    assert result["stale"] is True
    assert result["finance_allowed"] is False


def test_no_candidate_cannot_fabricate_ownership():
    result = _select([])
    assert result["resolution_status"] == "UNAVAILABLE"
    assert result["rows"] == []
    assert result["finance_allowed"] is False
