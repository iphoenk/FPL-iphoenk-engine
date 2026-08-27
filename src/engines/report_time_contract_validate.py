from __future__ import annotations

import json

from src.engines.report_time_intelligence import validate_registry
from src.utils import DATA, ROOT, read_json


def run() -> dict:
    machine_registry = read_json(ROOT / "config" / "sources" / "registry.json", {})
    report_registry = read_json(ROOT / "config" / "sources" / "report_time_registry.json", {})
    output = read_json(DATA / "report_time_intelligence.json", {})
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

    result = {
        "status": "PASS",
        "registry": health,
        "onefpl_machine_enabled": machine["onefpl"].get("enabled"),
        "onefpl_report_time_enabled": report["onefpl"].get("enabled"),
        "report_time_status": output.get("status"),
        "web_refresh_required": output.get("web_refresh_required", False),
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
