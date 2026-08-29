from src.models.tactical_matchup import _dimension_matrix, _edge_risk_label, _role_evidence_label, _system_formation_fit


def test_role_evidence_labels_are_truthful():
    observed = {
        "position": "MID",
        "role": "CREATOR_PROFILE",
        "evidence": {"class": "OBSERVED_ADVANCED_ROLE_PROFILE"},
    }
    inferred = {"position": "MID", "role": "CREATOR_PROFILE", "evidence": {"class": "OTHER"}}
    fpl_only = {"position": "MID", "role": None, "evidence": {}}
    unknown = {}
    assert _role_evidence_label(observed) == "OBSERVED_ROLE"
    assert _role_evidence_label(inferred) == "INFERRED_ROLE"
    assert _role_evidence_label(fpl_only) == "FPL_POSITION_ONLY"
    assert _role_evidence_label(unknown) == "UNKNOWN"


def test_fpl_position_shape_never_becomes_true_formation_or_fit_score():
    own = {
        "base_formation": "4-3-3",
        "coach": None,
        "evidence": {"class": "OBSERVED_FPL_POSITION_SHAPE"},
    }
    role = {
        "position": "MID",
        "role": "CREATOR_PROFILE",
        "evidence": {"class": "OBSERVED_ADVANCED_ROLE_PROFILE"},
    }
    fit = _system_formation_fit(own, role)
    assert fit["status"] == "PARTIAL"
    assert fit["role_evidence_label"] == "OBSERVED_ROLE"
    assert fit["fpl_position_shape_proxy"] == "4-3-3"
    assert fit["true_tactical_formation"] is None
    assert fit["fit_score"] is None
    assert fit["governance"]["fpl_position_shape_is_not_true_tactical_formation"] is True
    assert "coach_system" in fit["missing_inputs"]


def test_deep_tactical_dimension_matrix_is_explicit_not_fabricated():
    opponent = {
        "base_formation": "4-3-3",
        "coach": None,
        "build_up": None,
        "pressing": None,
        "defensive_line": None,
        "width": None,
        "transition": None,
        "set_piece_profile": "OBSERVED_HIGH_SET_PIECE_ACTIVITY",
        "vulnerabilities": ["box_pressure"],
        "strengths": [],
        "observed_style_proxies": ["set_piece_activity"],
    }
    dimensions = _dimension_matrix(opponent, [{"gw": 2}], {"is_home": False})
    required = {
        "opponent_coach", "formation_or_variants", "build_up", "press_height_intensity_triggers",
        "mid_low_block", "defensive_line", "wide_half_space_protection", "fullback_wingback_positioning",
        "transition_defense", "counter_profile", "set_pieces", "aerial_profile",
        "central_wide_vulnerability", "box_protection", "second_balls", "gk_distribution_shot_stopping",
        "expected_possession_game_state", "venue", "recent_tactical_adjustments_2_5",
        "structural_injuries_suspensions", "observed_strengths",
    }
    assert set(dimensions) == required
    assert set(dimensions.values()) <= {"AVAILABLE", "PARTIAL", "UNAVAILABLE"}
    assert dimensions["opponent_coach"] == "UNAVAILABLE"
    assert dimensions["formation_or_variants"] == "PARTIAL"
    assert dimensions["set_pieces"] == "PARTIAL"
    assert dimensions["venue"] == "AVAILABLE"


def test_tactical_label_only_uses_observed_route_overlap():
    role = {"return_routes": ["box_pressure", "chance_creation"]}
    opponent = {"vulnerabilities": ["box_pressure"], "strengths": ["chance_creation"]}
    label, edge, risk = _edge_risk_label(opponent, role)
    assert label == "MIXED"
    assert edge == ["box_pressure"]
    assert risk == ["chance_creation"]
