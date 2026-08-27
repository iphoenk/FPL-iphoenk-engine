from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_execution_plane_registry.json"


def registry() -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    if cfg.get("contract") != "V5_EXECUTION_PLANE_V1":
        raise RuntimeError("invalid V5 execution plane registry contract")
    planes = cfg.get("planes")
    mats = cfg.get("materializations")
    if not isinstance(planes, dict) or not isinstance(mats, dict):
        raise RuntimeError("invalid V5 execution plane registry")
    return cfg


def plane(name: str) -> dict[str, Any]:
    row = registry()["planes"].get(name)
    if not isinstance(row, dict):
        raise KeyError(f"unknown V5 execution plane: {name}")
    return row


def materialization(name: str | None = None) -> tuple[str, dict[str, Any]]:
    cfg = registry()
    resolved = str(name or plane("hot")["required_materialization"])
    row = cfg["materializations"].get(resolved)
    if not isinstance(row, dict):
        raise KeyError(f"unknown V5 materialization: {resolved}")
    return resolved, row


def freshness_budget_seconds(mode: str, name: str | None = None) -> int:
    _, row = materialization(name)
    budgets = row.get("freshness_seconds_by_mode")
    if not isinstance(budgets, dict) or mode not in budgets:
        raise KeyError(f"no V5 materialization freshness budget for mode: {mode}")
    value = int(budgets[mode])
    if value <= 0:
        raise RuntimeError(f"invalid V5 materialization freshness budget for mode {mode}: {value}")
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def evaluate_hot_materialization(
    payload: dict[str, Any] | None,
    *,
    mode: str,
    current_runtime_fingerprint: str,
    now: datetime | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    resolved_name, contract = materialization(name)
    hot = plane("hot")
    value = payload if isinstance(payload, dict) else {}
    required = [str(field) for field in contract.get("required_fields") or []]
    missing = [field for field in required if value.get(field) is None]
    if missing:
        return {
            "status": "NOT_READY",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "MISSING_REQUIRED_FIELDS",
            "missing_fields": missing,
            "action": contract.get("missing_field_action", "FAIL_CLOSED"),
        }

    fingerprint = str(value.get("runtime_fingerprint") or "")
    if not fingerprint:
        return {
            "status": "NOT_READY",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "MISSING_RUNTIME_FINGERPRINT",
            "action": contract.get("missing_fingerprint_action", "FAIL_CLOSED"),
        }
    if fingerprint != str(current_runtime_fingerprint):
        return {
            "status": "STALE",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "RUNTIME_FINGERPRINT_MISMATCH",
            "action": hot.get("stale_materialization_action", "FAIL_CLOSED"),
        }

    generated = _parse_timestamp(value.get("generated_at"))
    if generated is None:
        return {
            "status": "NOT_READY",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "INVALID_GENERATED_AT",
            "action": "FAIL_CLOSED",
        }
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (current - generated).total_seconds()
    if age_seconds < 0:
        return {
            "status": "NOT_READY",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "FUTURE_TIMESTAMP",
            "age_seconds": round(age_seconds, 3),
            "action": contract.get("future_timestamp_action", "FAIL_CLOSED"),
        }

    budget = freshness_budget_seconds(mode, resolved_name)
    if age_seconds > budget:
        return {
            "status": "STALE",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "FRESHNESS_BUDGET_EXCEEDED",
            "age_seconds": round(age_seconds, 3),
            "freshness_budget_seconds": budget,
            "action": hot.get("stale_materialization_action", "FAIL_CLOSED"),
        }

    return {
        "status": "READY",
        "eligible": True,
        "materialization": resolved_name,
        "age_seconds": round(age_seconds, 3),
        "freshness_budget_seconds": budget,
        "hard_limit_ms": int(hot["hard_limit_ms"]),
        "network_refresh_allowed": bool(hot.get("network_refresh_allowed", False)),
    }
