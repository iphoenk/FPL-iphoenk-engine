from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.governance.gate0 import audit as gate0_audit

ENH = "config/enhancement_layers_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enhancement_registry() -> list[dict[str, Any]]:
    data = load_json_config(ENH)
    rows = data.get("layers")
    if not isinstance(rows, list):
        raise RuntimeError("invalid enhancement layer registry")
    return rows


def _integrity(rows: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    return {
        "expected": expected,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "integrity_ok": len(rows) == expected and not duplicates,
    }


def _capability_sources(
    truth: dict[str, Any],
    prediction: dict[str, Any],
    price: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
    gate: dict[str, Any],
) -> dict[str, list[str]]:
    sources: dict[str, list[str]] = {}
    for service_name, payload in (
        ("truth", truth),
        ("prediction", prediction),
        ("price", price),
        ("decision", decision),
        ("evaluation", evaluation),
    ):
        for capability in payload.get("capabilities") or []:
            sources.setdefault(str(capability), []).append(service_name)

    prediction_caps = set(str(x) for x in prediction.get("capabilities") or [])
    decision_caps = set(str(x) for x in decision.get("capabilities") or [])
    evaluation_caps = set(str(x) for x in evaluation.get("capabilities") or [])
    if (
        "projection_uncertainty" in prediction_caps
        and "lineup_robustness" in decision_caps
        and "calibration_store" in evaluation_caps
    ):
        sources.setdefault("uncertainty_robustness", []).append("governance-derived")

    trace = decision.get("decision_trace") if isinstance(decision.get("decision_trace"), dict) else {}
    trace_complete = bool(
        trace.get("decision_type")
        and trace.get("evidence")
        and trace.get("constraints_checked")
        and trace.get("ruleset_id")
        and trace.get("projection_model")
    )
    if bool(gate.get("pass")) and trace_complete and decision.get("production_recommendation") is None:
        sources.setdefault("final_governance", []).append("governance")

    return {key: sorted(set(values)) for key, values in sources.items()}


def _audit_enhancements(capability_sources: dict[str, list[str]]) -> dict[str, Any]:
    rows = _enhancement_registry()
    items = []
    for row in rows:
        probe = str(row.get("operational_probe") or "")
        active = bool(probe and capability_sources.get(probe))
        items.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "critical": bool(row.get("critical")),
                "probe": probe,
                "status": "ACTIVE" if active else "PARTIAL",
                "evidence_services": capability_sources.get(probe, []),
                "detail": (
                    "capability contract satisfied"
                    if active
                    else "enhancement capability not yet fully backed by native V5 evidence"
                ),
            }
        )
    counts = Counter(item["status"] for item in items)
    return {**_integrity(rows, 8), "counts": dict(counts), "items": items}


def _decision_dss(decision: dict[str, Any], section: str, expected: int) -> dict[str, Any]:
    dss = decision.get("dss") if isinstance(decision.get("dss"), dict) else {}
    block = dss.get(section) if isinstance(dss.get(section), dict) else {}
    items = block.get("items") if isinstance(block.get("items"), list) else []
    return {
        **block,
        "expected": int(block.get("expected") or expected),
        "declared": int(block.get("declared") or len(items)),
        "integrity_ok": bool(block.get("integrity_ok")) and len(items) == expected,
        "items": items,
    }


def build_health(
    truth: dict[str, Any],
    prediction: dict[str, Any],
    price: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    gate = gate0_audit(truth, decision)
    core = _decision_dss(decision, "core", 50)
    extensions = _decision_dss(decision, "extensions", 16)
    capability_sources = _capability_sources(truth, prediction, price, decision, evaluation, gate)
    enhancements = _audit_enhancements(capability_sources)

    registry_integrity = bool(
        gate.get("registry_integrity", {}).get("integrity_ok")
        and core.get("integrity_ok")
        and extensions.get("integrity_ok")
        and enhancements.get("integrity_ok")
    )
    groups = (core, extensions, enhancements)
    critical_partial = [
        item
        for group in groups
        for item in group.get("items", [])
        if bool(item.get("critical")) and item.get("status") != "ACTIVE"
    ]
    gate_failures = [item for item in gate.get("items", []) if item.get("status") == "FAIL"]
    decision_ready = decision.get("status") == "READY"
    recommendation_allowed = bool(gate.get("pass") and registry_integrity and decision_ready)
    go_allowed = bool(recommendation_allowed and not critical_partial)
    overall = "RED" if not recommendation_allowed else ("GREEN" if go_allowed else "AMBER")

    return {
        "framework_schema": 6,
        "generated_at": _now(),
        "auditor": "v5-microservice-governance-v2",
        "overall": overall,
        "decision_engine": "HEALTHY" if go_allowed else ("DEGRADED" if recommendation_allowed else "BLOCKED"),
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "registry_integrity": registry_integrity,
        "rules_registry": {
            "status": "PASS" if truth.get("rules") else "FAIL",
            "detail": {
                "ruleset_id": (truth.get("rules") or {}).get("ruleset_id"),
                "authority": (truth.get("rules") or {}).get("authority"),
            },
        },
        "gate0": gate,
        "dss_core": core,
        "dss_extensions": extensions,
        "enhancements": enhancements,
        "capability_sources": capability_sources,
        "gate0_failures": gate_failures,
        "critical_partial": critical_partial,
        "governance": {
            "gate0_full_16_required": True,
            "gate0_fail_blocks_go": True,
            "dss_authority": "decision-service",
            "enhancement_authority": "governance-service",
            "dss_core_count_immutable": 50,
            "dss_extension_count_immutable": 16,
            "enhancement_count_immutable": 8,
            "service_boundary_enforced": True,
            "production_auto_submit": False,
        },
    }
