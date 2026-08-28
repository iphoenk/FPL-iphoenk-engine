from __future__ import annotations

import json
from time import perf_counter

from src.engines.fpl_legality import formation_from_rows
from src.engines.fpl_rules_2026 import CHIPS
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA, atomic_json, iso_now, read_json

ENGINE_LINEUP = DATA / "lineup_decision_v4.json"
TEAM = DATA / "team.json"
LATEST = DATA / "latest.json"
MANUAL = CONFIG / "manual_lineup.json"
LOCKED = CONFIG / "locked_squad.json"
OUTFILE = DATA / "effective_plan_v4.json"
ALLOWED_CHIPS = {"NONE"} | {str(chip).upper() for chip in CHIPS}


def _all_engine_rows(lineup: dict) -> dict[int, dict]:
    rows = list(lineup.get("starting_xi") or [])
    bench = lineup.get("bench") or {}
    if bench.get("gk"):
        rows.append(bench["gk"])
    rows.extend(bench.get("order") or [])
    out = {int(row.get("element") or 0): dict(row) for row in rows if row.get("element")}
    if len(out) != 15:
        raise RuntimeError(f"engine lineup must expose all 15 owned players, got {len(out)}")
    return out


def _formation(rows: list[dict]) -> str:
    if sum(row.get("position") == "GK" for row in rows) != 1:
        raise RuntimeError("manual XI must contain exactly one GK")
    formation = formation_from_rows(rows)
    if formation is None:
        raise RuntimeError("manual XI illegal formation")
    return formation


def _manual_is_active(manual: dict, planning_gw: int | None) -> bool:
    if not manual or not planning_gw:
        return False
    status = str(manual.get("status") or "").upper()
    if status in {"", "INACTIVE", "DISABLED", "NONE"}:
        return False
    target = int(manual.get("gw") or 0)
    if target != int(planning_gw):
        return False
    expiry = manual.get("expires_after_gw")
    if expiry is not None and int(planning_gw) > int(expiry):
        return False
    return True


def _engine_plan(lineup: dict, planning_gw: int | None) -> dict:
    return {
        "authority": "ENGINE_RECOMMENDATION",
        "status": "ADVISORY",
        "gw": planning_gw,
        "formation": lineup.get("formation"),
        "xi_xpts": lineup.get("xi_xpts"),
        "starting_xi": list(lineup.get("starting_xi") or []),
        "captain": dict(lineup.get("captain") or {}),
        "vice_captain": dict(lineup.get("vice_captain") or {}),
        "bench": dict(lineup.get("bench") or {}),
        "chip_context": dict(lineup.get("chip_context") or {}),
    }


def _manual_plan(lineup: dict, manual: dict, planning_gw: int, configured_lock: dict) -> tuple[dict, dict]:
    rows_by_id = _all_engine_rows(lineup)
    starting_ids = [int(x) for x in manual.get("starting_xi") or []]
    if len(starting_ids) != 11 or len(set(starting_ids)) != 11:
        raise RuntimeError("manual starting_xi must contain 11 unique elements")
    if any(element not in rows_by_id for element in starting_ids):
        raise RuntimeError("manual starting_xi contains player outside effective 15")
    starting = [rows_by_id[element] for element in starting_ids]
    formation = _formation(starting)

    captain_id = int(manual.get("captain") or 0)
    vice_id = int(manual.get("vice_captain") or 0)
    if captain_id == vice_id or captain_id not in starting_ids or vice_id not in starting_ids:
        raise RuntimeError("manual captain and vice must be distinct and inside starting XI")

    bench_gk = int(manual.get("bench_gk") or 0)
    bench_order = [int(x) for x in manual.get("bench_order") or []]
    bench_ids = [element for element in rows_by_id if element not in set(starting_ids)]
    if bench_gk not in bench_ids or rows_by_id[bench_gk].get("position") != "GK":
        raise RuntimeError("manual bench_gk invalid")
    if len(bench_order) != 3 or set(bench_order) != set(bench_ids) - {bench_gk}:
        raise RuntimeError("manual bench_order must contain the three remaining outfield players")

    chip = str(manual.get("active_chip") or "NONE").upper().replace(" ", "_")
    if chip not in ALLOWED_CHIPS:
        raise RuntimeError(f"unsupported manual chip: {chip}")
    target_lock = int(configured_lock.get("target_gw") or 0)
    wildcard_composition = bool(configured_lock.get("wildcard_active")) and target_lock == int(planning_gw)
    if wildcard_composition and chip != "WILDCARD":
        raise RuntimeError("target-GW wildcard composition requires WILDCARD chip in effective plan")

    xi_xpts = round(sum(float(row.get("xpts") or 0.0) for row in starting), 2)
    engine_ids = {int(row.get("element")) for row in lineup.get("starting_xi") or []}
    manual_ids = set(starting_ids)
    changed_slots = len(engine_ids ^ manual_ids) // 2
    engine_xpts = float(lineup.get("xi_xpts") or 0.0)
    delta = round(xi_xpts - engine_xpts, 3)

    effective = {
        "authority": "USER_OVERRIDE",
        "status": str(manual.get("status") or "MANUAL_DRAFT_ADJUSTABLE"),
        "gw": int(planning_gw),
        "source": manual.get("source") or "manual_config",
        "decision_authority": "USER",
        "overwrite_policy": "ENGINE_RECOMMENDS_USER_DECIDES",
        "formation": formation,
        "xi_xpts": xi_xpts,
        "starting_xi": starting,
        "captain": dict(rows_by_id[captain_id]),
        "vice_captain": dict(rows_by_id[vice_id]),
        "bench": {
            "gk": dict(rows_by_id[bench_gk]),
            "order": [{"slot": i + 1, **dict(rows_by_id[element])} for i, element in enumerate(bench_order)],
        },
        "chip_context": {
            "active_chip": chip,
            "source": "USER_OVERRIDE",
            "single_chip_rule_respected": True,
        },
    }
    comparison = {
        "changed_xi_slots_vs_engine": changed_slots,
        "user_xi_xpts": xi_xpts,
        "engine_xi_xpts": round(engine_xpts, 2),
        "user_minus_engine_xpts": delta,
        "formation_changed": formation != lineup.get("formation"),
        "captain_changed": captain_id != int((lineup.get("captain") or {}).get("element") or 0),
        "vice_changed": vice_id != int((lineup.get("vice_captain") or {}).get("element") or 0),
        "chip_changed": chip != str((lineup.get("chip_context") or {}).get("active_chip") or "NONE").upper(),
        "engine_can_warn_but_not_overwrite": True,
    }
    return effective, comparison


def build_effective_plan(lineup: dict, team: dict, latest: dict, manual: dict, configured_lock: dict) -> dict:
    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 0) or None
    if len(team.get("squad") or []) != 15:
        raise RuntimeError("effective team contract must contain 15 players")
    engine = _engine_plan(lineup, planning_gw)
    if _manual_is_active(manual, planning_gw):
        effective, comparison = _manual_plan(lineup, manual, int(planning_gw), configured_lock)
        override = {
            "active": True,
            "target_gw": int(planning_gw),
            "source": manual.get("source"),
            "status": manual.get("status"),
            "decision_authority": "USER",
        }
    else:
        effective = dict(engine)
        effective["decision_authority"] = "USER_NOT_OVERRIDDEN"
        comparison = {
            "changed_xi_slots_vs_engine": 0,
            "user_minus_engine_xpts": 0.0,
            "engine_can_warn_but_not_overwrite": True,
        }
        override = {
            "active": False,
            "target_gw": manual.get("gw") if manual else None,
            "reason": "no_matching_target_gw_manual_override",
        }

    return {
        "schema_version": 4941,
        "engine": "v4.9.4.1-user-decision-overlay",
        "generated_at": iso_now(),
        "status": "PASS",
        "planning_gw": planning_gw,
        "team_authority": team.get("squad_authority"),
        "engine_recommendation": engine,
        "user_override": override,
        "effective_plan": effective,
        "comparison": comparison,
        "guardrails": {
            "process_isolated_microservice": True,
            "official_api_refetch": False,
            "engine_is_advisory": True,
            "user_decision_is_final_authority": True,
            "engine_never_auto_overwrites_valid_user_override": True,
            "target_gw_override_required": True,
            "stale_override_ignored": True,
            "fpl_legality_still_enforced": True,
            "composition_from_effective_team_contract": True,
        },
    }


def run() -> dict:
    started = perf_counter()
    lineup = read_json(ENGINE_LINEUP, {})
    team = read_json(TEAM, {})
    latest = read_json(LATEST, {})
    manual = read_json(MANUAL, {})
    configured_lock = read_json(LOCKED, {})
    if not lineup or not team or not latest:
        raise RuntimeError("engine lineup, team contract and latest snapshot required")
    out = build_effective_plan(lineup, team, latest, manual, configured_lock)
    out["lineage"] = {
        "engine_lineup_sha256": file_digest(ENGINE_LINEUP),
        "team_sha256": file_digest(TEAM),
        "latest_sha256": file_digest(LATEST),
    }
    out["performance_ms"] = round((perf_counter() - started) * 1000.0, 2)
    atomic_json(OUTFILE, out)
    effective = out.get("effective_plan") or {}
    print(json.dumps({
        "service": "user_decision_overlay",
        "status": out["status"],
        "planning_gw": out["planning_gw"],
        "authority": effective.get("authority"),
        "formation": effective.get("formation"),
        "captain": (effective.get("captain") or {}).get("name"),
        "chip": (effective.get("chip_context") or {}).get("active_chip"),
        "user_minus_engine_xpts": (out.get("comparison") or {}).get("user_minus_engine_xpts"),
        "duration_ms": out["performance_ms"],
    }, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
