from src.engines.predictor_publication_contract import decorate_predictor_observation


def _row(**overrides):
    row = {
        "source": "OFFICIAL_FPL",
        "evidence_state": "AVAILABLE",
        "current_progress_percent": 63.7,
        "freshness_seconds": 90,
        "trajectory": "ACCELERATING",
        "direction": "RISE",
        "predicted_change_cycle": "NEXT_UPDATE",
        "predicted_change_at": "2026-09-01T06:00:00+07:00",
        "prediction_source": "OFFICIAL_PROJECTED_PROGRESS",
    }
    row.update(overrides)
    return row


def test_stale_predictor_snapshot_keeps_age_and_cannot_be_claimed_current():
    out = decorate_predictor_observation(_row(evidence_state="STALE", freshness_seconds=4560))
    assert out["model_signal_state"] == "SIGNAL"
    assert out["freshness_state"] == "STALE"
    assert out["age_seconds"] == 4560
    assert out["progress"] == 63.7
    assert out["trajectory"] == "ACCELERATING"
    assert out["direction"] == "RISE"
    assert out["eta"] == "2026-09-01T06:00:00+07:00"
    assert out["current_claim_allowed"] is False


def test_no_valid_predictor_signal_is_explicit_no_signal():
    out = decorate_predictor_observation(_row(
        predicted_change_cycle="NONE",
        predicted_change_at=None,
        prediction_source=None,
    ))
    assert out["model_signal_state"] == "NO_SIGNAL"
    assert out["eta"] is None
    assert out["eta_supported"] is False


def test_model_capability_field_failure_is_explicit_unavailable():
    out = decorate_predictor_observation(_row(
        evidence_state="FIELD_MISSING",
        predicted_change_cycle="NONE",
        predicted_change_at=None,
        prediction_source=None,
    ))
    assert out["model_signal_state"] == "UNAVAILABLE"
    assert out["current_claim_allowed"] is False
    assert out["eta"] is None
