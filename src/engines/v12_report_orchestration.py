from __future__ import annotations

"""V12 natural analytic/report orchestration.

This module does not acquire V6 data and does not own player mathematics.
It composes already-governed V12 analytic outputs into complete human-facing
report structures while keeping repository-Python execution truth separate
from ChatGPT/V12 analytic execution truth.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.engines.price_radar import (
    DISPLAY_TIMEZONE,
    MODEL_THRESHOLD as EXISTING_PRICE_MODEL_THRESHOLD,
    OFFICIAL_UPDATE_TIMEZONE,
)
from src.engines.visible_content_proof import canonical_mode_contract


SECTION_STATES = frozenset({"COMPLETE", "PARTIAL", "DEGRADED", "UNAVAILABLE"})
POSITIONS = ("GK", "DEF", "MID", "FWD")
ACTION_STATES = frozenset({"WAIT", "PREPARE", "ACT"})
PRICE_UP = frozenset({"RISE", "UP", "INCREASE", "RISING"})
PRICE_DOWN = frozenset({"FALL", "DOWN", "DECREASE", "FALLING"})
MACHINE_TERMS = (
    "issue #431",
    "mutation/readback",
    "natural_core_upkeep_gate",
    "authoritative_runtime_snapshot",
    "bound run id",
    "workflow run id",
)
SIGNAL_DELTA_FIELDS = (
    "availability",
    "p_start",
    "xmins",
    "role",
    "injury_news",
    "price",
    "fixture",
    "weather",
    "decision_route",
)


class ReportOrchestrationError(ValueError):
    pass


def _status(value: Any, *, label: str) -> str:
    out = str(value or "").strip().upper()
    if out not in SECTION_STATES:
        raise ReportOrchestrationError(
            f"{label} status must be COMPLETE/PARTIAL/DEGRADED/UNAVAILABLE"
        )
    return out


def analytic_execution_truth(
    *,
    repository_python_qa_executed: bool,
    repository_python_execution_evidence: Mapping[str, Any] | None,
    valid_current_inputs: bool,
    chatgpt_v12_analytic_executed: bool,
    analytic_outputs: Mapping[str, Any] | None,
    model_timestamp: str | None = None,
) -> dict[str, Any]:
    """Represent two independent execution truths without conflating them."""
    repo_executed = bool(repository_python_qa_executed)
    repo_evidence = dict(repository_python_execution_evidence or {})
    if not repo_executed and repo_evidence:
        raise ReportOrchestrationError(
            "repository Python execution evidence cannot be claimed when execution=false"
        )
    if repo_executed and not repo_evidence:
        raise ReportOrchestrationError(
            "repository Python execution=true requires exact execution evidence"
        )

    chatgpt_executed = bool(chatgpt_v12_analytic_executed)
    outputs = dict(analytic_outputs or {})
    if chatgpt_executed and not valid_current_inputs:
        raise ReportOrchestrationError(
            "ChatGPT V12 analytic execution requires valid current factual inputs"
        )
    if chatgpt_executed and not outputs:
        raise ReportOrchestrationError(
            "ChatGPT V12 analytic execution requires current analytic outputs"
        )

    if chatgpt_executed:
        model_refresh = "CURRENT"
    elif valid_current_inputs:
        model_refresh = "NOT RUN"
    else:
        model_refresh = "PARTIAL"

    return {
        "repository_python": {
            "executed": repo_executed,
            "evidence": repo_evidence or None,
        },
        "chatgpt_v12_analytics": {
            "executed": chatgpt_executed,
            "valid_current_inputs": bool(valid_current_inputs),
            "model_refresh": model_refresh,
            "model_timestamp": model_timestamp,
            "outputs": outputs if chatgpt_executed else None,
        },
        "repository_python_nonexecution_suppresses_v12_analytics": False,
        "execution_truths_are_separate": True,
    }


def build_watchlist20(
    *,
    evaluated_universe: Sequence[Mapping[str, Any]],
    owned_element_ids: Sequence[int],
    universe_authority: str,
) -> dict[str, Any]:
    """Select 5 per position using existing canonical evaluation outputs only."""
    authority = str(universe_authority or "").strip().upper()
    if authority not in {"FULL", "PARTIAL"}:
        raise ReportOrchestrationError("universe_authority must be FULL/PARTIAL")
    owned = {int(value) for value in owned_element_ids}
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(evaluated_universe):
        if not isinstance(raw, Mapping):
            continue
        element = raw.get("element_id")
        position = str(raw.get("position") or "").upper()
        if element is None or position not in POSITIONS:
            continue
        element = int(element)
        if element in owned or raw.get("eligible") is False:
            continue
        if raw.get("canonical_evaluation_complete") is False:
            continue
        score = raw.get("football_score")
        canonical_rank = raw.get("canonical_rank")
        rows.append(
            {
                **dict(raw),
                "element_id": element,
                "position": position,
                "_input_index": index,
                "_canonical_rank": canonical_rank,
                "_football_score": score,
            }
        )

    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for position in POSITIONS:
        pool = [row for row in rows if row["position"] == position]

        def key(row: Mapping[str, Any]):
            rank = row.get("_canonical_rank")
            score = row.get("_football_score")
            if rank is not None:
                try:
                    return (0, float(rank), 0.0, int(row["_input_index"]))
                except (TypeError, ValueError):
                    pass
            if score is not None:
                try:
                    return (1, 0.0, -float(score), int(row["_input_index"]))
                except (TypeError, ValueError):
                    pass
            return (2, 0.0, 0.0, int(row["_input_index"]))

        pool.sort(key=key)
        chosen = pool[:5]
        counts[position] = len(chosen)
        selected.extend(chosen)

    for row in selected:
        row.pop("_input_index", None)
        row.pop("_canonical_rank", None)
        row.pop("_football_score", None)

    complete = len(selected) == 20 and all(counts.get(pos) == 5 for pos in POSITIONS)
    if authority == "FULL" and complete:
        state = "COMPLETE"
        reason = None
    else:
        state = "DEGRADED" if selected else "UNAVAILABLE"
        missing = {pos: max(0, 5 - counts.get(pos, 0)) for pos in POSITIONS}
        reason = (
            "current canonical evaluated universe does not support exact 5/5/5/5"
            f"; missing={missing}"
        )
    return {
        "state": state,
        "available_count": len(selected),
        "expected_count": 20,
        "rows": selected,
        "position_counts": counts,
        "universe_authority": authority,
        "degradation_reason": reason,
        "selection_uses_existing_canonical_evaluation_only": True,
        "new_player_score_created": False,
    }


def _predictor_rows(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return predictor player rows; real V6 data.players is first-class."""
    data = artifact.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("players"), list):
        return [
            dict(row)
            for row in data.get("players") or []
            if isinstance(row, Mapping)
        ]
    for key in ("rows", "players", "predictions"):
        value = artifact.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _real_predictor_schema(artifact: Mapping[str, Any]) -> bool:
    data = artifact.get("data")
    return isinstance(data, Mapping) and isinstance(data.get("players"), list)


def _finite_price_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _official_current_price(now_cost: Any) -> Any:
    value = _finite_price_number(now_cost)
    if value is None:
        return "UNAVAILABLE"
    # Official FPL now_cost uses tenths of £m; retain normalized FACT price.
    return round(value / 10.0, 1) if value >= 20.0 else round(value, 1)


def _parse_price_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


_PRICE_UK = ZoneInfo(OFFICIAL_UPDATE_TIMEZONE)
_PRICE_WIB = ZoneInfo(DISPLAY_TIMEZONE)


def _next_official_price_cycle(evidence_timestamp: Any, *, offset: int = 0) -> tuple[str, str] | tuple[None, None]:
    """Return the governed daily 00:00 Europe/London cycle and the same instant in WIB."""
    observed = _parse_price_dt(evidence_timestamp)
    if observed is None:
        return None, None
    local = observed.astimezone(_PRICE_UK)
    target_date = local.date() + timedelta(days=1 + max(0, int(offset)))
    uk_cycle = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=_PRICE_UK)
    return uk_cycle.isoformat(), uk_cycle.astimezone(_PRICE_WIB).isoformat()


def _visible_price_direction(projected_percent: Any) -> str:
    value = _finite_price_number(projected_percent)
    if value is None:
        return "UNAVAILABLE"
    if value > 0:
        return "RISE"
    if value < 0:
        return "FALL"
    return "NEUTRAL"


def _format_price_cycle(value: Any, *, wib: bool) -> str | None:
    parsed = _parse_price_dt(value)
    if parsed is None:
        return None
    local = parsed.astimezone(_PRICE_WIB if wib else _PRICE_UK)
    zone = "WIB" if wib else (local.tzname() or "UK")
    return f"{local.strftime('%d %b %Y • %H:%M')} {zone}"


def _governed_expected_cycle(
    projections: Any,
    *,
    evidence_timestamp: Any,
    locked_until: Any,
) -> dict[str, Any]:
    """Map the existing 0/1/2 predictor horizon to truthful calendar date states."""
    next_uk, next_wib = _next_official_price_cycle(evidence_timestamp, offset=0)
    base = {
        "next_official_price_cycle_uk": next_uk or "UNAVAILABLE",
        "next_official_price_cycle_wib": next_wib or "UNAVAILABLE",
        "cycles_to_expected_change": "UNAVAILABLE",
        "estimated_change_window": "UNAVAILABLE",
        "eta_context": None,
        "estimated_change_date_uk": None,
        "estimated_change_date_wib": None,
        "estimated_change_at_uk": None,
        "estimated_change_at_wib": None,
        "last_supported_projection_date_uk": None,
        "last_supported_projection_date_wib": None,
        "last_supported_projection_at_uk": None,
        "last_supported_projection_at_wib": None,
        "horizon_cycles": 0,
        "latest_supported_projection": None,
        "projection_offset": None,
        "date_state": "DATE_UNAVAILABLE",
        "date_state_complete": True,
        "degradation_reason": None,
        "eta_reason": None,
        "eta_uses_existing_threshold": True,
        "governed_threshold_percent": EXISTING_PRICE_MODEL_THRESHOLD,
        "horizon_extension_used": False,
        "governed_projection_offsets": (0, 1, 2),
    }
    if next_uk is None or next_wib is None:
        reason = "EVIDENCE_TIMESTAMP_UNAVAILABLE"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base
    if not isinstance(projections, list):
        reason = "PREDICTOR_PROJECTIONS_UNAVAILABLE"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base

    locked = _parse_price_dt(locked_until)
    candidates: list[tuple[int, float]] = []
    for item in projections:
        if not isinstance(item, Mapping):
            continue
        try:
            offset = int(item.get("offset"))
        except (TypeError, ValueError):
            continue
        # The existing governed predictor contract exposes only these offsets.
        if offset not in {0, 1, 2}:
            continue
        projected = _finite_price_number(item.get("projected_percent"))
        if projected is None:
            continue
        candidates.append((offset, projected))

    candidates.sort()
    if not candidates:
        reason = "NO_VALID_GOVERNED_PROJECTION_OFFSETS"
        base.update({"eta_reason": reason, "degradation_reason": reason})
        return base

    max_offset, latest_projection = candidates[-1]
    last_uk, last_wib = _next_official_price_cycle(evidence_timestamp, offset=max_offset)
    base.update(
        {
            "horizon_cycles": max_offset + 1,
            "latest_supported_projection": latest_projection,
            "last_supported_projection_at_uk": last_uk,
            "last_supported_projection_at_wib": last_wib,
            "last_supported_projection_date_uk": _format_price_cycle(last_uk, wib=False),
            "last_supported_projection_date_wib": _format_price_cycle(last_wib, wib=True),
        }
    )

    for offset, projected in candidates:
        if abs(projected) < EXISTING_PRICE_MODEL_THRESHOLD:
            continue
        cycle_uk, cycle_wib = _next_official_price_cycle(evidence_timestamp, offset=offset)
        if cycle_uk is None or cycle_wib is None:
            continue
        cycle_dt = _parse_price_dt(cycle_uk)
        if (
            locked is not None
            and cycle_dt is not None
            and cycle_dt.astimezone(timezone.utc) < locked.astimezone(timezone.utc)
        ):
            continue
        cycle_label = "NEXT CYCLE" if offset == 0 else f"{offset} CYCLE" if offset == 1 else f"{offset} CYCLES"
        wib_display = _format_price_cycle(cycle_wib, wib=True)
        base.update(
            {
                "cycles_to_expected_change": cycle_label,
                "estimated_change_window": wib_display or "UNAVAILABLE",
                "eta_context": wib_display,
                "estimated_change_date_uk": _format_price_cycle(cycle_uk, wib=False),
                "estimated_change_date_wib": wib_display,
                "estimated_change_at_uk": cycle_uk,
                "estimated_change_at_wib": cycle_wib,
                "projection_offset": offset,
                "date_state": "EXPECTED_CHANGE_DATE",
                "date_state_complete": True,
                "eta_reason": None,
                "degradation_reason": None,
            }
        )
        return base

    last_display = base["last_supported_projection_date_wib"]
    base.update(
        {
            "date_state": "NO_CROSSING_WITHIN_GOVERNED_HORIZON",
            "date_state_complete": True,
            "estimated_change_window": "UNAVAILABLE",
            "eta_context": (
                f"Belum terdeteksi berubah sampai {last_display}"
                if last_display
                else "NO EXPECTED CHANGE WITHIN GOVERNED HORIZON"
            ),
            "eta_reason": "NO_EXISTING_PREDICTOR_CYCLE_CROSSES_GOVERNED_THRESHOLD",
            "degradation_reason": None,
        }
    )
    return base


def _price_decision_impact(
    *,
    element_id: int,
    direction: str,
    owned_ids: set[int],
    target_ids: set[int],
) -> str:
    if element_id in owned_ids:
        if direction == "FALL":
            return "OWNED — FALL MAY REDUCE SELL VALUE"
        if direction == "RISE":
            return "OWNED — RISE; MONITOR SELL-VALUE / AFFORDABILITY EFFECT"
        return "OWNED — NEUTRAL PRICE SIGNAL"
    if element_id in target_ids:
        if direction == "RISE":
            return "TARGET — RISE MAY REMOVE AFFORDABILITY"
        if direction == "FALL":
            return "TARGET — FALL MAY IMPROVE AFFORDABILITY"
        return "TARGET — NEUTRAL PRICE SIGNAL"
    return "WATCH ONLY — NO BOUND PERSONAL ROUTE"


def _visible_price_contract(
    row: Mapping[str, Any],
    *,
    evidence_timestamp: Any,
    predictor_health: str,
    owned_ids: set[int],
    target_ids: set[int],
) -> dict[str, Any]:
    out = dict(row)
    direction = _visible_price_direction(out.get("projected_percent"))
    timing = _governed_expected_cycle(
        out.get("price_change_projections"),
        evidence_timestamp=evidence_timestamp,
        locked_until=out.get("locked_until"),
    )
    likelihood = out.get("likelihood")
    out.update(
        {
            "direction": direction,
            "official_or_provider_progress": out.get("price_change_percent", "UNAVAILABLE"),
            "prediction_strength": likelihood if likelihood is not None else "UNAVAILABLE",
            **timing,
            "estimate_source": "official_price_predictor",
            "evidence_timestamp": evidence_timestamp or "UNAVAILABLE",
            "confidence": {
                "predictor_health": predictor_health,
                "native_likelihood": likelihood if likelihood is not None else "UNAVAILABLE",
                "calibrating": bool(out.get("calibrating")),
                "locked_until": out.get("locked_until"),
            },
            "impact_on_our_decision": _price_decision_impact(
                element_id=int(out["element_id"]),
                direction=direction,
                owned_ids=owned_ids,
                target_ids=target_ids,
            ),
        }
    )
    return out


def _offset_zero_projection(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    projections = row.get("price_change_projections")
    if not isinstance(projections, list):
        return None
    for projection in projections:
        if not isinstance(projection, Mapping):
            continue
        offset = projection.get("offset")
        try:
            is_zero = float(offset) == 0.0
        except (TypeError, ValueError):
            is_zero = False
        if is_zero:
            return projection
    return None


def _normalize_real_price_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    projection = _offset_zero_projection(row)
    if projection is None:
        return None
    projected = _finite_price_number(projection.get("projected_percent"))
    element = row.get("id")
    if projected is None or element is None:
        return None
    try:
        element_id = int(element)
    except (TypeError, ValueError):
        return None
    return {
        "element_id": element_id,
        "player": row.get("web_name") or f"element:{element_id}",
        "current_price": _official_current_price(row.get("now_cost")),
        "price_fact": "FACT",
        "projected_percent": projected,
        "likelihood": projection.get("likelihood"),
        "predictor_classification": "MODEL",
        "projection_offset": 0,
        "price_change_percent": row.get("price_change_percent"),
        "price_change_hourly_rate": row.get("price_change_hourly_rate"),
        "selected_by_percent": row.get("selected_by_percent"),
        "transfers_in_event": row.get("transfers_in_event"),
        "transfers_out_event": row.get("transfers_out_event"),
        "locked_until": row.get("price_change_locked_until"),
        "calibrating": row.get("price_change_calibrating"),
        "team": row.get("team"),
        "element_type": row.get("element_type"),
        "price_change_projections": [
            dict(item)
            for item in (row.get("price_change_projections") or [])
            if isinstance(item, Mapping)
        ],
    }


def build_price20(
    *,
    predictor_artifact: Mapping[str, Any] | None,
    direction: str,
    owned_element_ids: Sequence[int] | None = None,
    target_element_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Consume current official_price_predictor output; never predict price itself."""
    if not predictor_artifact:
        return {
            "state": "UNAVAILABLE",
            "available_count": 0,
            "expected_count": 20,
            "rows": [],
            "degradation_reason": "current official_price_predictor artifact absent",
        }
    artifact = dict(predictor_artifact)
    health = str(
        artifact.get("health")
        or artifact.get("status")
        or artifact.get("source_health")
        or "UNKNOWN"
    ).upper()
    evidence_timestamp = artifact.get("checked_at") or artifact.get("generated_at")
    owned_ids = {int(value) for value in (owned_element_ids or ())}
    target_ids = {int(value) for value in (target_element_ids or ())}
    direction_token = str(direction or "").upper()
    if direction_token not in {"RISE", "FALL"}:
        raise ReportOrchestrationError("direction must be RISE/FALL")
    rows = _predictor_rows(artifact)

    if _real_predictor_schema(artifact):
        normalized = [
            _visible_price_contract(
                bound,
                evidence_timestamp=evidence_timestamp,
                predictor_health=health,
                owned_ids=owned_ids,
                target_ids=target_ids,
            )
            for row in rows
            if (bound := _normalize_real_price_row(row)) is not None
        ]
        if direction_token == "RISE":
            normalized.sort(
                key=lambda row: (-float(row["projected_percent"]), int(row["element_id"]))
            )
        else:
            normalized.sort(
                key=lambda row: (float(row["projected_percent"]), int(row["element_id"]))
            )
        selected = normalized[:20]
        usable_count = len(normalized)
        adapter = "V6_DATA_PLAYERS_OFFSET0"
    else:
        wanted = PRICE_UP if direction_token == "RISE" else PRICE_DOWN
        selected: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            token = str(
                row.get("risk_direction")
                or row.get("direction")
                or row.get("prediction")
                or ""
            ).upper()
            if token not in wanted:
                continue
            copied = dict(row)
            copied["_artifact_index"] = index
            selected.append(copied)

        def legacy_key(row: Mapping[str, Any]):
            for name in ("rank", "predictor_rank", "direction_rank"):
                if row.get(name) is not None:
                    try:
                        return (0, float(row[name]), int(row["_artifact_index"]))
                    except (TypeError, ValueError):
                        pass
            return (1, 0.0, int(row["_artifact_index"]))

        selected.sort(key=legacy_key)
        selected = selected[:20]
        for row in selected:
            row.pop("_artifact_index", None)
        usable_count = len(selected)
        adapter = "COMPACT_COMPAT"

    enough = len(selected) == 20
    healthy = health in {"GREEN", "HEALTHY", "PASS", "CURRENT", "OK"}
    date_state_complete = (
        adapter != "V6_DATA_PLAYERS_OFFSET0"
        or all(bool(row.get("date_state_complete")) for row in selected)
    )
    missing_cycle_clock = (
        adapter == "V6_DATA_PLAYERS_OFFSET0"
        and any(
            row.get("next_official_price_cycle_uk") == "UNAVAILABLE"
            or row.get("next_official_price_cycle_wib") == "UNAVAILABLE"
            for row in selected
        )
    )
    unsupported_eta = (
        adapter == "V6_DATA_PLAYERS_OFFSET0"
        and any(
            row.get("cycles_to_expected_change") == "UNAVAILABLE"
            or row.get("estimated_change_window") == "UNAVAILABLE"
            for row in selected
        )
    )
    if enough and healthy and date_state_complete and not missing_cycle_clock and not unsupported_eta:
        state = "COMPLETE"
    elif selected:
        state = "DEGRADED"
    else:
        state = "UNAVAILABLE"

    reason = None
    if state != "COMPLETE":
        if adapter == "V6_DATA_PLAYERS_OFFSET0" and not date_state_complete:
            incomplete = sum(not bool(row.get("date_state_complete")) for row in selected)
            reason = f"date-state terminal contract incomplete for {incomplete}/20 rows"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and missing_cycle_clock:
            reason = "official_price_predictor evidence timestamp unavailable; official cycle timing cannot be derived"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and unsupported_eta:
            unsupported = sum(
                row.get("cycles_to_expected_change") == "UNAVAILABLE"
                or row.get("estimated_change_window") == "UNAVAILABLE"
                for row in selected
            )
            reason = (
                f"exact20 selected from healthy official_price_predictor; "
                f"governed expected-change cycle unsupported for {unsupported}/20 rows, "
                "so ETA remains UNAVAILABLE rather than inferred"
            )
        else:
            reason = (
                f"official_price_predictor health={health}; "
                f"usable offset-0 {direction_token.lower()} rows={len(selected)}/20"
                if adapter == "V6_DATA_PLAYERS_OFFSET0"
                else f"official_price_predictor health={health}; "
                f"{direction_token.lower()} rows={len(selected)}/20"
            )
    return {
        "state": state,
        "available_count": len(selected),
        "expected_count": 20,
        "usable_eligible_rows": usable_count,
        "rows": selected,
        "predictor_health": health,
        "degradation_reason": reason,
        "artifact_adapter": adapter,
        "sort_contract": (
            "projected_percent DESC, id ASC"
            if direction_token == "RISE" and adapter == "V6_DATA_PLAYERS_OFFSET0"
            else "projected_percent ASC, id ASC"
            if direction_token == "FALL" and adapter == "V6_DATA_PLAYERS_OFFSET0"
            else "legacy compact predictor order"
        ),
        "current_price_classification": "FACT",
        "projection_classification": "MODEL",
        "visible_contract_fields": (
            "player",
            "current_price",
            "direction",
            "official_or_provider_progress",
            "prediction_strength",
            "next_official_price_cycle_uk",
            "next_official_price_cycle_wib",
            "cycles_to_expected_change",
            "estimated_change_window",
            "estimated_change_date_uk",
            "estimated_change_date_wib",
            "date_state",
            "last_supported_projection_date_wib",
            "horizon_cycles",
            "latest_supported_projection",
            "estimate_source",
            "evidence_timestamp",
            "confidence",
            "impact_on_our_decision",
        ),
        "uses_existing_predictor_only": True,
        "existing_eta_threshold_source": "config/intelligence/price_radar.json:model_interpretation.threshold_percent",
        "new_price_threshold_model_created": False,
        "new_price_predictor_created": False,
        "horizon_extension_used": False,
        "governed_projection_offsets": (0, 1, 2),
        "date_state_complete_count": sum(
            bool(row.get("date_state_complete")) for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
        "expected_change_date_count": sum(
            row.get("date_state") == "EXPECTED_CHANGE_DATE" for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
        "no_crossing_count": sum(
            row.get("date_state") == "NO_CROSSING_WITHIN_GOVERNED_HORIZON" for row in selected
        ) if adapter == "V6_DATA_PLAYERS_OFFSET0" else None,
    }


def build_actionable_price_radar(
    *,
    owned15: Sequence[Mapping[str, Any]],
    predictor_artifact: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Always preserve owned identity; predictor evidence enriches but never removes OUR15."""
    artifact = dict(predictor_artifact or {})
    predictor_health = str(
        artifact.get("health")
        or artifact.get("status")
        or artifact.get("source_health")
        or "UNKNOWN"
    ).upper()
    evidence_timestamp = artifact.get("checked_at") or artifact.get("generated_at")
    predictor: dict[int, dict[str, Any]] = {}
    for row in _predictor_rows(artifact):
        raw_id = row.get("element_id", row.get("element", row.get("id")))
        if raw_id is None:
            continue
        try:
            predictor[int(raw_id)] = row
        except (TypeError, ValueError):
            continue

    identities: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in owned15:
        if not isinstance(raw, Mapping):
            continue
        element = raw.get("element_id", raw.get("element"))
        if element is None:
            continue
        element = int(element)
        if element in seen:
            continue
        seen.add(element)

        pred_raw = dict(predictor.get(element) or {})
        normalized = _normalize_real_price_row(pred_raw) if pred_raw.get("price_change_projections") is not None else None
        visible = (
            _visible_price_contract(
                normalized,
                evidence_timestamp=evidence_timestamp,
                predictor_health=predictor_health,
                owned_ids={element},
                target_ids=set(),
            )
            if normalized is not None
            else None
        )
        raw_current = raw.get("current_price", raw.get("price"))
        current_price = (
            visible.get("current_price")
            if visible is not None and visible.get("current_price") != "UNAVAILABLE"
            else _official_current_price(raw_current)
            if raw_current is not None
            else "UNAVAILABLE"
        )
        raw_sell = raw.get("authenticated_sell_value", raw.get("selling_price"))
        sell_value = _official_current_price(raw_sell) if raw_sell is not None else "UNAVAILABLE"
        raw_sell_state = str(
            raw.get("sell_value_evidence_state")
            or raw.get("authenticated_evidence_state")
            or raw.get("authenticated_state")
            or ""
        ).upper()
        if sell_value == "UNAVAILABLE":
            sell_value_evidence_state = "UNAVAILABLE"
        elif raw_sell_state in {"CURRENT_AUTHENTICATED", "AUTH_CURRENT", "CURRENT"}:
            sell_value_evidence_state = "CURRENT_AUTHENTICATED"
        elif raw_sell_state in {"STALE_AUTHENTICATED_FALLBACK", "AUTH_STALE", "STALE"}:
            sell_value_evidence_state = "STALE_AUTHENTICATED_FALLBACK"
        else:
            sell_value_evidence_state = "AUTHENTICATED_FRESHNESS_UNPROVEN"

        identities.append(
            {
                "element_id": element,
                "name": raw.get("name") or (visible or {}).get("player"),
                "current_price": current_price,
                "price_fact": "FACT" if current_price != "UNAVAILABLE" else "UNAVAILABLE",
                "authenticated_sell_value": sell_value,
                "sell_value_evidence_state": sell_value_evidence_state,
                "predictor_direction": (visible or {}).get("direction", "UNAVAILABLE"),
                "predictor_progress": (visible or {}).get("official_or_provider_progress", "UNAVAILABLE"),
                "prediction_strength": (visible or {}).get("prediction_strength", "UNAVAILABLE"),
                "next_official_price_cycle_uk": (visible or {}).get("next_official_price_cycle_uk", "UNAVAILABLE"),
                "next_official_price_cycle_wib": (visible or {}).get("next_official_price_cycle_wib", "UNAVAILABLE"),
                "cycles_to_expected_change": (visible or {}).get("cycles_to_expected_change", "UNAVAILABLE"),
                "estimated_change_date_uk": (visible or {}).get("estimated_change_date_uk"),
                "estimated_change_date_wib": (visible or {}).get("estimated_change_date_wib"),
                "date_state": (visible or {}).get("date_state", "DATE_UNAVAILABLE"),
                "date_state_complete": bool((visible or {}).get("date_state_complete", True)),
                "date_state_reason": (
                    (visible or {}).get("degradation_reason")
                    or (None if visible is not None else "PREDICTOR_EVIDENCE_UNAVAILABLE")
                ),
                "last_supported_projection_date_wib": (visible or {}).get("last_supported_projection_date_wib"),
                "horizon_cycles": (visible or {}).get("horizon_cycles", 0),
                "latest_supported_projection": (visible or {}).get("latest_supported_projection"),
                "estimated_change_window": (visible or {}).get(
                    "estimated_change_window",
                    "UNAVAILABLE",
                ),
                "eta_context": (visible or {}).get("eta_context"),
                "eta_reason": (visible or {}).get(
                    "eta_reason",
                    "PREDICTOR_EVIDENCE_UNAVAILABLE" if visible is None else None,
                ),
                "estimate_source": (visible or {}).get("estimate_source", "official_price_predictor" if pred_raw else "UNAVAILABLE"),
                "evidence_timestamp": (visible or {}).get("evidence_timestamp", evidence_timestamp or "UNAVAILABLE"),
                "confidence": (visible or {}).get("confidence", "UNAVAILABLE"),
                "sell_value_affordability_impact": (visible or {}).get(
                    "impact_on_our_decision",
                    "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; DO NOT FABRICATE PRICE ACTION",
                ),
                "decision_implication": (visible or {}).get(
                    "impact_on_our_decision",
                    "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; FOOTBALL DECISION CONTINUES",
                ),
                "predictor_projected_percent": (visible or {}).get("projected_percent", "UNAVAILABLE"),
                "predictor_classification": "MODEL" if pred_raw else "UNAVAILABLE",
                "predictor_evidence": pred_raw or None,
            }
        )

    complete = len(identities) == 15
    return {
        "state": "COMPLETE" if complete else ("DEGRADED" if identities else "UNAVAILABLE"),
        "available_count": len(identities),
        "expected_count": 15,
        "rows": identities,
        "identity_complete": complete,
        "predictor_complete_count": sum(
            row.get("predictor_direction") != "UNAVAILABLE" for row in identities
        ),
        "date_state_complete_count": sum(
            bool(row.get("date_state_complete")) for row in identities
        ),
        "degradation_reason": None if complete else "owned price identity coverage is not exact15",
        "price_alone_may_create_act": False,
    }


def build_icon_subscopes(
    *,
    submitted_picks: Sequence[Mapping[str, Any]] | None,
    submitted_denominator: int | None,
    standings: Sequence[Mapping[str, Any]] | None,
    standings_denominator: int | None,
    eo_rows: Sequence[Mapping[str, Any]] | None = None,
    rival_live_points: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep healthy ICON+ sub-scopes visible when another sub-scope is unavailable."""
    picks = [dict(row) for row in (submitted_picks or ()) if isinstance(row, Mapping)]
    standing_rows = [dict(row) for row in (standings or ()) if isinstance(row, Mapping)]
    eo = [dict(row) for row in (eo_rows or ()) if isinstance(row, Mapping)]
    live = [dict(row) for row in (rival_live_points or ()) if isinstance(row, Mapping)]

    if submitted_denominator is not None and len(picks) > int(submitted_denominator):
        raise ReportOrchestrationError("submitted pick coverage exceeds denominator")
    if standings_denominator is not None and len(standing_rows) > int(standings_denominator):
        raise ReportOrchestrationError("standings coverage exceeds denominator")

    picks_full = submitted_denominator is not None and len(picks) == int(submitted_denominator)
    standings_full = (
        standings_denominator is not None
        and len(standing_rows) == int(standings_denominator)
    )
    submitted_state = "COMPLETE" if picks_full else ("PARTIAL" if picks else "UNAVAILABLE")
    standings_state = (
        "COMPLETE" if standings_full else ("PARTIAL" if standing_rows else "UNAVAILABLE")
    )

    return {
        "submitted_picks_exposure": {
            "state": submitted_state,
            "available_count": len(picks),
            "expected_count": submitted_denominator,
            "rows": picks,
        },
        "live_standings_rank": {
            "state": standings_state,
            "available_count": len(standing_rows),
            "expected_count": standings_denominator,
            "rows": standing_rows,
        },
        "eo": {
            "state": "COMPLETE" if eo and picks_full else "UNAVAILABLE",
            "rows": eo if picks_full else [],
            "reason": None if eo and picks_full else "exact multiplier/coverage denominator unavailable",
        },
        "rival_live_points": {
            "state": "PARTIAL" if live else "UNAVAILABLE",
            "rows": live,
        },
        "subscopes_fail_operational_independently": True,
    }


def materialize_all15(
    *,
    owned15: Sequence[Mapping[str, Any]],
    model_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Keep all owned identities even when model fields are unavailable."""
    model_map = {
        int(row.get("element_id")): dict(row)
        for row in (model_rows or ())
        if isinstance(row, Mapping) and row.get("element_id") is not None
    }
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for owned in owned15:
        if not isinstance(owned, Mapping):
            continue
        element = owned.get("element_id", owned.get("element"))
        if element is None:
            continue
        element = int(element)
        if element in seen:
            continue
        seen.add(element)
        model = model_map.get(element) or {}
        rows.append(
            {
                "element_id": element,
                "player": owned.get("name") or model.get("name"),
                "opponent": model.get("opponent", "UNAVAILABLE"),
                "recommended_or_locked_role": model.get(
                    "recommended_or_locked_role", "UNAVAILABLE"
                ),
                "p_available": model.get("p_available", "UNAVAILABLE"),
                "p_start": model.get("p_start", "UNAVAILABLE"),
                "p_cameo": model.get("p_cameo", "UNAVAILABLE"),
                "p_dnp": model.get("p_dnp", "UNAVAILABLE"),
                "xmins": model.get("xmins", "UNAVAILABLE"),
                "tactical_role": model.get("tactical_role", "UNAVAILABLE"),
                "set_piece_penalty_role": model.get(
                    "set_piece_penalty_role", "UNAVAILABLE"
                ),
                "matchup": model.get("matchup", "UNAVAILABLE"),
                "gw_plus_1": model.get("gw_plus_1", "UNAVAILABLE"),
                "three_gw": model.get("three_gw", "UNAVAILABLE"),
                "five_gw": model.get("five_gw", "UNAVAILABLE"),
                "uncertainty_floor_upside": model.get(
                    "uncertainty_floor_upside", "UNAVAILABLE"
                ),
                "action": model.get("action", "HOLD"),
            }
        )
    complete = len(rows) == 15
    return {
        "state": "COMPLETE" if complete else ("DEGRADED" if rows else "UNAVAILABLE"),
        "available_count": len(rows),
        "expected_count": 15,
        "rows": rows,
        "identity_complete": complete,
        "model_complete": complete
        and all(row["p_start"] != "UNAVAILABLE" and row["xmins"] != "UNAVAILABLE" for row in rows),
        "degradation_reason": None if complete else "owned identity evidence is not exact15",
    }


def build_signal_delta(
    *,
    baseline_0430: Mapping[str, Any] | None,
    current_1230: Mapping[str, Any] | None,
) -> dict[str, Any]:
    current = dict(current_1230 or {})
    if not baseline_0430:
        return {
            "status": "BASELINE UNAVAILABLE",
            "rows": [
                {
                    "signal": field,
                    "04:30_or_baseline_state": "BASELINE UNAVAILABLE",
                    "12:30_state": current.get(field, "UNAVAILABLE"),
                    "change": "UNAVAILABLE",
                    "evidence": current.get(f"{field}_evidence"),
                    "decision_effect": current.get(f"{field}_decision_effect"),
                }
                for field in SIGNAL_DELTA_FIELDS
            ],
        }
    baseline = dict(baseline_0430)
    rows = []
    for field in SIGNAL_DELTA_FIELDS:
        before = baseline.get(field, "UNAVAILABLE")
        after = current.get(field, "UNAVAILABLE")
        rows.append(
            {
                "signal": field,
                "04:30_or_baseline_state": before,
                "12:30_state": after,
                "change": "NO CHANGE" if before == after else "CHANGED",
                "evidence": current.get(f"{field}_evidence"),
                "decision_effect": current.get(f"{field}_decision_effect"),
            }
        )
    return {"status": "AVAILABLE", "rows": rows}


def _locked_default(label: str, locked_state: Mapping[str, Any]) -> dict[str, Any] | None:
    upper = label.upper()
    if "FORMATION/XI/BENCH" in upper:
        return {
            "state": "COMPLETE",
            "content": {
                "status": "GW LOCKED — NO EXECUTABLE XI CHANGE",
                "formation": locked_state.get("formation"),
                "xi": locked_state.get("xi"),
                "bench": locked_state.get("bench"),
            },
        }
    if "XI BATTLE" in upper:
        return {
            "state": "COMPLETE",
            "content": {"status": "GW LOCKED — XI battle retained as factual locked state"},
        }
    if label.upper() == "C/VC":
        return {
            "state": "COMPLETE",
            "content": {
                "status": "LOCKED",
                "captain": locked_state.get("captain"),
                "vice_captain": locked_state.get("vice_captain"),
            },
        }
    if label.upper() == "CHIP":
        return {
            "state": "COMPLETE",
            "content": {"status": "LOCKED", "chip": locked_state.get("chip")},
        }
    return None


def materialize_deep_report(
    *,
    canonical_text: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize every Canonical DEEP block; unavailable data never omits a section."""
    contract = canonical_mode_contract(canonical_text, "DEEP")
    payloads = dict(section_payloads or {})
    sections: list[dict[str, Any]] = []
    locked = dict(locked_state or {})

    for section_id, label in zip(
        contract["expected_section_ids"],
        contract["expected_visible_order"],
    ):
        raw = payloads.get(section_id) or payloads.get(label)
        if raw is None and current_gw_locked:
            raw = _locked_default(label, locked)
        if raw is None:
            raw = {
                "state": "UNAVAILABLE",
                "degradation_reason": "current authoritative evidence unavailable",
                "content": None,
            }
        row = dict(raw)
        state = _status(row.get("state"), label=section_id)
        if state != "COMPLETE" and not str(row.get("degradation_reason") or "").strip():
            raise ReportOrchestrationError(
                f"{section_id} degraded/unavailable section requires reason"
            )
        content = row.get("content")
        if section_id == "S03" and str(checkpoint_time or "") == "12:30":
            content = dict(content or {})
            content["signal_delta_since_0430"] = dict(
                signal_delta
                or {
                    "status": "BASELINE UNAVAILABLE",
                    "rows": [],
                }
            )
        sections.append(
            {
                "section_id": section_id,
                "label": label,
                "state": state,
                "available_count": row.get("available_count"),
                "expected_count": row.get("expected_count"),
                "degradation_reason": row.get("degradation_reason"),
                "content": content,
            }
        )

    return {
        "report_mode": "DEEP",
        "sections": sections,
        "rendered_section_ids": [row["section_id"] for row in sections],
        "rendered_visible_order": [row["label"] for row in sections],
        "exact_canonical_order": [row["section_id"] for row in sections]
        == contract["expected_section_ids"],
        "numbered_headings": 19,
        "rendered_blocks_including_15B": len(sections),
    }


def render_deep_text(report: Mapping[str, Any]) -> str:
    """Simple human-facing structural renderer for conformance tests."""
    blocks = []
    for row in report.get("sections") or []:
        label = str(row.get("label") or "")
        state = str(row.get("state") or "")
        blocks.append(f"## {label}\nStatus: {state}")
    return "\n\n".join(blocks)


def validate_human_facing_body(
    body: str,
    *,
    material_technical_failure: bool = False,
) -> list[str]:
    """Reject low-level orchestration narration from normal healthy reports."""
    if material_technical_failure:
        return []
    text = str(body or "")
    lower = text.lower()
    failures = [
        f"MACHINE_LANGUAGE={token}"
        for token in MACHINE_TERMS
        if token in lower
    ]
    if re.search(r"\b[0-9a-f]{40}\b", lower):
        failures.append("MACHINE_LANGUAGE=RAW_BRANCH_SHA")
    return failures


def compact_engine_data_status(
    *,
    v6_data: str,
    publication: str,
    universe: str,
    personal_squad_data: str,
    model_refresh: str,
    mc: str,
    icon: str,
    data_time: str,
) -> dict[str, str]:
    return {
        "V6 data": str(v6_data),
        "Publication": str(publication),
        "Universe": str(universe),
        "Personal squad data": str(personal_squad_data),
        "Model refresh": str(model_refresh),
        "MC": str(mc),
        "ICON+": str(icon),
        "Data time": str(data_time),
    }


def weather_report_time_evidence(
    *,
    venue: str | None,
    kickoff: str | None,
    weather: Mapping[str, Any] | None,
    lookup_accessible: bool,
    failure_reason: str | None = None,
    fixture: str | None = None,
) -> dict[str, Any]:
    """Normalize SIMPLE visible weather evidence without creating a weather model."""
    if weather:
        payload = dict(weather)
        impact = str(
            payload.get("fpl_impact")
            or payload.get("impact")
            or payload.get("impact_classification")
            or ""
        ).strip().upper()
        if impact not in {"NORMAL", "LOW", "MATERIAL"}:
            impact = "UNAVAILABLE"
        precipitation = payload.get(
            "precipitation_probability",
            payload.get(
                "precipitation_chance_pct",
                payload.get("precipitation_probability_pct", "UNAVAILABLE"),
            ),
        )
        wind = payload.get(
            "wind_kph",
            payload.get(
                "wind_kmh",
                payload.get("wind_speed_kmh", "UNAVAILABLE"),
            ),
        )
        evidence_timestamp = payload.get(
            "weather_evidence_timestamp",
            payload.get("evidence_timestamp", payload.get("checked_at", "UNAVAILABLE")),
        )
        impact_reason = payload.get("impact_reason", payload.get("fpl_impact_reason", "UNAVAILABLE"))
        visible_row = {
            "fixture": fixture or payload.get("fixture") or "UNAVAILABLE",
            "venue": venue or payload.get("venue") or "UNAVAILABLE",
            "kickoff": kickoff or payload.get("kickoff") or "UNAVAILABLE",
            "condition": payload.get("condition") or payload.get("weather_condition") or "UNAVAILABLE",
            "temperature_c": payload.get("temperature_c", "UNAVAILABLE"),
            "temperature": payload.get("temperature_c", "UNAVAILABLE"),
            "precipitation_probability": precipitation,
            "precipitation_chance_pct": precipitation,
            "wind_kph": wind,
            "wind_kmh": wind,
            "fpl_impact": impact,
            "impact_class": impact,
            "impact_reason": impact_reason,
            "evidence_timestamp": evidence_timestamp,
            "weather_evidence_timestamp": evidence_timestamp,
        }
        required = (
            "fixture",
            "venue",
            "kickoff",
            "condition",
            "temperature_c",
            "precipitation_probability",
            "wind_kph",
            "fpl_impact",
            "weather_evidence_timestamp",
        )
        missing = [
            key for key in required
            if visible_row.get(key) in {None, "", "UNAVAILABLE"}
        ]
        return {
            "state": "COMPLETE" if not missing else "PARTIAL",
            "venue": visible_row["venue"],
            "kickoff": visible_row["kickoff"],
            "weather": payload,
            "visible_row": visible_row,
            "missing_visible_fields": missing,
            "source_layer": "REPORT_TIME",
            "v6_weather_required": False,
            "new_weather_model_created": False,
            "weather_adjusted_xpts": False,
            "weather_mutates_p_start": False,
            "weather_mutates_xmins": False,
            "weather_mutates_p1_6_tactical_score": False,
            "weather_failure_isolated_to_weather": True,
            "weather_may_independently_create_action": False,
            "raw_provider_plumbing_visible": False,
        }
    reason = str(failure_reason or "").strip()
    if not reason:
        reason = (
            "report-time weather lookup unavailable"
            if lookup_accessible
            else "report-time weather access unavailable"
        )
    return {
        "state": "UNAVAILABLE",
        "venue": venue,
        "kickoff": kickoff,
        "weather": None,
        "visible_row": {
            "fixture": fixture or "UNAVAILABLE",
            "venue": venue or "UNAVAILABLE",
            "kickoff": kickoff or "UNAVAILABLE",
            "condition": "UNAVAILABLE",
            "temperature_c": "UNAVAILABLE",
            "temperature": "UNAVAILABLE",
            "precipitation_probability": "UNAVAILABLE",
            "precipitation_chance_pct": "UNAVAILABLE",
            "wind_kph": "UNAVAILABLE",
            "wind_kmh": "UNAVAILABLE",
            "fpl_impact": "UNAVAILABLE",
            "impact_class": "UNAVAILABLE",
            "impact_reason": reason,
            "evidence_timestamp": "UNAVAILABLE",
            "weather_evidence_timestamp": "UNAVAILABLE",
        },
        "source_layer": "REPORT_TIME",
        "v6_weather_required": False,
        "degradation_reason": reason,
        "new_weather_model_created": False,
        "weather_adjusted_xpts": False,
        "weather_mutates_p_start": False,
        "weather_mutates_xmins": False,
        "weather_mutates_p1_6_tactical_score": False,
        "weather_failure_isolated_to_weather": True,
        "weather_may_independently_create_action": False,
        "raw_provider_plumbing_visible": False,
    }

