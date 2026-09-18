from __future__ import annotations

"""Canonical report-plane owner for current user decision context.

This state is intentionally outside the V6 factual data plane. It hydrates the
latest explicit user decision state for a report occurrence and keeps active
routes visible independently of optimizer ranking.
"""

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .delivery_integrity import DeliveryIntegrityError
from .temporal import canonical_timestamp, parse_timestamp


SCENARIO_STATES = frozenset({"CONTEMPLATED", "EXECUTED", "REJECTED", "SUPERSEDED"})


def _timestamp(value: Any, *, label: str) -> datetime:
    try:
        return parse_timestamp(value, label=label)
    except Exception as exc:
        raise DeliveryIntegrityError(f"{label} must be timezone-aware ISO-8601") from exc


def _canonical_event(raw: Mapping[str, Any], *, sequence: int) -> dict[str, Any]:
    scenario_id = str(raw.get("scenario_id") or "").strip()
    if not scenario_id:
        raise DeliveryIntegrityError("scenario_id is required")
    state = str(raw.get("state") or "").strip().upper()
    if state not in SCENARIO_STATES:
        raise DeliveryIntegrityError(f"invalid scenario state: {state or '<empty>'}")
    updated = _timestamp(raw.get("updated_at"), label=f"scenario[{scenario_id}].updated_at")
    route = raw.get("route")
    if route is not None and not isinstance(route, Mapping):
        raise DeliveryIntegrityError(f"scenario[{scenario_id}].route must be an object")
    candidates = raw.get("player_candidates") or []
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise DeliveryIntegrityError(f"scenario[{scenario_id}].player_candidates must be a sequence")
    return {
        **dict(raw),
        "scenario_id": scenario_id,
        "state": state,
        "updated_at": canonical_timestamp(updated, timespec="seconds"),
        "route": dict(route) if isinstance(route, Mapping) else None,
        "player_candidates": [str(value) for value in candidates if str(value).strip()],
        "_sequence": sequence,
        "_updated": updated,
    }


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def hydrate_current_decision_context(
    *,
    report_slot_id: str,
    hydrated_at: str | datetime,
    confirmed_our15: Sequence[Mapping[str, Any]],
    latest_confirmed_squad_state: Mapping[str, Any],
    scenario_events: Sequence[Mapping[str, Any]],
    current_horizon: str,
    current_xi: Sequence[int | str] | None = None,
    current_bench: Sequence[int | str] | None = None,
    latest_manual_state: Mapping[str, Any] | None = None,
    latest_user_constraints: Sequence[str] = (),
    locked_decisions: Sequence[Mapping[str, Any]] = (),
    decision_window_open: bool = True,
) -> dict[str, Any]:
    """Hydrate one canonical CURRENT_DECISION_CONTEXT.

    Latest explicit state wins per scenario. Optimizer membership never changes
    scenario state, so a contemplated user route remains visible until an explicit
    user transition, confirmed execution, supersession, rejection, or window close.
    """
    slot = str(report_slot_id or "").strip()
    if not slot:
        raise DeliveryIntegrityError("report_slot_id is required")
    hydrated = _timestamp(hydrated_at, label="hydrated_at")
    horizon = str(current_horizon or "").strip().upper()
    if not horizon:
        raise DeliveryIntegrityError("current_horizon is required")

    canonical_events = [
        _canonical_event(event, sequence=index)
        for index, event in enumerate(scenario_events)
    ]
    latest_by_id: dict[str, dict[str, Any]] = {}
    for event in canonical_events:
        previous = latest_by_id.get(event["scenario_id"])
        if previous is None or (event["_updated"], event["_sequence"]) >= (
            previous["_updated"],
            previous["_sequence"],
        ):
            latest_by_id[event["scenario_id"]] = event

    resolved: list[dict[str, Any]] = []
    for scenario_id in sorted(latest_by_id):
        row = dict(latest_by_id[scenario_id])
        row.pop("_updated", None)
        row.pop("_sequence", None)
        row["active"] = bool(decision_window_open and row["state"] == "CONTEMPLATED")
        row["executed"] = row["state"] == "EXECUTED"
        resolved.append(row)

    active = [row for row in resolved if row["active"]]
    executed = [row for row in resolved if row["state"] == "EXECUTED"]
    rejected = [row for row in resolved if row["state"] == "REJECTED"]
    superseded = [row for row in resolved if row["state"] == "SUPERSEDED"]
    player_candidates = sorted(
        {
            candidate
            for row in active
            for candidate in row.get("player_candidates", [])
            if candidate
        }
    )

    payload = {
        "report_slot_id": slot,
        "hydrated_at": canonical_timestamp(hydrated, timespec="seconds"),
        "confirmed_our15": [dict(row) for row in confirmed_our15],
        "latest_confirmed_squad_state": dict(latest_confirmed_squad_state),
        "current_xi": list(current_xi or []),
        "current_bench": list(current_bench or []),
        "latest_manual_state": dict(latest_manual_state or {}),
        "active_contemplated_transfers": active,
        "executed_transfers": executed,
        "rejected_scenarios": rejected,
        "superseded_scenarios": superseded,
        "player_candidates_explicitly_discussed": player_candidates,
        "current_horizon": horizon,
        "latest_user_constraints": [str(value) for value in latest_user_constraints],
        "locked_decisions": [dict(value) for value in locked_decisions],
        "decision_window_open": bool(decision_window_open),
        "execution_state": "EXECUTED_PRESENT" if executed else "NO_NEW_EXECUTION_CONFIRMED",
        "optimizer_may_hide_active_scenario": False,
        "v6_factual_data_plane_owner": False,
    }
    payload["context_fingerprint"] = _fingerprint(payload)
    return {
        "status": "PASS",
        "context_kind": "CURRENT_DECISION_CONTEXT",
        "active_scenario_count": len(active),
        "active_scenario_ids": [row["scenario_id"] for row in active],
        "active_scenarios": active,
        "executed_scenario_ids": [row["scenario_id"] for row in executed],
        "rejected_scenario_ids": [row["scenario_id"] for row in rejected],
        "superseded_scenario_ids": [row["scenario_id"] for row in superseded],
        **payload,
    }
