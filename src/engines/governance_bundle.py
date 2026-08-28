from __future__ import annotations

"""FAST/LIVE governance bundle.

FAST/LIVE run one complete postflight audit after all governed inputs exist.
The legacy preflight+postflight pair is retained by FULL/DEEP as a conservative
reference path, but running a so-called preflight only after the complete final
DAG has already materialized is temporally redundant in FAST and duplicates the
same registry/probe work.

All P0, lineup, decision-quality, source, DSS operationalization and evidence
maturity overlays remain unchanged. Gate0 still must finish 16/16 before GO.
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
        "audit_phases": ["postflight"],
        "duplicate_late_preflight_removed": True,
        "evidence_maturity": out.get("evidence_maturity"),
    }, ensure_ascii=False))
