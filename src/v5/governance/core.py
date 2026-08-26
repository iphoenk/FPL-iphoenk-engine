from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.governance.gate0 import audit as gate0_audit

ENH = "config/enhancement_layers_registry.json"
DSS_POLICY = "config/v5_dss_policy_registry.json"
GATE_REGISTRY = "config/gate0_registry.json"
GATE_POLICY = "config/v5_gate0_policy_registry.json"
SERVICE_REGISTRY = "config/v5_service_registry.json"
DEGRADED_POLICY = "config/v5_degraded_mode_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expected_ids(contract: dict[str, Any]) -> set[str]:
    expected = int(contract["expected_count"])
    first = int(contract.get("first_index", 1))
    prefix = str(contract["id_prefix"])
    zero_pad = int(contract.get("zero_pad", 0))
    return {
        f"{prefix}{index:0{zero_pad}d}" if zero_pad else f"{prefix}{index}"
        for index in range(first, first + expected)
    }


def _integrity(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    expected_ids = _expected_ids(contract)
    declared_ids = set(ids)
    expected = int(contract["expected_count"])
    return {
        "expected": expected,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "missing_ids": sorted(expected_ids - declared_ids),
        "unexpected_ids": sorted(declared_ids - expected_ids),
        "integrity_ok": len(rows) == expected and not duplicates and declared_ids == expected_ids,
    }


def _enhancement_registry() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data = load_json_config(ENH)
    rows = data.get("layers")
    contract = data.get("contract")
    if not isinstance(rows, list) or not isinstance(contract, dict):
        raise RuntimeError("invalid enhancement layer registry")
    return rows, contract


def _dss_policy() -> dict[str, Any]:
    data = load_json_config(DSS_POLICY)
    if not isinstance(data.get("registries"), dict):
        raise RuntimeError("invalid DSS governance policy registry")
    return data


def _gate_contract() -> dict[str, Any]:
    data = load_json_config(GATE_REGISTRY)
    contract = data.get("contract")
    if not isinstance(contract, dict):
        raise RuntimeError("invalid Gate0 registry contract")
    return contract


def degraded_contexts(
    truth: dict[str, Any],
    prediction: dict[str, Any],
    price: dict[str, Any],
    decision: dict[str, Any],
    evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for service_name, payload in (
        ("truth", truth),
        ("prediction", prediction),
        ("price", price),
        ("decision", decision),
        ("evaluation", evaluation),
    ):
        context = payload.get("degraded_context") if isinstance(payload, dict) else None
        if not isinstance(context, dict):
            continue
        rows.append(
            {
                "service": service_name,
                "service_id": context.get("service_id") or service_name,
                "operation": context.get("operation"),
                "behavior": context.get("behavior"),
                "blocks_unqualified_go": bool(context.get("blocks_unqualified_go")),
                "error_type": context.get("error_type"),
                "error": context.get("error"),
                "generated_at": context.get("generated_at"),
            }
        )
    return rows


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
    rows, contract = _enhancement_registry()
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
    return {**_integrity(rows, contract), "counts": dict(counts), "items": items}


def _decision_dss(decision: dict[str, Any], section: str) -> dict[str, Any]:
    policy = _dss_policy()
    registry_policy = (policy.get("registries") or {}).get(section)
    if not isinstance(registry_policy, dict):
        raise RuntimeError(f"missing DSS registry policy section: {section}")
    expected = int(registry_policy["expected_count"])
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
    core = _decision_dss(decision, "core")
    extensions = _decision_dss(decision, "extensions")
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
    degraded = degraded_contexts(truth, prediction, price, decision, evaluation)
    degraded_policy = load_json_config(DEGRADED_POLICY).get("policy") or {}
    degraded_blocks = bool(
        degraded_policy.get("degraded_context_blocks_unqualified_go", True)
        and any(bool(row.get("blocks_unqualified_go")) for row in degraded)
    )
    decision_ready = decision.get("status") == "READY"
    recommendation_allowed = bool(gate.get("pass") and registry_integrity and decision_ready)
    go_allowed = bool(recommendation_allowed and not critical_partial and not degraded_blocks)
    overall = "RED" if not recommendation_allowed else ("GREEN" if go_allowed else "AMBER")

    gate_contract = _gate_contract()
    dss_registries = _dss_policy()["registries"]
    _, enhancement_contract = _enhancement_registry()
    gate_policy = load_json_config(GATE_POLICY)
    service_registry = load_json_config(SERVICE_REGISTRY)

    return {
        "framework_schema": 8,
        "generated_at": _now(),
        "auditor": "v5-microservice-governance-v4",
        "overall": overall,
        "decision_engine": "HEALTHY" if go_allowed else ("DEGRADED" if recommendation_allowed else "BLOCKED"),
        "recommendation_allowed": recommendation_allowed,
        "go_allowed": go_allowed,
        "registry_integrity": registry_integrity,
        "degraded_contexts": degraded,
        "degraded_blocks_unqualified_go": degraded_blocks,
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
            "gate0_required_count": int(gate_contract["expected_count"]),
            "gate0_fail_blocks_go": bool(gate_policy.get("fail_closed", True)),
            "dss_authority": "decision-service",
            "enhancement_authority": "governance-service",
            "dss_core_required_count": int(dss_registries["core"]["expected_count"]),
            "dss_extension_required_count": int(dss_registries["extensions"]["expected_count"]),
            "enhancement_required_count": int(enhancement_contract["expected_count"]),
            "degraded_context_blocks_unqualified_go": bool(
                degraded_policy.get("degraded_context_blocks_unqualified_go", True)
            ),
            "service_boundary_enforced": bool(service_registry.get("mandatory")),
            "production_auto_submit": False,
        },
    }
