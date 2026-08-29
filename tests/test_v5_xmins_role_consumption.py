from src.v5.intelligence.xmins import estimate_xmins


def _player():
    return {
        "starts": 2,
        "minutes": 180,
        "status": "a",
        "chance_of_playing_next_round": None,
    }


def _base_context():
    return {
        "team_matches_played": 2,
        "prior_start_probability": 0.92,
        "prior_evidence_minutes": 2500,
        "starter_minutes_prior": 84,
        "role_start_probability": 0.78,
        "rotation_risk": 0.30,
    }


def test_role_rotation_risk_is_not_applied_twice_without_independent_evidence():
    context = _base_context()
    result = estimate_xmins(_player(), context)
    no_rotation = estimate_xmins(_player(), {**context, "rotation_risk": 0.0})
    assert result["start_probability"] == no_rotation["start_probability"]
    assert result["rotation_risk"] == 0.30
    assert result["effective_rotation_risk"] == 0.0
    assert result["rotation_risk_independent_evidence"] is False
    assert result["governance"]["role_probability_and_role_rotation_risk_not_double_counted"] is True


def test_independently_governed_rotation_evidence_can_apply_second_penalty():
    context = {**_base_context(), "rotation_risk_independent_evidence": True}
    result = estimate_xmins(_player(), context)
    baseline = estimate_xmins(_player(), {**context, "rotation_risk": 0.0})
    assert result["effective_rotation_risk"] == 0.30
    assert result["start_probability"] < baseline["start_probability"]
