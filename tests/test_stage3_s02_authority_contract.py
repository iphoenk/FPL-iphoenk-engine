from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.v12_deep_delivery import select_personal_evidence
from src.engines.v12_stage3_acceptance import (
    _verified_s02_public_fallback,
    _verified_s05_pl_fixtures,
)


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


def test_official_next_gw_authorizes_editable_squad_without_relabelling_scoring_gw():
    candidate = _auth_candidate(gw=6)
    candidate["payload"]["editable_planning_gw"] = 7
    result = _select([_public_candidate(), candidate])
    assert result["source_class"] == "AUTHENTICATED_CURRENT_TEAM"
    assert result["finance_allowed"] is True
    assert result["gw"] == 7
    assert result["source_scoring_gw"] == 6


def test_next_gw_override_without_live_me_and_my_team_stays_unbound():
    candidate = _auth_candidate(gw=6)
    candidate["payload"]["editable_planning_gw"] = 7
    candidate["payload"]["lineage"]["authenticated"].pop()
    result = _select([_public_candidate(), candidate])
    assert result["source_class"] == "OFFICIAL_SUBMITTED_PICKS"
    assert result["finance_allowed"] is False


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


def test_s05_valid_official_fixtures_and_missing_non_pl_source_are_distinct():
    fixtures = [
        {"id": 7001, "event": 7, "team_h": 1, "team_a": 2,
         "kickoff_time": "2026-10-18T12:00:00Z"},
        {"id": 7002, "event": 7, "team_h": 3, "team_a": 4,
         "kickoff_time": "2026-10-18T14:00:00Z"},
    ]
    section = {
        "state": "DEGRADED",
        "degradation_reason": "verified non-PL schedule source not bound",
        "content": {
            "fixtures": deepcopy(fixtures),
            "competition_coverage": {
                "official_pl": True,
                "verified_non_pl_schedule_bound": False,
                "verified_non_pl_event_count": 0,
            },
        },
    }
    catalog = {"official": {"fixtures": fixtures}}
    assert _verified_s05_pl_fixtures(section, catalog, planning_gw=7) == []

    section["content"]["fixtures"][0]["team_a"] = 99
    assert "S05_PL_FIXTURE_OFFICIAL_MISMATCH" in _verified_s05_pl_fixtures(
        section, catalog, planning_gw=7
    )
    section["content"]["fixtures"] = []
    assert "S05_PL_FIXTURES_MISSING" in _verified_s05_pl_fixtures(
        section, catalog, planning_gw=7
    )


def test_s05_fabricated_official_complete_flag_does_not_replace_fixture_catalog():
    section = {
        "content": {
            "fixtures": [
                {"id": 99, "event": 7, "team_h": 1, "team_a": 3,
                 "kickoff_time": "2026-10-18T12:00:00Z"},
            ],
            "competition_coverage": {"official_pl": True},
        }
    }
    expected = {"official": {"fixtures": [
        {"id": 98, "event": 7, "team_h": 1, "team_a": 3,
         "kickoff_time": "2026-10-18T12:00:00Z"},
    ]}}
    assert "S05_PL_FIXTURE_OFFICIAL_MISMATCH" in _verified_s05_pl_fixtures(
        section, expected, planning_gw=7
    )


def test_wrong_authenticated_team_without_public_proof_cannot_supply_owned15():
    result = _select([_auth_candidate(entry=TEAM + 1)])
    assert result["resolution_status"] == "UNAVAILABLE"
    assert result["rows"] == []
    assert result["finance_allowed"] is False


def test_missing_public_provenance_does_not_supply_owned15():
    candidate = _public_candidate()
    candidate["payload"]["lineage"] = {}
    result = _select([candidate])
    assert result["resolution_status"] == "UNAVAILABLE"
    assert result["rows"] == []


# --- S02 observation chronology: governed occurrence window (P3, 27 Oct 2026) ---
from datetime import datetime, timedelta, timezone

from src.engines.v12_stage3_acceptance import S02_OBSERVATION_WINDOW_MINUTES


def _with_observation(value, *, generated=None, slot=SLOT):
    section, submitted = deepcopy(_public_evidence())
    section["content"]["current15_authority"]["observed_at"] = value
    submitted["generated_at"] = generated if generated is not None else value
    return _verified_s02_public_fallback(
        section, submitted, planning_gw=7, report_slot=slot
    )


def _iso(slot, minutes, tz=timezone.utc):
    base = datetime.fromisoformat(slot)
    return (base + timedelta(minutes=minutes)).astimezone(tz).isoformat()


def test_window_matches_downstream_occurrence_window():
    from ops.render_external_clock import DOWNSTREAM_WINDOW_MINUTES

    assert S02_OBSERVATION_WINDOW_MINUTES == DOWNSTREAM_WINDOW_MINUTES


def test_production_26_oct_late_tick_observation_is_accepted():
    # Real shape: slot 21:30 WIB, observation 15:33:40.016323Z (+63m40s).
    slot = "2026-10-26T21:30:00+07:00"
    observed = "2026-10-26T15:33:40.016323+00:00"
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" not in _with_observation(observed, slot=slot)


@pytest.mark.parametrize("minutes", [-5, 0, 15, 56, 63, 70])
def test_observation_inside_governed_window_is_accepted(minutes):
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" not in _with_observation(_iso(SLOT, minutes))


@pytest.mark.parametrize("minutes", [-6, -60, 71, 240, 24 * 60])
def test_observation_outside_governed_window_fails_closed(minutes):
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _with_observation(_iso(SLOT, minutes))


def test_stale_observation_from_previous_occurrence_fails_closed():
    previous_slot = "2026-10-26T12:30:00+07:00"
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _with_observation(
        _iso(previous_slot, 5), slot="2026-10-26T21:30:00+07:00"
    )


@pytest.mark.parametrize("value", [None, "", "not-a-time", "2026-10-11T00:43:00"])
def test_missing_invalid_or_naive_timestamp_fails_closed(value):
    section, submitted = deepcopy(_public_evidence())
    section["content"]["current15_authority"]["observed_at"] = value
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _errors(section, submitted)
    section, submitted = deepcopy(_public_evidence())
    submitted["generated_at"] = value
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _errors(section, submitted)


def test_observed_and_generated_must_agree_within_five_seconds():
    observed = _iso(SLOT, 10)
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" not in _with_observation(
        observed, generated=_iso(SLOT, 10, tz=timezone(timedelta(hours=7)))
    )
    skewed = (datetime.fromisoformat(observed) + timedelta(seconds=6)).isoformat()
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _with_observation(observed, generated=skewed)


def test_naive_slot_fails_closed():
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" in _with_observation(
        OBSERVED, slot="2026-10-11T07:44:00"
    )


@pytest.mark.parametrize("zone", [timezone.utc, timezone(timedelta(hours=7)), timezone(timedelta(hours=1))])
def test_equivalent_instants_in_any_offset_are_equal_across_dst_boundary(zone):
    # London DST end (25 Oct 2026 01:00Z): the same instant must validate in any offset.
    slot = "2026-10-25T23:30:00+00:00"
    assert "S02_OBSERVATION_TIMESTAMP_INVALID" not in _with_observation(
        _iso(slot, 20, tz=zone), slot=slot
    )
