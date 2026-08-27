import json

from src.engines import dss_evidence_maturity as em


def _policy():
    return {
        "evidence_maturity": {
            "tiers": ["NATIVE", "DERIVED", "PROXY", "SAFE_FALLBACK", "UNAVAILABLE"],
            "evaluator_available_tier": {
                "fixture_schedule": "NATIVE",
                "projection_rates": "DERIVED",
                "projection_role_proxy": "PROXY",
            },
            "state_overrides": {
                "AVAILABLE_PROXY": "PROXY",
                "UNAVAILABLE_WITH_SAFE_FALLBACK": "SAFE_FALLBACK",
                "ARMED_NO_SETTLED_SAMPLE": "SAFE_FALLBACK",
                "INSUFFICIENT": "UNAVAILABLE",
            },
        }
    }


def test_evidence_tier_is_independent_from_active_module_health():
    policy = _policy()
    assert em.classify_evidence_tier(
        {"evaluator": "projection_role_proxy", "evidence_state": "AVAILABLE_PROXY"},
        "ACTIVE",
        policy,
    ) == "PROXY"
    assert em.classify_evidence_tier(
        {"evaluator": "projection_rates", "evidence_state": "UNAVAILABLE_WITH_SAFE_FALLBACK"},
        "ACTIVE",
        policy,
    ) == "SAFE_FALLBACK"
    assert em.classify_evidence_tier(
        {"evaluator": "fixture_schedule", "evidence_state": "AVAILABLE"},
        "ACTIVE",
        policy,
    ) == "NATIVE"


def test_unresolved_module_is_unavailable_regardless_of_evaluator():
    assert em.classify_evidence_tier(
        {"evaluator": "fixture_schedule", "evidence_state": "AVAILABLE"},
        "UNRESOLVED",
        _policy(),
    ) == "UNAVAILABLE"


def test_maturity_overlay_preserves_module_status_and_adds_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(em, "DATA", tmp_path)
    monkeypatch.setattr(em, "EVIDENCE_PATH", tmp_path / "dss_operational_evidence.json")
    monkeypatch.setattr(em, "HEALTH_PATH", tmp_path / "framework_health.json")
    monkeypatch.setattr(em, "_policy", _policy)

    evidence = {
        "evaluated": [
            {"id": 1, "status": "ACTIVE", "detail": {"evaluator": "fixture_schedule", "evidence_state": "AVAILABLE"}},
            {"id": 2, "status": "ACTIVE", "detail": {"evaluator": "projection_role_proxy", "evidence_state": "AVAILABLE_PROXY"}},
            {"id": 3, "status": "ACTIVE", "detail": {"evaluator": "projection_rates", "evidence_state": "UNAVAILABLE_WITH_SAFE_FALLBACK"}},
            {"id": 4, "status": "UNRESOLVED", "detail": {"evaluator": "fixture_schedule", "evidence_state": "INSUFFICIENT"}},
        ]
    }
    (tmp_path / "dss_operational_evidence.json").write_text(json.dumps(evidence))
    (tmp_path / "framework_health.json").write_text(json.dumps({"overall": "GREEN"}))
    (tmp_path / "latest.json").write_text(json.dumps({}))

    result = em.run()
    rows = result["evaluated"]
    assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE", "ACTIVE", "UNRESOLVED"]
    assert [row["evidence_tier"] for row in rows] == ["NATIVE", "PROXY", "SAFE_FALLBACK", "UNAVAILABLE"]
    assert result["evidence_maturity"]["counts"] == {
        "NATIVE": 1,
        "DERIVED": 0,
        "PROXY": 1,
        "SAFE_FALLBACK": 1,
        "UNAVAILABLE": 1,
    }
