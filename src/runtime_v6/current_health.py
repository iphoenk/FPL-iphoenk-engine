from __future__ import annotations

from typing import Any, Mapping

from .report_contract import build_status_view


_OPERATIONAL_HEALTHY = frozenset(
    {
        "GREEN",
        "PASS",
        "CURRENT",
        "COMPLETE",
        "AVAILABLE",
        "IMMUTABLE_GW_CACHE_REUSED",
        "NOT_REQUESTED",
        "N/A",
    }
)


def _state(value: Any) -> str:
    return str(value or "").strip().upper()


def _scope_failures(states: Mapping[str, Any] | None) -> dict[str, str]:
    failures: dict[str, str] = {}
    for scope, raw in (states or {}).items():
        state = _state(raw)
        if state not in _OPERATIONAL_HEALTHY:
            failures[str(scope)] = state or "UNKNOWN"
    return failures


def current_report_semantics(
    *,
    runtime_control: Mapping[str, Any] | None,
    prefetch_health: Mapping[str, Any] | None = None,
    required_scope_states: Mapping[str, Any] | None = None,
    optional_scope_states: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve report status for the *current invocation*, not the last stored artifact.

    Historical report-prefetch health is retained as evidence, but a normal core cycle
    must never inherit STALE/AMBER/DEGRADED from that historical artifact. Optional
    provider warnings are scope-local and do not degrade the aggregate report mode.
    """
    control = dict(runtime_control or {})
    health = dict(prefetch_health or {})
    schedule_kind = _state(control.get("schedule_kind"))
    is_current_prefetch = bool(control.get("report_prefetch")) and schedule_kind == "REPORT_PREFETCH"

    optional_warnings = _scope_failures(optional_scope_states)
    required_failures = _scope_failures(required_scope_states)
    strict_status = _state(health.get("strict_prefetch_status")) or None
    public_status = _state(health.get("public_core_status") or health.get("prefetch_status")) or None

    if not is_current_prefetch:
        return {
            "report_prefetch": "N/A",
            "target_report_freshness": "N/A",
            "report_delivery": "N/A",
            "report_mode": "NORMAL",
            "historical_prefetch_ignored": bool(health),
            "historical_prefetch_status": _state(health.get("prefetch_status")) or None,
            "strict_prefetch_status": strict_status,
            "required_scope_failures": {},
            "optional_scope_warnings": optional_warnings,
        }

    fresh_for_target = health.get("fresh_for_target_report") is True
    public_complete = bool(health.get("public_core_complete", public_status == "GREEN"))

    if public_status == "GREEN" and public_complete and fresh_for_target and not required_failures:
        report_prefetch = "PASS"
        target_freshness = "COMPLETE"
        report_delivery = "PASS | FRESH V6"
        report_mode = "NORMAL"
    elif public_status == "STALE" or not fresh_for_target:
        report_prefetch = "STALE"
        target_freshness = "STALE"
        report_delivery = "DEGRADED | CURRENT REPORT INPUT STALE"
        report_mode = "DEGRADED"
    else:
        report_prefetch = "DEGRADED"
        target_freshness = "PARTIAL"
        report_delivery = "DEGRADED | CURRENT REQUIRED REPORT SCOPE"
        report_mode = "DEGRADED"

    if required_failures:
        report_prefetch = "DEGRADED"
        target_freshness = "PARTIAL"
        report_delivery = "DEGRADED | CURRENT REQUIRED REPORT SCOPE"
        report_mode = "DEGRADED"

    return {
        "report_prefetch": report_prefetch,
        "target_report_freshness": target_freshness,
        "report_delivery": report_delivery,
        "report_mode": report_mode,
        "historical_prefetch_ignored": False,
        "historical_prefetch_status": None,
        "strict_prefetch_status": strict_status,
        "required_scope_failures": required_failures,
        "optional_scope_warnings": optional_warnings,
    }


def build_current_status_view(
    *,
    runtime_control: Mapping[str, Any] | None,
    prefetch_health: Mapping[str, Any] | None = None,
    required_scope_states: Mapping[str, Any] | None = None,
    optional_scope_states: Mapping[str, Any] | None = None,
    **status_kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """Build visible status layers with current-invocation report semantics enforced."""
    semantics = current_report_semantics(
        runtime_control=runtime_control,
        prefetch_health=prefetch_health,
        required_scope_states=required_scope_states,
        optional_scope_states=optional_scope_states,
    )
    status_kwargs = dict(status_kwargs)
    status_kwargs["report_prefetch"] = semantics["report_prefetch"]
    status_kwargs["target_report_freshness"] = semantics["target_report_freshness"]
    status_kwargs["report_delivery"] = semantics["report_delivery"]
    return build_status_view(**status_kwargs)
