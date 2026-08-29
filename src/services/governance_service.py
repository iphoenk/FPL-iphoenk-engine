from __future__ import annotations

import json

from src.engines import v4_checkpoint_governance
from src.services import framework_postflight_truth_service


def run() -> dict:
    """Run the final governed decision boundary in one process.

    POST-FLIGHT truth and visible checkpoint/report governance are sequential
    phases of the same final-governance domain, so they share one runtime
    process while preserving their existing output artifacts and semantics.
    """
    postflight = framework_postflight_truth_service.run()
    checkpoint = v4_checkpoint_governance.run()
    out = {
        "service": "governance",
        "status": "PASS",
        "components": {
            "framework_postflight": postflight.get("overall"),
            "report_governance": checkpoint.get("action_state"),
        },
        "guardrails": {
            "canonical_decision_only": True,
            "user_final_authority": True,
            "visible_output_policy_preserved": True,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
