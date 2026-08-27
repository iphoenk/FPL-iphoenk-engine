from __future__ import annotations

import json
import traceback
from multiprocessing import get_context
from time import perf_counter

from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import build_candidates
from src.engines.v4_wc_optimizer_fast import decision_report_from_candidates_fast
from src.engines.v4_wc_package_audit_fast import audit_packages_from_candidates_fast
from src.engines.v4_lineup_optimizer import optimize_lineup, MANUAL_FILE
from src.engines.v4_recommendation_sanity import sanity_report

OUTFILE = DATA / "decision_pipeline_v4.json"
_SHARED = None


def effective_planning_squad(team: dict, configured_lock: dict, latest: dict) -> dict:
    """Build optimizer-owned squad from the authoritative team contract.

    `team.json` already reflects the raw-snapshot authority decision: normally the
    previous submitted GW squad, or a target-GW planning override. The static lock
    file may contribute metadata only; it must never reintroduce stale players.
    """
    squad = list(team.get("squad") or [])
    ledger = {int(row.get("element") or 0): row for row in team.get("team_value_ledger") or []}
    if len(squad) != 15:
        raise RuntimeError(f"effective team contract must contain 15 players, got {len(squad)}")
    players: list[dict] = []
    for row in squad:
        element = int(row.get("element") or 0)
        value = ledger.get(element) or {}
        purchase_cost = value.get("purchase_cost", row.get("purchase_cost"))
        sell_cost = value.get("sell_cost")
        if sell_cost is None and purchase_cost is None:
            raise RuntimeError(f"effective owned player {element} lacks price evidence")
        players.append({
            "element": element,
            "name": row.get("name") or value.get("name"),
            "position": row.get("position") or value.get("position"),
            "purchase_cost": purchase_cost,
            "sell_cost": sell_cost,
        })

    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 0) or None
    target_raw = configured_lock.get("target_gw")
    target_gw = int(target_raw) if target_raw is not None else None
    authority = str(team.get("squad_authority") or "")
    targeted_override = authority == "LOCKED_PRE_DEADLINE" and target_gw == planning_gw
    wildcard_for_planning = bool(configured_lock.get("wildcard_active")) and targeted_override
    return {
        "players": players,
        "itb_tenths": int((team.get("totals") or {}).get("itb") or 0),
        "wildcard_active": wildcard_for_planning,
        "planning_override_active": targeted_override,
        "target_gw": target_gw if targeted_override else None,
        "authority_source": configured_lock.get("authority_source") if targeted_override else "OFFICIAL_FPL_PICKS",
        "squad_authority": authority,
        "baseline_gw": ((latest.get("phase") or {}).get("submitted_gw")),
        "planning_gw": planning_gw,
    }


def _decision_worker(kind, conn):
    """Linux fork worker: read shared in-memory inputs via copy-on-write, write compact result."""
    t = perf_counter()
    try:
        shared = _SHARED
        if not shared:
            raise RuntimeError("decision worker started without shared inputs")
        if kind == "wc":
            out = decision_report_from_candidates_fast(shared["candidates"], shared["locked"])
            out["engine"] = "v4.9.2-wc-optimizer-truthful-health-exact-streaming"
            atomic_json(DATA / "wc_decision_v4.json", out)
        elif kind == "packages":
            out = audit_packages_from_candidates_fast(shared["candidates"], shared["locked"])
            atomic_json(DATA / "wc_package_audit_v4.json", out)
        else:
            raise RuntimeError(f"unknown decision worker: {kind}")
        conn.send({"ok": True, "ms": round((perf_counter() - t) * 1000.0, 1)})
    except Exception:
        conn.send({"ok": False, "ms": round((perf_counter() - t) * 1000.0, 1), "error": traceback.format_exc()})
    finally:
        conn.close()


def _run_parallel_wc_package(candidates, locked):
    global _SHARED
    _SHARED = {"candidates": candidates, "locked": locked}
    ctx = get_context("fork")
    recv_wc, send_wc = ctx.Pipe(duplex=False)
    recv_pkg, send_pkg = ctx.Pipe(duplex=False)
    p_wc = ctx.Process(target=_decision_worker, args=("wc", send_wc), name="v493-wc-fast")
    p_pkg = ctx.Process(target=_decision_worker, args=("packages", send_pkg), name="v493-packages-fast")
    wall = perf_counter()
    p_wc.start()
    p_pkg.start()
    send_wc.close()
    send_pkg.close()
    wc_status = recv_wc.recv()
    pkg_status = recv_pkg.recv()
    p_wc.join()
    p_pkg.join()
    wall_ms = round((perf_counter() - wall) * 1000.0, 1)
    _SHARED = None
    if not wc_status.get("ok") or p_wc.exitcode != 0:
        raise RuntimeError("parallel WC worker failed:\n" + str(wc_status.get("error") or p_wc.exitcode))
    if not pkg_status.get("ok") or p_pkg.exitcode != 0:
        raise RuntimeError("parallel package worker failed:\n" + str(pkg_status.get("error") or p_pkg.exitcode))
    return wc_status, pkg_status, wall_ms


def run():
    t0 = perf_counter()
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    team = read_json(DATA / "team.json", {})
    manual = read_json(MANUAL_FILE, {})
    latest = read_json(DATA / "latest.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    candidates = build_candidates(predictions, universe)
    timings = {"load_shared_inputs_and_candidates_ms": round((perf_counter() - t0) * 1000.0, 1)}

    wc_status, pkg_status, parallel_wall = _run_parallel_wc_package(candidates, locked)
    timings["wc_decision_cpu_ms"] = wc_status["ms"]
    timings["package_audit_cpu_ms"] = pkg_status["ms"]
    timings["wc_package_parallel_wall_ms"] = parallel_wall
    timings["parallel_speedup_estimate"] = round((wc_status["ms"] + pkg_status["ms"]) / max(1.0, parallel_wall), 3)
    wc = read_json(DATA / "wc_decision_v4.json", {})
    packages = read_json(DATA / "wc_package_audit_v4.json", {})

    t = perf_counter()
    lineup = optimize_lineup(predictions, universe, locked, manual=manual)
    atomic_json(DATA / "lineup_decision_v4.json", lineup)
    timings["lineup_ms"] = round((perf_counter() - t) * 1000.0, 1)

    t = perf_counter()
    sanity = sanity_report(predictions, universe, packages, latest)
    atomic_json(DATA / "recommendation_sanity_v4.json", sanity)
    timings["evidence_sanity_ms"] = round((perf_counter() - t) * 1000.0, 1)
    timings["total_pipeline_ms"] = round((perf_counter() - t0) * 1000.0, 1)

    out = {
        "schema_version": 473,
        "engine": "v4.7.3-unified-decision-pipeline-checkpoint-aware",
        "checkpoint_context": latest.get("checkpoint_context") or {},
        "planning_squad": {
            "authority": locked.get("squad_authority"),
            "baseline_gw": locked.get("baseline_gw"),
            "planning_gw": locked.get("planning_gw"),
            "override_active": locked.get("planning_override_active"),
            "target_gw": locked.get("target_gw"),
            "authority_source": locked.get("authority_source"),
            "wildcard_active": locked.get("wildcard_active"),
        },
        "timings": timings,
        "results": {
            "wc_raw": wc.get("classification"),
            "package_raw": packages.get("overall_verdict"),
            "recommendation_final": sanity.get("final_verdict"),
            "recommended_replacements": (sanity.get("recommended_package") or {}).get("replacements"),
            "lineup_governance": (lineup.get("governance") or {}).get("decision"),
            "formation": lineup.get("formation"),
            "captain": (lineup.get("captain") or {}).get("name"),
        },
        "performance_guardrails": {
            "shared_json_loaded_once": True,
            "shared_candidates_built_once": True,
            "fork_copy_on_write": True,
            "parallel_wc_package": True,
            "fast_wc_finalist_scoring": True,
            "redundant_package_validation_removed": True,
            "concise_stdout": True,
            "search_quality_reduction": False,
            "wc_beam_unchanged": True,
            "package_frontier_beam_unchanged": True,
            "bounded_top_k_same_wc_beam": True,
            "exact_streaming_wc_topk": bool((wc.get("performance") or {}).get("exact_streaming_topk")),
            "stable_wc_tie_semantics": bool((wc.get("performance") or {}).get("stable_tie_semantics")),
            "safe_wc_objective_bound": bool((wc.get("performance") or {}).get("safe_objective_bound")),
            "fixed_position_finalist_scoring": bool((wc.get("performance") or {}).get("fixed_position_finalist_scoring")),
            "compact_package_keep_profile": bool((packages.get("performance") or {}).get("compact_keep_profile")),
            "package_scalar_delta_metrics": bool((packages.get("performance") or {}).get("scalar_delta_metrics")),
            "package_position_value_reuse": bool((packages.get("performance") or {}).get("position_value_reuse")),
            "top_packages_only_payload_materialization": True,
            "checkpoint_action_deferred_until_postflight_health": True,
            "planning_squad_from_team_contract": True,
            "stale_lock_players_not_direct_optimizer_input": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
