from __future__ import annotations

import json

from src.engines.report_time_intelligence import validate_registry
from src.utils import DATA, ROOT, read_json


def run() -> dict:
    machine_registry = read_json(ROOT / "config" / "sources" / "registry.json", {})
    report_registry = read_json(ROOT / "config" / "sources" / "report_time_registry.json", {})
    technical = read_json(DATA / "technical_appendix.json", {})
    output = technical.get("report_time_intelligence") or {}
    user = read_json(DATA / "user_report.json", {})

    machine = {row.get("id"): row for row in machine_registry.get("sources") or []}
    report = {row.get("id"): row for row in report_registry.get("sources") or []}
    health = validate_registry(report_registry)

    assert health.get("integrity_ok") is True, health
    assert machine["onefpl"].get("enabled") is False
    assert machine["onefpl"].get("delegated_to") == "REPORT_TIME_SOURCE_REGISTRY_V1"
    assert report["onefpl"].get("enabled") is True
    assert report["onefpl"].get("retrieval") == "REPORT_TIME_WEB"
    assert report["ben_crellin"].get("class") == "FIXTURE_STRATEGY_EXPERT"
    assert report["ben_crellin"].get("consensus_vote") is False
    assert report["reddit_fantasypl"].get("class") == "COMMUNITY_SIGNAL"
    assert report["reddit_fantasypl"].get("consensus_vote") is False

    assert output.get("status") in {"REFRESH_REQUIRED", "READY", "INVALID_EVIDENCE_CONTRACT"}
    policy = output.get("policy") or {}
    assert policy.get("dss_is_not_mutated") is True
    assert policy.get("report_time_evidence_is_advisory") is True
    if output.get("status") == "REFRESH_REQUIRED":
        assert output.get("web_refresh_required") is True

    block = user.get("report_time_intelligence") or {}
    assert block.get("status") == output.get("status")
    assert "pundit_consensus_vs_dss" in block
    assert "fixture_strategy" in block
    assert "community_signal" in block

    readiness = user.get("readiness") or {}
    assert readiness.get("engine") in {"ENGINE_READY", "ENGINE_REVIEW_REQUIRED"}
    assert readiness.get("final_report_evidence") in {
        "FINAL_REPORT_EVIDENCE_READY",
        "FINAL_REPORT_EVIDENCE_PENDING",
    }
    if output.get("status") == "READY":
        assert readiness.get("final_report_evidence") == "FINAL_REPORT_EVIDENCE_READY"
    else:
        assert readiness.get("final_report_evidence") == "FINAL_REPORT_EVIDENCE_PENDING"

    validation = readiness.get("predictive_validation") or {}
    assert validation.get("model_derived_actionability") in {"ACTIVE", "GATED"}
    model_active = validation.get("model_derived_actionability") == "ACTIVE"
    action_rows = user.get("action_board") or []
    assert action_rows
    for row in action_rows:
        action_class = row.get("action_class")
        assert action_class in {"FACT_CONSTRAINT", "MODEL_DERIVED"}
        if action_class == "FACT_CONSTRAINT":
            assert row.get("actionability") == "ACTIONABLE"
            assert row.get("calibration_gate_applies") is False
        else:
            expected = "ACTIONABLE" if model_active else "ADVISORY_UNTIL_SETTLED_VALIDATION"
            assert row.get("actionability") == expected
            assert row.get("calibration_gate_applies") is True

    governance = technical.get("readiness_and_actionability") or {}
    gov_policy = governance.get("policy") or {}
    assert gov_policy.get("runtime_readiness_is_separate_from_final_report_evidence") is True
    assert gov_policy.get("fact_constraint_actionability_is_not_blocked_by_model_sample_size") is True
    assert gov_policy.get("model_derived_actionability_requires_prediction_evaluation_eligibility") is True
    assert gov_policy.get("existing_decisions_are_annotated_not_rewritten") is True

    result = {
        "status": "PASS",
        "registry": health,
        "onefpl_machine_enabled": machine["onefpl"].get("enabled"),
        "onefpl_report_time_enabled": report["onefpl"].get("enabled"),
        "report_time_status": output.get("status"),
        "web_refresh_required": output.get("web_refresh_required", False),
        "engine_readiness": readiness.get("engine"),
        "final_report_evidence": readiness.get("final_report_evidence"),
        "model_derived_actionability": validation.get("model_derived_actionability"),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
