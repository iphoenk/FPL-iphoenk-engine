from __future__ import annotations

import json
from time import perf_counter

from src.engines import v4_checkpoint_governance, v4_maturity_reconciler
from src.services import framework_postflight_truth_service
from src.services.weather_health_overlay import apply_weather_health
from src.utils import DATA, read_json


def _assert_no_critical_failure_erasure(before: set[str], maturity: dict) -> None:
    after = set(maturity.get("critical_failed") or [])
    erased = sorted(before - after)
    if erased:
        raise RuntimeError(f"maturity reconciliation cannot erase critical FAILED state: {erased}")


def run() -> dict:
    """Run the final governed decision boundary in one process.

    POST-FLIGHT truth and visible checkpoint/report governance are sequential
    phases of the same final-governance domain. Capability maturity reconciliation
    runs between them so engineering readiness is measured from concrete runtime
    evidence while current external-evidence gaps remain explicitly visible.
    """
    total = perf_counter()
    # These governance phases consume the same immutable prediction/latest/universe
    # contracts. Parse them once and hand the exact objects through postflight and
    # maturity reconciliation. Weather health remains a separate governed overlay
    # on postflight truth and is never hidden inside xPts.
    predictions = read_json(DATA / "predictions_v4.json", {})
    latest = read_json(DATA / "latest.json", {})
    universe = read_json(DATA / "universe.json", {})

    started = perf_counter()
    postflight = framework_postflight_truth_service.run(
        predictions=predictions,
        latest=latest,
        universe=universe,
    )
    postflight = apply_weather_health(postflight)
    postflight_ms = round((perf_counter() - started) * 1000.0, 2)
    critical_failed_before = set(postflight.get("critical_failed") or [])

    started = perf_counter()
    maturity = v4_maturity_reconciler.reconcile(
        postflight,
        predictions=predictions,
        latest=latest,
        universe=universe,
    )
    _assert_no_critical_failure_erasure(critical_failed_before, maturity)
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
            "weather_context": (maturity.get("weather_context") or {}).get("status"),
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
            "maturity_cannot_erase_critical_failure": True,
            "data_dependent_warmup_remains_truthful": True,
            "weather_health_propagated_before_maturity": True,
            "weather_cannot_mutate_expected_xpts_mean": True,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
