from __future__ import annotations

"""V12 natural analytic/report orchestration.

This module does not acquire V6 data and does not own player mathematics.
It composes already-governed V12 analytic outputs into complete human-facing
report structures while keeping repository-Python execution truth separate
from ChatGPT/V12 analytic execution truth.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from src.engines.price_radar import (
    DISPLAY_TIMEZONE,
    MODEL_THRESHOLD as EXISTING_PRICE_MODEL_THRESHOLD,
    OFFICIAL_MAX_AGE_SECONDS,
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


def _price_freshness(
    evidence_timestamp: Any,
    *,
    as_of: Any = None,
) -> dict[str, Any]:
    observed = _parse_price_dt(evidence_timestamp)
    reference = _parse_price_dt(as_of)
    if as_of is None:
        return {
            "freshness_state": "UNASSESSED",
            "source_age_seconds": None,
            "freshness_threshold_seconds": OFFICIAL_MAX_AGE_SECONDS,
        }
    if observed is None or reference is None:
        return {
            "freshness_state": "UNAVAILABLE",
            "source_age_seconds": None,
            "freshness_threshold_seconds": OFFICIAL_MAX_AGE_SECONDS,
        }
    age = max(
        0,
        int(
            (
                reference.astimezone(timezone.utc)
                - observed.astimezone(timezone.utc)
            ).total_seconds()
        ),
    )
    return {
        "freshness_state": (
            "FRESH" if age <= OFFICIAL_MAX_AGE_SECONDS else "STALE"
        ),
        "source_age_seconds": age,
        "freshness_threshold_seconds": OFFICIAL_MAX_AGE_SECONDS,
    }


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
    as_of: Any = None,
) -> dict[str, Any]:
    out = dict(row)
    freshness = _price_freshness(
        evidence_timestamp,
        as_of=as_of,
    )
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
            "estimate_source": "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR",
            "artifact_source": "official_price_predictor",
            "visible_source_label": (
                "Official FPL Price Change Predictor — official predictor guidance; "
                "not a guarantee of the next confirmed price change"
            ),
            "evidence_timestamp": evidence_timestamp or "UNAVAILABLE",
            **freshness,
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
                as_of=as_of,
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
    as_of: Any = None,
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
    freshness = _price_freshness(
        evidence_timestamp,
        as_of=as_of,
    )
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
                as_of=as_of,
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

    artifact_payload_hash = hashlib.sha256(
        json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()

    enough = len(selected) == 20
    healthy = (
        health in {"GREEN", "HEALTHY", "PASS", "CURRENT", "OK"}
        and freshness["freshness_state"] in {"FRESH", "UNASSESSED"}
    )
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
    invalid_eta_state = (
        adapter == "V6_DATA_PLAYERS_OFFSET0"
        and any(
            row.get("date_state") == "DATE_UNAVAILABLE"
            or bool(row.get("degradation_reason"))
            for row in selected
        )
    )
    # NO_CROSSING_WITHIN_GOVERNED_HORIZON is a healthy terminal predictor
    # outcome. It intentionally leaves expected-change-cycle fields unavailable
    # because no governed threshold crossing exists; that is not degradation.
    if enough and healthy and date_state_complete and not missing_cycle_clock and not invalid_eta_state:
        state = "COMPLETE"
    elif selected:
        state = "DEGRADED"
    else:
        state = "UNAVAILABLE"

    reason = None
    if state != "COMPLETE":
        if freshness["freshness_state"] == "STALE":
            reason = (
                "official_price_predictor evidence is stale: "
                f"age_seconds={freshness['source_age_seconds']} "
                f"> governed_max={freshness['freshness_threshold_seconds']}"
            )
        elif freshness["freshness_state"] == "UNAVAILABLE" and as_of is not None:
            reason = "official_price_predictor freshness cannot be established"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and not enough:
            reason = (
                f"official_price_predictor health={health}; "
                f"usable offset-0 {direction_token.lower()} rows={len(selected)}/20"
            )
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and not date_state_complete:
            incomplete = sum(not bool(row.get("date_state_complete")) for row in selected)
            reason = f"date-state terminal contract incomplete for {incomplete}/20 rows"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and missing_cycle_clock:
            reason = "official_price_predictor evidence timestamp unavailable; official cycle timing cannot be derived"
        elif adapter == "V6_DATA_PLAYERS_OFFSET0" and invalid_eta_state:
            invalid = sum(
                row.get("date_state") == "DATE_UNAVAILABLE"
                or bool(row.get("degradation_reason"))
                for row in selected
            )
            reason = (
                f"official_price_predictor has genuinely unavailable/invalid ETA evidence "
                f"for {invalid}/20 rows"
            )
        else:
            reason = (
                f"official_price_predictor health={health}; "
                f"{direction_token.lower()} rows={len(selected)}/20"
            )
    return {
        "state": state,
        "available_count": len(selected),
        "expected_count": 20,
        "usable_eligible_rows": usable_count,
        "rows": selected,
        "predictor_health": health,
        **freshness,
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
        "predictor_payload_hash": artifact_payload_hash,
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
    as_of: Any = None,
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
    freshness = _price_freshness(
        evidence_timestamp,
        as_of=as_of,
    )
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
                "estimate_source": (visible or {}).get("estimate_source", "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR" if pred_raw else "UNAVAILABLE"),
                "artifact_source": (visible or {}).get("artifact_source", "official_price_predictor" if pred_raw else "UNAVAILABLE"),
                "visible_source_label": (visible or {}).get(
                    "visible_source_label",
                    "Official FPL Price Change Predictor — official predictor guidance; not a guarantee of the next confirmed price change"
                    if pred_raw
                    else "UNAVAILABLE",
                ),
                "evidence_timestamp": (visible or {}).get("evidence_timestamp", evidence_timestamp or "UNAVAILABLE"),
                "source_age_seconds": (visible or {}).get(
                    "source_age_seconds",
                    freshness.get("source_age_seconds"),
                ),
                "freshness_state": (visible or {}).get(
                    "freshness_state",
                    freshness.get("freshness_state"),
                ),
                "freshness_threshold_seconds": (visible or {}).get(
                    "freshness_threshold_seconds",
                    freshness.get("freshness_threshold_seconds"),
                ),
                "confidence": (visible or {}).get("confidence", "UNAVAILABLE"),
                "sell_value_affordability_impact": (visible or {}).get(
                    "impact_on_our_decision",
                    "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; DO NOT FABRICATE PRICE ACTION",
                ),
                "decision_implication": (
                    "STALE PREDICTOR — DO NOT TREAT PRICE SIGNAL AS LIVE"
                    if freshness.get("freshness_state") == "STALE"
                    else (visible or {}).get(
                        "impact_on_our_decision",
                        "OWNED — PREDICTOR EVIDENCE UNAVAILABLE; FOOTBALL DECISION CONTINUES",
                    )
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
        **freshness,
        "degradation_reason": (
            "official_price_predictor evidence is stale"
            if freshness.get("freshness_state") == "STALE"
            else None
            if complete
            else "owned price identity coverage is not exact15"
        ),
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


def build_contextual_player_blocks(
    player_projection: Mapping[str, Any],
    *,
    fixture: Any | None = None,
) -> dict[str, Any]:
    """Nested human-facing player detail without changing DEEP top-level count."""
    contextual = dict(player_projection.get("contextual_dynamics") or {})
    fixture_contexts = [
        dict(row)
        for row in contextual.get("fixture_contexts") or []
        if isinstance(row, Mapping)
    ]
    selected = None
    if fixture is not None:
        selected = next(
            (
                row
                for row in fixture_contexts
                if str(row.get("fixture")) == str(fixture)
            ),
            None,
        )
    if selected is None and fixture_contexts:
        selected = fixture_contexts[0]
    if selected is None:
        return {
            "state": "UNAVAILABLE",
            "degradation_reason": "contextual trajectory/matchup evidence unavailable",
            "blocks": {},
        }

    matchup = dict(selected.get("matchup") or {})
    network = dict(selected.get("linkup_network") or {})
    relationships = [
        dict(row)
        for row in network.get("relationships") or []
        if isinstance(row, Mapping)
        and float(row.get("confidence") or 0.0) > 0.0
    ]
    relationships.sort(
        key=lambda row: (
            float(row.get("confidence") or 0.0),
            float(row.get("dependency_strength") or 0.0),
        ),
        reverse=True,
    )
    chains = [
        dict(row)
        for row in network.get("multi_player_chains") or []
        if isinstance(row, Mapping)
        and row.get("status") == "AVAILABLE"
        and float(row.get("confidence") or 0.0) > 0.0
    ]
    chains.sort(
        key=lambda row: (
            float(row.get("confidence") or 0.0),
            abs(float(row.get("multiplier") or 1.0) - 1.0),
        ),
        reverse=True,
    )
    return {
        "state": "COMPLETE",
        "fixture": selected.get("fixture"),
        "trajectory_classification": selected.get(
            "trajectory_classification"
        ),
        "latest_match_evidence": selected.get("latest_match_evidence"),
        "blocks": {
            "OPPONENT-SPECIFIC MATCHUP": {
                "historical_meetings": matchup.get("historical_meetings"),
                "result_evidence": (
                    matchup.get("result_process") or {}
                ).get("result_evidence"),
                "process_evidence": (
                    matchup.get("result_process") or {}
                ).get("process_evidence"),
                "tactical_similarity": matchup.get("tactical_similarity"),
                "sample_size": matchup.get("sample_size"),
                "bayesian_confidence": matchup.get("sample_shrinkage"),
                "current_relevance": matchup.get("tactical_similarity"),
                "classification": matchup.get("classification"),
                "opponent_history_scope": matchup.get("opponent_history_scope"),
                "prior_season_matchup_status": matchup.get(
                    "prior_season_matchup_status"
                ),
                "prior_season_meetings": matchup.get(
                    "prior_season_meetings"
                ),
            },
            "LINK-UP / COMBINATION NETWORK": {
                "PAIRWISE LINKS": relationships,
                "relationships": relationships,
                "relationship_count": len(relationships),
                "MULTI-PLAYER CHAINS": chains,
                "multi_player_chains": chains,
                "chain_count": len(chains),
                "insufficient_pairs_suppressed": True,
                "low_confidence_chains_suppressed": True,
            },
        },
    }


def build_post_match_universe_movers(
    post_match_scan: Mapping[str, Any] | None,
    *,
    post_match_deep_analysis: Mapping[str, Any] | None = None,
    limit_per_category: int = 5,
) -> dict[str, Any]:
    """Compact POST-MATCH Universe Movers block from the V12 broad scan.

    The block is descriptive evidence only. It does not create a transfer or
    mutate WAIT/PREPARE/ACT.
    """
    scan = dict(post_match_scan or {})
    deep = dict(post_match_deep_analysis or scan.get("deep_execution") or {})
    executed_ids = {
        int(value)
        for value in deep.get("executed_element_ids") or []
        if value is not None
    }
    players = [
        dict(row)
        for row in scan.get("material_players") or []
        if isinstance(row, Mapping)
    ]
    limit = max(1, int(limit_per_category))

    category_rules = (
        (
            "BREAKOUT / CONFIRMATION",
            {"BREAKOUT_PROCESS", "OUTPUT_CONFIRMING_PROCESS"},
        ),
        (
            "PROCESS UP — RETURNS NOT YET ARRIVED",
            {"UNDERLYING_IMPROVING_NO_RETURN"},
        ),
        (
            "ROLE / MINUTES RISERS",
            {"ROLE_BREAKOUT", "MINUTES_BREAKOUT", "SET_PIECE_GAIN"},
        ),
        (
            "LINK-UP RISERS",
            {"LINKUP_BREAKOUT"},
        ),
        (
            "REGRESSION / SELL-RISK",
            {
                "REGRESSION_RISK",
                "ROLE_DECLINE",
                "MINUTES_DECLINE",
                "LINKUP_BROKEN",
            },
        ),
        (
            "NOISE / DO NOT CHASE",
            {"OUTPUT_WITHOUT_PROCESS"},
        ),
    )

    def compact(row: Mapping[str, Any]) -> dict[str, Any]:
        latest = dict(row.get("latest_match") or {})
        comparison = dict(row.get("universe_comparison") or {})
        return {
            "element_id": row.get("element_id"),
            "name": row.get("name"),
            "position": row.get("position"),
            "owned": bool(row.get("owned")),
            "primary_classification": row.get("primary_classification"),
            "classifications": list(row.get("classifications") or []),
            "materiality_score": row.get("materiality_score"),
            "latest_fpl_points": latest.get("fpl_points"),
            "latest_xgi": latest.get("xgi"),
            "xmins_delta": (row.get("xmins") or {}).get("delta"),
            "p_start_delta": (row.get("p_start") or {}).get("delta"),
            "universe_comparison_state": comparison.get("state"),
            "published_position_pool_rank": comparison.get(
                "published_position_pool_rank"
            ),
            "beats_hold_in_any_published_package": comparison.get(
                "beats_hold_in_any_published_package"
            ),
            "deep_detail": (
                bool(row.get("deep_detail_available"))
                or int(row.get("element_id") or -1) in executed_ids
            ),
            "automatic_transfer_recommendation": False,
        }

    categories: dict[str, list[dict[str, Any]]] = {}
    for label, accepted in category_rules:
        rows = [
            row
            for row in players
            if accepted.intersection(set(row.get("classifications") or []))
        ]
        rows.sort(
            key=lambda row: (
                float(row.get("materiality_score") or 0.0),
                bool(
                    (row.get("universe_comparison") or {}).get(
                        "beats_hold_in_any_published_package"
                    )
                ),
                -int(
                    (row.get("universe_comparison") or {}).get(
                        "published_position_pool_rank"
                    )
                    or 999
                ),
            ),
            reverse=True,
        )
        categories[label] = [compact(row) for row in rows[:limit]]

    comparison = dict(scan.get("universe_comparison") or {})
    scanned_count = int(scan.get("scanned_count") or 0)
    eligible_count = int(scan.get("eligible_count") or 0)
    search_authority = str(comparison.get("search_authority") or "").upper()
    if not scan:
        state = "UNAVAILABLE"
        reason = "post-match full-universe scan unavailable"
    elif scanned_count <= 0:
        state = "DEGRADED"
        reason = "eligible universe scan returned zero supportable players"
    elif (
        (eligible_count > 0 and scanned_count < eligible_count)
        or search_authority == "PARTIAL"
    ):
        state = "DEGRADED"
        reason = (
            "post-match universe coverage/search authority is partial; "
            f"scanned={scanned_count}/{eligible_count or 'UNKNOWN'} "
            f"search_authority={search_authority or 'UNAVAILABLE'}"
        )
    else:
        state = "COMPLETE"
        reason = None

    return {
        "state": state,
        "degradation_reason": reason,
        "title": "UNIVERSE MOVERS",
        "scope": scan.get("scope"),
        "scanned_count": scan.get("scanned_count"),
        "eligible_count": scan.get("eligible_count"),
        "material_count": scan.get("material_count"),
        "summary": (
            "NO MATERIAL MOVERS"
            if scan and int(scan.get("material_count") or 0) == 0
            else None
        ),
        "search_authority": comparison.get("search_authority"),
        "missing_scope": (
            comparison.get("missing_scope")
            or (
                None
                if state == "COMPLETE"
                else "PARTIAL_OR_UNAVAILABLE_UNIVERSE_EVIDENCE"
            )
        ),
        "deep_requested_count": deep.get("deep_requested_count"),
        "deep_executed_count": deep.get("deep_executed_count"),
        "deep_deferred_count": deep.get("deep_deferred_count"),
        "deep_execution_scope": deep.get("deep_execution_scope"),
        "categories": categories,
        "deep_detail_element_ids": list(
            scan.get("deep_analysis_element_ids") or []
        ),
        "full_universe_comparison": scan.get("universe_comparison"),
        "governance": {
            "scorer_assister_only_scouting_prohibited": True,
            "non_scorers_can_surface": True,
            "one_match_haul_never_creates_act": True,
            "deep_detail_materiality_gated": True,
            "full_universe_comparison_required_before_transfer": True,
            "operational_action_enum_unchanged": "WAIT_PREPARE_ACT",
        },
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


_DEEP_LEGACY_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "S01": ("Decision/status",),
    "S02": ("OUR15",),
    "S03": ("DECISION DELTA",),
    "S04": ("Changes",),
    "S05": ("Fixtures/rest/conditions",),
    "S06": ("Formation/XI/bench",),
    "S07": ("XI battle",),
    "S08": ("C/VC",),
    "S09": ("Chip",),
    "S10": ("Actionable Price Radar",),
    "S11": ("Watchlist20 exact20",),
    "S12": ("RISE20 exact20 where required",),
    "S13": ("FALL20 exact20 where required",),
    "S14": ("Package optimizer/frontier including HOLD baseline",),
    "S15": ("Evidence quality",),
    "S15B": ("ICON+ mini-league",),
    "S16": ("ALL15 exact15 next-GW tactical/probability table",),
    "S17": ("Source health/freshness/lineage",),
    "S18": ("WAIT/PREPARE/ACT + trigger/reversal",),
    "S19": ("Final judgement",),
}


def _payload_for_section(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    section_id: str,
    label: str,
) -> Mapping[str, Any] | None:
    direct = payloads.get(section_id) or payloads.get(label)
    if direct is not None:
        return direct
    for alias in _DEEP_LEGACY_LABEL_ALIASES.get(section_id, ()):
        if alias in payloads:
            return payloads[alias]
    return None


def _locked_default(
    section_id: str,
    label: str,
    locked_state: Mapping[str, Any],
) -> dict[str, Any] | None:
    sid = str(section_id or "").upper()
    if sid == "S06":
        raw_bench = locked_state.get("bench")
        if isinstance(raw_bench, Mapping):
            bench = dict(raw_bench)
        else:
            bench_rows = list(raw_bench or [])
            bench = {
                "gk": bench_rows[0] if bench_rows else None,
                "order": bench_rows[1:4],
            }
        return {
            "state": "COMPLETE",
            "content": {
                "status": "GW LOCKED — NO EXECUTABLE XI CHANGE",
                "formation": locked_state.get("formation"),
                "starting_xi": locked_state.get("xi"),
                "xi": locked_state.get("xi"),
                "bench": bench,
                "lineup_score": {"state": "LOCKED"},
                "formation_comparison": [],
            },
        }
    if sid == "S07":
        return {
            "state": "COMPLETE",
            "content": {
                "status": "GW LOCKED — XI battle retained as factual locked state",
                "battles": [],
                "empty_is_truthful": True,
            },
        }
    if sid == "S08":
        return {
            "state": "COMPLETE",
            "content": {
                "status": "LOCKED",
                "captain": locked_state.get("captain"),
                "vice_captain": locked_state.get("vice_captain"),
            },
        }
    if sid == "S09":
        return {
            "state": "COMPLETE",
            "content": {"status": "LOCKED", "chip": locked_state.get("chip")},
        }
    return None


def _materialize_canonical_report(
    *,
    canonical_text: str,
    structural_mode: str,
    reported_mode: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
    universe_movers: Mapping[str, Any] | None = None,
    universe_movers_target_label: str | None = None,
) -> dict[str, Any]:
    """One existing V12 structural materializer used by DEEP and post-match."""
    contract = canonical_mode_contract(canonical_text, structural_mode)
    payloads = dict(section_payloads or {})
    sections: list[dict[str, Any]] = []
    locked = dict(locked_state or {})
    mover_attachments = 0

    for section_id, label in zip(
        contract["expected_section_ids"],
        contract["expected_visible_order"],
    ):
        raw = _payload_for_section(
            payloads,
            section_id=section_id,
            label=label,
        )
        if raw is None and current_gw_locked:
            raw = _locked_default(section_id, label, locked)
        if raw is None:
            raw = {
                "state": "UNAVAILABLE",
                "degradation_reason": "current authoritative evidence unavailable",
                "content": None,
            }
        row = dict(raw)
        state = _status(row.get("state"), label=section_id)
        if state != "COMPLETE" and not str(
            row.get("degradation_reason") or ""
        ).strip():
            raise ReportOrchestrationError(
                f"{section_id} degraded/unavailable section requires reason"
            )
        content = row.get("content")
        if state == "COMPLETE" and (
            content is None
            or content == ""
            or content == {}
            or content == []
        ):
            state = "DEGRADED"
            row["degradation_reason"] = (
                "section declared COMPLETE but no human-facing content was materialized"
            )
        if section_id == "S03" and str(checkpoint_time or "") == "12:30":
            content = dict(content or {})
            content["signal_delta_since_0430"] = dict(
                signal_delta
                or {
                    "status": "BASELINE UNAVAILABLE",
                    "rows": [],
                }
            )
        if (
            universe_movers is not None
            and universe_movers_target_label
            and (
                str(section_id).upper()
                == str(universe_movers_target_label).upper()
                or str(label).upper()
                == str(universe_movers_target_label).upper()
            )
        ):
            content = dict(content or {})
            if "universe_movers" in content:
                raise ReportOrchestrationError(
                    "UNIVERSE MOVERS may be attached only once"
                )
            content["universe_movers"] = dict(universe_movers)
            mover_attachments += 1
        if "PACKAGE OPTIMIZER" in str(label or "").upper() and state == "COMPLETE":
            package_failures = _package_frontier_contract_failures(
                content if isinstance(content, Mapping) else None
            )
            if package_failures:
                state = "DEGRADED"
                row["degradation_reason"] = (
                    "full-universe package/frontier visible contract incomplete: "
                    + ",".join(package_failures)
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

    if universe_movers is not None and mover_attachments != 1:
        raise ReportOrchestrationError(
            "natural post-match report must attach UNIVERSE MOVERS exactly once"
        )
    return {
        "report_mode": reported_mode,
        "structural_mode": structural_mode,
        "sections": sections,
        "rendered_section_ids": [row["section_id"] for row in sections],
        "rendered_visible_order": [row["label"] for row in sections],
        "exact_canonical_order": [row["section_id"] for row in sections]
        == contract["expected_section_ids"],
        "numbered_headings": 19 if structural_mode == "DEEP" else len(sections),
        "rendered_blocks_including_suffix_sections": len(sections), 
        "rendered_blocks_including_15B": len(sections),
        "universe_movers_attachment_count": mover_attachments,
        "universe_movers_visible": mover_attachments == 1,
    }


def build_visible_mathematical_decision_stack(
    decision_proof: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Expose existing V12 decision evidence without recomputing any model."""
    proof = dict(decision_proof or {})
    probability = dict(proof.get("probability_state") or {})
    unconditional = dict(probability.get("unconditional") or {})
    xmins = dict(proof.get("xmins_distribution") or {})
    horizons = dict(proof.get("horizons") or {})
    robustness = dict(proof.get("robustness") or {})
    posterior_predictive = dict(proof.get("posterior_predictive") or {})
    event_probabilities = dict(
        posterior_predictive.get("event_probabilities")
        or proof.get("event_probabilities")
        or proof.get("posterior_predictive_event_probabilities")
        or {}
    )
    point_distribution = dict(
        posterior_predictive.get("point_distribution") or {}
    )
    mc = dict(proof.get("monte_carlo") or {})
    missing: list[str] = []
    if not proof.get("bayesian_shrinkage_lineage"):
        missing.append("bayesian_shrinkage_lineage")
    if not unconditional:
        missing.append("availability_mixture")
    if not xmins:
        missing.append("xmins_distribution")
    if not event_probabilities:
        missing.append("event_probabilities")
    if not horizons:
        missing.append("horizons")
    if not robustness:
        missing.append("robustness")
    if not mc:
        missing.append("monte_carlo")

    def event_value(*keys: str) -> Any:
        for key in keys:
            if key in event_probabilities:
                return event_probabilities.get(key)
        return "UNAVAILABLE"

    def distribution_value(*keys: str) -> Any:
        for key in keys:
            if key in point_distribution:
                return point_distribution.get(key)
        return "UNAVAILABLE"

    return {
        "state": "COMPLETE" if not missing else ("PARTIAL" if proof else "UNAVAILABLE"),
        "missing_scope": missing,
        "bayesian_prior_posterior_shrinkage": (
            proof.get("bayesian_shrinkage_lineage") or "UNAVAILABLE"
        ),
        "availability_mixture": {
            "p_available": unconditional.get("p_available", "UNAVAILABLE"),
            "p_start": unconditional.get("p_start", "UNAVAILABLE"),
            "p_bench": unconditional.get("p_bench", "UNAVAILABLE"),
            "p_cameo": unconditional.get("p_cameo", "UNAVAILABLE"),
            "p_late_cameo": unconditional.get("p_late_cameo", "UNAVAILABLE"),
            "p_dnp": unconditional.get("p_dnp", "UNAVAILABLE"),
        },
        "xmins_distribution": xmins or "UNAVAILABLE",
        "event_probabilities": {
            "p_goal": event_value(
                "p_goal_return", "p_goal", "goal"
            ),
            "p_assist": event_value(
                "p_assist_return", "p_assist", "assist"
            ),
            "p_return": event_value(
                "p_attacking_return", "p_return", "return"
            ),
            "p_two_plus_returns": event_value(
                "p_total_ga_ge_2",
                "p_multiple_attacking_returns",
                "p_two_plus_returns",
                "p_2_plus_returns",
                "two_plus_returns",
            ),
            "p_haul": distribution_value(
                "p_haul_10_plus", "p_haul", "haul"
            ),
            "p_blank": distribution_value(
                "p_fpl_blank", "p_blank", "blank"
            ),
            "p_no_attacking_return": event_value(
                "p_no_attacking_return"
            ),
        },
        "point_distribution": point_distribution or "UNAVAILABLE",
        "posterior_predictive_source": (
            posterior_predictive.get("source_contract")
            or "UNAVAILABLE"
        ),
        "horizons": horizons or "UNAVAILABLE",
        "p_outperform": robustness.get(
            "p_outperform",
            proof.get("p_outperform", "UNAVAILABLE"),
        ),
        "expected_regret": robustness.get(
            "expected_regret",
            proof.get("expected_regret", "UNAVAILABLE"),
        ),
        "tail_risk": {
            "conditional_floor": robustness.get(
                "conditional_floor", "UNAVAILABLE"
            ),
            "upper_tail": robustness.get("upper_tail", "UNAVAILABLE"),
        },
        "information_value_of_waiting": proof.get(
            "information_value_of_waiting", "UNAVAILABLE"
        ),
        "covariance_correlation": (
            proof.get("covariance_correlation")
            or proof.get("correlation")
            or "UNAVAILABLE"
        ),
        "monte_carlo": mc or {
            "execution_state": "UNAVAILABLE",
            "reason": "NO OCCURRENCE-BOUND MONTE CARLO EVIDENCE",
        },
    }


def _render_match_scout_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = ["### POST-MATCH MATCH-BY-MATCH SCOUT"]
    labels = (
        ("result", "RESULT"),
        ("formation_system", "FORMATION/SYSTEM"),
        ("coach_pattern", "COACH PATTERN"),
        ("player_roles", "PLAYER ROLES"),
        ("minutes_substitution_pattern", "MINUTES/SUBS"),
        ("xg_xa_xgi_shots_chances", "xG/xA/xGI/SHOTS/CHANCES"),
        ("set_pieces_penalties", "SET PIECES/PENALTIES"),
        ("defcon", "DEFCON"),
        ("opponent_channels", "OPPONENT CHANNELS"),
        ("sustainable_vs_noisy", "SUSTAINABLE VS NOISE"),
        ("implication_for_our15", "OUR15 IMPLICATION"),
        ("implication_for_next_opponent", "NEXT OPPONENT IMPLICATION"),
        (
            "posterior_calibration_implication",
            "POSTERIOR CALIBRATION IMPLICATION",
        ),
    )
    for row in rows:
        fixture_id = row.get("fixture_id", "UNAVAILABLE")
        lines.append(f"#### FIXTURE ID: {fixture_id}")
        for field, label in labels:
            value = row.get(field, "UNAVAILABLE")
            lines.append(f"{label}: {value}")
    return lines


def _render_math_stack_lines(stack: Mapping[str, Any]) -> list[str]:
    payload = dict(stack or {})

    def mapping_or_empty(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    availability = mapping_or_empty(payload.get("availability_mixture"))
    events = mapping_or_empty(payload.get("event_probabilities"))
    point_distribution = mapping_or_empty(payload.get("point_distribution"))
    mc = mapping_or_empty(payload.get("monte_carlo"))
    lines = [
        "### MATHEMATICAL DECISION STACK",
        "BAYESIAN PRIOR -> POSTERIOR / SHRINKAGE: "
        f"{payload.get('bayesian_prior_posterior_shrinkage', 'UNAVAILABLE')}",
        "AVAILABILITY MIXTURE: "
        f"P(AVAILABLE)={availability.get('p_available', 'UNAVAILABLE')} | "
        f"P(START)={availability.get('p_start', 'UNAVAILABLE')} | "
        f"P(BENCH)={availability.get('p_bench', 'UNAVAILABLE')} | "
        f"P(CAMEO)={availability.get('p_cameo', 'UNAVAILABLE')} | "
        f"P(LATE CAMEO)={availability.get('p_late_cameo', 'UNAVAILABLE')} | "
        f"P(DNP)={availability.get('p_dnp', 'UNAVAILABLE')}",
        f"XMINS DISTRIBUTION: {payload.get('xmins_distribution', 'UNAVAILABLE')}",
        "EVENT PROBABILITIES: "
        f"P(GOAL)={events.get('p_goal', 'UNAVAILABLE')} | "
        f"P(ASSIST)={events.get('p_assist', 'UNAVAILABLE')} | "
        f"P(RETURN)={events.get('p_return', 'UNAVAILABLE')} | "
        f"P(2+ RETURNS)={events.get('p_two_plus_returns', 'UNAVAILABLE')} | "
        f"P(HAUL)={events.get('p_haul', 'UNAVAILABLE')} | "
        f"P(BLANK)={events.get('p_blank', 'UNAVAILABLE')} | "
        f"P(NO ATTACK RETURN)={events.get('p_no_attacking_return', 'UNAVAILABLE')}",
        "P1.3B POINT DISTRIBUTION: "
        f"source={payload.get('posterior_predictive_source', 'UNAVAILABLE')} | "
        f"E[xPts]={point_distribution.get('expected_points', 'UNAVAILABLE')} | "
        f"variance={point_distribution.get('variance', 'UNAVAILABLE')} | "
        f"std={point_distribution.get('std', 'UNAVAILABLE')} | "
        f"quantiles={point_distribution.get('quantiles', 'UNAVAILABLE')} | "
        f"tails={point_distribution.get('tails', 'UNAVAILABLE')}",
        f"HORIZONS 1GW / 3GW / 5GW: {payload.get('horizons', 'UNAVAILABLE')}",
        f"P(OUTPERFORM HOLD/COMPARATOR): {payload.get('p_outperform', 'UNAVAILABLE')}",
        f"EXPECTED REGRET: {payload.get('expected_regret', 'UNAVAILABLE')}",
        f"TAIL / FLOOR / CEILING: {payload.get('tail_risk', 'UNAVAILABLE')}",
        "INFORMATION VALUE OF WAITING: "
        f"{payload.get('information_value_of_waiting', 'UNAVAILABLE')}",
        f"COVARIANCE / CORRELATION: {payload.get('covariance_correlation', 'UNAVAILABLE')}",
        "MONTE CARLO: "
        f"state={mc.get('execution_state', 'UNAVAILABLE')} | "
        f"N={mc.get('actual_paths', 'UNAVAILABLE')} | "
        f"correlated={mc.get('correlated', 'UNAVAILABLE')} | "
        f"reason={mc.get('reason', mc.get('degradation_reason', 'UNAVAILABLE'))} | "
        f"convergence={mc.get('convergence_evidence', 'UNAVAILABLE')}",
    ]
    return lines


def _package_frontier_contract_failures(content: Mapping[str, Any] | None) -> list[str]:
    """Validate visible package/full-universe evidence without creating new ranking math."""
    payload = dict(content or {})
    proof = payload.get("package_search_proof") or payload.get("search_proof")
    challengers = list(
        payload.get("package_universe_challengers")
        or payload.get("universe_challengers")
        or ()
    )
    routes = list(
        payload.get("package_routes")
        or payload.get("routes")
        or payload.get("frontier")
        or ()
    )
    failures: list[str] = []
    if not isinstance(proof, Mapping):
        failures.append("SEARCH_PROOF_MISSING")
    else:
        try:
            owned_expected = int(proof.get("owned_expected"))
            owned_evaluated = int(proof.get("owned_evaluated"))
            universe_expected = int(proof.get("eligible_universe_expected"))
            universe_evaluated = int(proof.get("eligible_universe_evaluated"))
            outgoing = int(proof.get("outgoing_candidate_count"))
            legal_routes = int(proof.get("legal_route_count"))
        except (TypeError, ValueError):
            failures.append("SEARCH_PROOF_NUMERIC_INVALID")
        else:
            if owned_expected != 15 or owned_evaluated != 15:
                failures.append(f"OUR15={owned_evaluated}/{owned_expected}")
            if universe_expected <= 0 or universe_evaluated != universe_expected:
                failures.append(f"UNIVERSE={universe_evaluated}/{universe_expected}")
            if outgoing != 15:
                failures.append(f"OUTGOING={outgoing}/15")
            if legal_routes <= 0:
                failures.append("LEGAL_ROUTES=0")
        if proof.get("hold_included") is not True:
            failures.append("HOLD_MISSING")
        if proof.get("lossy_pruning") is not False:
            failures.append("LOSSY_PRUNING")
        if str(proof.get("search_authority") or "").upper() != "FULL":
            failures.append("SEARCH_AUTHORITY_NOT_FULL")
    if not challengers:
        failures.append("SCAN_DERIVED_CHALLENGERS_MISSING")
    if not routes:
        failures.append("PACKAGE_ROUTES_MISSING")
    elif not any(
        str(row.get("route") or "").upper() == "HOLD"
        for row in routes
        if isinstance(row, Mapping)
    ):
        failures.append("HOLD_ROUTE_MISSING")
    return failures


def _render_package_frontier_lines(
    content: Mapping[str, Any] | None,
    *,
    section_state: str,
) -> list[str]:
    """Render the full-universe team-impact surface without recomputing models."""
    payload = dict(content or {})
    proof = dict(
        payload.get("package_search_proof")
        or payload.get("search_proof")
        or {}
    )
    challengers = [
        dict(row)
        for row in (
            payload.get("package_universe_challengers")
            or payload.get("universe_challengers")
            or ()
        )
        if isinstance(row, Mapping)
    ]
    routes = [
        dict(row)
        for row in (
            payload.get("package_routes")
            or payload.get("routes")
            or payload.get("frontier")
            or ()
        )
        if isinstance(row, Mapping)
    ]
    lines = ["### UNIVERSE SCAN / OPTIMAL TEAM IMPACT"]
    if proof:
        lines.append(
            "SEARCH PROOF: "
            f"OUR15 {proof.get('owned_evaluated', 'UNAVAILABLE')}/"
            f"{proof.get('owned_expected', 'UNAVAILABLE')} | "
            f"UNIVERSE {proof.get('eligible_universe_evaluated', 'UNAVAILABLE')}/"
            f"{proof.get('eligible_universe_expected', 'UNAVAILABLE')} | "
            f"OUTGOING {proof.get('outgoing_candidate_count', 'UNAVAILABLE')}/15 | "
            f"LEGAL ROUTES {proof.get('legal_route_count', 'UNAVAILABLE')} | "
            f"HOLD {proof.get('hold_included', 'UNAVAILABLE')} | "
            f"LOSSY PRUNING {proof.get('lossy_pruning', 'UNAVAILABLE')} | "
            f"AUTHORITY {proof.get('search_authority', 'UNAVAILABLE')}"
        )
    else:
        lines.append(
            f"SEARCH PROOF: {section_state} — current full-universe proof unavailable"
        )

    lines.append("#### SCAN-DERIVED CHALLENGERS")
    if not challengers:
        lines.append("UNAVAILABLE — no supportable scan-derived challenger rows")
    for row in challengers:
        components = row.get("football_score_components", "UNAVAILABLE")
        distribution = row.get("expected_points_distribution", "UNAVAILABLE")
        lines.append(
            "- "
            f"#{row.get('rank', 'NA')} {row.get('player') or row.get('element_id')} "
            f"({row.get('position', 'NA')}, {row.get('club', 'NA')}) | "
            f"BEST OUT {row.get('best_outgoing', 'UNAVAILABLE')} | "
            f"ROUTE {row.get('package_route', 'UNAVAILABLE')} | "
            f"FOOTBALL {row.get('football_score', 'UNAVAILABLE')} "
            f"[20/25/30/25={components}] | "
            f"P(avail/start/cameo/DNP)="
            f"{row.get('p_available', 'UNAVAILABLE')}/"
            f"{row.get('p_start', 'UNAVAILABLE')}/"
            f"{row.get('p_cameo', 'UNAVAILABLE')}/"
            f"{row.get('p_dnp', 'UNAVAILABLE')} | "
            f"xMins {row.get('xmins', 'UNAVAILABLE')} | "
            f"P(return/blank/haul)="
            f"{row.get('p_return', 'UNAVAILABLE')}/"
            f"{row.get('p_blank', 'UNAVAILABLE')}/"
            f"{row.get('p_haul', 'UNAVAILABLE')} | "
            f"xPtsDist {distribution} | "
            f"TACTICAL {row.get('tactical_role', 'UNAVAILABLE')} | "
            f"SP/PEN {row.get('set_piece_penalty_role', 'UNAVAILABLE')} | "
            f"1GW {row.get('gw_plus_1', 'UNAVAILABLE')} | "
            f"3GW {row.get('three_gw', 'UNAVAILABLE')} | "
            f"5GW {row.get('five_gw', 'UNAVAILABLE')} | "
            f"UTILITY ΔHOLD {row.get('package_utility_delta_vs_hold', 'UNAVAILABLE')} | "
            f"PRICE {row.get('price_economics', 'UNAVAILABLE')} | "
            f"STRUCTURE {row.get('structure_effect', 'UNAVAILABLE')} | "
            f"REGRET {row.get('expected_regret', 'UNAVAILABLE')} | "
            f"IVW {row.get('information_value_of_waiting', 'UNAVAILABLE')} | "
            f"ICON+ {row.get('mini_league_leverage', 'UNAVAILABLE')} | "
            f"UPSIDE {row.get('main_upside', 'UNAVAILABLE')} | "
            f"RISK {row.get('main_risk', 'UNAVAILABLE')} | "
            f"ACTION {row.get('action', 'UNAVAILABLE')}"
        )

    lines.append("#### PACKAGE FRONTIER")
    mc = dict(payload.get("monte_carlo") or {})
    lines.append(
        "MC PATHS: "
        f"{mc.get('actual_paths', 'UNAVAILABLE')} | "
        f"canonical_pass={mc.get('canonical_pass', 'UNAVAILABLE')} | "
        f"convergence={(mc.get('convergence_evidence') or {}).get('status', 'UNAVAILABLE')}"
    )
    if not routes:
        lines.append("UNAVAILABLE — package routes not materialized")

    def move_label(move: Mapping[str, Any]) -> str:
        return str(
            move.get("name")
            or move.get("player")
            or move.get("element")
            or "UNAVAILABLE"
        )

    for row in routes:
        moves_raw = row.get("moves")
        if isinstance(moves_raw, Mapping):
            moves = dict(moves_raw)
            outs = [
                dict(item) for item in moves.get("out") or []
                if isinstance(item, Mapping)
            ]
            ins = [
                dict(item) for item in moves.get("in") or []
                if isinstance(item, Mapping)
            ]
            structured_move_text = (
                ", ".join(move_label(item) for item in outs)
                + " → "
                + ", ".join(move_label(item) for item in ins)
            )
        else:
            moves = {}
            outs = []
            ins = []
            structured_move_text = (
                " | ".join(str(item) for item in (moves_raw or []))
                if isinstance(moves_raw, (list, tuple))
                else str(moves_raw or "UNAVAILABLE")
            )
        if str(row.get("route") or "").upper() == "HOLD":
            move_text = "HOLD → HOLD"
        else:
            move_text = structured_move_text
        outgoing_value = sum(
            float(item.get("sell_value"))
            for item in outs
            if item.get("sell_value") is not None
        ) if any(item.get("sell_value") is not None for item in outs) else None
        incoming_cost = sum(
            float(item.get("buy_price", item.get("price")))
            for item in ins
            if item.get("buy_price", item.get("price")) is not None
        ) if any(item.get("buy_price", item.get("price")) is not None for item in ins) else None
        transfer_cost_raw = row.get("transfer_cost")
        transfer_cost = (
            dict(transfer_cost_raw)
            if isinstance(transfer_cost_raw, Mapping)
            else {"legacy_value": transfer_cost_raw}
        )
        lines.append(
            "- "
            f"{row.get('route_kind', 'ROUTE')} | "
            f"{row.get('route', 'UNAVAILABLE')} | OUT → IN {move_text} | "
            f"SELL {outgoing_value if outgoing_value is not None else 'UNAVAILABLE'} | "
            f"BUY {incoming_cost if incoming_cost is not None else 'UNAVAILABLE'} | "
            f"BANK BEFORE {row.get('bank_before', 'UNAVAILABLE')} | "
            f"BANK AFTER {transfer_cost.get('bank_after', 'UNAVAILABLE')} | "
            f"AFFORDABILITY {row.get('affordability', 'UNAVAILABLE')} | "
            f"HIT/FT {transfer_cost} | "
            f"1GW {row.get('gw1_net', 'UNAVAILABLE')} | "
            f"2GW {row.get('two_gw_if_relevant', 'UNAVAILABLE')} | "
            f"3GW {row.get('three_gw', 'UNAVAILABLE')} | "
            f"5GW {row.get('five_gw', 'UNAVAILABLE')} | "
            f"RAW GAIN {row.get('raw_gain', 'UNAVAILABLE')} | "
            f"NET GAIN {row.get('net_gain', 'UNAVAILABLE')} | "
            f"P>HOLD {row.get('p_beats_hold', 'UNAVAILABLE')} | "
            f"Q10 {row.get('Q10', 'UNAVAILABLE')} | "
            f"Q25 {row.get('Q25', 'UNAVAILABLE')} | "
            f"MEDIAN {row.get('median', 'UNAVAILABLE')} | "
            f"Q75 {row.get('Q75', 'UNAVAILABLE')} | "
            f"Q90 {row.get('Q90', 'UNAVAILABLE')} | "
            f"TACTICAL/FIXTURE {row.get('tactical_fixture_effect', 'UNAVAILABLE')} | "
            f"PRICE/OPTIONALITY {row.get('price_risk', 'UNAVAILABLE')} | "
            f"ICON+ UTILITY {row.get('mini_league_utility', 'UNAVAILABLE')} | "
            f"REGRET {row.get('expected_regret', 'UNAVAILABLE')} | "
            f"ROBUSTNESS {row.get('robustness', 'UNAVAILABLE')} | "
            f"REVERSAL RISK {row.get('sensitivity', 'UNAVAILABLE')} | "
            f"VERDICT {row.get('action_verdict', 'UNAVAILABLE')}"
        )
    return lines


def materialize_deep_report(
    *,
    canonical_text: str,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
    post_all_match_scout: Sequence[Mapping[str, Any]] | None = None,
    mathematical_decision_stack: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Materialize Canonical DEEP plus nested post-match/math evidence when due."""
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode="DEEP",
        reported_mode="DEEP",
        section_payloads=section_payloads,
        checkpoint_time=checkpoint_time,
        signal_delta=signal_delta,
        current_gw_locked=current_gw_locked,
        locked_state=locked_state,
    )
    scout = [
        dict(row)
        for row in (post_all_match_scout or ())
        if isinstance(row, Mapping)
    ]
    if scout:
        target = next(
            (
                row
                for row in report["sections"]
                if str(row.get("section_id") or "").strip().upper() == "S04"
            ),
            None,
        )
        if target is None:
            raise ReportOrchestrationError(
                "DEEP Changes surface required for post-match scout carryover"
            )
        content = dict(target.get("content") or {})
        content["post_match_match_by_match_scout"] = scout
        target["content"] = content
        report["post_all_match_context"] = True
        report["completed_fixture_ids"] = [
            str(row.get("fixture_id")) for row in scout
        ]
    if mathematical_decision_stack:
        target = next(
            (
                row
                for row in report["sections"]
                if str(row.get("section_id") or "").strip().upper() == "S14"
            ),
            None,
        )
        if target is None:
            raise ReportOrchestrationError(
                "DEEP package surface required for mathematical decision stack"
            )
        content = dict(target.get("content") or {})
        content["mathematical_decision_stack"] = dict(
            mathematical_decision_stack
        )
        target["content"] = content
        report["serious_decision_required"] = True
    return report


def _post_match_structural_route(
    report_mode: str,
    *,
    post_match_context: bool,
) -> tuple[str, str | None]:
    mode = str(report_mode or "").strip().upper()
    if mode == "POST_ALL_MATCH":
        return "POST_ALL_MATCH", "GW COMPLETED MATCH-BY-MATCH SCOUT"
    if mode == "POST_MATCH":
        return "MATCH", "RELEVANT LEAGUE-WIDE SIGNALS"
    if mode == "MATCH" and post_match_context:
        return "MATCH", "RELEVANT LEAGUE-WIDE SIGNALS"
    if mode in {
        "OVERLAP",
        "FULL+MATCH",
        "MATCH+FULL",
        "DEEP+MATCH",
        "MATCH+DEEP",
    }:
        return "DEEP", "S04"
    return mode, None


def materialize_natural_post_match_report(
    *,
    canonical_text: str,
    report_mode: str,
    projections_payload: Mapping[str, Any] | None,
    section_payloads: Mapping[str, Mapping[str, Any]] | None,
    post_match_context: bool = True,
    checkpoint_time: str | None = None,
    signal_delta: Mapping[str, Any] | None = None,
    current_gw_locked: bool = False,
    locked_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Natural V12 post-match renderer binding projections -> movers -> report.

    No new top-level backbone is created. Universe Movers is nested exactly
    once in the existing MATCH, POST-ALL-MATCH or overlap surface.
    """
    mode = str(report_mode or "").strip().upper()
    structural_mode, target_label = _post_match_structural_route(
        mode,
        post_match_context=post_match_context,
    )
    if target_label is None:
        raise ReportOrchestrationError(
            f"UNIVERSE MOVERS not applicable for pure mode {mode or '<empty>'}"
        )
    projections = dict(projections_payload or {})
    scan = projections.get("post_match_universe_scan")
    deep = projections.get("post_match_deep_analysis")
    movers = build_post_match_universe_movers(
        scan if isinstance(scan, Mapping) else None,
        post_match_deep_analysis=(
            deep if isinstance(deep, Mapping) else None
        ),
    )
    report = _materialize_canonical_report(
        canonical_text=canonical_text,
        structural_mode=structural_mode,
        reported_mode=mode,
        section_payloads=section_payloads,
        checkpoint_time=checkpoint_time,
        signal_delta=signal_delta,
        current_gw_locked=current_gw_locked,
        locked_state=locked_state,
        universe_movers=movers,
        universe_movers_target_label=target_label,
    )
    report["post_match_universe_movers"] = movers
    report["post_match_source"] = "projections.post_match_universe_scan"
    report["post_match_deep_source"] = (
        "projections.post_match_deep_analysis"
    )
    return report


def _visible_section_heading(section_id: Any, label: Any) -> str:
    """Render a heading shape that the visible-body validator can parse."""
    section = str(section_id or "").strip().upper()
    title = str(label or "Report Section").strip()
    match = re.fullmatch(r"S(\d{1,2})(B?)", section)
    if match:
        return f"## {int(match.group(1))}{match.group(2)}. {title}"
    match = re.fullmatch(r"MATCH(\d{1,2})", section)
    if match:
        return f"## MATCH {int(match.group(1))} — {title}"
    match = re.fullmatch(r"PRICE(\d{1,2})", section)
    if match:
        return f"## PRICE {int(match.group(1))} — {title}"
    match = re.fullmatch(r"POST_ALL_MATCH(\d{1,2})", section)
    if match:
        return f"## POST-ALL-MATCH {int(match.group(1))} — {title}"
    if section == "GW_LOCK_PACKAGE":
        return "## GW LOCK PACKAGE"
    return f"## {title}"


def _human_label(value: Any) -> str:
    return str(value or "").strip().replace("_", " ").upper()


def _render_generic_human_content(
    content: Mapping[str, Any] | None,
    *,
    excluded_keys: Sequence[str] = (),
) -> list[str]:
    """Render user-facing structured content without dumping runtime internals."""
    payload = dict(content or {})
    excluded = {str(key) for key in excluded_keys}
    lines: list[str] = []
    hidden_tokens = (
        "fingerprint",
        "sha",
        "run_id",
        "workflow",
        "issue_431",
        "mutation",
        "readback",
        "raw_payload",
    )
    for key, value in payload.items():
        key_text = str(key)
        lower = key_text.lower()
        if key_text in excluded or any(token in lower for token in hidden_tokens):
            continue
        if value is None:
            lines.append(f"{_human_label(key_text)}: UNAVAILABLE")
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{_human_label(key_text)}: {value}")
            continue
        if isinstance(value, Mapping):
            compact = []
            for subkey, subvalue in value.items():
                if isinstance(subvalue, (str, int, float, bool)) or subvalue is None:
                    compact.append(
                        f"{_human_label(subkey)}={subvalue if subvalue is not None else 'UNAVAILABLE'}"
                    )
            if compact:
                lines.append(f"{_human_label(key_text)}: " + " | ".join(compact))
            continue
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            items = list(value)
            if not items:
                lines.append(f"{_human_label(key_text)}: NONE")
                continue
            scalar_items = [
                item for item in items
                if isinstance(item, (str, int, float, bool))
            ]
            if len(scalar_items) == len(items):
                lines.append(
                    f"{_human_label(key_text)}: "
                    + ", ".join(str(item) for item in scalar_items)
                )
                continue
            for index, item in enumerate(items, start=1):
                if not isinstance(item, Mapping):
                    continue
                compact = []
                for subkey, subvalue in item.items():
                    if isinstance(subvalue, (str, int, float, bool)) or subvalue is None:
                        compact.append(
                            f"{_human_label(subkey)}={subvalue if subvalue is not None else 'UNAVAILABLE'}"
                        )
                if compact:
                    lines.append(f"- {index}. " + " | ".join(compact))
    return lines


def render_natural_post_match_text(report: Mapping[str, Any]) -> str:
    """Visible natural post-match renderer including fixture scout and movers."""
    blocks: list[str] = []
    for section in report.get("sections") or []:
        label = str(section.get("label") or "")
        state = str(section.get("state") or "")
        section_id = section.get("section_id")
        lines = [_visible_section_heading(section_id, label), f"Status: {state}"]
        reason = str(section.get("degradation_reason") or "").strip()
        if state != "COMPLETE" and reason:
            lines.append(f"Reason: {reason}")
        content = section.get("content")
        content_map = dict(content or {}) if isinstance(content, Mapping) else {}

        scout = [
            dict(row)
            for row in (
                content_map.get("match_scout")
                or content_map.get("post_match_match_by_match_scout")
                or ()
            )
            if isinstance(row, Mapping)
        ]
        if scout:
            lines.extend(_render_match_scout_lines(scout))

        math_stack = content_map.get("mathematical_decision_stack")
        if isinstance(math_stack, Mapping):
            lines.extend(_render_math_stack_lines(math_stack))

        if "PACKAGE OPTIMIZER" in label.upper():
            lines.extend(
                _render_package_frontier_lines(
                    content_map,
                    section_state=state,
                )
            )

        movers = dict(content_map.get("universe_movers") or {})
        if movers:
            lines.append("### UNIVERSE MOVERS")
            mover_state = str(movers.get("state") or "UNAVAILABLE")
            if mover_state != "COMPLETE":
                lines.append(
                    f"{mover_state} — "
                    f"{movers.get('degradation_reason') or 'evidence unavailable'}"
                )
            elif movers.get("summary") == "NO MATERIAL MOVERS":
                lines.append("NO MATERIAL MOVERS")
            else:
                for category, rows in (
                    movers.get("categories") or {}
                ).items():
                    if not rows:
                        continue
                    lines.append(f"**{category}**")
                    for row in rows:
                        owner = "OWNED" if row.get("owned") else "NON-OWNED"
                        deep = "DEEP" if row.get("deep_detail") else "BROAD"
                        lines.append(
                            "- "
                            f"{row.get('name') or row.get('element_id')} "
                            f"({row.get('position') or 'NA'}) | "
                            f"{row.get('primary_classification')} | "
                            f"Pts {row.get('latest_fpl_points')} | "
                            f"xGI {row.get('latest_xgi')} | "
                            f"xMins Δ {row.get('xmins_delta')} | "
                            f"P(start) Δ {row.get('p_start_delta')} | "
                            f"{row.get('universe_comparison_state') or 'UNAVAILABLE'} | "
                            f"{owner} | {deep}"
                        )
            lines.append(
                "Coverage: "
                f"{movers.get('scanned_count')}/{movers.get('eligible_count')} | "
                f"Material {movers.get('material_count')} | "
                f"Deep {movers.get('deep_executed_count')}/"
                f"{movers.get('deep_requested_count')} | "
                f"Authority {movers.get('search_authority') or 'UNAVAILABLE'}"
            )
        generic = _render_generic_human_content(
            content_map,
            excluded_keys=(
                "match_scout",
                "post_match_match_by_match_scout",
                "mathematical_decision_stack",
                "universe_movers",
                "package_search_proof",
                "search_proof",
                "package_universe_challengers",
                "universe_challengers",
                "package_routes",
                "routes",
                "frontier",
            ),
        )
        if generic:
            lines.extend(generic)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)



def _markdown_cell(value: Any) -> str:
    text = str("UNAVAILABLE" if value is None else value)
    return text.replace("|", "/").replace("\n", " ").strip()


def _markdown_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[str]:
    header = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(value) for value in row) + " |"
        for row in rows
    ]
    return [header, separator, *body]


DEEP_HUMAN_SECTION_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "S01": ("operational_state", "planning_gw", "primary_decision", "key_decision_driver"),
    "S02": ("rows",),
    "S03": ("decision_delta",),
    "S04": ("changes",),
    "S05": ("fixtures",),
    "S06": ("formation", "starting_xi", "bench", "lineup_score", "formation_comparison"),
    "S06B": (
        "stance",
        "raw_ev_formation",
        "mini_league_objective_formation",
        "formation_alternatives",
        "high_eo_protection",
        "differential_slots",
    ),
    "S07": ("battles",),
    "S08": ("captain", "vice_captain"),
    "S09": ("chip",),
    "S10": ("rows",),
    "S11": ("rows",),
    "S12": ("rows",),
    "S13": ("rows",),
    "S14": ("package_routes", "frontier"),
    "S14B": ("staging_rows", "squad_classification", "target_formation"),
    "S15": ("evidence_quality",),
    "S15B": (
        "current_league_context",
        "exposures",
        "rank_battle",
        "our15_rival_exposure",
        "direct_rival_scope",
        "direct_rivals",
        "direct_rival_our15_exposure",
        "rival_threats",
        "captain_leverage",
        "strategy_implication",
        "report_contract",
    ),
    "S16": ("rows", "position_mechanisms"),
    "S16B": ("our15", "material_universe_candidates", "recency_weighting", "bayesian_update"),
    "S17": ("engine_data_status", "source_health"),
    "S18": (
        "NOW",
        "NEXT",
        "TRIGGER TO ACT",
        "LATEST SAFE DECISION POINT",
        "COST OF WAITING",
        "ABORT / REVERSAL",
        "BEST ALTERNATIVE",
    ),
    "S19": ("final_judgement",),
}


def build_deep_human_facing_manifest(
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Durable semantic manifest for required DEEP human-facing content."""
    sections = {
        str(row.get("section_id") or "").strip().upper(): dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    }
    entries: list[dict[str, Any]] = []
    failures: list[str] = []
    for section_id, required_keys in DEEP_HUMAN_SECTION_REQUIREMENTS.items():
        section = sections.get(section_id)
        if section is None:
            failures.append(f"HUMAN_SECTION_MISSING={section_id}")
            entries.append({
                "section_id": section_id,
                "status": "MISSING",
                "required_keys": list(required_keys),
                "missing_keys": list(required_keys),
            })
            continue
        content = section.get("content")
        payload = dict(content or {}) if isinstance(content, Mapping) else {}
        missing = [key for key in required_keys if key not in payload]
        empty = [
            key
            for key in required_keys
            if key in payload and payload.get(key) in (None, "", [], {})
        ]
        # Degraded/unavailable sections may truthfully carry empty factual rows,
        # but the semantic key must remain visible. Some COMPLETE decision
        # sections can also be truthfully empty when the payload explicitly
        # proves there is no material item (for example no XI battle).
        state = str(section.get("state") or "").upper()
        truthful_empty = payload.get("empty_is_truthful") is True
        all_required_empty = bool(required_keys) and len(empty) == len(required_keys)
        hard_empty = (
            list(required_keys)
            if state == "COMPLETE" and all_required_empty and not truthful_empty
            else []
        )
        if missing:
            failures.append(
                f"HUMAN_SECTION_KEYS_MISSING={section_id}:{','.join(missing)}"
            )
        if hard_empty:
            failures.append(
                f"HUMAN_SECTION_CONTENT_EMPTY={section_id}:{','.join(hard_empty)}"
            )
        entries.append({
            "section_id": section_id,
            "label": section.get("label"),
            "status": state,
            "required_keys": list(required_keys),
            "missing_keys": missing,
            "empty_keys": empty,
            "semantic_pass": not missing and not hard_empty,
        })
    return {
        "contract": "V12_DEEP_HUMAN_FACING_MANIFEST_V2",
        "required_section_ids": list(DEEP_HUMAN_SECTION_REQUIREMENTS),
        "entries": entries,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def validate_deep_human_facing_manifest(
    manifest: Mapping[str, Any],
) -> list[str]:
    if str(manifest.get("status") or "").upper() == "PASS":
        return []
    return [str(value) for value in manifest.get("failures") or []]


def _render_deep_visible_contract_lines(
    *,
    section_id: str,
    content: Mapping[str, Any],
    owned_ids: set[int],
    owned_names: Mapping[int, str],
) -> tuple[list[str], tuple[str, ...]]:
    """Render the existing DEEP content into the visible-body QA contract.

    This is presentation only. It does not recompute xPts, xMins, posterior,
    tactical scores, price predictions, ownership, or mini-league facts.
    """
    payload = dict(content or {})
    lines: list[str] = []
    excluded: list[str] = []

    if section_id == "S02":
        rows = [
            dict(row)
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        lines.extend(
            _markdown_table(
                (
                    "element_id",
                    "player_name",
                    "opponent",
                    "p_available",
                    "p_start",
                    "p_cameo",
                    "p_dnp",
                    "xmins",
                    "tactical_role",
                    "injury_rotation_warning",
                    "price_relevance",
                    "1gw",
                    "3gw",
                    "5gw",
                    "action",
                ),
                [
                    (
                        row.get("element_id"),
                        row.get("player") or row.get("name"),
                        row.get("opponent"),
                        row.get("p_available"),
                        row.get("p_start"),
                        row.get("p_cameo"),
                        row.get("p_dnp"),
                        row.get("xmins"),
                        row.get("tactical_role"),
                        row.get("injury_rotation_warning", "NONE_MATERIAL"),
                        row.get("price_relevance", "NONE_MATERIAL"),
                        row.get("gw_plus_1"),
                        row.get("three_gw"),
                        row.get("five_gw"),
                        row.get("action"),
                    )
                    for row in rows
                ],
            )
        )
        excluded.append("rows")

    elif section_id == "S05":
        lines.append("WEATHER SOURCE: DEGRADED")

    elif section_id == "S06":
        def player_name(value: Any) -> str:
            if isinstance(value, Mapping):
                element = value.get("element", value.get("element_id"))
                name = value.get("name") or value.get("player")
                if name:
                    return str(name)
                try:
                    return owned_names.get(int(element), str(element))
                except (TypeError, ValueError):
                    return str(element)
            try:
                element = int(value)
            except (TypeError, ValueError):
                return str(value)
            return owned_names.get(element, str(element))

        xi_raw = list(payload.get("starting_xi") or [])
        bench = dict(payload.get("bench") or {})
        xi_names = [player_name(row) for row in xi_raw]
        bench_names: list[str] = []
        if bench.get("gk") is not None:
            bench_names.append(player_name(bench.get("gk")))
        bench_names.extend(
            player_name(row)
            for row in (bench.get("order") or [])
        )
        lines.append(f"FORMATION: {payload.get('formation') or 'UNAVAILABLE'}")
        lines.append("XI: " + ", ".join(xi_names))
        lines.append("BENCH: " + ", ".join(bench_names))
        score = dict(payload.get("lineup_score") or {})
        score_semantics = dict(payload.get("score_semantics") or {})
        lines.append(
            "XI_BASE_XPTS: "
            + str(
                score_semantics.get(
                    "xi_base_xpts",
                    score.get("xpts_mean", "UNAVAILABLE"),
                )
            )
        )
        lines.append(
            "CAPTAIN_ADJUSTED_XPTS: "
            + str(
                score_semantics.get(
                    "captain_adjusted_xpts",
                    "UNAVAILABLE",
                )
            )
        )
        lines.append(
            "LINEUP_ROUTE_UTILITY: "
            + str(
                score_semantics.get(
                    "lineup_route_utility",
                    "UNAVAILABLE",
                )
            )
        )
        comparisons = [
            dict(item)
            for item in payload.get("formation_comparison") or []
            if isinstance(item, Mapping)
        ]
        if comparisons:
            lines.append("FORMATION ALTERNATIVES:")
            lines.extend(
                _markdown_table(
                    ("formation", "projected_points", "route_utility", "downside", "upside", "selected"),
                    [
                        (
                            item.get("formation"),
                            item.get("expected_fpl_points_with_captain_vice"),
                            item.get("route_utility"),
                            item.get("distributional_downside"),
                            item.get("supportable_upside"),
                            item.get("selected"),
                        )
                        for item in comparisons
                    ],
                )
            )
        else:
            lines.append("FORMATION ALTERNATIVES: NONE MATERIAL / NONE SUPPORTABLE")
        excluded.extend((
            "starting_xi",
            "bench",
            "formation_comparison",
            "lineup_score",
            "score_semantics",
        ))

    elif section_id == "S06B":
        lines.append(f"MINI-LEAGUE STANCE: {payload.get('stance') or 'UNAVAILABLE'}")
        league = dict(payload.get("league_context") or {})
        lines.append(
            "LEAGUE POSITION: "
            f"rank={league.get('our_rank', 'UNAVAILABLE')} / "
            f"{league.get('manager_count', 'UNAVAILABLE')} | "
            f"points={league.get('our_total_points', 'UNAVAILABLE')} | "
            f"leader_gap={league.get('points_to_leader', 'UNAVAILABLE')} | "
            f"top3_gap={league.get('points_to_top_3', 'UNAVAILABLE')} | "
            f"top5_gap={league.get('points_to_top_5', 'UNAVAILABLE')} | "
            f"rival_above_gap={league.get('points_to_nearest_above', 'UNAVAILABLE')} | "
            f"rival_below_cushion={league.get('points_ahead_nearest_below', 'UNAVAILABLE')}"
        )
        lines.append(f"RAW EV FORMATION: {payload.get('raw_ev_formation') or 'UNAVAILABLE'}")
        lines.append(
            "MINI-LEAGUE OBJECTIVE FORMATION: "
            + str(payload.get("mini_league_objective_formation") or "UNAVAILABLE")
        )
        lines.append(
            "PROJECTED POINTS DIFFERENCE: "
            + str(payload.get("projected_points_difference", "UNAVAILABLE"))
        )
        lines.append(
            "OBJECTIVES SAME: "
            + str(payload.get("objectives_same", "UNAVAILABLE"))
        )
        lines.append(
            "RATIONAL DIFFERENTIAL EXPOSURE: "
            + str(payload.get("rational_differential_exposure", "UNAVAILABLE"))
        )
        lines.append(
            "AGGRESSIVE DOWNSIDE: "
            + str(payload.get("aggressive_downside") or "UNAVAILABLE")
        )
        alternatives = [
            dict(item)
            for item in payload.get("formation_alternatives") or []
            if isinstance(item, Mapping)
        ]
        if alternatives:
            lines.extend(
                _markdown_table(
                    ("formation", "projected_points", "utility", "downside", "upside", "selected"),
                    [
                        (
                            item.get("formation"),
                            item.get("expected_fpl_points_with_captain_vice"),
                            item.get("route_utility"),
                            item.get("distributional_downside"),
                            item.get("supportable_upside"),
                            item.get("selected"),
                        )
                        for item in alternatives
                    ],
                )
            )
        lines.append(
            "HIGH-EO PROTECTION: "
            + ", ".join(
                str(item.get("player") or item.get("element_id"))
                for item in payload.get("high_eo_protection") or []
                if isinstance(item, Mapping)
            )
        )
        lines.append(
            "DIFFERENTIAL SLOTS: "
            + ", ".join(
                str(item.get("player") or item.get("element_id"))
                for item in payload.get("differential_slots") or []
                if isinstance(item, Mapping)
            )
        )
        excluded.extend((
            "formation_alternatives",
            "high_eo_protection",
            "differential_slots",
        ))

    elif section_id == "S07":
        battles = [
            dict(item)
            for item in payload.get("battles") or []
            if isinstance(item, Mapping)
        ]
        lines.extend(
            _markdown_table(
                ("player_a", "player_b", "xmins_a", "xmins_b", "p_start_a", "p_start_b", "1gw_a", "1gw_b", "eo_a", "eo_b", "starter", "reason"),
                [
                    (
                        item.get("player_a"),
                        item.get("player_b"),
                        item.get("xmins_a"),
                        item.get("xmins_b"),
                        item.get("p_start_a"),
                        item.get("p_start_b"),
                        item.get("projection_1gw_a"),
                        item.get("projection_1gw_b"),
                        item.get("eo_a"),
                        item.get("eo_b"),
                        item.get("final_starter"),
                        item.get("tactical_reason"),
                    )
                    for item in battles
                ],
            )
        )
        excluded.append("battles")

    elif section_id == "S08":
        captain_rows = []
        for role_label, raw_candidate in (
            ("C", payload.get("captain")),
            ("VC", payload.get("vice_captain")),
        ):
            candidate = (
                dict(raw_candidate)
                if isinstance(raw_candidate, Mapping)
                else {
                    "element_id": raw_candidate,
                    "player": (
                        owned_names.get(int(raw_candidate), str(raw_candidate))
                        if raw_candidate is not None and str(raw_candidate).isdigit()
                        else raw_candidate
                    ),
                }
            )
            goal_involvement = dict(candidate.get("goal_involvement") or {})
            fixture = dict(candidate.get("fixture") or {})
            captain_rows.append(
                (
                    role_label,
                    candidate.get("player") or candidate.get("element_id"),
                    candidate.get("expected_points"),
                    candidate.get("ceiling_q90"),
                    candidate.get("haul_probability"),
                    candidate.get("xmins"),
                    candidate.get("p_start"),
                    goal_involvement.get("p_goal"),
                    goal_involvement.get("p_assist"),
                    goal_involvement.get("p_return"),
                    candidate.get("penalties"),
                    candidate.get("set_pieces"),
                    fixture.get("opponent"),
                    "H" if fixture.get("home") is True else "A" if fixture.get("home") is False else "UNAVAILABLE",
                    candidate.get("captain_pct"),
                    candidate.get("eo_pct"),
                    candidate.get("mini_league_downside"),
                    candidate.get("mini_league_upside"),
                )
            )
        lines.extend(
            _markdown_table(
                (
                    "role",
                    "player",
                    "xPts",
                    "Q90",
                    "P(haul)",
                    "xMins",
                    "P(start)",
                    "P(goal)",
                    "P(assist)",
                    "P(return)",
                    "penalty",
                    "set-piece",
                    "fixture",
                    "H/A",
                    "captain%",
                    "EO%",
                    "ML downside",
                    "ML upside",
                ),
                captain_rows,
            )
        )
        lines.append(
            "CAPTAIN AUTHORITY: "
            + str(
                payload.get("authority")
                or "distributional evidence; raw 1GW mean alone is insufficient"
            )
        )
        excluded.extend(("captain", "vice_captain", "captain_safe_pool"))

    elif section_id == "S14B":
        lines.append("STAGING IS A ROADMAP, NOT A TRANSFER COMMITMENT.")
        staging = [
            dict(item)
            for item in payload.get("staging_rows") or []
            if isinstance(item, Mapping)
        ]
        lines.extend(
            _markdown_table(
                ("Timing", "Planned Move", "Status", "Trigger", "Expected Gain", "Dependency"),
                [
                    (
                        item.get("timing"),
                        item.get("planned_move"),
                        item.get("status"),
                        item.get("trigger"),
                        item.get("expected_gain"),
                        item.get("dependency"),
                    )
                    for item in staging
                ],
            )
        )
        classifications = [
            dict(item)
            for item in payload.get("squad_classification") or []
            if isinstance(item, Mapping)
        ]
        if classifications:
            lines.extend(
                _markdown_table(
                    ("player", "classification", "reason"),
                    [
                        (
                            item.get("player"),
                            item.get("classification"),
                            item.get("reason"),
                        )
                        for item in classifications
                    ],
                )
            )
        excluded.extend(("staging_rows", "squad_classification"))

    elif section_id == "S11":
        rows = [
            dict(row)
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        lines.extend(
            _markdown_table(
                (
                    "rank",
                    "element_id",
                    "player_name",
                    "position",
                    "price",
                    "xmins",
                    "p_start",
                    "predictor",
                    "ownership_tag",
                    "football_score",
                    "watchlist_relevance",
                    "transfer_relevance",
                ),
                [
                    (
                        rank,
                        row.get("element_id", row.get("element")),
                        row.get("name"),
                        row.get("position"),
                        row.get("current_price"),
                        row.get("xmins"),
                        row.get("p_start"),
                        {
                            "direction": row.get("predictor_direction"),
                            "progress": row.get("predictor_progress"),
                        },
                        "NON_OWNED",
                        row.get("football_score"),
                        row.get("watchlist_relevance"),
                        row.get("transfer_relevance"),
                    )
                    for rank, row in enumerate(rows, start=1)
                ],
            )
        )
        excluded.append("rows")

    elif section_id in {"S12", "S13"}:
        rows = [
            dict(row)
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        fields = (
            "rank",
            "element_id",
            "player_name",
            "current_price",
            "ownership_percent",
            "ownership_tag",
            "direction",
            "current_progress_percent",
            "projection_offset_0_percent",
            "predicted_change_cycle",
            "predicted_change_at",
            "eta_human",
            "model_urgency",
            "confidence",
            "source",
            "observed_at",
            "raw_payload_hash",
        )
        payload_hash = str(
            payload.get("predictor_payload_hash")
            or hashlib.sha256(
                json.dumps(
                    rows,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        )
        visible_rows = []
        for rank, row in enumerate(rows, start=1):
            element_id = int(row.get("element_id") or 0)
            confidence = row.get("confidence")
            if isinstance(confidence, Mapping):
                confidence = json.dumps(
                    confidence,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=str,
                )
            visible_rows.append(
                {
                    "rank": rank,
                    "element_id": element_id,
                    "player_name": (
                        row.get("player")
                        or row.get("player_name")
                        or f"element:{element_id}"
                    ),
                    "current_price": row.get("current_price"),
                    "ownership_percent": row.get(
                        "selected_by_percent",
                        row.get("ownership_percent", "UNAVAILABLE"),
                    ),
                    "ownership_tag": (
                        "OWNED"
                        if element_id in owned_ids
                        else "NON_OWNED"
                    ),
                    "direction": row.get("direction"),
                    "current_progress_percent": row.get(
                        "official_or_provider_progress",
                        row.get(
                            "current_progress_percent",
                            "UNAVAILABLE",
                        ),
                    ),
                    "projection_offset_0_percent": row.get(
                        "projected_percent",
                        row.get(
                            "projection_offset_0_percent",
                            "UNAVAILABLE",
                        ),
                    ),
                    "predicted_change_cycle": (
                        row.get("cycles_to_expected_change")
                        or row.get("predicted_change_cycle")
                        or row.get("date_state")
                        or "UNAVAILABLE"
                    ),
                    "predicted_change_at": (
                        row.get("estimated_change_at_wib")
                        or row.get("predicted_change_at")
                        or row.get("date_state")
                        or "UNAVAILABLE"
                    ),
                    "eta_human": (
                        row.get("eta_context")
                        or row.get("eta_human")
                        or row.get("estimated_change_window")
                        or row.get("date_state")
                        or "UNAVAILABLE"
                    ),
                    "model_urgency": (
                        row.get("impact_on_our_decision")
                        or row.get("model_urgency")
                        or "WATCH"
                    ),
                    "confidence": confidence or "UNAVAILABLE",
                    "source": (
                        row.get("estimate_source")
                        or row.get("source")
                        or "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR"
                    ),
                    "observed_at": (
                        row.get("evidence_timestamp")
                        or row.get("observed_at")
                        or "UNAVAILABLE"
                    ),
                    "raw_payload_hash": (
                        row.get("raw_payload_hash")
                        or payload_hash
                    ),
                }
            )
        lines.extend(
            _markdown_table(
                fields,
                [
                    tuple(row.get(field) for field in fields)
                    for row in visible_rows
                ],
            )
        )
        excluded.extend(("rows", "predictor_payload_hash"))

    elif section_id == "S15B":
        coverage = str(payload.get("coverage_state") or "").upper()
        expected = payload.get("expected_manager_count")
        available = payload.get("submitted_picks_available_count")
        rival_denominator = payload.get("rival_exposure_denominator")
        disclosed_gw = payload.get("disclosed_picks_gw")
        lines.append(
            "MINI_LEAGUE_DENOMINATOR: "
            + ("COMPLETE" if coverage == "FULL" else "DEGRADED")
        )
        lines.append(
            "MINI_LEAGUE_COVERAGE: "
            f"submitted={available}/{expected} | "
            f"rival_denominator={rival_denominator} | "
            f"disclosed_picks=GW{disclosed_gw}"
        )
        lines.append(
            "RIVAL PICKS NOTE: latest disclosed submitted picks are a behavioral/"
            "structural baseline, not a forecast of the still-private planning-GW picks."
        )
        lines.append(
            "VISIBLE METRIC CONTRACT: "
            "OWNERSHIP_COUNT=OWN | STARTER_COUNT=START | BENCH_COUNT=BENCH | "
            "CAPTAIN_COUNT=C | VICE_COUNT=VC | EO_PCT=EO"
        )
        context = dict(payload.get("current_league_context") or {})
        lines.append(
            "LEAGUE LANDSCAPE: "
            f"rank={context.get('our_rank')} / {context.get('manager_count')} | "
            f"points={context.get('our_total_points')} | "
            f"leader={context.get('leader_points')} | "
            f"leader_gap={context.get('points_to_leader')} | "
            f"top3_gap={context.get('points_to_top_3')} | "
            f"top5_gap={context.get('points_to_top_5')} | "
            f"above_gap={context.get('points_to_nearest_above')} | "
            f"below_cushion={context.get('points_ahead_nearest_below')}"
        )

        def _mini_num(value: Any) -> str:
            if value is None:
                return "UNAVAILABLE"
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return str(value)
            if numeric.is_integer():
                return str(int(numeric))
            return f"{numeric:.2f}".rstrip("0").rstrip(".")

        def _mini_ratio(
            row: Mapping[str, Any],
            count_key: str,
            pct_key: str,
            *,
            numerator_key: str | None = None,
        ) -> str:
            denominator = row.get("denominator")
            numerator = (
                row.get(numerator_key)
                if numerator_key is not None
                else row.get(count_key)
            )
            pct = row.get(pct_key)
            if denominator in (None, 0) or numerator is None:
                return "UNAVAILABLE"
            pct_text = (
                "UNAVAILABLE"
                if pct is None
                else f"{float(pct):.1f}%"
            )
            return (
                f"{_mini_num(numerator)}/{_mini_num(denominator)} "
                f"({pct_text})"
            )

        def _mini_player(row: Mapping[str, Any], *, owned: bool) -> str:
            name = str(
                row.get("player")
                or row.get("name")
                or row.get("element_id")
                or "UNAVAILABLE"
            )
            return f"**{name}**" if owned else name

        rank_battle = [
            dict(item)
            for item in payload.get("rank_battle") or []
            if isinstance(item, Mapping)
        ]
        lines.append("### RANK BATTLE")
        if rank_battle:
            lines.extend(
                _markdown_table(
                    ("Rank", "Manager", "Team", "Total", "Gap vs us", "GW"),
                    [
                        (
                            (
                                f"**{item.get('rank')}**"
                                if item.get("is_us")
                                else item.get("rank")
                            ),
                            (
                                f"**{item.get('manager')}**"
                                if item.get("is_us")
                                else item.get("manager")
                            ),
                            (
                                f"**{item.get('team')}**"
                                if item.get("is_us")
                                else item.get("team")
                            ),
                            item.get("total_points"),
                            item.get("gap_vs_us"),
                            item.get("gw_score"),
                        )
                        for item in rank_battle
                    ],
                )
            )
        else:
            lines.append("UNAVAILABLE — no supportable rank battle rows")

        our15 = [
            dict(item)
            for item in payload.get("our15_rival_exposure") or []
            if isinstance(item, Mapping)
        ]
        lines.append("### OUR15 VS ALL RIVALS")
        if our15:
            lines.extend(
                _markdown_table(
                    ("Player", "OWN", "START", "BENCH", "C", "VC", "EO"),
                    [
                        (
                            _mini_player(item, owned=True),
                            _mini_ratio(item, "ownership_count", "ownership_pct"),
                            _mini_ratio(item, "starter_count", "starter_pct"),
                            _mini_ratio(item, "bench_count", "bench_pct"),
                            _mini_ratio(item, "captain_count", "captain_pct"),
                            _mini_ratio(item, "vice_count", "vice_pct"),
                            _mini_ratio(
                                item,
                                "effective_multiplier_sum",
                                "eo_pct",
                                numerator_key="effective_multiplier_sum",
                            ),
                        )
                        for item in our15
                    ],
                )
            )
        else:
            lines.append("UNAVAILABLE — OUR15 rival exposure not materialized")

        direct_scope = dict(payload.get("direct_rival_scope") or {})
        lines.append(
            "### DIRECT RIVALS ABOVE US"
        )
        lines.append(
            "DIRECT RIVAL SCOPE: "
            f"requested={direct_scope.get('requested_above_count')} | "
            f"standings={direct_scope.get('standings_rival_count')} | "
            f"picks={direct_scope.get('picks_available_count')} | "
            f"denominator={direct_scope.get('denominator')} | "
            f"complete={direct_scope.get('complete')}"
        )
        direct = [
            dict(item)
            for item in payload.get("direct_rivals") or []
            if isinstance(item, Mapping)
        ]
        if direct:
            lines.extend(
                _markdown_table(
                    (
                        "Rank",
                        "Manager",
                        "Team",
                        "Points",
                        "Gap",
                        "Overlap",
                        "Captain",
                        "Vice",
                    ),
                    [
                        (
                            item.get("rank"),
                            item.get("manager"),
                            item.get("team"),
                            item.get("total_points"),
                            item.get("gap_vs_us"),
                            (
                                f"{item.get('overlap_count')}/"
                                f"{item.get('overlap_denominator')}"
                            ),
                            item.get("captain"),
                            item.get("vice"),
                        )
                        for item in direct
                    ],
                )
            )
            lines.append("#### DIRECT RIVAL DIFFERENCE DETAIL")
            for item in direct:
                overlap = ", ".join(
                    str(row.get("player"))
                    for row in item.get("overlap_players") or []
                    if isinstance(row, Mapping)
                ) or "NONE"
                our_unique = ", ".join(
                    str(row.get("player"))
                    for row in item.get("our_unique_players") or []
                    if isinstance(row, Mapping)
                ) or "NONE"
                rival_unique = ", ".join(
                    str(row.get("player"))
                    for row in item.get("rival_unique_players") or []
                    if isinstance(row, Mapping)
                ) or "NONE"
                lines.append(
                    f"- #{item.get('rank')} {item.get('manager')} | "
                    f"OVERLAP [{overlap}] | "
                    f"OUR UNIQUE [{our_unique}] | "
                    f"RIVAL UNIQUE [{rival_unique}]"
                )
        else:
            lines.append("UNAVAILABLE — no direct-rival picks available")

        direct_owned = [
            dict(item)
            for item in payload.get("direct_rival_our15_exposure") or []
            if isinstance(item, Mapping)
        ]
        lines.append("### OUR15 VS DIRECT RIVALS")
        if direct_owned:
            lines.extend(
                _markdown_table(
                    ("Player", "OWN", "START", "BENCH", "C", "VC", "EO"),
                    [
                        (
                            _mini_player(item, owned=True),
                            _mini_ratio(item, "ownership_count", "ownership_pct"),
                            _mini_ratio(item, "starter_count", "starter_pct"),
                            _mini_ratio(item, "bench_count", "bench_pct"),
                            _mini_ratio(item, "captain_count", "captain_pct"),
                            _mini_ratio(item, "vice_count", "vice_pct"),
                            _mini_ratio(
                                item,
                                "effective_multiplier_sum",
                                "eo_pct",
                                numerator_key="effective_multiplier_sum",
                            ),
                        )
                        for item in direct_owned
                    ],
                )
            )
        else:
            lines.append("UNAVAILABLE — direct-rival OUR15 exposure not materialized")

        threats = [
            dict(item)
            for item in payload.get("rival_threats") or []
            if isinstance(item, Mapping)
        ]
        lines.append("### RIVAL THREATS NOT IN OUR15")
        if threats:
            lines.extend(
                _markdown_table(
                    ("Player", "OWN", "START", "BENCH", "C", "VC", "EO"),
                    [
                        (
                            _mini_player(item, owned=False),
                            _mini_ratio(item, "ownership_count", "ownership_pct"),
                            _mini_ratio(item, "starter_count", "starter_pct"),
                            _mini_ratio(item, "bench_count", "bench_pct"),
                            _mini_ratio(item, "captain_count", "captain_pct"),
                            _mini_ratio(item, "vice_count", "vice_pct"),
                            _mini_ratio(
                                item,
                                "effective_multiplier_sum",
                                "eo_pct",
                                numerator_key="effective_multiplier_sum",
                            ),
                        )
                        for item in threats
                    ],
                )
            )
        else:
            lines.append("NONE MATERIAL / UNAVAILABLE")

        def _probability_cell(value: Any) -> str:
            if value is None:
                return "UNAVAILABLE"
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return str(value)
            if 0.0 <= numeric <= 1.0:
                numeric *= 100.0
            return f"{numeric:.1f}%"

        captain_rows = [
            dict(item)
            for item in payload.get("captain_leverage") or []
            if isinstance(item, Mapping)
        ]
        lines.append("### CAPTAIN LEVERAGE")
        if captain_rows:
            lines.extend(
                _markdown_table(
                    (
                        "Player",
                        "xPts",
                        "P(haul)",
                        "ALL OWN",
                        "ALL C",
                        "ALL EO",
                        "DIRECT OWN",
                        "DIRECT C",
                        "DIRECT EO",
                        "Rank utility",
                    ),
                    [
                        (
                            f"**{item.get('player')}**",
                            item.get("expected_points"),
                            _probability_cell(item.get("haul_probability")),
                            _mini_ratio(
                                dict(item.get("all_rivals") or {}),
                                "ownership_count",
                                "ownership_pct",
                            ),
                            _mini_ratio(
                                dict(item.get("all_rivals") or {}),
                                "captain_count",
                                "captain_pct",
                            ),
                            _mini_ratio(
                                dict(item.get("all_rivals") or {}),
                                "effective_multiplier_sum",
                                "eo_pct",
                                numerator_key="effective_multiplier_sum",
                            ),
                            _mini_ratio(
                                dict(item.get("direct_rivals") or {}),
                                "ownership_count",
                                "ownership_pct",
                            ),
                            _mini_ratio(
                                dict(item.get("direct_rivals") or {}),
                                "captain_count",
                                "captain_pct",
                            ),
                            _mini_ratio(
                                dict(item.get("direct_rivals") or {}),
                                "effective_multiplier_sum",
                                "eo_pct",
                                numerator_key="effective_multiplier_sum",
                            ),
                            item.get("expected_rank_utility"),
                        )
                        for item in captain_rows
                    ],
                )
            )
            lines.append(
                "CAPTAIN RULE: raw mean xPts is not sole authority; "
                "P(haul), availability, all-rival EO and direct-rival EO must "
                "be read together."
            )
        else:
            lines.append("UNAVAILABLE — captain leverage candidates not materialized")

        implication = dict(payload.get("strategy_implication") or {})
        lines.append("### CHASE / BALANCED / DEFEND IMPLICATION")
        lines.append(
            f"POSTURE: {implication.get('human_posture')} "
            f"(model={implication.get('model_posture')})"
        )
        lines.append(
            f"TRANSFER: {implication.get('transfer_action')} | "
            f"RULE: {implication.get('transfer_rule')}"
        )
        lines.append(f"XI: {implication.get('xi_rule')}")
        lines.append(f"CAPTAIN: {implication.get('captain_rule')}")

        excluded.extend(
            (
                "current_league_context",
                "exposures",
                "rank_battle",
                "our15_rival_exposure",
                "direct_rival_scope",
                "direct_rivals",
                "direct_rival_our15_exposure",
                "rival_threats",
                "captain_leverage",
                "strategy_implication",
                "report_contract",
                "disclosed_picks_gw",
                "disclosed_picks_are_baseline_not_gw_forecast",
            )
        )

    elif section_id == "S16":
        rows = [
            dict(row)
            for row in payload.get("rows") or []
            if isinstance(row, Mapping)
        ]
        lines.extend(
            _markdown_table(
                (
                    "element_id",
                    "player_name",
                    "availability",
                    "p_start",
                    "xmins",
                    "posterior",
                    "role / set-piece / penalty",
                    "fixture",
                    "defensive contribution",
                    "1gw",
                    "3gw",
                    "5gw",
                    "price / optionality",
                    "ICON+ relevance",
                    "action",
                ),
                [
                    (
                        row.get("element_id"),
                        row.get("player") or row.get("name"),
                        row.get("availability", row.get("p_available")),
                        row.get("p_start"),
                        row.get("xmins"),
                        row.get("posterior_signal"),
                        row.get("role_detail"),
                        row.get("fixture_detail"),
                        row.get("defensive_contribution"),
                        row.get("projection_1gw", row.get("gw_plus_1")),
                        row.get("projection_3gw", row.get("three_gw")),
                        row.get("projection_5gw", row.get("five_gw")),
                        row.get("price_optionality"),
                        row.get("mini_league_relevance"),
                        row.get("action"),
                    )
                    for row in rows
                ],
            )
        )
        excluded.append("rows")

    elif section_id == "S16B":
        lines.append(
            "RECENCY WEIGHTING: "
            + str(payload.get("recency_weighting") or "EXPONENTIAL_HALF_LIFE_GW")
        )
        lines.append(
            "BAYESIAN UPDATE: "
            + str(payload.get("bayesian_update") or "POSTERIOR_RECENT_RATE_WITH_SHRINKAGE")
        )
        for item in payload.get("our15") or []:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "### "
                + str(item.get("player") or item.get("element_id"))
                + " | GW1→NOW"
            )
            trajectory = dict(item.get("trajectory") or {})
            role = dict(trajectory.get("role_minutes_evolution") or {})
            lines.append(
                "TREND: "
                f"{trajectory.get('trajectory_classification')} | "
                f"sustained_role_change={role.get('sustained_role_change')} | "
                f"recent_role={role.get('recent_role')} | prior_role={role.get('prior_role')}"
            )
            for match in trajectory.get("matches") or []:
                if not isinstance(match, Mapping):
                    continue
                lines.append(
                    "- GW{gw} vs {opp} {ha} | {start} {mins}m | "
                    "Result {result} | Pts {pts} | G {goals} A {assists} | "
                    "xG {xg} npxG {npxg} xA {xa} xGI {xgi} | "
                    "Sh {shots} SOT {sot} Box {box} KP/CC {kp}/{cc} BC {bc} | "
                    "SP {sp} PEN {pen} DEF {deff} | "
                    "team shape {shape} opp shape {opp_shape} role {role} | "
                    "Bayesian {bayes} | price {price} | outlook 1/3/5 {outlook}".format(
                        gw=match.get("gw"),
                        opp=match.get("opponent_team_id"),
                        ha="H" if match.get("home") is True else "A" if match.get("home") is False else "?",
                        start="START" if match.get("starter") else "SUB",
                        mins=match.get("minutes"),
                        result=match.get("result", "UNAVAILABLE"),
                        pts=match.get("fpl_points"),
                        goals=match.get("goals", "UNAVAILABLE"),
                        assists=match.get("assists", "UNAVAILABLE"),
                        xg=match.get("xg"),
                        npxg=match.get("npxg", "UNAVAILABLE"),
                        xa=match.get("xa"),
                        xgi=match.get("xgi"),
                        shots=match.get("shots"),
                        sot=match.get("shots_on_target"),
                        box=match.get("box_touches"),
                        kp=match.get("key_passes"),
                        cc=match.get("chances_created"),
                        bc=match.get("big_chances"),
                        sp=match.get("set_piece_role", match.get("set_piece_involvement")),
                        pen=match.get("penalty_role", match.get("penalty_involvement")),
                        deff=match.get("defensive_contribution"),
                        shape=match.get("team_formation"),
                        opp_shape=match.get("opponent_formation", "UNAVAILABLE"),
                        role=match.get("role"),
                        bayes=match.get("bayesian_update", item.get("bayesian_state", "UNAVAILABLE")),
                        price=match.get("price_movement", "UNAVAILABLE"),
                        outlook=match.get("outlook_1_3_5gw", "UNAVAILABLE"),
                    )
                )
            link = item.get("linkup_dependency")
            if link:
                lines.append("LINK-UP DEPENDENCY: " + _markdown_cell(link))
        candidates = [
            dict(item)
            for item in payload.get("material_universe_candidates") or []
            if isinstance(item, Mapping)
        ]
        if candidates:
            lines.append("### MATERIAL UNIVERSE CANDIDATES")
            for item in candidates:
                trajectory = dict(item.get("trajectory") or {})
                lines.append(
                    "- "
                    f"{item.get('name') or item.get('element_id')} | "
                    f"{item.get('primary_classification')} | "
                    f"trend={trajectory.get('trajectory_classification')} | "
                    f"xMins={(item.get('minutes') or {}).get('xmins')} | "
                    f"P(start)={(item.get('minutes') or {}).get('p_start')} | "
                    f"1/3/5GW={item.get('horizon_1gw')}/{item.get('horizon_3gw')}/{item.get('horizon_5gw')}"
                )
        excluded.extend(("our15", "material_universe_candidates"))

    elif section_id == "S17":
        lines.extend(
            (
                "FACT: OFFICIAL_FPL_OCCURRENCE_FACTS",
                "MODEL: V12_OCCURRENCE_MODEL_OUTPUTS",
                "INFERENCE: V12_DECISION_INFERENCE",
            )
        )

    return lines, tuple(excluded)


def render_deep_text(report: Mapping[str, Any]) -> str:
    """Human-facing DEEP renderer retaining nested analytic evidence."""
    sections = [
        dict(row)
        for row in report.get("sections") or []
        if isinstance(row, Mapping)
    ]
    owned_ids = {
        int(item.get("element_id"))
        for section in sections
        if str(section.get("section_id") or "") == "S02"
        for item in (
            (section.get("content") or {}).get("rows") or []
            if isinstance(section.get("content"), Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and item.get("element_id") is not None
    }
    owned_names = {
        int(item.get("element_id")): str(
            item.get("player")
            or item.get("name")
            or item.get("element_id")
        )
        for section in sections
        if str(section.get("section_id") or "") == "S02"
        for item in (
            (section.get("content") or {}).get("rows") or []
            if isinstance(section.get("content"), Mapping)
            else []
        )
        if isinstance(item, Mapping)
        and item.get("element_id") is not None
    }

    blocks: list[str] = []
    for row in sections:
        label = str(row.get("label") or "")
        state = str(row.get("state") or "")
        section_id = str(row.get("section_id") or "")
        lines = [
            _visible_section_heading(section_id, label),
            f"Status: {state}",
        ]
        reason = str(row.get("degradation_reason") or "").strip()
        if state != "COMPLETE" and reason:
            lines.append(f"Reason: {reason}")
        content = row.get("content")
        content_map = (
            dict(content or {})
            if isinstance(content, Mapping)
            else {}
        )
        # Renderer consumes the bound payload verbatim. Binding metadata is
        # deliberately not synthesized here: missing binding must fail QA,
        # never be repaired by presentation code.
        binding = content_map.get("authoritative_binding")
        if isinstance(binding, Mapping):
            lines.append(
                "AUTHORITY: "
                + str(binding.get("producer") or "UNAVAILABLE")
                + " | BINDING="
                + str(binding.get("status") or "UNAVAILABLE")
            )

        visible_lines, visible_excluded = (
            _render_deep_visible_contract_lines(
                section_id=section_id,
                content=content_map,
                owned_ids=owned_ids,
                owned_names=owned_names,
            )
        )
        lines.extend(visible_lines)

        scout = [
            dict(item)
            for item in content_map.get(
                "post_match_match_by_match_scout"
            )
            or ()
            if isinstance(item, Mapping)
        ]
        if scout:
            lines.extend(_render_match_scout_lines(scout))

        math_stack = content_map.get(
            "mathematical_decision_stack"
        )
        if isinstance(math_stack, Mapping):
            lines.extend(_render_math_stack_lines(math_stack))

        if "PACKAGE OPTIMIZER" in label.upper():
            lines.extend(
                _render_package_frontier_lines(
                    content_map,
                    section_state=state,
                )
            )

        stagec = content_map.get("stagec_universe_intelligence")
        if section_id == "S04" and isinstance(stagec, Mapping):
            from src.engines.v12_stagec_reporting import (
                render_stagec_deep_lines,
            )

            lines.extend(render_stagec_deep_lines(stagec))

        generic = _render_generic_human_content(
            content_map,
            excluded_keys=(
                "post_match_match_by_match_scout",
                "mathematical_decision_stack",
                "package_search_proof",
                "search_proof",
                "package_universe_challengers",
                "universe_challengers",
                "package_routes",
                "routes",
                "frontier",
                "stagec_universe_intelligence",
                *visible_excluded,
            ),
        )
        if generic:
            lines.extend(generic)
        blocks.append("\n".join(lines))
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

