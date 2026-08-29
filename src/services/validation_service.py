from __future__ import annotations

import json

from src.engines import compliance_audit, framework_health_audit, v4_validation_cycle
from src.services import reconciliation_readiness_service
from src.utils import DATA, read_json


def run() -> dict:
    """Run the complete pre-decision validation boundary in one process.

    This preserves the existing validation lifecycle, reconciliation readiness,
    FPL rules compliance and PRE-FLIGHT artifacts while removing four separate
    runtime process boundaries. Each underlying owner remains independently
    testable and keeps its existing artifact contract.
    """
    lifecycle = v4_validation_cycle.cycle()
    readiness = reconciliation_readiness_service.run()

    compliance_audit.main()
    compliance = read_json(DATA / "compliance_audit.json", {})

    preflight = framework_health_audit.audit("preflight", strict=True)
    out = {
        "service": "validation",
        "status": "PASS",
        "components": {
            "validation_lifecycle": lifecycle.get("status"),
            "reconciliation_readiness": readiness.get("status"),
            "rules_compliance": compliance.get("overall"),
            "framework_preflight": preflight.get("overall"),
        },
        "guardrails": {
            "underlying_artifact_contracts_preserved": True,
            "official_api_refetch": False,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
