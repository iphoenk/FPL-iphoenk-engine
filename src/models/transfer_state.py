from __future__ import annotations

from collections import Counter
from typing import Any

from src.rules import CHIP_API_NAMES, RULESET_ID, TRANSFER_RULES


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _chip_name(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return str(CHIP_API_NAMES.get(raw, raw)).strip().lower()


def _chip_events(history: dict[str, Any]) -> set[int]:
    out: set[int] = set()
    for row in history.get("chips") or []:
        if not isinstance(row, dict):
            continue
        event = _int(row.get("event"))
        if event is None:
            continue
        if _chip_name(row.get("name")) in {"wildcard", "free_hit"}:
            out.add(event)
    return out


def _transfers_by_event(transfers: list[dict[str, Any]]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for row in transfers or []:
        if not isinstance(row, dict):
            continue
        event = _int(row.get("event"))
        if event is not None and event > 0:
            counts[event] += 1
    return counts


def reconstruct_entering_free_transfers(
    entry: dict[str, Any],
    history: dict[str, Any],
    transfers: list[dict[str, Any]],
    planning_gw: int,
) -> dict[str, Any]:
    """Reconstruct the public, deadline-settled free-transfer bank.

    This never pretends that public transfer history can see unpublished current-
    Gameweek moves. It returns the bank entering ``planning_gw``; callers decide
    whether current-GW remaining transfers are observable/exact.
    """
    started_event = _int(entry.get("started_event"))
    gw = int(planning_gw or 0)
    grant = int(TRANSFER_RULES["free_transfers_per_gameweek"])
    max_bank = int(TRANSFER_RULES["max_bank_free_transfers"])
    if started_event is None or started_event <= 0 or gw <= 0:
        return {"status": "UNAVAILABLE", "reason": "STARTED_EVENT_OR_PLANNING_GW_UNAVAILABLE"}
    if gw <= started_event:
        return {
            "status": "EXACT",
            "free_transfers_entering_gameweek": None,
            "unlimited_initial_transfers": bool(TRANSFER_RULES.get("unlimited_before_first_deadline")),
            "started_event": started_event,
        }

    chip_events = _chip_events(history)
    transfer_counts = _transfers_by_event(transfers)
    available = grant
    trace: list[dict[str, Any]] = []
    for event in range(started_event + 1, gw):
        before = available
        if event in chip_events:
            after = before
            mode = "CHIP_PRESERVES_SAVED_FREE_TRANSFERS"
        else:
            used = int(transfer_counts[event])
            after = min(max_bank, max(0, before - used) + grant)
            mode = "NORMAL_ROLL"
        trace.append({
            "event": event,
            "free_transfers_before": before,
            "observed_transfers": int(transfer_counts[event]),
            "chip_preservation": event in chip_events,
            "free_transfers_next_gameweek": after,
            "mode": mode,
        })
        available = after
    return {
        "status": "EXACT",
        "free_transfers_entering_gameweek": int(available),
        "unlimited_initial_transfers": False,
        "started_event": started_event,
        "trace": trace,
    }


def build_transfer_state(
    *,
    lock: dict[str, Any],
    projection_baseline: dict[str, Any],
    entry: dict[str, Any],
    history: dict[str, Any],
    transfers: list[dict[str, Any]],
    planning_gw: int,
    submitted_gw: int | None,
) -> dict[str, Any]:
    """Resolve current transfer-cost authority without fabricating private state."""
    hit = int(TRANSFER_RULES["additional_transfer_cost_points"])
    max_bank = int(TRANSFER_RULES["max_bank_free_transfers"])
    current_chip = "wildcard" if bool(lock.get("wildcard_active")) else "free_hit" if bool(lock.get("free_hit_active")) else None
    override_applied = projection_baseline.get("override_applied") is True
    captured_free = _int(lock.get("free_transfers"))
    captured_cost = _int(lock.get("transfer_cost_points"))
    if override_applied and captured_free is not None and 0 <= captured_free <= max_bank and captured_cost is not None and captured_cost >= 0:
        return {
            "contract": "FPL_TRANSFER_STATE_V1",
            "ruleset_id": RULESET_ID,
            "status": "EXACT",
            "authority": "STRUCTURED_USER_CAPTURE",
            "planning_gw": int(planning_gw),
            "free_transfers_remaining": captured_free,
            "existing_transfer_cost_points": captured_cost,
            "additional_transfer_cost_points": hit,
            "unlimited_transfers_active": current_chip in {"wildcard", "free_hit"},
            "active_transfer_chip": current_chip,
            "exact_incremental_hit_available": True,
            "public_reconstruction": reconstruct_entering_free_transfers(entry, history, transfers, int(planning_gw)),
            "governance": {
                "current_private_transfer_state_not_inferred_from_public_absence": True,
                "exact_user_capture_wins_for_exact_target_gw": True,
                "saved_free_transfer_cap_registry_owned": True,
            },
        }

    reconstructed = reconstruct_entering_free_transfers(entry, history, transfers, int(planning_gw))
    entering = _int(reconstructed.get("free_transfers_entering_gameweek"))
    submitted = _int(submitted_gw)
    settled_current_event = submitted is not None and int(planning_gw) == submitted
    if reconstructed.get("unlimited_initial_transfers") is True:
        return {
            "contract": "FPL_TRANSFER_STATE_V1",
            "ruleset_id": RULESET_ID,
            "status": "EXACT",
            "authority": "OFFICIAL_INITIAL_SQUAD_RULE",
            "planning_gw": int(planning_gw),
            "free_transfers_remaining": None,
            "existing_transfer_cost_points": 0,
            "additional_transfer_cost_points": hit,
            "unlimited_transfers_active": True,
            "active_transfer_chip": None,
            "exact_incremental_hit_available": True,
            "public_reconstruction": reconstructed,
        }
    if entering is not None and settled_current_event:
        count = int(_transfers_by_event(transfers)[int(planning_gw)])
        current_chip_event = int(planning_gw) in _chip_events(history)
        remaining = entering if current_chip_event else max(0, entering - count)
        existing_cost = 0 if current_chip_event else max(0, count - entering) * hit
        return {
            "contract": "FPL_TRANSFER_STATE_V1",
            "ruleset_id": RULESET_ID,
            "status": "EXACT",
            "authority": "OFFICIAL_SETTLED_TRANSFER_HISTORY",
            "planning_gw": int(planning_gw),
            "free_transfers_remaining": remaining,
            "existing_transfer_cost_points": existing_cost,
            "additional_transfer_cost_points": hit,
            "unlimited_transfers_active": current_chip_event,
            "active_transfer_chip": "WILDCARD_OR_FREE_HIT" if current_chip_event else None,
            "exact_incremental_hit_available": True,
            "public_reconstruction": reconstructed,
        }

    return {
        "contract": "FPL_TRANSFER_STATE_V1",
        "ruleset_id": RULESET_ID,
        "status": "PARTIAL",
        "authority": "PUBLIC_PRE_TRANSFER_RECONSTRUCTION_ONLY",
        "planning_gw": int(planning_gw),
        "free_transfers_entering_gameweek": entering,
        "free_transfers_remaining": None,
        "existing_transfer_cost_points": None,
        "additional_transfer_cost_points": hit,
        "unlimited_transfers_active": False,
        "active_transfer_chip": None,
        "exact_incremental_hit_available": False,
        "public_reconstruction": reconstructed,
        "reason": "CURRENT_PRE_DEADLINE_PRIVATE_TRANSFER_STATE_NOT_OBSERVABLE",
        "governance": {
            "public_source_absence_is_not_zero_transfers": True,
            "package_hit_must_not_be_claimed_exact": True,
        },
    }


def incremental_hit_cost(changes: int, transfer_state: dict[str, Any] | None) -> tuple[float, bool]:
    state = transfer_state or {}
    if state.get("exact_incremental_hit_available") is not True:
        return 0.0, False
    if state.get("unlimited_transfers_active") is True:
        return 0.0, True
    free = _int(state.get("free_transfers_remaining"))
    per_transfer = _int(state.get("additional_transfer_cost_points"))
    if free is None or per_transfer is None or free < 0 or per_transfer < 0:
        return 0.0, False
    return float(max(0, int(changes) - free) * per_transfer), True
