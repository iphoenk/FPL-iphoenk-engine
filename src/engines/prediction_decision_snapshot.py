from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.utils import DATA, atomic_json, parse_dt, read_json, utcnow

OUT = DATA / "decision_validation_snapshots.json"
OWNER = "reporting.decision_snapshot_evidence"
CONTRACT = "DECISION_VALIDATION_SNAPSHOTS_V1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _compact_comparisons(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in payload.get("top_comparisons") or []:
        player_out = row.get("player_out") or {}
        player_in = row.get("player_in") or {}
        out_id = _i(player_out.get("element"))
        in_id = _i(player_in.get("element"))
        if out_id <= 0 or in_id <= 0:
            continue
        rows.append({
            "player_out": out_id,
            "player_in": in_id,
            "state": row.get("state"),
            "actionability": row.get("actionability"),
            "challenger_type": row.get("challenger_type"),
            "exact_hit_cost": None,
            "hit_cost_state": "UNAVAILABLE_EXACT_HIT_COST",
        })
    return rows[:20]


def _persisted_comparator() -> dict[str, Any]:
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    comparator = watchlist.get("owned_challenger_decision") or {}
    if comparator.get("contract") != "OWNED_CHALLENGER_DECISION_V3":
        raise RuntimeError("prediction snapshot requires persisted governed owned challenger decision")
    if ((comparator.get("publication_validation") or {}).get("status")) != "PASS":
        raise RuntimeError("prediction snapshot refuses unvalidated owned challenger decision")
    return comparator


def run() -> dict[str, Any]:
    latest = read_json(DATA / "latest.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    team = read_json(DATA / "team.json", {})
    phase = latest.get("phase") or {}
    planning_gw = _i(phase.get("planning_gw", lineup.get("planning_gw")), 0)
    deadline = parse_dt(phase.get("deadline_time"))
    payload = read_json(OUT, {"schema_version": 2, "contract": CONTRACT, "records": {}})
    payload["schema_version"] = 2
    payload["contract"] = CONTRACT
    payload["owner"] = OWNER
    records = payload.setdefault("records", {})

    if planning_gw <= 0 or deadline is None or utcnow() >= deadline:
        payload["updated_at"] = _now()
        atomic_json(OUT, payload)
        return {"status": "NO_PREDEADLINE_CAPTURE", "planning_gw": planning_gw}

    comparator = _persisted_comparator()
    xi = []
    for row in lineup.get("starting_xi") or []:
        element = _i(row.get("element"))
        if element > 0:
            xi.append({"element": element, "position": row.get("position")})
    owned = []
    for row in team.get("team_value_ledger") or []:
        element = _i(row.get("element"))
        if element > 0:
            owned.append({"element": element, "position": row.get("position")})
    captain = _i((lineup.get("captain") or {}).get("element"))
    vice = _i((lineup.get("vice_captain") or {}).get("element"))
    captain_pool = []
    for row in lineup.get("captain_safe_pool") or []:
        element = _i(row.get("element"))
        if element > 0:
            captain_pool.append(element)
    if captain > 0 and captain not in captain_pool:
        captain_pool.append(captain)
    if vice > 0 and vice not in captain_pool:
        captain_pool.append(vice)

    bench = lineup.get("bench") or {}
    bench_gk = _i((bench.get("gk") or {}).get("element"))
    bench_order = [_i(row.get("element")) for row in bench.get("order") or []]
    bench_order = [element for element in bench_order if element > 0]

    record = {
        "gw": planning_gw,
        "captured_at": _now(),
        "deadline_time": phase.get("deadline_time"),
        "status": "PREDEADLINE_CAPTURED",
        "lineup": {
            "starting_xi": xi,
            "owned_squad": owned,
            "captain": captain if captain > 0 else None,
            "vice_captain": vice if vice > 0 else None,
            "captain_candidates": captain_pool,
            "bench_gk": bench_gk if bench_gk > 0 else None,
            "bench_order": bench_order,
        },
        "comparator": {
            "contract": comparator.get("contract"),
            "capability_status": comparator.get("capability_status"),
            "decision": comparator.get("decision") or {},
            "comparisons": _compact_comparisons(comparator),
        },
        "governance": {
            "genuine_predeadline_only": True,
            "postdeadline_overwrite_forbidden": True,
            "optimizer_change_penalty_is_not_fpl_hit_cost": True,
            "missing_exact_hit_cost_is_never_invented": True,
            "vice_and_bench_are_captured_only_when_genuinely_available_predeadline": True,
            "historical_snapshots_are_not_retrofitted": True,
            "reporting_owns_snapshot_capture": True,
            "prediction_evaluation_is_consumer_only": True,
            "challenger_decision_is_persisted_not_recomputed": True,
        },
    }
    records[str(planning_gw)] = record
    payload["updated_at"] = _now()
    atomic_json(OUT, payload)
    return {
        "status": "PREDEADLINE_CAPTURED",
        "planning_gw": planning_gw,
        "xi": len(xi),
        "owned": len(owned),
        "vice_captured": vice > 0,
        "bench_outfield_captured": len(bench_order),
        "comparisons": len(record["comparator"]["comparisons"]),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
