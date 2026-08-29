from src.runtime_v3.domain_orchestrator import _reuse_diagnostic_summary


def test_reuse_summary_prefers_pre_execution_decision_state():
    rows = {
        "prediction": {
            "status": "SUCCESS",
            "reuse_mode": None,
            "reuse_diagnostic_before": {
                "reason": "INPUT_FINGERPRINT_CHANGED",
                "current": "new",
                "stored": "old",
                "match": False,
            },
        }
    }
    out = _reuse_diagnostic_summary("prediction", rows, "fast_decision")
    assert out["reason"] == "INPUT_FINGERPRINT_CHANGED"
    assert out["match"] is False
    assert out["decision_time"] is True
    assert out["execution_status"] == "SUCCESS"
    assert out["reuse_mode"] is None


def test_reuse_summary_exposes_actual_content_addressed_reuse():
    rows = {
        "prediction": {
            "status": "REUSED",
            "reuse_mode": "CONTENT_ADDRESSED",
            "reuse_diagnostic_before": {
                "reason": "MATCH",
                "current": "same",
                "stored": "same",
                "match": True,
            },
        }
    }
    out = _reuse_diagnostic_summary("prediction", rows, "fast_decision")
    assert out["reason"] == "MATCH"
    assert out["match"] is True
    assert out["decision_time"] is True
    assert out["execution_status"] == "REUSED"
    assert out["reuse_mode"] == "CONTENT_ADDRESSED"
