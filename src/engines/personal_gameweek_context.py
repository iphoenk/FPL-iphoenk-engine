from __future__ import annotations

from collections import Counter
from typing import Any

from src.utils import CONFIG, read_json

POSITION_BY_TYPE = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
LEGAL_FORMATIONS = {
    (3, 4, 3), (3, 5, 2),
    (4, 3, 3), (4, 4, 2), (4, 5, 1),
    (5, 2, 3), (5, 3, 2), (5, 4, 1),
}
ALLOWED_CHIPS = {"NONE", "WILDCARD", "FREE_HIT", "BENCH_BOOST", "TRIPLE_CAPTAIN"}
CHIP_ALIASES = {
    "": "NONE", "none": "NONE",
    "wildcard": "WILDCARD",
    "freehit": "FREE_HIT", "free_hit": "FREE_HIT",
    "bboost": "BENCH_BOOST", "bench_boost": "BENCH_BOOST",
    "3xc": "TRIPLE_CAPTAIN", "triple_captain": "TRIPLE_CAPTAIN",
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_chip(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = CHIP_ALIASES.get(raw, raw.upper() if raw else "NONE")
    if normalized not in ALLOWED_CHIPS:
        raise RuntimeError(f"unsupported chip in personal GW context: {normalized}")
    return normalized


def _gw_mean(projection: dict[str, Any], gw: int) -> float:
    for row in projection.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(gw):
            return _f(row.get("mean"))
    return 0.0


def _formation(rows: list[dict[str, Any]]) -> str:
    counts = Counter(str(row.get("position")) for row in rows)
    if counts.get("GK", 0) != 1:
        raise RuntimeError("effective XI must contain exactly one GK")
    shape = (counts.get("DEF", 0), counts.get("MID", 0), counts.get("FWD", 0))
    if shape not in LEGAL_FORMATIONS:
        raise RuntimeError(f"illegal effective formation: {shape}")
    return f"{shape[0]}-{shape[1]}-{shape[2]}"


def _manual_active(manual: dict[str, Any], planning_gw: int) -> bool:
    status = str(manual.get("status") or "INACTIVE").upper()
    if status in {"", "INACTIVE", "DISABLED", "NONE"}:
        return False
    return int(manual.get("gw") or 0) == int(planning_gw)


def _projection_rows(team: dict[str, Any], projections: dict[str, Any], planning_gw: int) -> dict[int, dict[str, Any]]:
    owned = {int(row.get("element") or -1): row for row in team.get("team_value_ledger") or []}
    pmap = {int(row.get("element") or -1): row for row in projections.get("players") or []}
    if len(owned) != 15:
        raise RuntimeError(f"personal GW context requires 15 owned players, got {len(owned)}")
    rows: dict[int, dict[str, Any]] = {}
    for element, owned_row in owned.items():
        proj = pmap.get(element) or {}
        rows[element] = {
            "element": element,
            "name": owned_row.get("name") or proj.get("name"),
            "position": owned_row.get("position") or proj.get("position"),
            "xpts": round(_gw_mean(proj, planning_gw), 3),
        }
    return rows


def _engine_effective_plan(lineup: dict[str, Any], rows: dict[int, dict[str, Any]], planning_gw: int) -> dict[str, Any]:
    xi_ids = [int(row.get("element") or -1) for row in lineup.get("starting_xi") or []]
    if len(xi_ids) != 11 or len(set(xi_ids)) != 11:
        raise RuntimeError("engine lineup must contain 11 unique starters")
    if any(element not in rows for element in xi_ids):
        raise RuntimeError("engine lineup contains player outside authoritative squad")
    captain = int((lineup.get("captain") or {}).get("element") or 0)
    vice = int((lineup.get("vice_captain") or {}).get("element") or 0)
    if captain not in xi_ids or vice not in xi_ids or captain == vice:
        raise RuntimeError("engine captain/vice contract invalid")
    bench_ids = [element for element in rows if element not in set(xi_ids)]
    bench_gk = next((element for element in bench_ids if rows[element].get("position") == "GK"), None)
    outfield = [element for element in bench_ids if element != bench_gk]
    engine_order = [int(row.get("element") or -1) for row in ((lineup.get("bench") or {}).get("order") or [])]
    ordered = [element for element in engine_order if element in outfield]
    ordered.extend(element for element in outfield if element not in ordered)
    return {
        "authority": "ENGINE_RECOMMENDATION",
        "gw": planning_gw,
        "starting_xi": xi_ids,
        "captain": captain,
        "vice_captain": vice,
        "bench_gk": bench_gk,
        "bench_order": ordered,
        "active_chip": _normalize_chip((lineup.get("chip_context") or {}).get("active_chip")),
    }


def _manual_effective_plan(manual: dict[str, Any], rows: dict[int, dict[str, Any]], planning_gw: int) -> dict[str, Any]:
    xi_ids = [int(x) for x in manual.get("starting_xi") or []]
    if len(xi_ids) != 11 or len(set(xi_ids)) != 11:
        raise RuntimeError("manual starting_xi must contain 11 unique element IDs")
    if any(element not in rows for element in xi_ids):
        raise RuntimeError("manual starting_xi contains player outside authoritative squad")
    captain = int(manual.get("captain") or 0)
    vice = int(manual.get("vice_captain") or 0)
    if captain not in xi_ids or vice not in xi_ids or captain == vice:
        raise RuntimeError("manual captain and vice must be distinct starters")
    bench_gk = int(manual.get("bench_gk") or 0)
    bench_order = [int(x) for x in manual.get("bench_order") or []]
    remaining = set(rows) - set(xi_ids)
    if bench_gk not in remaining or rows[bench_gk].get("position") != "GK":
        raise RuntimeError("manual bench_gk invalid")
    if len(bench_order) != 3 or set(bench_order) != remaining - {bench_gk}:
        raise RuntimeError("manual bench_order must contain all three remaining outfield players")
    return {
        "authority": "USER_OVERRIDE",
        "gw": planning_gw,
        "source": manual.get("source") or "manual_config",
        "starting_xi": xi_ids,
        "captain": captain,
        "vice_captain": vice,
        "bench_gk": bench_gk,
        "bench_order": bench_order,
        "active_chip": _normalize_chip(manual.get("active_chip")),
        "note": manual.get("note"),
    }


def _project_plan(plan: dict[str, Any], rows: dict[int, dict[str, Any]]) -> dict[str, Any]:
    starters = [rows[element] for element in plan["starting_xi"]]
    formation = _formation(starters)
    captain = rows[int(plan["captain"])]
    vice = rows[int(plan["vice_captain"])]
    bench_ids = [int(plan["bench_gk"])] + [int(x) for x in plan["bench_order"]]
    bench = [rows[element] for element in bench_ids]
    chip = _normalize_chip(plan.get("active_chip"))
    xi_xpts = sum(_f(row.get("xpts")) for row in starters)
    captain_extra = _f(captain.get("xpts")) * (2 if chip == "TRIPLE_CAPTAIN" else 1)
    bench_xpts = sum(_f(row.get("xpts")) for row in bench)
    counted_bench = bench_xpts if chip == "BENCH_BOOST" else 0.0
    return {
        "status": "PROJECTION",
        "gw": int(plan["gw"]),
        "decision_authority": plan.get("authority"),
        "source": plan.get("source"),
        "formation": formation,
        "active_chip": chip,
        "starting_xi": starters,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice,
        "xi_xpts": round(xi_xpts, 2),
        "bench_xpts": round(bench_xpts, 2),
        "estimated_points": round(xi_xpts + captain_extra + counted_bench, 2),
        "scoring_guardrails": {
            "captain_multiplier_applied_once": True,
            "triple_captain_extra_is_two_captain_xpts": True,
            "bench_counted_only_for_bench_boost": True,
            "wildcard_and_free_hit_add_no_scoring_points": True,
            "estimate_not_actual": True,
        },
    }


def build_planning_context(team: dict[str, Any], projections: dict[str, Any], lineup: dict[str, Any], manual: dict[str, Any] | None = None) -> dict[str, Any]:
    planning_gw = int(projections.get("planning_gw") or lineup.get("planning_gw") or 0)
    if planning_gw <= 0:
        return {"status": "UNAVAILABLE", "reason": "planning_gw_missing"}
    rows = _projection_rows(team, projections, planning_gw)
    engine = _engine_effective_plan(lineup, rows, planning_gw)
    manual = manual if manual is not None else read_json(CONFIG / "manual_lineup_override.json", {})
    effective = _manual_effective_plan(manual, rows, planning_gw) if _manual_active(manual, planning_gw) else engine
    projected = _project_plan(effective, rows)
    engine_projected = _project_plan(engine, rows)
    projected["baseline"] = dict(team.get("projection_baseline") or {})
    projected["user_override_active"] = effective.get("authority") == "USER_OVERRIDE"
    projected["engine_recommendation"] = {
        "formation": engine_projected.get("formation"),
        "captain": (engine_projected.get("captain") or {}).get("name"),
        "vice_captain": (engine_projected.get("vice_captain") or {}).get("name"),
        "active_chip": engine_projected.get("active_chip"),
        "estimated_points": engine_projected.get("estimated_points"),
    }
    projected["comparison"] = {
        "user_minus_engine_estimated_points": round(_f(projected.get("estimated_points")) - _f(engine_projected.get("estimated_points")), 2),
        "formation_changed": projected.get("formation") != engine_projected.get("formation"),
        "captain_changed": (projected.get("captain") or {}).get("element") != (engine_projected.get("captain") or {}).get("element"),
        "vice_changed": (projected.get("vice_captain") or {}).get("element") != (engine_projected.get("vice_captain") or {}).get("element"),
        "chip_changed": projected.get("active_chip") != engine_projected.get("active_chip"),
        "engine_can_warn_but_not_overwrite_user": True,
    }
    return projected


def _historical_players(submitted: dict[str, Any], bootstrap: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {int(row.get("id") or -1): row for row in bootstrap.get("elements") or []}
    teams = {int(row.get("id") or -1): row.get("name") for row in bootstrap.get("teams") or []}
    rows = []
    for pick in submitted.get("picks") or []:
        element = int(pick.get("element") or -1)
        player = by_id.get(element) or {}
        rows.append({
            "element": element,
            "name": player.get("web_name"),
            "team": teams.get(int(player.get("team") or -1)),
            "position": POSITION_BY_TYPE.get(int(player.get("element_type") or 0)),
            "pick_position": pick.get("position"),
            "multiplier": pick.get("multiplier"),
            "captain": bool(pick.get("is_captain")),
            "vice_captain": bool(pick.get("is_vice_captain")),
        })
    return rows


def build_history_context(official_detail: dict[str, Any], official_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    historical = official_detail.get("historical_entry") or {}
    bootstrap = official_snapshot.get("bootstrap") or {}
    output = []
    for key, record in sorted((historical.get("gameweeks") or {}).items(), key=lambda item: int(item[0])):
        if record.get("status") != "PUBLIC_OFFICIAL_SUBMITTED_TEAM":
            continue
        gw = int(record.get("gw") or key)
        submitted = record.get("submitted") or {}
        history = record.get("history") or submitted.get("entry_history") or {}
        players = _historical_players(submitted, bootstrap)
        xi = [row for row in players if int(row.get("pick_position") or 99) <= 11]
        try:
            formation = _formation(xi)
        except RuntimeError:
            formation = None
        captain = next((row for row in players if row.get("captain")), None)
        vice = next((row for row in players if row.get("vice_captain")), None)
        output.append({
            "gw": gw,
            "status": "FINAL",
            "authority": "PUBLIC_OFFICIAL_POST_DEADLINE",
            "actual_points": history.get("points", (submitted.get("entry_history") or {}).get("points")),
            "transfer_cost": history.get("event_transfers_cost", (submitted.get("entry_history") or {}).get("event_transfers_cost")),
            "points_on_bench": history.get("points_on_bench", (submitted.get("entry_history") or {}).get("points_on_bench")),
            "overall_rank": history.get("overall_rank", (submitted.get("entry_history") or {}).get("overall_rank")),
            "event_rank": history.get("rank", (submitted.get("entry_history") or {}).get("rank")),
            "chip": _normalize_chip(submitted.get("active_chip")),
            "formation": formation,
            "captain": captain,
            "vice_captain": vice,
            "submitted_squad": players,
            "forecast_capture": "NOT_RECONSTRUCTED",
        })
    return output


def build_personal_gameweek_context(
    team: dict[str, Any],
    projections: dict[str, Any],
    lineup: dict[str, Any],
    official_detail: dict[str, Any],
    official_snapshot: dict[str, Any],
    manual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "personal_gameweek_context.v1",
        "historical": build_history_context(official_detail, official_snapshot),
        "planning": build_planning_context(team, projections, lineup, manual=manual),
        "governance": {
            "past_gameweeks_are_actual_official_truth": True,
            "planning_gameweek_is_estimated_not_actual": True,
            "previous_submitted_squad_is_default_planning_baseline": True,
            "targeted_wc_fh_or_user_lock_may_override_planning_squad": True,
            "user_lineup_captain_chip_override_is_allowed": True,
            "engine_recommendation_remains_visible_for_comparison": True,
            "historical_truth_never_reconstructed_as_old_forecast": True,
        },
    }
