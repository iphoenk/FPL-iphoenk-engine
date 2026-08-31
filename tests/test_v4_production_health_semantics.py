from src.services.governance_service import _production_operational_health


def _health(**overrides):
    health = {
        "overall": "GREEN",
        "pipeline_health": "GREEN",
        "gate0": {"counts": {"PASS": 16, "FAIL": 0}},
        "critical_failed": [],
        "critical_partial": [],
        "critical_warmup": ["DSS-44", "DSS-X12"],
        "prediction_health": "AMBER",
        "capability_health": "AMBER",
        "decision_engine": "PROVISIONAL",
        "go_allowed": False,
    }
    health.update(overrides)
    return health


def _readiness(**overrides):
    readiness = {
        "status": "PASS",
        "stage": "PREDEADLINE_READY",
        "pending": ["gw_finish", "post_gw_reconciliation"],
        "blockers": [],
    }
    readiness.update(overrides)
    return readiness


def test_expected_calibration_warmup_can_be_operationally_green_without_fake_maturity():
    health = _health()
    out = _production_operational_health(health, _readiness())

    assert out["status"] == "GREEN"
    assert out["operationally_ready"] is True
    assert out["maturity_state"] == "WARMUP"
    assert out["expected_lifecycle_warmup"] is True
    assert health["prediction_health"] == "AMBER"
    assert health["decision_engine"] == "PROVISIONAL"
    assert health["go_allowed"] is False
    assert out["guardrails"]["does_not_promote_warmup_modules"] is True


def test_unexpected_critical_warmup_cannot_be_reported_green():
    out = _production_operational_health(
        _health(critical_warmup=["DSS-44", "DSS-X12", "DSS-99"]),
        _readiness(),
    )
    assert out["status"] == "AMBER"
    assert "UNEXPECTED_CRITICAL_WARMUP" in out["hard_blockers"]


def test_readiness_blocker_prevents_operational_green():
    out = _production_operational_health(
        _health(),
        _readiness(blockers=["RECONCILIATION_INTEGRITY"], pending=[]),
    )
    assert out["status"] == "AMBER"
    assert "UNEXPECTED_CRITICAL_WARMUP" in out["hard_blockers"]


def test_critical_failure_remains_red_fail_closed():
    out = _production_operational_health(
        _health(critical_failed=["DSS-01"], critical_warmup=[]),
        _readiness(),
    )
    assert out["status"] == "RED"
    assert out["operationally_ready"] is False
    assert "CRITICAL_CAPABILITY_FAILED" in out["hard_blockers"]


def test_gate0_failure_remains_red_fail_closed():
    out = _production_operational_health(
        _health(gate0={"counts": {"PASS": 15, "FAIL": 1}}, critical_warmup=[]),
        _readiness(),
    )
    assert out["status"] == "RED"
    assert "GATE0_FAILURE" in out["hard_blockers"]
