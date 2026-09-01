from __future__ import annotations

import json
from collections import Counter
from time import perf_counter

from src import utils as runtime_utils
from src.engines import v4_checkpoint_governance, v4_maturity_reconciler
from src.engines.v4_challenger_serving_composition import compose as compose_challenger_serving
from src.services import framework_postflight_truth_service
from src.services.weather_health_overlay import apply_weather_health
from src.utils import DATA, atomic_json, read_json

_EXPECTED_LIFECYCLE_WARMUP = {"DSS-44", "DSS-X12"}


def _assert_no_critical_failure_erasure(before: set[str], maturity: dict) -> None:
    after = set(maturity.get("critical_failed") or [])
    erased = sorted(before - after)
    if erased:
        raise RuntimeError(f"maturity reconciliation cannot erase critical FAILED state: {erased}")


def _publication_integrity_state() -> dict:
    """Read the publication sidecar when present without coupling earlier governance phases to it."""
    try:
        payload = read_json(DATA / "publication_integrity_v4.json", {})
    except (KeyError, FileNotFoundError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _expected_warmup_only(maturity: dict, readiness: dict) -> bool:
    critical_warmup = sorted(set(maturity.get("critical_warmup") or []))
    return (
        bool(critical_warmup)
        and set(critical_warmup).issubset(_EXPECTED_LIFECYCLE_WARMUP)
        and readiness.get("status") == "PASS"
        and not list(readiness.get("blockers") or [])
        and bool(list(readiness.get("pending") or []))
    )


def _normalize_health_maturity_semantics(maturity: dict, readiness: dict) -> dict:
    """Separate runtime health from data-dependent maturity without false-green.

    Expected calibration WARMUP is not a runtime defect. The modules remain WARMUP,
    the decision engine remains PROVISIONAL, and unqualified GO stays blocked until
    calibration is genuinely mature.
    """
    critical_failed = sorted(set(maturity.get("critical_failed") or []))
    critical_partial = sorted(set(maturity.get("critical_partial") or []))
    critical_warmup = sorted(set(maturity.get("critical_warmup") or []))
    expected_warmup = _expected_warmup_only(maturity, readiness)

    if critical_failed:
        prediction_health, decision_engine = "RED", "BLOCKED"
    elif critical_partial:
        prediction_health, decision_engine = "AMBER", "DEGRADED"
    elif critical_warmup:
        prediction_health = "GREEN" if expected_warmup else "AMBER"
        decision_engine = "PROVISIONAL"
    else:
        prediction_health, decision_engine = "GREEN", "HEALTHY"

    coverage = maturity.get("capability_coverage") or {}
    failed_count = int(coverage.get("failed") or 0)
    partial_count = int(coverage.get("partial") or 0)
    warmup_count = int(coverage.get("warmup") or 0)
    capability_health = "RED" if failed_count else "AMBER" if partial_count else "GREEN"
    capability_maturity = "WARMUP" if warmup_count or critical_warmup else "MATURE"

    gate0 = maturity.get("gate0") or {}
    gate0_counts = gate0.get("counts") or {}
    gate0_pass = gate0.get("pass") is True or (
        int(gate0_counts.get("PASS") or 0) == 16 and int(gate0_counts.get("FAIL") or 0) == 0
    )
    postflight_complete = int(gate0_counts.get("DEFERRED") or 0) == 0

    maturity["prediction_health"] = prediction_health
    maturity["capability_health"] = capability_health
    maturity["capability_maturity"] = capability_maturity
    maturity["decision_engine"] = decision_engine
    maturity["go_allowed"] = (
        maturity.get("pipeline_health") == "GREEN"
        and prediction_health == "GREEN"
        and decision_engine == "HEALTHY"
        and gate0_pass
        and postflight_complete
    )
    maturity.setdefault("governance", {}).update({
        "operational_health_separate_from_capability_maturity": True,
        "expected_warmup_does_not_degrade_operational_prediction_health": True,
        "warmup_never_promoted_to_active": True,
        "provisional_engine_blocks_unqualified_go": True,
    })
    return maturity


def _align_prediction_telemetry_maturity(maturity: dict) -> dict:
    telemetry = maturity.get("capability_telemetry") or {}
    capabilities = telemetry.get("capabilities") or {}
    prediction = capabilities.get("Prediction")
    if isinstance(prediction, dict):
        health = str(maturity.get("prediction_health") or "").upper()
        engine = str(maturity.get("decision_engine") or "").upper()
        if health == "RED":
            state = "BLOCKED"
        elif health == "AMBER":
            state = "DEGRADED"
        elif engine == "PROVISIONAL":
            state = "WARMUP"
        else:
            state = "ACTIVE"
        prediction["state"] = state
        evidence = prediction.setdefault("evidence", {})
        evidence["prediction_health"] = maturity.get("prediction_health")
        evidence["decision_engine"] = maturity.get("decision_engine")
        evidence["maturity_state"] = maturity.get("capability_maturity")
    if capabilities:
        telemetry["summary"] = dict(Counter(
            row.get("state") for row in capabilities.values() if isinstance(row, dict)
        ))
        maturity["capability_telemetry"] = telemetry
    return maturity


def _production_operational_health(maturity: dict, readiness: dict) -> dict:
    """Separate deploy/runtime health from evidence maturity without hiding either."""
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
            "operational_health_is_separate_from_maturity": True,
            "provisional_engine_blocks_unqualified_go": True,
            "critical_failure_remains_fail_closed": True,
        },
    }


def run(*, predictions_snapshot: dict | None = None) -> dict:
    """Run the final governed decision boundary in one process."""
    total = perf_counter()
    predictions_preloaded = predictions_snapshot is not None
    predictions = predictions_snapshot if predictions_preloaded else read_json(DATA / "predictions_v4.json", {})
    latest = read_json(DATA / "latest.json", {})
    universe = read_json(DATA / "universe.json", {})
    try:
        lifecycle = read_json(DATA / "validation" / "lifecycle_v4.json", {})
    except (KeyError, FileNotFoundError):
        lifecycle = {}
    validation_eligibility = lifecycle.get("eligibility") or {}

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
        validation_eligibility=validation_eligibility,
        persist=False,
    )
    _assert_no_critical_failure_erasure(critical_failed_before, maturity)

    readiness = runtime_utils.read_json(DATA / "validation" / "reconciliation_readiness_v4.json", {})
    maturity = _normalize_health_maturity_semantics(maturity, readiness)

    maturity["capability_telemetry"] = framework_postflight_truth_service._canonical_capability_telemetry(
        maturity,
        latest,
        predictions,
        universe,
    )
    maturity = _align_prediction_telemetry_maturity(maturity)
    maturity = apply_weather_health(maturity, write=False)

    production_health = _production_operational_health(maturity, readiness)
    maturity["production_health"] = production_health["status"]
    maturity["production_operational_health"] = production_health
    maturity.setdefault("governance", {}).update({
        "production_health_separate_from_model_maturity": True,
        "expected_lifecycle_warmup_is_not_operational_failure": True,
        "warmup_modules_remain_unpromoted": True,
        "capability_telemetry_refreshed_after_maturity": True,
        "prediction_telemetry_preserves_provisional_as_warmup": True,
        "weather_overlay_applied_after_telemetry_refresh": True,
    })
    atomic_json(DATA / "framework_health_v4.json", maturity)
    maturity_ms = round((perf_counter() - started) * 1000.0, 2)

    started = perf_counter()
    try:
        checkpoint = v4_checkpoint_governance.run()
    except RuntimeError:
        integrity = _publication_integrity_state()
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

    if (DATA / "owned_challenger_decision_v4.json").exists() and (DATA / "serving_payload_v4.json").exists():
        challenger_serving = compose_challenger_serving()
    else:
        challenger_serving = {"status": "NOT_MATERIALIZED"}

    integrity = _publication_integrity_state()
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
            "prediction_health": maturity.get("prediction_health"),
            "capability_health": maturity.get("capability_health"),
            "capability_maturity": maturity.get("capability_maturity"),
            "decision_engine": maturity.get("decision_engine"),
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
            "operational_health_separate_from_maturity": True,
            "provisional_engine_blocks_unqualified_go": True,
            "capability_telemetry_refreshed_after_maturity": True,
            "weather_health_propagated_after_maturity": True,
            "weather_cannot_mutate_expected_xpts_mean": True,
            "production_health_does_not_promote_model_maturity": True,
            "prediction_handoff_optional_and_file_fallback_preserved": True,
            "predictions_received_preloaded": predictions_preloaded,
            "validation_integrity_proof_passed_to_maturity": True,
            "fail_closed": True,
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
