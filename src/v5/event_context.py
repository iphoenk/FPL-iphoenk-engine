from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.state import Phase, resolve_phase

REGISTRY_CONFIG = "config/v5_event_context_registry.json"


@dataclass(frozen=True)
class EventContext:
    current_gw: int | None
    next_gw: int | None
    last_finished_gw: int | None
    planning_gw: int | None
    submitted_gw: int | None
    scoring_gw: int | None
    deadline_time: str | None
    is_live_event: bool
    phase: Phase


def _cfg() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("event_flags"), dict):
        raise RuntimeError("invalid V5 event context registry")
    return data


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_event_context(bootstrap: dict, *, now: datetime | None = None) -> EventContext:
    flags = _cfg()["event_flags"]
    events = tuple(row for row in bootstrap.get("events", []) if isinstance(row, dict))
    current = next((e for e in events if e.get(flags["current"])), None)
    nxt = next((e for e in events if e.get(flags["next"])), None)
    finished = [e for e in events if e.get(flags["finished"])]
    last = max(finished, key=lambda e: int(e["id"])) if finished else None
    current_deadline = _parse(current.get(flags["deadline"])) if current else None
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if current and current_deadline and current_deadline > current_time:
        planning = current
    else:
        planning = nxt or current

    planning_deadline = planning.get(flags["deadline"]) if planning else None
    submitted = current or last
    scoring = current
    live_started = bool(
        current
        and not current.get(flags["finished"])
        and current_deadline
        and current_time >= current_deadline
    )

    planning_is_current = bool(
        planning
        and current
        and int(planning.get("id") or -1) == int(current.get("id") or -2)
    )
    # Live scoring and planning authority are distinct clocks. A current GW may
    # be live while the next GW is already the planning target. In that state,
    # keep is_live_event=True for scoring/Match Mode, but resolve the decision
    # phase against the NEXT deadline so the governed pre-deadline authority
    # chain (user lock -> authenticated -> public) remains intact.
    planning_live_started = bool(live_started and planning_is_current)
    planning_is_finished_current = bool(
        planning_is_current
        and current
        and current.get(flags["finished"])
        and not nxt
    )
    phase = resolve_phase(
        deadline_time=planning_deadline,
        now=current_time,
        live_started=planning_live_started,
        finished=planning_is_finished_current,
    )
    return EventContext(
        current_gw=int(current["id"]) if current else None,
        next_gw=int(nxt["id"]) if nxt else None,
        last_finished_gw=int(last["id"]) if last else None,
        planning_gw=int(planning["id"]) if planning else None,
        submitted_gw=int(submitted["id"]) if submitted else None,
        scoring_gw=int(scoring["id"]) if scoring else None,
        deadline_time=str(planning_deadline) if planning_deadline else None,
        is_live_event=live_started,
        phase=phase,
    )
