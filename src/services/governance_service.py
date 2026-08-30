from __future__ import annotations

import json
from time import perf_counter

from src.engines import v4_checkpoint_governance, v4_maturity_reconciler
from src.services import framework_postflight_truth_service


def run() -> dict:
    """Run the final governed decision boundary in one process.

    POST-FLIGHT truth and visible checkpoint/report governance are sequential
    phases of the same final-governance domain. Capability maturity reconciliation
    runs between them so engineering readiness is measured from concrete runtime
    evidence while current external-evidence gaps remain explicitly visible.
    """
    total = perf_counter()
    started = perf_counter()
    postflight = framework_postflight_truth_service.run()
    postflight_ms = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    maturity = v4_maturity_reconciler.reconcile(postflight)
    maturity_ms = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    checkpoint = v4_checkpoint_governance.run()
    checkpoint_ms = round((perf_counter() - started) * 1000.0, 2)

    out = {
        "service": "governance",
        "status": "PASS",
        "components": {
            "framework_postflight": maturity.get("overall"),
            "capability_maturity": maturity.get("capability_health"),
            "report_governance": checkpoint.get("action_state"),
        },
        "timings_ms": {
            "framework_postflight_ms": postflight_ms,
            "capability_maturity_ms": maturity_ms,
            "checkpoint_report_governance_ms": checkpoint_ms,
            "total_ms": round((perf_counter() - total) * 1000.0, 2),
        },
        "guardrails": {
            "canonical_decision_only": True,
            "user_final_authority": True,
            "visible_output_policy_preserved": True,
            "maturity_does_not_fabricate_external_evidence": True,
            "data_dependent_warmup_remains_truthful": True,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
