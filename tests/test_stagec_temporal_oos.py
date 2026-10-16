from src.models.v12_stagec_temporal_oos import audit_oos_calibration


def _prediction(**updates):
    row = dict(element=1, match_id="m1", prediction_as_of="2026-10-01T10:00:00Z",
               kickoff="2026-10-02T10:00:00Z", p_start=0.9, xmins=82,
               baseline_p_start=0.5, baseline_xmins=40, model_owner="V12_PLAYER_MINUTES")
    row.update(updates)
    return row


def _outcome(**updates):
    row = dict(element=1, match_id="m1", settled_at="2026-10-02T13:00:00Z",
               starter=True, minutes=85)
    row.update(updates)
    return row


def test_shadow_oos_improvement_requires_both_metrics():
    result = audit_oos_calibration([_prediction()], [_outcome()], minimum_sample=1)
    assert result["verdict"] == "PASS_SHADOW"
    assert result["beats_baseline_both"]
    assert not result["production_activation_allowed"]
    assert not result["numeric_parameters_mutated"]


def test_temporal_leakage_fails_closed():
    result = audit_oos_calibration([_prediction(prediction_as_of="2026-10-03T10:00:00Z")],
                                   [_outcome()], minimum_sample=1)
    assert result["verdict"] == "INSUFFICIENT_OR_FAIL"
    assert result["scored_sample"] == 0
    assert result["rejected_by_reason"]["TEMPORAL_LEAKAGE_OR_UNSETTLED"] == 1


def test_no_real_sample_never_claims_pass():
    result = audit_oos_calibration([], [], minimum_sample=1)
    assert result["verdict"] == "INSUFFICIENT_OR_FAIL"


def test_unverified_model_owner_fails_closed():
    result = audit_oos_calibration([_prediction(model_owner="OTHER")], [_outcome()], minimum_sample=1)
    assert result["rejected_by_reason"]["MODEL_OWNER_UNVERIFIED"] == 1


def test_duplicate_predictions_fail_closed():
    import pytest
    with pytest.raises(ValueError, match="PREDICTION_IDENTITY_INVALID_OR_DUPLICATE"):
        audit_oos_calibration([_prediction(), _prediction()], [_outcome()], minimum_sample=1)
