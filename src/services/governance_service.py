from __future__ import annotations

import json
from time import perf_counter

from src import utils as runtime_utils
from src.engines import v4_checkpoint_governance, v4_maturity_reconciler
from src.services import framework_postflight_truth_service
from src.services.weather_health_overlay import apply_weather_health
from src.utils import DATA, atomic_json, read_json

_EXPECTED_LIFECYCLE_WARMUP = {"DSS-44", "DSS-X12"}


def _assert_no_critical_failure_erasure(before: set[str], maturity: dict) -> None:
    after = set(maturity.get("critical_failed") or [])
    erased = sorted(before - after)
    if erased:
        raise RuntimeError(f"maturity reconciliation cannot erase critical FAILED state: {erased}")


def _production_operational_health(maturity: dict, readiness: dict) -> dict:
    """Separate deploy/runtime health from evidence maturity without hiding either.

    A pre-deadline calibration warmup is an expected lifecycle state, not an
    operational production failure. It remains visible through capability_health,
    prediction_health, decision_engine and go_allowed. Production health may be
    GREEN only when the runtime pipeline is healthy, Gate0 has no failures,
    there are no critical FAILED/PARTIAL capabilities, and every critical WARMUP
    is one of the governed calibration modules with reconciliation readiness
    explicitly PASS and pending future evidence rather than a blocker.
    """
    pipeline_green = maturity.get("pipeline_health") == "GREEN" and maturity.get("overall") == "GREEN"
    gate0_counts = ((maturity.get("gate0") or {}).get("counts") or {})
    gate0_failures = int(gate0_counts.get("FAIL", 0) or 0)
    critical_failed = sorted(set(maturity.get("critical_failed") or []))
    critical_partial = sorted(set(maturity.get("critical_partial") or []))
    critical_warmup = sorted(set(maturity.get("critical_warmup") or []))

    readiness_pass = readiness.get("status") == "PASS"
    readiness_blockers = list(readiness.get("blockers") or [])
    pending = list(readiness.get("pending") or [])
    expected_warmup_only = (
        bool(critical_warmup)
        and set(critical_warmup).issubset(_EXPECTED_LIFECYCLE_WARMUP)
        and readiness_pass
        and not readiness_blockers
        and bool(pending)
    )
    no_warmup = not critical_warmup

    hard_blockers: list[str] = []
    if not pipeline_green:
        hard_blockers.append("PIPELINE_NOT_GREEN")
    if gate0_failures:
        hard_blockers.append("GATE0_FAILURE")
    if critical_failed:
        hard_blockers.append("CRITICAL_CAPABILITY_FAILED")
    if critical_partial:
        hard_blockers.append("CRITICAL_CAPABILITY_PARTIAL")
    if critical_warmup and not expected_warmup_only:
        hard_blockers.append("UNEXPECTED_CRITICAL_WARMUP")

    if critical_failed or gate0_failures:
        status = "RED"
    elif hard_blockers:
        status = "AMBER"
    elif no_warmup or expected_warmup_only:
        status = "GREEN"
    else:
        status = "AMBER"

    return {
        "status": status,
        "operationally_ready": status == "GREEN",
        "maturity_state": "WARMUP" if critical_warmup else "MATURE",
        "expected_lifecycle_warmup": expected_warmup_only,
        "critical_warmup": critical_warmup,
        "hard_blockers": hard_blockers,
        "reconciliation_readiness": {
            "status": readiness.get("status"),
            "stage": readiness.get("stage"),
            "pending": pending,
            "blockers": readiness_blockers,
        },
        "guardrails": {
            "does_not_promote_warmup_modules": True,
            "does_not_change_prediction_health": True,
            "does_not_change_decision_engine": True,
            "does_not_change_go_allowed": True,
            "critical_failure_remains_fail_closed": True,
        },
    }


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

    # Postflight telemetry is generated before capability maturity is reconciled.
    # Rebuild it from the reconciled capability states so ACTIVE DSS modules cannot
    # remain falsely reported as PARTIAL. Weather is then applied as the final
    # advisory evidence overlay and remains separate from xPts.
    maturity["capability_telemetry"] = framework_postflight_truth_service._canonical_capability_telemetry(
        maturity,
        latest,
        predictions,
        universe,
    )
    maturity = apply_weather_health(maturity, write=False)

    # Reconciliation readiness is a separate validation artifact, not part of the
    # immutable prediction-context read set reused above.
    readiness = runtime_utils.read_json(DATA / "validation" / "reconciliation_readiness_v4.json", {})
    production_health = _production_operational_health(maturity, readiness)
    maturity["production_health"] = production_health["status"]
    maturity["production_operational_health"] = production_health
    maturity.setdefault("governance", {}).update({
        "production_health_separate_from_model_maturity": True,
        "expected_lifecycle_warmup_is_not_operational_failure": True,
        "warmup_modules_remain_unpromoted": True,
        "capability_telemetry_refreshed_after_maturity": True,
        "weather_overlay_applied_after_telemetry_refresh": True,
    })
    atomic_json(DATA / "framework_health_v4.json", maturity)
    maturity_ms = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    try:
        checkpoint = v4_checkpoint_governance.run()
    except RuntimeError:
        integrity = read_json(DATA / "publication_integrity_v4.json", {})
        if integrity.get("status") == "BLOCKED":
            maturity["publication_integrity"] = integrity
            maturity["publication_integrity_health"] = "BLOCKED"
            maturity["reporting_health"] = "BLOCKED"
            maturity["serving_health"] = "BLOCKED"
            maturity["overall"] = "RED"
            maturity["production_health"] = "RED"
            operational = maturity.setdefault("production_operational_health", {})
            operational["status"] = "RED"
            operational["operationally_ready"] = False
            blockers = operational.setdefault("hard_blockers", [])
            if "PUBLICATION_INTEGRITY_BLOCKED" not in blockers:
                blockers.append("PUBLICATION_INTEGRITY_BLOCKED")
            atomic_json(DATA / "framework_health_v4.json", maturity)
        raise
    checkpoint_ms = round((perf_counter() - started) * 1000.0, 2)

    integrity = read_json(DATA / "publication_integrity_v4.json", {})
    if integrity:
        capabilities = integrity.get("capabilities") or {}
        maturity["publication_integrity"] = integrity
        maturity["publication_integrity_health"] = capabilities.get("publication_integrity") or integrity.get("status")
        maturity["reporting_health"] = capabilities.get("reporting") or "UNAVAILABLE"
        maturity["serving_health"] = capabilities.get("serving") or "UNAVAILABLE"
        maturity.setdefault("governance", {}).update({
            "publication_integrity_registered": True,
            "publication_failure_cannot_leave_visible_health_green": True,
        })
        if integrity.get("status") != "PASS":
            maturity["overall"] = "RED"
            maturity["production_health"] = "RED"
            operational = maturity.setdefault("production_operational_health", {})
            operational["status"] = "RED"
            operational["operationally_ready"] = False
            blockers = operational.setdefault("hard_blockers", [])
            if "PUBLICATION_INTEGRITY_BLOCKED" not in blockers:
                blockers.append("PUBLICATION_INTEGRITY_BLOCKED")
        atomic_json(DATA / "framework_health_v4.json", maturity)

    out = {
        "service": "governance",
        "status": "PASS",
        "components": {
            "framework_postflight": maturity.get("overall"),
            "production_health": maturity.get("production_health"),
            "capability_maturity": maturity.get("capability_health"),
            "weather_context": (maturity.get("weather_context") or {}).get("status"),
            "report_governance": checkpoint.get("action_state"),
            "publication_integrity": (integrity.get("capabilities") or {}).get("publication_integrity") or integrity.get("status") or "UNAVAILABLE",
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
            "capability_telemetry_refreshed_after_maturity": True,
            "weather_health_propagated_after_maturity": True,
            "weather_cannot_mutate_expected_xpts_mean": True,
            "production_health_does_not_promote_model_maturity": True,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
