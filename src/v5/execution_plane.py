from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.release_integrity import runtime_fingerprint

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


@lru_cache(maxsize=1)
def current_runtime_fingerprint() -> str:
    """Return the immutable runtime fingerprint for this long-lived process.

    Runtime/governance code changes require a process restart, so hashing once per
    process avoids adding repository hashing to the user-facing hot-path budget.
    """
    value = runtime_fingerprint().get("fingerprint")
    if not value:
        raise RuntimeError("V5 runtime fingerprint unavailable")
    return str(value)


def reset_runtime_fingerprint_for_tests() -> None:
    current_runtime_fingerprint.cache_clear()


def build_hot_bundle(
    snapshot: dict[str, Any],
    watchlist: dict[str, Any],
    report: dict[str, Any],
    *,
    generated_at: str | None = None,
    runtime_fingerprint_value: str | None = None,
) -> dict[str, Any]:
    _, contract = materialization()
    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    fingerprint = runtime_fingerprint_value or current_runtime_fingerprint()
    return {
        "schema_version": int(contract.get("schema_version") or 1),
        "contract": str(contract.get("contract") or ""),
        "generated_at": timestamp,
        "runtime_fingerprint": fingerprint,
        "mode": str(snapshot.get("mode") or "daily"),
        "phase": snapshot.get("phase") if isinstance(snapshot.get("phase"), dict) else {},
        "team_id": int(snapshot.get("team_id") or 0),
        "squad_authority": snapshot.get("squad_authority"),
        "source_fusion_health": snapshot.get("source_fusion_health") if isinstance(snapshot.get("source_fusion_health"), dict) else {},
        "prediction_summary": snapshot.get("prediction_summary") if isinstance(snapshot.get("prediction_summary"), dict) else {},
        "evaluation_summary": snapshot.get("evaluation_summary") if isinstance(snapshot.get("evaluation_summary"), dict) else {},
        "decision_summary": snapshot.get("decision_summary") if isinstance(snapshot.get("decision_summary"), dict) else {},
        "framework_health": snapshot.get("framework_health") if isinstance(snapshot.get("framework_health"), dict) else {},
        "watchlist_summary": {
            "status": watchlist.get("status"),
            "candidate_count": watchlist.get("candidate_count"),
            "target_count": watchlist.get("target_count"),
            "screening_contract": watchlist.get("screening_contract"),
        },
        "user_report": report.get("user_report") if isinstance(report.get("user_report"), dict) else {},
        "technical_appendix": report.get("technical_appendix") if isinstance(report.get("technical_appendix"), dict) else {},
        "report_state": report.get("report_state") if isinstance(report.get("report_state"), dict) else {},
        "governance": {
            "materialized_from_full_refresh": True,
            "quality_reduction_for_latency": False,
            "hidden_synchronous_refresh_allowed": False,
            "durable_store_authoritative": True,
        },
    }


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

    materialized_mode = str(value.get("mode") or "")
    requested_mode = str(mode or "")
    if materialized_mode != requested_mode:
        return {
            "status": "STALE",
            "eligible": False,
            "materialization": resolved_name,
            "reason": "MODE_MISMATCH",
            "materialized_mode": materialized_mode,
            "requested_mode": requested_mode,
            "action": hot.get("stale_materialization_action", "FAIL_CLOSED"),
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

    budget = freshness_budget_seconds(requested_mode, resolved_name)
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
        "mode": requested_mode,
        "age_seconds": round(age_seconds, 3),
        "freshness_budget_seconds": budget,
        "hard_limit_ms": int(hot["hard_limit_ms"]),
        "network_refresh_allowed": bool(hot.get("network_refresh_allowed", False)),
    }
