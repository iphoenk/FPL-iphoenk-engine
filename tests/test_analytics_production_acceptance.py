from src.engines.report_materializer import (
    _analytics_acceptance,
    _full_season_history_acceptance,
)


def test_full_history_acceptance_preserves_production_gate():
    out = _full_season_history_acceptance(
        {
            "full_season_history": {
                "contract": "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
                "as_of": {"planning_gw": 7, "historical_gws": [1, 2, 3, 4, 5, 6]},
                "universe": {"expected_players": 667, "covered_players": 667},
                "coverage_gate": {
                    "status": "PASS",
                    "fixture_identity_status": "PASS",
                    "all_historical_gws_finalized": True,
                    "available_gw_slots": 4002,
                    "expected_player_slots": 4002,
                    "pending_never_coerced_to_zero": True,
                    "dnp_and_blank_distinguished": True,
                    "double_gameweeks_aggregate_fixture_rows": True,
                },
            }
        },
        7,
    )
    assert out["status"] == "PASS"
    assert out["historical_range"] == "GW1-GW6"
    assert out["expected_players"] == 667
    assert out["pending_never_coerced_to_zero"] is True


def test_analytics_acceptance_separates_evidence_from_resolution_and_lock():
    out = _analytics_acceptance(
        user={
            "rows": [
                {
                    "p_start": 0.83,
                    "p_start_evidence": {
                        "signals": ["season_start_rate", "role_start_probability"]
                    },
                }
            ] * 15,
            "captaincy": {
                "captain_state": "PREPARE",
                "captain_frontier": [{"player": "A"}, {"player": "B"}],
            },
        },
        full_history={
            "status": "PASS",
            "planning_gw": 7,
            "historical_range": "GW1-GW6",
            "covered_players": 667,
            "expected_players": 667,
        },
    )
    assert out["p_start"]["evidence_status"] == "PASS"
    assert out["p_start"]["resolution_status"] == "LIMITED_RESOLUTION"
    assert out["p_start"]["resolution_audit"]["individual_evidence_rows"] == 0
    assert out["p_start"]["acceptance_layers"]["CALIBRATION"] == "NO_SETTLED_SAMPLE"
    assert out["s08_captain"]["evidence_status"] == "PASS"
    assert out["s08_captain"]["decision_state"] == "PREPARE"
    assert out["full_history"]["evidence_status"] == "PASS"


def test_report_architecture_binds_owned_player_minutes_evidence():
    from src.engines.report_architecture import _pstart_rows

    rows = _pstart_rows(
        {"team_value_ledger": [{"element": 11, "name": "Alpha", "position": "MID"}]},
        {"players": [{
            "element": 11,
            "xmins": {
                "start_probability": 0.73,
                "expected_minutes": 68,
                "dnp_probability": 0.11,
                "p_start_evidence": {
                    "source": "V12_PLAYER_MINUTES",
                    "signals": ["season_start_rate", "role_start_probability"],
                },
            },
        }]},
    )
    assert rows == [{
        "element": 11,
        "name": "Alpha",
        "position": "MID",
        "p_start": 0.73,
        "p_dnp": 0.11,
        "xmins": 68,
        "p_start_evidence": {
            "source": "V12_PLAYER_MINUTES",
            "signals": ["season_start_rate", "role_start_probability"],
        },
        "pstart_context_evidence": {
            "contract": "V12_PSTART_CONTEXT_OBSERVABILITY_V1",
            "role": {
                "profile": None, "source": None, "status": "UNAVAILABLE",
                "calibrated_start_signal_applied": True,
            },
            "manager": {
                "manager_id": None, "source": None,
                "status": "NO_VERIFIED_MANAGER_TIMELINE",
                "calibrated_start_signal_applied": False,
            },
            "availability": {
                "fpl_status": None,
                "official_status_observed": False,
                "authority": "UNVERIFIED",
                "normalized_gw_state": "UNKNOWN",
                "normalized_start_signal_applied": False,
                "normal_status_no_numeric_adjustment": False,
                "official_status_is_not_start_probability": True,
                "normal_status_is_not_medical_clearance": True,
            },
            "readiness": {
                "role_manager_calibration": "NOT_ESTABLISHED",
                "asof_feature_lineage": "NOT_ESTABLISHED",
                "shadow_only": True,
                "changes_to_canonical_pstart": False,
            },
        },
    }]

    from src.models.v12_pstart_context_evidence import build_pstart_context_observability
    proof = build_pstart_context_observability(
        {
            "element": 11, "status": "a", "position": "MID",
            "tactical_role": {
                "profile": "attacking-midfielder",
                "source": "understat_normalized_exact_identity",
                "decision_influence": "ADVISORY_ONLY",
            },
        },
        {
            "availability_observation": {"gw_availability": "UNKNOWN"},
        },
        {"signals": ["neutral_prior", "player_selection_posterior"]},
    )
    assert proof["role"]["status"] == "PROFILE_ADVISORY_UNCALIBRATED"
    assert proof["availability"]["normal_status_no_numeric_adjustment"] is True
    assert proof["availability"]["official_status_is_not_start_probability"] is True
    assert proof["manager"]["status"] == "NO_VERIFIED_MANAGER_TIMELINE"
    assert proof["readiness"]["changes_to_canonical_pstart"] is False

    no_observation = build_pstart_context_observability(
        {"element": 11, "status": "d"},
        {"availability_observation": {"gw_availability": "DOUBT"}},
        {"signals": ["neutral_prior"]},
    )
    assert no_observation["availability"]["normal_status_no_numeric_adjustment"] is False


def test_gw7_history_rejects_v6_gw1_to_gw5_nominal_pass():
    source = {
        "full_season_history": {
            "contract": "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
            "as_of": {"planning_gw": 6, "historical_gws": [1, 2, 3, 4, 5]},
            "coverage_gate": {
                "status": "PASS",
                "fixture_identity_status": "PASS",
                "all_historical_gws_finalized": True,
            },
            "universe": {"expected_players": 667, "covered_players": 667},
        },
    }
    out = _full_season_history_acceptance(source, 7)
    assert out["status"] == "PARTIAL"
    assert out["source_planning_gw"] == 6
    assert out["required_planning_gw"] == 7
    assert out["historical_range_matches_target"] is False
    assert "PLANNING_GW_HISTORY_RANGE_MISMATCH" in out["coverage_rejection_reasons"]


def test_gw7_history_rejects_unsettled_gw6_even_when_all_slots_present():
    source = {
        "full_season_history": {
            "as_of": {"planning_gw": 7, "historical_gws": [1, 2, 3, 4, 5, 6]},
            "coverage_gate": {
                "status": "PASS",
                "fixture_identity_status": "PASS",
                "all_historical_gws_finalized": False,
                "pending_historical_gws": [6],
            },
        },
    }
    out = _full_season_history_acceptance(source, 7)
    assert out["status"] == "PARTIAL"
    assert "HISTORICAL_GW_NOT_FINALIZED" in out["coverage_rejection_reasons"]


def test_gw7_history_rejects_legacy_missing_fixture_identity():
    source = {
        "full_season_history": {
            "as_of": {"planning_gw": 7, "historical_gws": [1, 2, 3, 4, 5, 6]},
            "coverage_gate": {"status": "PASS", "all_historical_gws_finalized": True},
        },
    }
    out = _full_season_history_acceptance(source, 7)
    assert out["status"] == "PARTIAL"
    assert "OFFICIAL_FIXTURE_IDENTITY_UNVERIFIED" in out["coverage_rejection_reasons"]
