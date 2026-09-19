from __future__ import annotations

"""Deterministic V12 runtime conformance helpers.

This module is downstream report-plane logic only. It does not acquire/publish V6,
change methodology, or become authority. Canonical V12 remains authoritative.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

ALLOWED_OPERATIONAL_ACTIONS = frozenset({"WAIT", "PREPARE", "ACT"})
CONTENT_SEVERITIES = frozenset({"PASS", "DEGRADED", "FAIL"})
DEGRADED_STATES = frozenset({"PARTIAL", "DEGRADED", "UNAVAILABLE"})
EXECUTION_STATES = frozenset({"EXECUTED", "NOT_EXECUTED"})


class RuntimeConformanceError(ValueError):
    pass


def _parse_iso(value: Any, *, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise RuntimeConformanceError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeConformanceError(f"{label} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise RuntimeConformanceError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def plan_due_report_refresh(
    *,
    report_due: bool,
    report_mode: str,
    required_scope_age_minutes: float | None,
    canonical_freshness_threshold_minutes: float | None,
    acquisition_in_progress: bool = False,
    acquisition_just_completed: bool = False,
    recent_result_reusable: bool = False,
    same_logical_data_slot_fulfilled: bool = False,
    previous_refresh_attempts: int = 0,
) -> dict[str, Any]:
    """Plan at most one existing #431 refresh for a stale due-report scope."""
    mode = str(report_mode or "").strip().upper()
    attempts = int(previous_refresh_attempts)
    if attempts < 0 or attempts > 1:
        raise RuntimeConformanceError("previous_refresh_attempts must be 0 or 1")
    if not report_due:
        return {
            "status": "NOT_DUE",
            "report_mode": mode,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
            "report_can_continue": False,
            "duplicate_acquisition_forbidden": True,
        }
    if required_scope_age_minutes is None or canonical_freshness_threshold_minutes is None:
        return {
            "status": "FRESHNESS_UNRESOLVED",
            "report_mode": mode,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
            "report_can_continue": True,
            "core_refresh": "DEGRADED",
            "reason": "required scope age/threshold unavailable; continue evidence ladder",
            "duplicate_acquisition_forbidden": True,
        }

    age = float(required_scope_age_minutes)
    threshold = float(canonical_freshness_threshold_minutes)
    stale = age > threshold
    if not stale:
        return {
            "status": "REUSE_CURRENT",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    reuse_reason = None
    if acquisition_in_progress:
        reuse_reason = "RELEVANT_ACQUISITION_IN_PROGRESS"
    elif acquisition_just_completed:
        reuse_reason = "RELEVANT_ACQUISITION_JUST_COMPLETED"
    elif recent_result_reusable:
        reuse_reason = "RECENT_RESULT_REUSABLE"
    elif same_logical_data_slot_fulfilled:
        reuse_reason = "SAME_LOGICAL_DATA_SLOT_FULFILLED"

    if reuse_reason:
        return {
            "status": "RE_READ_EXISTING_RESULT",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "reason": reuse_reason,
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    if attempts >= 1:
        return {
            "status": "REFRESH_ATTEMPT_EXHAUSTED",
            "report_mode": mode,
            "scope_age_minutes": age,
            "freshness_threshold_minutes": threshold,
            "attempt_governed_refresh": False,
            "refresh_attempt_count": attempts,
            "core_refresh": "DEGRADED",
            "report_can_continue": True,
            "duplicate_acquisition_forbidden": True,
        }

    return {
        "status": "GOVERNED_REFRESH_REQUIRED",
        "report_mode": mode,
        "scope_age_minutes": age,
        "freshness_threshold_minutes": threshold,
        "attempt_governed_refresh": True,
        "refresh_attempt_count": 1,
        "transport": "ISSUE_431_EXISTING_GOVERNED_TRANSPORT",
        "alternate_transport_allowed": False,
        "v6_master_acquire_allowed": False,
        "backfill_future_fill_allowed": False,
        "report_can_continue": True,
        "duplicate_acquisition_forbidden": True,
    }


def resolve_governed_refresh_result(plan: Mapping[str, Any], *, result: str) -> dict[str, Any]:
    """Bind refresh outcome without turning refresh success into a report barrier."""
    row = dict(plan or {})
    outcome = str(result or "").strip().upper()
    if row.get("attempt_governed_refresh") is not True:
        raise RuntimeConformanceError("refresh result requires an actual planned attempt")
    if outcome in {"SUCCESS", "PASS", "COMPLETED"}:
        row.update(
            {
                "refresh_result": "SUCCESS",
                "core_refresh": "PASS",
                "next_action": "RE_READ_AND_CONTINUE_ORIGINAL_REPORT_SLOT",
                "report_can_continue": True,
            }
        )
    elif outcome in {"FAILED", "BLOCKED", "TIMEOUT", "ERROR"}:
        row.update(
            {
                "refresh_result": outcome,
                "core_refresh": "DEGRADED",
                "next_action": "CONTINUE_CANONICAL_EVIDENCE_LADDER_SAME_REPORT_SLOT",
                "report_can_continue": True,
            }
        )
    else:
        raise RuntimeConformanceError("unsupported refresh result")
    return row


def apply_scenario_lifecycle(
    scenario: Mapping[str, Any],
    *,
    observed_at: str,
    official_deadlines: Mapping[int, str],
) -> dict[str, Any]:
    """Expire only explicit target-GW execution routes whose window is closed."""
    row = dict(scenario or {})
    state = str(row.get("scenario_state") or row.get("state") or "").strip().upper()
    execution_state = str(row.get("execution_state") or "NOT_EXECUTED").strip().upper()
    if execution_state not in EXECUTION_STATES:
        raise RuntimeConformanceError("scenario execution_state must be EXECUTED/NOT_EXECUTED")
    target = row.get("target_gw")
    if target is None:
        row["currently_valid"] = bool(row.get("currently_valid", state == "CONTEMPLATED"))
        return row

    target_gw = int(target)
    deadline_raw = official_deadlines.get(target_gw)
    if not deadline_raw:
        row["currently_valid"] = bool(row.get("currently_valid", state == "CONTEMPLATED"))
        return row
    deadline = _parse_iso(deadline_raw, label=f"GW{target_gw} deadline")
    observed = _parse_iso(observed_at, label="observed_at")
    execution_window = str(row.get("execution_window") or "").upper()
    bounded = execution_window in {
        "UNTIL_TARGET_GW_DEADLINE",
        "TARGET_GW_ONLY",
        "GW_DEADLINE",
    } or str(row.get("route_type") or "").upper() in {"ONE_GW_PUNT", "GW_SPECIFIC_ACTION"}

    if (
        state == "CONTEMPLATED"
        and execution_state != "EXECUTED"
        and bounded
        and observed >= deadline
    ):
        row["state"] = "EXPIRED"
        row["scenario_state"] = "EXPIRED"
        row["currently_valid"] = False
        row["active_for_merge"] = False
        row["expired_at"] = deadline.isoformat().replace("+00:00", "Z")
        row["expiry_reason"] = "TARGET_GW_EXECUTION_WINDOW_CLOSED_NOT_EXECUTED"
        row["historical_review_available"] = True
        row["counterfactual_available"] = True
    else:
        row["currently_valid"] = state == "CONTEMPLATED"
    return row


def scenario_is_active(row: Mapping[str, Any]) -> bool:
    state = str(row.get("scenario_state") or row.get("state") or "").strip().upper()
    return state == "CONTEMPLATED" and row.get("currently_valid", True) is True


def future_transfer_economics_inputs(scenario: Mapping[str, Any], *, target_gw: int) -> dict[str, Any]:
    """Return only assumptions allowed to flow into a future-GW economics calculation."""
    row = dict(scenario or {})
    if str(row.get("scenario_state") or row.get("state") or "").upper() == "EXPIRED":
        return {
            "target_gw": int(target_gw),
            "historical_route_id": row.get("scenario_id"),
            "carried_hit_points_assumption": None,
            "fresh_full_universe_rescan_required": True,
            "historical_assumptions_excluded": True,
        }
    return {
        "target_gw": int(target_gw),
        "historical_route_id": row.get("scenario_id"),
        "carried_hit_points_assumption": row.get("hit_points_assumption"),
        "fresh_full_universe_rescan_required": False,
        "historical_assumptions_excluded": False,
    }


def build_all15_identity_rows(
    owned_players: Sequence[Mapping[str, Any]],
    *,
    model_by_element: Mapping[int | str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Always materialize 15 owned identities; unavailable model fields stay explicit."""
    players = [dict(row) for row in owned_players]
    ids = [row.get("element_id") for row in players]
    if len(players) != 15 or any(value is None for value in ids) or len(set(map(str, ids))) != 15:
        raise RuntimeConformanceError("ALL15 identity source must contain exactly 15 unique element_id values")
    model_map = dict(model_by_element or {})
    fields = (
        "p_available",
        "p_start",
        "p_cameo",
        "p_dnp",
        "xmins",
        "gw_plus_1",
        "three_gw",
        "five_gw",
        "uncertainty_floor_upside",
    )
    rows = []
    unavailable_fields = 0
    for player in players:
        eid = player["element_id"]
        model = dict(model_map.get(eid) or model_map.get(str(eid)) or {})
        row = {
            "element_id": eid,
            "player": player.get("player") or player.get("display_name"),
            "opponent": player.get("opponent", "UNAVAILABLE"),
            "recommended_or_locked_role": player.get("recommended_or_locked_role")
            or player.get("locked_role")
            or "OWNED",
            "tactical_role": player.get("tactical_role", "UNAVAILABLE"),
            "set_piece_penalty_role": player.get("set_piece_penalty_role", "UNAVAILABLE"),
            "matchup": player.get("matchup", "UNAVAILABLE"),
            "action": player.get("action", "HOLD"),
        }
        for field in fields:
            if field in model and model[field] is not None:
                row[field] = model[field]
            else:
                row[field] = "MODEL UPDATE PENDING NEXT COMPUTE"
                unavailable_fields += 1
        rows.append(row)
    return {
        "state": "COMPLETE" if unavailable_fields == 0 else "DEGRADED",
        "identity_state": "COMPLETE",
        "identity_available_count": 15,
        "identity_expected_count": 15,
        "model_state": "COMPLETE" if unavailable_fields == 0 else "DEGRADED",
        "rows": rows,
        "no_identity_fabrication": True,
    }


_DECISION_DELTA_FIELDS = (
    "decision_item",
    "previous_state",
    "current_state",
    "material_change",
    "reason",
    "evidence_time",
)


def validate_decision_delta_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    failures: list[str] = []
    for index, raw in enumerate(rows, start=1):
        row = dict(raw)
        missing = [field for field in _DECISION_DELTA_FIELDS if field not in row]
        if missing:
            failures.append(f"ROW_{index}_MISSING={','.join(missing)}")
        if "material_change" in row and not isinstance(row.get("material_change"), bool):
            failures.append(f"ROW_{index}_MATERIAL_CHANGE_NOT_BOOL")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


_SIGNAL_DELTA_FIELDS = (
    "signal",
    "baseline_state",
    "current_state",
    "change",
    "evidence",
    "decision_effect",
)


def validate_1230_signal_delta(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline_available: bool,
) -> dict[str, Any]:
    failures: list[str] = []
    for index, raw in enumerate(rows, start=1):
        row = dict(raw)
        missing = [field for field in _SIGNAL_DELTA_FIELDS if field not in row]
        if missing:
            failures.append(f"ROW_{index}_MISSING={','.join(missing)}")
        if not baseline_available and str(row.get("baseline_state") or "").upper() != "BASELINE UNAVAILABLE":
            failures.append(f"ROW_{index}_BASELINE_MUST_BE_UNAVAILABLE")
        signal = str(row.get("signal") or "").upper()
        if signal in {"P(START)", "XMINs".upper()}:
            evidence = str(row.get("evidence") or "").upper()
            change = str(row.get("change") or "").upper()
            if any(token in change for token in ("+", "-", "%")) and not any(
                token in evidence for token in ("RECOMPUTE", "EXECUTED MODEL", "EXECUTION PROOF")
            ):
                failures.append(f"ROW_{index}_UNPROVEN_MODEL_NUMERIC_CHANGE")
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def split_bench_for_display(
    bench_players: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in bench_players]
    if len(rows) != 4:
        raise RuntimeConformanceError("bench display requires exactly four locked bench players")
    gks = [
        row for row in rows
        if str(row.get("position") or row.get("position_name") or "").upper() in {"GK", "GKP"}
    ]
    if len(gks) != 1:
        raise RuntimeConformanceError("bench display requires exactly one reserve goalkeeper")
    outfield = [row for row in rows if row is not gks[0]]
    outfield.sort(
        key=lambda row: (
            int(row.get("bench_order")) if row.get("bench_order") is not None else 99,
            int(row.get("squad_position")) if row.get("squad_position") is not None else 99,
        )
    )
    return {
        "bench_gk": gks[0],
        "outfield_autosub_priority": outfield,
        "gk_in_outfield_queue": False,
    }


def compose_operational_action(
    *,
    football_action: str,
    operational_action: str,
    trigger: str,
    reversal_or_abort: str,
    next_checkpoint: str,
) -> dict[str, Any]:
    op = str(operational_action or "").strip().upper()
    if op not in ALLOWED_OPERATIONAL_ACTIONS:
        raise RuntimeConformanceError("operational_action must be WAIT/PREPARE/ACT")
    return {
        "football_action": str(football_action or "").strip().upper(),
        "operational_action": op,
        "trigger": str(trigger or ""),
        "reversal_or_abort": str(reversal_or_abort or ""),
        "next_checkpoint": str(next_checkpoint or ""),
        "football_and_operational_actions_separate": True,
    }


def content_contract_severity(value: str) -> str:
    severity = str(value or "").strip().upper()
    if severity not in CONTENT_SEVERITIES:
        raise RuntimeConformanceError("content contract severity must be PASS/DEGRADED/FAIL")
    return severity


def compose_icon_subscopes(
    *,
    picks_scope: Mapping[str, Any] | None,
    standings_scope: Mapping[str, Any] | None,
    eo_scope: Mapping[str, Any] | None = None,
    rival_live_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve healthy ICON+ sub-scopes instead of blanking the whole section."""
    scopes = {
        "SUBMITTED_PICKS_EXPOSURE": dict(picks_scope or {}),
        "LIVE_STANDINGS_RANK": dict(standings_scope or {}),
        "EO_CAPTAINCY": dict(eo_scope or {}),
        "RIVAL_LIVE_POINTS": dict(rival_live_scope or {}),
    }
    states = []
    for name, row in scopes.items():
        state = str(row.get("state") or "UNAVAILABLE").strip().upper()
        if state not in {"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE", "STALE"}:
            raise RuntimeConformanceError(f"invalid ICON+ sub-scope state {name}={state}")
        row["state"] = state
        scopes[name] = row
        states.append(state)
    overall = "COMPLETE" if all(state == "COMPLETE" for state in states) else "DEGRADED"
    return {
        "state": overall,
        "subscopes": scopes,
        "healthy_subscopes_retained": True,
        "cross_gw_mix_forbidden": True,
    }


def compute_pick_exposure(
    manager_pick_entries: Mapping[str, Mapping[str, Any]],
    *,
    element_id: int,
) -> dict[str, Any]:
    """Compute submitted-picks exposure only from a complete manager-picks denominator."""
    entries = [dict(row) for row in manager_pick_entries.values() if isinstance(row, Mapping)]
    denominator = len(entries)
    if denominator <= 0:
        raise RuntimeConformanceError("manager-picks denominator must be positive")
    owned = started = captain = vice = 0
    for entry in entries:
        picks = [dict(row) for row in entry.get("picks") or [] if isinstance(row, Mapping)]
        target = next((row for row in picks if int(row.get("element_id", -1)) == int(element_id)), None)
        if target is None:
            continue
        owned += 1
        if int(target.get("multiplier") or 0) > 0:
            started += 1
        if target.get("captain") is True:
            captain += 1
        if target.get("vice_captain") is True:
            vice += 1

    def metric(value: int) -> dict[str, Any]:
        return {
            "numerator": value,
            "denominator": denominator,
            "percentage": round(value * 100.0 / denominator, 1),
        }

    return {
        "state": "COMPLETE",
        "denominator": denominator,
        "ownership": metric(owned),
        "starter_share": metric(started),
        "captain_share": metric(captain),
        "vice_share": metric(vice),
        "eo": None,
        "eo_status": "UNAVAILABLE_UNLESS_EXACT_MULTIPLIER_CHIP_INPUTS_SUPPORT_IT",
    }
