from src.engines.competitive_load import _state, load_config


def test_competitive_load_state_contract_is_exact():
    assert load_config()["states"] == ["RESTED", "NORMAL", "CONGESTED", "HIGH_ROTATION_RISK", "UNKNOWN"]


def test_unknown_when_rest_window_is_not_verified():
    assert _state(None, 90, 0, 1, 1) == "UNKNOWN"


def test_heavy_minutes_short_rest_is_high_rotation_risk():
    assert _state(60, 90, 0, 1, 2) == "HIGH_ROTATION_RISK"


def test_extra_time_short_turnaround_is_high_rotation_risk():
    assert _state(90, 120, 30, 1, 2) == "HIGH_ROTATION_RISK"


def test_dense_schedule_is_congested_without_blanket_high_risk():
    assert _state(96, 70, 0, 2, 3) == "CONGESTED"


def test_long_rest_is_rested():
    assert _state(168, 90, 0, 1, 2) == "RESTED"


def test_governance_forbids_direct_prediction_mutation():
    governance = load_config()["governance"]
    assert governance["no_blanket_fatigue_penalty"] is True
    assert governance["direct_xpts_mutation_forbidden"] is True
    assert governance["direct_xmins_mutation_forbidden_until_calibrated"] is True
    assert governance["coach_rotation_tendency_must_not_be_inferred_without_evidence"] is True
    assert governance["travel_distance_must_not_be_invented"] is True
