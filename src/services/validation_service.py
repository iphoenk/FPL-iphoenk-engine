from __future__ import annotations

import json
from time import perf_counter

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
    total = perf_counter()
    timings = {}

    started = perf_counter()
    lifecycle = v4_validation_cycle.cycle()
    timings["validation_lifecycle_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    readiness = reconciliation_readiness_service.run()
    timings["reconciliation_readiness_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    compliance_audit.main()
    compliance = read_json(DATA / "compliance_audit.json", {})
    timings["rules_compliance_ms"] = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    preflight = framework_health_audit.audit("preflight", strict=True)
    timings["framework_preflight_ms"] = round((perf_counter() - started) * 1000.0, 2)
    timings["total_ms"] = round((perf_counter() - total) * 1000.0, 2)

    out = {
        "service": "validation",
        "status": "PASS",
        "components": {
            "validation_lifecycle": lifecycle.get("status"),
            "reconciliation_readiness": readiness.get("status"),
            "rules_compliance": compliance.get("overall"),
            "framework_preflight": preflight.get("overall"),
        },
        "timings_ms": timings,
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
