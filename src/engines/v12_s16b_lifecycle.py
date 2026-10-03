from __future__ import annotations

"""S16B once-per-completed-GW lifecycle resolver.

This module owns report visibility state only. It does not acquire facts, compute
football projections, rank players, or create a second post-match authority.
"""

from datetime import datetime
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")
STATE_SCHEMA = "V12_S16B_DELIVERY_STATE_V1"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fixture_id(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or row.get("fixture_id") or row.get("fixture") or "").strip()


def _fixture_gw(row: Mapping[str, Any]) -> int:
    return _int(row.get("event"), _int(row.get("gw"), _int(row.get("gameweek"), 0)))


def _match_fixture_id(row: Mapping[str, Any]) -> str:
    return str(
        row.get("fixture_id")
        or row.get("fixture")
        or row.get("match_id")
        or row.get("id")
        or ""
    ).strip()


def _match_gw(row: Mapping[str, Any]) -> int:
    return _int(
        row.get("gw"),
        _int(row.get("event"), _int(row.get("gameweek"), _int(row.get("round"), 0))),
    )


def _has_settled_fpl_row(row: Mapping[str, Any]) -> bool:
    if row.get("minutes") is None:
        return False
    return any(row.get(key) is not None for key in ("fpl_points", "total_points", "points"))


def resolve_completed_gw(fixtures: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the highest scoring GW whose known Official fixture set is fully finished."""
    by_gw: dict[int, list[dict[str, Any]]] = {}
    for raw in fixtures or ():
        if not isinstance(raw, Mapping):
            continue
        gw = _fixture_gw(raw)
        if gw <= 0:
            continue
        by_gw.setdefault(gw, []).append(dict(raw))

    completed: list[int] = []
    gw_proof: dict[int, dict[str, Any]] = {}
    for gw, rows in sorted(by_gw.items()):
        expected_ids = [_fixture_id(row) for row in rows if _fixture_id(row)]
        finished_ids = [
            _fixture_id(row)
            for row in rows
            if _fixture_id(row)
            and row.get("started") is True
            and row.get("finished") is True
        ]
        complete = bool(
            expected_ids
            and len(expected_ids) == len(rows)
            and len(finished_ids) == len(expected_ids)
            and len(set(expected_ids)) == len(expected_ids)
        )
        gw_proof[gw] = {
            "gw": gw,
            "expected_fixture_count": len(expected_ids),
            "completed_fixture_count": len(finished_ids),
            "expected_fixture_ids": expected_ids,
            "completed_fixture_ids": finished_ids,
            "fully_finished": complete,
        }
        if complete:
            completed.append(gw)

    completed_gw = max(completed) if completed else 0
    return {
        "completed_gw": completed_gw or None,
        "proof": gw_proof.get(completed_gw, {}) if completed_gw else {},
        "known_gws": sorted(by_gw),
    }


def assess_post_match_evidence_ready(
    *,
    completed_gw: int | None,
    completed_gw_proof: Mapping[str, Any] | None,
    player_match_rows: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Require settled match-level rows for every fixture; advanced metrics may be absent."""
    gw = _int(completed_gw, 0)
    proof = dict(completed_gw_proof or {})
    expected_ids = [str(value) for value in proof.get("expected_fixture_ids") or []]
    if gw <= 0 or not proof.get("fully_finished") or not expected_ids:
        return {
            "ready": False,
            "reason": "GW_NOT_FULLY_COMPLETE",
            "expected_fixture_count": len(expected_ids),
            "settled_fixture_count": 0,
            "missing_fixture_ids": expected_ids,
        }

    settled: set[str] = set()
    for raw in player_match_rows or ():
        if not isinstance(raw, Mapping) or _match_gw(raw) != gw:
            continue
        fixture_id = _match_fixture_id(raw)
        if fixture_id in expected_ids and _has_settled_fpl_row(raw):
            settled.add(fixture_id)

    missing = [fixture_id for fixture_id in expected_ids if fixture_id not in settled]
    return {
        "ready": not missing,
        "reason": None if not missing else "MATCH_LEVEL_FACTS_NOT_SETTLED",
        "expected_fixture_count": len(expected_ids),
        "settled_fixture_count": len(settled),
        "missing_fixture_ids": missing,
        "advanced_metrics_required": False,
    }


def normalize_delivery_state(
    raw_state: Mapping[str, Any] | None,
    *,
    completed_gw: int | None,
) -> dict[str, Any]:
    """Migrate prospectively without manufacturing historical S16B delivery."""
    state = dict(raw_state or {})
    valid = (
        state.get("schema") == STATE_SCHEMA
        and _int(state.get("baseline_completed_gw"), -1) >= 0
        and _int(state.get("last_delivered_gw"), -1) >= 0
    )
    if valid:
        return {
            "schema": STATE_SCHEMA,
            "baseline_completed_gw": _int(state.get("baseline_completed_gw")),
            "last_delivered_gw": _int(state.get("last_delivered_gw")),
            "delivered_occurrence": state.get("delivered_occurrence"),
            "body_fingerprint": state.get("body_fingerprint"),
            "generated_at": state.get("generated_at"),
            "migration": str(state.get("migration") or "ESTABLISHED"),
        }

    baseline = max(0, _int(completed_gw, 0))
    return {
        "schema": STATE_SCHEMA,
        "baseline_completed_gw": baseline,
        "last_delivered_gw": baseline,
        "delivered_occurrence": None,
        "body_fingerprint": None,
        "generated_at": None,
        "migration": "PROSPECTIVE_BASELINE_NO_HISTORICAL_INVENTION",
    }


def resolve_s16b_context(
    *,
    report_slot: str,
    report_mode: str,
    fixtures: Sequence[Mapping[str, Any]],
    player_match_rows: Sequence[Mapping[str, Any]] | None,
    prior_delivery_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    parsed = datetime.fromisoformat(str(report_slot).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("report_slot must be timezone-aware")
    local = parsed.astimezone(JAKARTA)

    completion = resolve_completed_gw(fixtures)
    completed_gw = completion.get("completed_gw")
    completion_proof = dict(completion.get("proof") or {})
    readiness = assess_post_match_evidence_ready(
        completed_gw=completed_gw,
        completed_gw_proof=completion_proof,
        player_match_rows=player_match_rows,
    )
    state = normalize_delivery_state(
        prior_delivery_state,
        completed_gw=completed_gw,
    )

    mode_has_deep = "DEEP" in str(report_mode or "").upper()
    eligible_time = local.hour == 4 and local.minute == 30
    delivered = (
        _int(completed_gw, 0) > 0
        and _int(state.get("last_delivered_gw"), 0) >= _int(completed_gw, 0)
    )
    due = bool(
        mode_has_deep
        and eligible_time
        and completion_proof.get("fully_finished") is True
        and readiness.get("ready") is True
        and not delivered
    )

    if not mode_has_deep:
        due_reason = "REPORT_MODE_NOT_DEEP"
    elif not eligible_time:
        due_reason = "NOT_04_30_ASIA_JAKARTA"
    elif not completion_proof.get("fully_finished"):
        due_reason = "GW_NOT_FULLY_COMPLETE"
    elif readiness.get("ready") is not True:
        due_reason = str(readiness.get("reason") or "POST_MATCH_EVIDENCE_NOT_READY")
    elif delivered:
        due_reason = "ALREADY_DELIVERED_FOR_COMPLETED_GW"
    else:
        due_reason = "DUE"

    return {
        "schema": "V12_S16B_LIFECYCLE_CONTEXT_V1",
        "report_slot": report_slot,
        "report_slot_asia_jakarta": local.isoformat(),
        "report_mode": str(report_mode or "").upper(),
        "eligible_04_30": eligible_time,
        "completed_gw": completed_gw,
        "gw_completion": completion_proof,
        "post_match_evidence": readiness,
        "delivery_state_before": state,
        "s16b_due": due,
        "due_reason": due_reason,
        "expected_section_count": 23 if due else 22,
    }


def state_after_occurrence(
    context: Mapping[str, Any],
    *,
    occurrence_id: str,
    generated_at: str,
    body_fingerprint: str | None = None,
) -> dict[str, Any]:
    state = dict(context.get("delivery_state_before") or {})
    state["schema"] = STATE_SCHEMA
    if context.get("s16b_due") is True:
        gw = _int(context.get("completed_gw"), 0)
        if gw > 0:
            state["last_delivered_gw"] = gw
            state["delivered_occurrence"] = occurrence_id
            state["body_fingerprint"] = body_fingerprint
            state["generated_at"] = generated_at
    return state
