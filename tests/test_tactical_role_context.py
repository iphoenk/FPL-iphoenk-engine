from src.models.tactical_role_context import build_team_system_context, classify_role, load_config


def _advanced(**overrides):
    payload = {
        "minutes": 360.0,
        "sample_quality": "DEVELOPING",
        "xg_per90": 0.10,
        "xa_per90": 0.10,
        "touches_opposition_box_per90": 2.0,
        "chances_created_per90": 1.0,
        "shots_per90": 1.0,
    }
    payload.update(overrides)
    return payload


def test_missing_role_evidence_is_explicit_and_neutral():
    row = classify_role("MID", {"minutes": 0, "sample_quality": "NO_ADVANCED_EVIDENCE"})
    assert row["profile"] == "UNASSESSED"
    assert row["confidence"] == "NONE"
    assert row["decision_influence"] == "ADVISORY_ONLY"


def test_midfielder_role_profile_distinguishes_shooter_creator_and_hybrid():
    shooter = classify_role("MID", _advanced(touches_opposition_box_per90=5.0, shots_per90=2.4, xg_per90=0.30))
    creator = classify_role("MID", _advanced(chances_created_per90=2.6, xa_per90=0.25))
    hybrid = classify_role("MID", _advanced(touches_opposition_box_per90=5.0, shots_per90=2.4, xg_per90=0.30, chances_created_per90=2.6, xa_per90=0.25))
    assert shooter["profile"] == "ADVANCED_RUNNER_SHOOTER_PROFILE"
    assert creator["profile"] == "CREATOR_PROFILE"
    assert hybrid["profile"] == "HYBRID_ATTACKING_MID_PROFILE"
    assert hybrid["confidence"] == "MEDIUM"


def test_defender_role_profile_uses_observed_attacking_involvement():
    row = classify_role("DEF", _advanced(touches_opposition_box_per90=3.1, chances_created_per90=1.2))
    assert row["profile"] == "ATTACKING_DEFENDER_PROFILE"
    assert "box-touch" in row["reason"]


def test_team_system_context_labels_fpl_position_shape_not_tactical_formation():
    elements = []
    rows = []
    element = 1
    for element_type, count in ((1, 1), (2, 4), (3, 3), (4, 3)):
        for _ in range(count):
            elements.append({"id": element, "team": 7, "element_type": element_type})
            rows.append({"player_id": str(element), "match_id": "m1", "minutes_played": "90", "start_min": "0"})
            element += 1
    context = build_team_system_context(elements, rows)
    team = context["7"]
    assert team["label"] == "FPL_POSITION_SHAPE"
    assert team["dominant_shape"] == "4-3-3"
    assert team["valid_matches"] == 1
    assert team["confidence"] == "LOW"
    assert team["governance"]["not_claimed_as_true_tactical_formation"] is True
    assert team["decision_influence"] == "ADVISORY_ONLY"


def test_rec41_policy_blocks_model_adjustment_until_future_calibrated_opt_in():
    cfg = load_config()
    policy = cfg["policy"]
    assert policy["decision_influence"] == "ADVISORY_ONLY"
    assert policy["xmins_adjustment_enabled"] is False
    assert policy["xpts_rate_adjustment_enabled"] is False
    assert policy["fpl_position_shape_is_not_claimed_as_true_tactical_formation"] is True
