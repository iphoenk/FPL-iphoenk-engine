from src.models.v12_stagec_shadow_evidence import audit_stagec_context


def test_stagec_shadow_rejects_fpl_tactical_inference_and_unmapped():
    result = audit_stagec_context(
        [1, 2],
        [
            {"element": 1, "field": "role", "source": "OFFICIAL_FPL", "match_id": "m1", "value": "MID"},
            {"element": 1, "field": "formation", "source": "V6_OBSERVED_MATCH", "match_id": "m1", "value": "4-3-3"},
            {"element": 3, "field": "coach", "source": "V6_OBSERVED_MATCH", "match_id": "m1", "value": "Coach"},
            {"element": 2, "field": "availability", "source": "OFFICIAL_FPL", "match_id": "m1", "value": "a"},
        ],
    )
    assert result["official_universe_count"] == 2
    assert result["observed_players_by_field"] == {"coach": 0, "formation": 1, "role": 0, "availability": 1}
    assert result["rejected_observations_by_reason"] == {
        "FPL_POSITION_NOT_TACTICAL_PROOF": 1, "UNMAPPED_PLAYER": 1
    }
    assert result["production_activation_allowed"] is False
    assert result["numeric_model_effect"] == "NONE"


def test_stagec_shadow_rejects_duplicate_official_ids():
    import pytest
    with pytest.raises(ValueError, match="OFFICIAL_UNIVERSE_INVALID"):
        audit_stagec_context([1, 1], [])


def test_conflicting_observations_cannot_be_reintroduced():
    base = {"element": 1, "field": "role", "source": "V6_OBSERVED_MATCH", "match_id": "m1"}
    result = audit_stagec_context([1], [
        {**base, "value": "WINGER"},
        {**base, "value": "FULLBACK"},
        {**base, "value": "WINGER"},
    ])
    assert result["observed_players_by_field"]["role"] == 0
    assert result["rejected_observations_by_reason"]["CONFLICTING_OBSERVATION"] == 2
