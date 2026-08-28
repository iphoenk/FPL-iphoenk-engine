from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.governance.core import build_health
from src.v5.governance.gate0 import audit as gate0_audit, postflight as gate0_postflight, preflight as gate0_preflight
from src.v5.schedule_governance import resolve_schedule

GATE0_POLICY = "config/v5_gate0_policy_registry.json"
DSS_POLICY = "config/v5_dss_policy_registry.json"


def _gate0_policy() -> dict[str, Any]:
    return load_json_config(GATE0_POLICY)


def _dss_policy() -> dict[str, Any]:
    return load_json_config(DSS_POLICY)


def _strict_dss_active(decision: dict[str, Any]) -> bool:
    policy = (_dss_policy().get("governance") or {})
    if not bool(policy.get("all_modules_active_for_unqualified_go", True)):
        return True
    dss = decision.get("dss") if isinstance(decision.get("dss"), dict) else {}
    for section in ("core", "extensions"):
        block = dss.get(section) if isinstance(dss.get(section), dict) else {}
        expected = int(block.get("expected") or 0)
        active = int((block.get("counts") or {}).get("ACTIVE") or 0)
        if expected <= 0 or active != expected or not bool(block.get("integrity_ok")):
            return False
    return True


def _apply_strict_postflight(health: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    policy = (_dss_policy().get("governance") or {})
    required = bool(policy.get("all_modules_active_for_unqualified_go", True))
    active = _strict_dss_active(decision)
    out = {
        **health,
        "strict_postflight_requires_all_dss_active": required,
        "strict_postflight_dss_active": active,
    }
    if required and not active:
        out["go_allowed"] = False
        if bool(out.get("recommendation_allowed")):
            out["overall"] = "AMBER"
            out["decision_engine"] = "DEGRADED"
    return out


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation == "status":
        return {
            "status": "ACTIVE",
            "capabilities": [
                "gate0",
                "framework_health",
                "enhancement_layers",
                "final_governance",
                "time_schedule_governance",
            ],
            "gate0_model": _gate0_policy().get("model_id"),
            "strict_postflight_policy": (_dss_policy().get("governance") or {}).get("all_modules_active_for_unqualified_go"),
        }
    if operation == "schedule":
        return resolve_schedule(
            payload.get("context") if isinstance(payload.get("context"), dict) else {},
            now=payload.get("now"),
            official_deadline_time=payload.get("official_deadline_time"),
            live_match_active=bool(payload.get("live_match_active", False)),
            runtime_age_minutes=payload.get("runtime_age_minutes"),
            material_native_state_may_have_changed=bool(payload.get("material_native_state_may_have_changed", False)),
            price_actionable=bool(payload.get("price_actionable", False)),
            permitted_emergency=bool(payload.get("permitted_emergency", False)),
            source_observations=payload.get("source_observations") if isinstance(payload.get("source_observations"), dict) else None,
        )
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    if operation == "gate0_preflight":
        return gate0_preflight(truth)
    if operation == "gate0_postflight":
        return gate0_postflight(truth, decision)
    if operation == "gate0_audit":
        return gate0_audit(truth, decision)
    if operation != "audit":
        raise KeyError(f"unsupported governance operation: {operation}")
    health = build_health(
        truth,
        payload.get("prediction") if isinstance(payload.get("prediction"), dict) else {},
        payload.get("price") if isinstance(payload.get("price"), dict) else {},
        decision,
        payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {},
    )
    return _apply_strict_postflight(health, decision)
