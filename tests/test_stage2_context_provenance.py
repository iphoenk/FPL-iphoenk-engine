"""Stage 2 source-admission tests: real source shape, no P(start) promotion."""
from copy import deepcopy

import pytest

from src.models.v12_stage2_context_provenance import audit_stage2_context_provenance


def source_shape():
    bootstrap = {
        "teams": [{"id": i} for i in range(1, 21)],
        "elements": [
            {"id": i, "team": ((i - 1) % 20) + 1, "status": "a"}
            for i in range(1, 668)
        ],
    }
    game = {
        "gw": 6, "fixture_id": 54, "team_id": 1, "manager": "Coach",
        "manager_native_id": 567, "formation": "4-3-3",
        "provider_position_id": 6, "source_snapshot_sha256": "a" * 64,
    }
    rows = [
        {
            "element_id": p["id"], "team_id": p["team"],
            "provider_position_id_semantics": "SOURCE_NATIVE_OPAQUE_ONLY",
            "semantic_role": None,
            "target_gw_manager_fit_probability": None,
            "target_gw_role_start_probability": None,
            "numeric_pstart_effect": "NONE",
            "history": [deepcopy(game)] if p["id"] == 1 else [],
        }
        for p in bootstrap["elements"]
    ]
    longitudinal = {
        "contract": "V12_ALLCLUB_MANAGER_ROLE_LONGITUDINAL_V1",
        "observation_scope": "GW1_GW6_POST_MATCH_RETROSPECTIVE_ONLY",
        "numeric_pstart_effect": "NONE",
        "source_asof_before_historical_deadline_verified": False,
        "manager_start_effect_calibrated": False,
        "semantic_tactical_role_calibrated": False,
        "players": rows,
    }
    return bootstrap, longitudinal


def test_stage2_positive_667_status_and_one_historical_slot_not_a_role():
    bootstrap, ledger = source_shape()
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_integrity_state"] == "PASS"
    assert out["official_universe_count"] == 667
    assert out["official_club_count"] == 20
    assert out["observed_official_status_players"] == 667
    assert out["historical_source_players"] == 1
    assert out["historical_match_player_observations"] == 1
    assert out["verified_manager_history_players"] == 1
    assert out["verified_formation_history_players"] == 1
    assert out["verified_opaque_provider_slot_players"] == 1
    assert out["verified_semantic_tactical_role_players"] == 0
    assert out["verified_target_gw_manager_effect_players"] == 0
    assert out["verified_medical_predeadline_players"] == 0
    assert out["numeric_pstart_effect"] == "NONE"
    assert out["numeric_xmins_effect"] == "NONE"
    assert out["production_activation_allowed"] is False


def test_stage2_no_historical_observation_does_not_create_a_coach_signal():
    bootstrap, ledger = source_shape()
    ledger["players"][0]["history"] = []
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_integrity_state"] == "PASS"
    assert out["verified_manager_history_players"] == 0
    assert out["historical_match_player_observations"] == 0
    assert not out["production_activation_allowed"]


@pytest.mark.parametrize("field,value", [
    ("source_snapshot_sha256", "forged"),
    ("fixture_id", 0),
    ("gw", 7),
    ("formation", ""),
])
def test_stage2_source_identity_violations_fail_closed(field, value):
    bootstrap, ledger = source_shape()
    ledger["players"][0]["history"][0][field] = value
    result = audit_stage2_context_provenance(bootstrap, ledger)
    assert result["source_integrity_state"] == "PARTIAL"
    assert result["source_rejections"]["SOURCE_MATCH_FIXTURE_SHA_INVALID"] == 1
    assert result["historical_source_players"] == 0


@pytest.mark.parametrize("field,value,reason", [
    ("team_id", 2, "LONGITUDINAL_CLUB_DRIFT"),
    ("semantic_role", "WINGER", "UNVERIFIED_TACTICAL_OR_NUMERIC_PROMOTION"),
    ("target_gw_manager_fit_probability", 0.9, "UNVERIFIED_TACTICAL_OR_NUMERIC_PROMOTION"),
    ("numeric_pstart_effect", "ENABLED", "UNVERIFIED_TACTICAL_OR_NUMERIC_PROMOTION"),
])
def test_stage2_spoofed_context_cannot_activate_model(field, value, reason):
    bootstrap, ledger = source_shape()
    ledger["players"][0][field] = value
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_integrity_state"] == "PARTIAL"
    assert out["source_rejections"][reason] == 1
    assert out["production_activation_allowed"] is False


def test_stage2_duplicate_match_observation_rejected():
    bootstrap, ledger = source_shape()
    ledger["players"][0]["history"].append(deepcopy(ledger["players"][0]["history"][0]))
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_rejections"]["SOURCE_MATCH_FIXTURE_SHA_INVALID"] == 1


def test_stage2_official_bootstrap_666_with_matching_ledger_still_fails():
    bootstrap, ledger = source_shape()
    bootstrap["elements"].pop()
    ledger["players"].pop()
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_integrity_state"] == "PARTIAL"
    assert out["source_rejections"]["OFFICIAL_UNIVERSE_INCOMPLETE"] == 1


def test_stage2_unknown_extra_player_fails_closed():
    bootstrap, ledger = source_shape()
    ledger["players"].append({**ledger["players"][0], "element_id": 9999})
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_rejections"]["LONGITUDINAL_IDENTITY_DUPLICATE_OR_UNKNOWN"] == 1


def test_stage2_retroactive_claim_of_predeadline_source_rejected():
    bootstrap, ledger = source_shape()
    ledger["source_asof_before_historical_deadline_verified"] = True
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["source_rejections"]["LONGITUDINAL_SOURCE_AUTHORITY_INVALID"] == 1
    assert out["historical_predeadline_model_witness"] == "NOT_ESTABLISHED"


def test_stage2_missing_official_availability_must_not_equal_medical_clearance():
    bootstrap, ledger = source_shape()
    bootstrap["elements"][0]["status"] = None
    out = audit_stage2_context_provenance(bootstrap, ledger)
    assert out["observed_official_status_players"] == 666
    assert out["source_rejections"]["OFFICIAL_STATUS_PARTIAL"] == 1
    assert out["verified_medical_predeadline_players"] == 0
