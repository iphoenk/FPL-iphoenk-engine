from __future__ import annotations

"""Post-deadline immutable personal-team semantics for Match reporting.

This module derives a factual view from authenticated Official FPL personal data.
It is not an authority, does not acquire data, and does not mutate V6.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

AUTH_AVAILABLE = "AUTH_AVAILABLE"
APPEARED = {"STARTED", "CAMEO"}
FINISHED = {"FT", "FINISHED", "COMPLETED"}
LIVE_OR_FINISHED = FINISHED | {"LIVE"}

_POSITION = {
    1: "GK", 2: "DEF", 3: "MID", 4: "FWD",
    "GKP": "GK", "GK": "GK", "DEF": "DEF", "MID": "MID", "FWD": "FWD",
}


def _position(value: Any) -> str | None:
    if value is None:
        return None
    key = str(value).upper() if not isinstance(value, int) else value
    return _POSITION.get(key)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def deadline_passed_for_gw(
    official_snapshot: Mapping[str, Any],
    gw: int,
    *,
    now: datetime | None = None,
) -> bool:
    events = ((official_snapshot.get("bootstrap") or {}).get("events") or [])
    event = next((row for row in events if _int(row.get("id"), -1) == int(gw)), None)
    if not isinstance(event, Mapping) or not event.get("deadline_time"):
        return False
    raw = str(event["deadline_time"]).replace("Z", "+00:00")
    try:
        deadline = datetime.fromisoformat(raw)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc) >= deadline.astimezone(timezone.utc)


def build_post_deadline_locked_team_view(
    current_team: Mapping[str, Any],
    *,
    target_gw: int,
    deadline_passed: bool,
    volatile_scope_status: str = "UNKNOWN",
) -> dict[str, Any]:
    """Build one immutable locked-team view from authenticated personal picks."""
    if not deadline_passed:
        raise RuntimeError("post-deadline locked team view requires passed deadline")
    if _int(current_team.get("gw"), -1) != int(target_gw):
        raise RuntimeError("personal team GW does not match target GW")
    if str(current_team.get("authority") or "").upper() != "OFFICIAL_FPL":
        raise RuntimeError("personal team authority must be OFFICIAL_FPL")
    if str(current_team.get("auth_state") or "").upper() != AUTH_AVAILABLE:
        raise RuntimeError("personal team must be authenticated")
    if current_team.get("canonical") is not True:
        raise RuntimeError("personal team must be canonical")

    players = [dict(row) for row in (current_team.get("players") or []) if row.get("element_id") is not None]
    if len(players) != 15 or len({_int(row["element_id"]) for row in players}) != 15:
        raise RuntimeError("locked personal team requires exactly 15 unique element_id values")

    for row in players:
        row["element_id"] = _int(row["element_id"])
        row["squad_position"] = _int(row.get("squad_position"), 99)
        row["bench_order"] = (
            _int(row.get("bench_order"))
            if row.get("bench_order") is not None
            else (row["squad_position"] - 11 if row["squad_position"] > 11 else None)
        )
        row["multiplier"] = _int(row.get("multiplier"))
        row["position"] = _position(row.get("position"))

    ordered = sorted(players, key=lambda row: (row["squad_position"], row["element_id"]))
    xi = [row for row in ordered if row["squad_position"] <= 11]
    bench = sorted(
        [row for row in ordered if row["squad_position"] > 11],
        key=lambda row: (row["bench_order"] if row["bench_order"] is not None else 99, row["squad_position"]),
    )
    if len(xi) != 11 or len(bench) != 4:
        raise RuntimeError("locked personal team requires exact XI=11 and bench=4")

    captains = [row for row in ordered if bool(row.get("captain"))]
    vice = [row for row in ordered if bool(row.get("vice_captain"))]
    if len(captains) != 1 or len(vice) != 1:
        raise RuntimeError("locked personal team requires exactly one captain and one vice captain")

    return {
        "schema": "post_deadline_locked_team_view.v1",
        "status": "CURRENT_IMMUTABLE",
        "derived_view_only": True,
        "authority": "OFFICIAL_FPL_AUTHENTICATED_PERSONAL_STATE",
        "gw": int(target_gw),
        "our15": [row["element_id"] for row in ordered],
        "starting_xi": [row["element_id"] for row in xi],
        "bench_order": [row["element_id"] for row in bench],
        "captain": captains[0]["element_id"],
        "vice_captain": vice[0]["element_id"],
        "multiplier_by_element": {str(row["element_id"]): row["multiplier"] for row in ordered},
        "squad_position_by_element": {str(row["element_id"]): row["squad_position"] for row in ordered},
        "position_by_element": {str(row["element_id"]): row["position"] for row in ordered},
        "players": ordered,
        "freshness": {
            "locked_lineup": "CURRENT_IMMUTABLE",
            "artifact_age_can_stale_locked_fields": False,
            "volatile_live_scope": str(volatile_scope_status or "UNKNOWN"),
            "volatile_scope_is_independent": True,
        },
        "deadline_lock": {
            "passed": True,
            "same_target_gw": True,
            "authenticated": True,
            "generated_at": current_team.get("generated_at"),
            "squad_state": current_team.get("squad_state"),
            "lineage": current_team.get("lineage"),
        },
    }


def _appearance(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("appearance_state") or row.get("appearance_status") or "").upper()
    if explicit in {"STARTED", "CAMEO", "DNP"}:
        return explicit
    if row.get("started_club_match") is True or row.get("started") is True:
        return "STARTED"
    if row.get("came_on_as_sub") is True or row.get("substitute") is True:
        return "CAMEO"
    minutes = _int(row.get("minutes"))
    fixture = str(row.get("fixture_status") or "").upper()
    if minutes == 0 and fixture in FINISHED:
        return "DNP"
    if minutes > 0 and (row.get("started_club_match") is False or row.get("started") is False):
        return "CAMEO"
    if minutes > 0:
        return "APPEARED_START_STATUS_UNRESOLVED"
    return "NOT_YET_RESOLVED"


def _formation_legal(positions: Sequence[str | None]) -> bool:
    counts = Counter(pos for pos in positions if pos)
    return (
        counts.get("GK", 0) == 1
        and 3 <= counts.get("DEF", 0) <= 5
        and 2 <= counts.get("MID", 0) <= 5
        and 1 <= counts.get("FWD", 0) <= 3
        and sum(counts.values()) == 11
    )


def _bench_availability(outcome: Mapping[str, Any] | None) -> str:
    if not outcome:
        return "PENDING"
    state = str(outcome.get("appearance_state") or "")
    if state == "DNP":
        return "DNP"
    if state in APPEARED or state == "APPEARED_START_STATUS_UNRESOLVED":
        return "PLAYED"
    return "PENDING"


def _solve_autosub_world(
    *,
    locked: Mapping[str, Any],
    dnp_elements: Sequence[int],
    played_bench: set[int],
) -> dict[int, int]:
    """Resolve one fully-known bench-availability world in priority order.

    A played bench candidate must be used when at least one remaining DNP slot
    can accept that candidate without making the selected XI formation illegal.
    If several DNP slots are legal, use global look-ahead to preserve the
    maximum number of later legal substitutions, then prefer same-position and
    earlier XI slots deterministically.
    """
    positions = {int(k): v for k, v in (locked.get("position_by_element") or {}).items()}
    xi_order = [int(x) for x in locked.get("starting_xi") or []]
    bench_order = [int(x) for x in locked.get("bench_order") or []]
    dnp = tuple(eid for eid in xi_order if eid in {int(x) for x in dnp_elements})
    xi_rank = {eid: index for index, eid in enumerate(xi_order)}
    initial_slots = {eid: positions.get(eid) for eid in xi_order}

    def score(mapping: Mapping[int, int]) -> tuple[Any, ...]:
        same_position = sum(
            positions.get(out_id) == positions.get(in_id)
            for out_id, in_id in mapping.items()
        )
        assigned_out_rank = tuple(
            -xi_rank[out_id]
            for in_id in bench_order
            for out_id, mapped_in in mapping.items()
            if mapped_in == in_id
        )
        return (len(mapping), same_position, assigned_out_rank)

    def walk(
        bench_index: int,
        slots: dict[int, str | None],
        remaining: tuple[int, ...],
        mapping: dict[int, int],
    ) -> dict[int, int]:
        if bench_index >= len(bench_order) or not remaining:
            return dict(mapping)

        candidate = bench_order[bench_index]
        if candidate not in played_bench:
            return walk(bench_index + 1, slots, remaining, mapping)

        candidate_position = positions.get(candidate)
        legal_outs: list[int] = []
        for out_id in remaining:
            out_position = positions.get(out_id)
            if candidate_position == "GK":
                if out_position != "GK":
                    continue
            elif out_position == "GK" or candidate_position not in {"DEF", "MID", "FWD"}:
                continue
            proposed = dict(slots)
            proposed[out_id] = candidate_position
            if _formation_legal(list(proposed.values())):
                legal_outs.append(out_id)

        if not legal_outs:
            return walk(bench_index + 1, slots, remaining, mapping)

        branches: list[dict[int, int]] = []
        for out_id in legal_outs:
            proposed = dict(slots)
            proposed[out_id] = candidate_position
            next_mapping = dict(mapping)
            next_mapping[out_id] = candidate
            branches.append(
                walk(
                    bench_index + 1,
                    proposed,
                    tuple(eid for eid in remaining if eid != out_id),
                    next_mapping,
                )
            )
        return max(branches, key=score)

    return walk(0, initial_slots, dnp, {})


def _resolve_global_autosubs(
    *,
    locked: Mapping[str, Any],
    outcome_by_element: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    """Resolve all confirmed XI DNPs as one global sequential substitution state."""
    xi_order = [int(x) for x in locked.get("starting_xi") or []]
    bench_order = [int(x) for x in locked.get("bench_order") or []]
    dnp_elements = [
        eid
        for eid in xi_order
        if str((outcome_by_element.get(eid) or {}).get("appearance_state") or "") == "DNP"
    ]
    if not dnp_elements:
        return {
            "status": "RESOLVED",
            "substitution_map": {},
            "consumed_bench": [],
            "pending_bench": [],
            "world_count": 1,
        }

    bench_state = {
        eid: _bench_availability(outcome_by_element.get(eid))
        for eid in bench_order
    }
    fixed_played = {eid for eid, state in bench_state.items() if state == "PLAYED"}
    pending = [eid for eid, state in bench_state.items() if state == "PENDING"]

    world_maps: list[dict[int, int]] = []
    for mask in range(1 << len(pending)):
        played = set(fixed_played)
        for index, eid in enumerate(pending):
            if mask & (1 << index):
                played.add(eid)
        world_maps.append(
            _solve_autosub_world(
                locked=locked,
                dnp_elements=dnp_elements,
                played_bench=played,
            )
        )

    final_map: dict[str, int | str] = {}
    for out_id in dnp_elements:
        outcomes = {world.get(out_id) for world in world_maps}
        if len(outcomes) == 1:
            only = next(iter(outcomes))
            final_map[str(out_id)] = only if only is not None else "no_legal_sub"
        else:
            final_map[str(out_id)] = "pending"

    consumed = sorted(
        {
            int(value)
            for value in final_map.values()
            if isinstance(value, int)
        },
        key=lambda eid: bench_order.index(eid),
    )
    return {
        "status": "PENDING" if any(value == "pending" for value in final_map.values()) else "RESOLVED",
        "substitution_map": final_map,
        "consumed_bench": consumed,
        "pending_bench": pending,
        "bench_state": {str(eid): bench_state[eid] for eid in bench_order},
        "world_count": len(world_maps),
        "sequential_global": True,
        "bench_player_consumed_at_most_once": True,
        "formation_checked_after_each_substitution": True,
    }


def reconcile_owned_match_events(
    locked: Mapping[str, Any],
    match_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Join owned match outcomes to the immutable locked XI using element_id only."""
    if locked.get("status") != "CURRENT_IMMUTABLE":
        raise RuntimeError("owned match reconciliation requires immutable locked-team view")

    owned = {int(x) for x in locked.get("our15") or []}
    xi = {int(x) for x in locked.get("starting_xi") or []}
    captain = _int(locked.get("captain"), -1)
    vice = _int(locked.get("vice_captain"), -1)
    bench_rank = {int(eid): idx + 1 for idx, eid in enumerate(locked.get("bench_order") or [])}

    by_element: dict[int, Mapping[str, Any]] = {}
    for row in match_rows:
        raw = row.get("element_id", row.get("element"))
        if raw is None:
            continue
        eid = _int(raw, -1)
        if eid in owned:
            by_element[eid] = row

    preliminary: dict[int, dict[str, Any]] = {}
    for eid, row in by_element.items():
        fixture_status = str(row.get("fixture_status") or "").upper()
        if fixture_status not in LIVE_OR_FINISHED:
            continue
        appearance = _appearance(row)
        preliminary[eid] = {
            "element_id": eid,
            "fixture_status": fixture_status,
            "appearance_state": appearance,
            "minutes": _int(row.get("minutes")),
        }

    autosub_resolution = _resolve_global_autosubs(
        locked=locked,
        outcome_by_element=preliminary,
    )
    final_substitution_map = autosub_resolution.get("substitution_map") or {}

    reconciled: list[dict[str, Any]] = []
    for eid in sorted(preliminary):
        row = by_element[eid]
        base = preliminary[eid]
        in_xi = eid in xi
        appearance = base["appearance_state"]
        autosub = None

        if in_xi and appearance == "DNP":
            resolved_sub = final_substitution_map.get(str(eid), "no_legal_sub")
            if isinstance(resolved_sub, int):
                autosub = {"status": "ACTIVATES", "element_id": resolved_sub}
                personal_state = "DNP_WITH_AUTOSUB_POSSIBLE"
            elif resolved_sub == "pending":
                autosub = {"status": "PENDING"}
                personal_state = "DNP_AUTOSUB_PENDING"
            else:
                personal_state = "DNP_NO_LEGAL_AUTOSUB"
        elif in_xi and appearance == "CAMEO":
            autosub = {"status": "BLOCKED_BY_APPEARANCE"}
            personal_state = "CAMEO_BLOCKED_AUTOSUB"
        elif in_xi and appearance == "STARTED":
            personal_state = "STARTED"
        elif in_xi and appearance == "APPEARED_START_STATUS_UNRESOLVED":
            personal_state = "APPEARED_AUTOSUB_BLOCKED_START_STATUS_UNRESOLVED"
        elif not in_xi and appearance == "DNP":
            personal_state = "BENCH_DNP_NO_DIRECT_XI_AUTOSUB_EFFECT"
        elif not in_xi and appearance in APPEARED | {"APPEARED_START_STATUS_UNRESOLVED"}:
            personal_state = "BENCH_APPEARED_NO_DIRECT_XI_AUTOSUB_EFFECT"
        else:
            personal_state = "PENDING_MATCH_RESOLUTION"

        reconciled.append({
            **base,
            "owned": True,
            "locked_role": "STARTING_XI" if in_xi else "BENCH",
            "bench_order": bench_rank.get(eid),
            "captain": eid == captain,
            "vice_captain": eid == vice,
            "started_club_match": True if appearance == "STARTED" else False if appearance == "CAMEO" else None,
            "substitute": True if appearance == "CAMEO" else False if appearance == "STARTED" else None,
            "dnp": appearance == "DNP",
            "fpl_points": _int(row.get("total_points", row.get("fpl_points"))),
            "yellow_cards": _int(row.get("yellow_cards")),
            "red_cards": _int(row.get("red_cards")),
            "defensive_contribution": row.get("defensive_contribution", row.get("defensive_contributions")),
            "personal_state": personal_state,
            "autosub": autosub,
            "identity_join": "CANONICAL_ELEMENT_ID",
        })

    priority = sorted(
        reconciled,
        key=lambda row: (
            0 if row["locked_role"] == "STARTING_XI" and row["personal_state"] in {
                "CAMEO_BLOCKED_AUTOSUB",
                "DNP_WITH_AUTOSUB_POSSIBLE",
                "DNP_AUTOSUB_PENDING",
                "DNP_NO_LEGAL_AUTOSUB",
            } else 1,
            row["element_id"],
        ),
    )
    expected = len([
        row for row in match_rows
        if _int(row.get("element_id", row.get("element")), -1) in owned
        and str(row.get("fixture_status") or "").upper() in LIVE_OR_FINISHED
    ])
    return {
        "schema": "owned_match_reconciliation.v1",
        "status": "PASS" if len(reconciled) == expected else "PARTIAL",
        "gw": locked.get("gw"),
        "identity_join": "CANONICAL_ELEMENT_ID_ONLY",
        "completed_or_live_owned_expected": expected,
        "completed_or_live_owned_reconciled": len(reconciled),
        "coverage_complete": len(reconciled) == expected,
        "autosub_resolution": autosub_resolution,
        "final_substitution_map": final_substitution_map,
        "players": reconciled,
        "personal_impact_priority": priority,
        "governance": {
            "personal_consequences_before_generic_observations": True,
            "cameo_blocks_autosub": True,
            "dnp_may_enable_legal_autosub": True,
            "autosubs_resolved_globally_in_bench_priority_order": True,
            "bench_candidate_consumed_once": True,
            "benched_dnp_does_not_activate_autosub_for_itself": True,
            "name_guessing_for_identity_forbidden": True,
        },
    }
