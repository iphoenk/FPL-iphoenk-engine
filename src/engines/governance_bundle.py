from __future__ import annotations

"""FAST/LIVE governance bundle.

Runs the existing governance stages in-process so the logical `governance`
service keeps exactly the same artifact ownership and ordering without paying
seven extra Python interpreter startups. FULL/DEEP continue to use the
unbundled service registry commands as the conservative acceptance path.
"""

import json

from src.engines import decision_quality_overlay
from src.engines import dss_evidence_maturity
from src.engines import dss_operationalization_overlay
from src.engines import framework_health_service
from src.engines import lineup_framework_health_overlay
from src.engines import p0_framework_health_overlay
from src.engines import source_framework_overlay
from src.engines import framework_health_audit as audit_engine


def run() -> dict:
    expected = framework_health_service.activate_registry_contract()
    framework_health_service.activate_freshness_contract()

    audit_engine.audit("preflight", strict=True)
    framework_health_service._publish_gate0_registry_contract(expected)
    audit_engine.audit("postflight", strict=True)
    framework_health_service._publish_gate0_registry_contract(expected)

    p0_framework_health_overlay.run()
    lineup_framework_health_overlay.run()
    decision_quality_overlay.run()
    source_framework_overlay.run()
    dss_operationalization_overlay.run(strict=True)
    evidence = dss_evidence_maturity.run()
    return evidence


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": "PASS",
        "bundle": "governance",
        "evidence_maturity": out.get("evidence_maturity"),
    }, ensure_ascii=False))
