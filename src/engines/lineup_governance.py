from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.models.package_optimizer_v2 import legal_squad
from src.rules import LINEUP_RULES, RULESET_ID, SQUAD_RULES
from src.utils import CONFIG, DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "lineup_governance.json"
LINEUP_OUT = DATA / "lineup_decision.json"
PACKAGE_DECISION_OUT = DATA / "package_decision.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _gw_projection(proj: dict[str, Any], gw: int) -> dict[str, Any]:
    for row in proj.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(gw):
            return row
    return {"gw": gw, "mean": 0.0, "std": 0.0, "fixtures": []}


def _player_row(proj: dict[str, Any], gw: int, policy: dict[str, Any]) -> dict[str, Any]:
    gw_row = _gw_projection(proj, gw)
    xmins = proj.get("xmins") or {}
    mean = _f(gw_row.get("mean"))
    std = _f(gw_row.get("std"))
    dnp = _f(xmins.get("dnp_probability"))
    selection = policy.get("selection") or {}
    captaincy = policy.get("captaincy") or {}
    bench = policy.get("bench") or {}
    selection_score = mean - _f(selection.get("risk_aversion_std")) * std - _f(selection.get("dnp_penalty_points")) * dnp
    captain_score = mean - _f(captaincy.get("risk_aversion_std")) * std - _f(captaincy.get("dnp_penalty_points")) * dnp
    bench_score = mean - _f(bench.get("risk_aversion_std")) * std - _f(bench.get("dnp_penalty_points")) * dnp
    return {
        "element": int(proj["element"]),
        "name": proj.get("name"),
        "position": proj.get("position"),
        "team_id": int(proj.get("team_id") or -1),
        "now_cost": int(proj.get("now_cost") or 0),
        "xpts_mean": round(mean, 3),
        "xpts_std": round(std, 3),
        "selection_score": round(selection_score, 4),
        "captain_score": round(captain_score, 4),
        "bench_score": round(bench_score, 4),
        "start_probability": round(_f(xmins.get("start_probability")), 4),
        "bench_probability": round(_f(xmins.get("bench_probability")), 4),
        "dnp_probability": round(dnp, 4),
        "expected_minutes": round(_f(xmins.get("expected_minutes")), 2),
        "projection_confidence": proj.get("projection_confidence"),
    }


def _formation(rows: list[dict[str, Any]]) -> str | None:
    counts = {pos: sum(1 for p in rows if p.get("position") == pos) for pos in ("DEF", "MID", "FWD")}
    form = f"{counts['DEF']}-{counts['MID']}-{counts['FWD']}"
    return form if form in set(LINEUP_RULES.get("legal_formations") or []) else None


def _lineup_candidates(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required_size = int(LINEUP_RULES.get("starting_xi_size") or 11)
    required_gk = int(LINEUP_RULES.get("starting_goalkeepers") or 1)
    candidates = []
    for combo in itertools.combinations(players, required_size):
        rows = list(combo)
        if sum(1 for p in rows if p.get("position") == "GK") != required_gk:
            continue
        form = _formation(rows)
        if not form:
            continue
        score = sum(_f(p.get("selection_score")) for p in rows)
        mean = sum(_f(p.get("xpts_mean")) for p in rows)
        variance = sum(_f(p.get("xpts_std")) ** 2 for p in rows)
        candidates.append({
            "formation": form,
            "score": round(score, 4),
            "xpts_mean": round(mean, 3),
            "xpts_std": round(variance ** 0.5, 3),
            "element_ids": sorted(int(p["element"]) for p in rows),
        })
    candidates.sort(key=lambda row: (row["score"], row["xpts_mean"], row["formation"]), reverse=True)
    return candidates


def _safe_captain_pool(starters: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = policy.get("captaincy") or {}
    min_start = _f(cfg.get("minimum_start_probability"), 0.70)
    max_dnp = _f(cfg.get("maximum_dnp_probability"), 0.15)
    pool = [
        p for p in starters
        if _f(p.get("start_probability")) >= min_start and _f(p.get("dnp_probability")) <= max_dnp
    ]
    if len(pool) < 2:
        pool = list(starters)
    pool.sort(key=lambda p: (_f(p.get("captain_score")), _f(p.get("xpts_mean"))), reverse=True)
    return pool[: max(2, int(cfg.get("safe_pool_size") or 5))]


def _battle(best: dict[str, Any], second: dict[str, Any] | None, pmap: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if not second:
        return {"status": "NO_ALTERNATIVE", "margin": None, "starter_side": [], "bench_side": []}
    best_ids = set(best.get("element_ids") or [])
    second_ids = set(second.get("element_ids") or [])
    starter_side = [pmap[e] for e in sorted(best_ids - second_ids) if e in pmap]
    bench_side = [pmap[e] for e in sorted(second_ids - best_ids) if e in pmap]
    margin = round(_f(best.get("score")) - _f(second.get("score")), 4)
    return {
        "status": "CLOSE" if margin < 0.75 else "CLEAR",
        "margin": margin,
        "starter_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in starter_side],
        "bench_side": [{"element": p["element"], "name": p["name"], "position": p["position"], "selection_score": p["selection_score"]} for p in bench_side],
        "alternative_formation": second.get("formation"),
    }


def _chip_context(lock: dict[str, Any], chips: dict[str, Any], planning_gw: int, policy: dict[str, Any]) -> dict[str, Any]:
    chip_cfg = policy.get("chip_governance") or {}
    active = None
    if chip_cfg.get("wildcard_context_from_locked_authority") and lock.get("wildcard_active") and lock.get("authoritative_phase") == "pre_deadline_wc":
        active = "wildcard"
    used_this_gw = []
    for row in chips.get("used") or []:
        if int(row.get("event") or -1) == planning_gw:
            used_this_gw.append(row.get("name"))
    active_count = len(used_this_gw) + (1 if active and active not in used_this_gw else 0)
    return {
        "planning_gw": planning_gw,
        "active_chip": active,
        "used_this_gw": used_this_gw,
        "single_chip_rule_respected": active_count <= 1,
        "auto_activate_chip": bool(chip_cfg.get("auto_activate_chip", False)),
        "ruleset_id": RULESET_ID,
    }


def build_lineup_decision(projections: dict[str, Any], lock: dict[str, Any], chips: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy()
    planning_gw = int(projections.get("planning_gw") or 1)
    proj_map = {int(p["element"]): p for p in projections.get("players") or []}
    locked_ids = [int(p.get("element") or -1) for p in lock.get("players") or []]
    missing = [e for e in locked_ids if e not in proj_map]
    if len(locked_ids) != int(SQUAD_RULES.get("squad_size") or 15) or missing:
        raise RuntimeError(f"cannot govern lineup: locked={len(locked_ids)} missing_projection_ids={missing}")

    players = [_player_row(proj_map[e], planning_gw, policy) for e in locked_ids]
    pmap = {int(p["element"]): p for p in players}
    candidates = _lineup_candidates(players)
    if not candidates:
        raise RuntimeError("no legal starting XI candidate")
    best = candidates[0]
    best_ids = set(best["element_ids"])
    starters = [pmap[e] for e in best["element_ids"]]
    starters.sort(key=lambda p: ({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}.get(str(p.get("position")), 9), -_f(p.get("selection_score"))))

    safe_pool = _safe_captain_pool(starters, policy)
    captain = safe_pool[0]
    vice = next(p for p in safe_pool[1:] if int(p["element"]) != int(captain["element"]))

    bench_players = [p for p in players if int(p["element"]) not in best_ids]
    bench_gk = next((p for p in bench_players if p.get("position") == "GK"), None)
    outfield_bench = [p for p in bench_players if p.get("position") != "GK"]
    outfield_bench.sort(key=lambda p: (_f(p.get("bench_score")), _f(p.get("xpts_mean"))), reverse=True)
    if not bench_gk or len(outfield_bench) != int((LINEUP_RULES.get("bench") or {}).get("outfield") or 3):
        raise RuntimeError("invalid governed bench structure")

    alt_n = max(2, int((policy.get("selection") or {}).get("publish_alternative_lineups") or 3))
    alternatives = candidates[:alt_n]
    decision = {
        "generated_at": _now(),
        "model": policy.get("model_id"),
        "ruleset_id": RULESET_ID,
        "planning_gw": planning_gw,
        "squad_authority": lock.get("authoritative_phase"),
        "formation": best["formation"],
        "starting_xi": starters,
        "captain": {"element": captain["element"], "name": captain["name"], "captain_score": captain["captain_score"], "dnp_probability": captain["dnp_probability"]},
        "vice_captain": {"element": vice["element"], "name": vice["name"], "captain_score": vice["captain_score"], "dnp_probability": vice["dnp_probability"]},
        "captain_safe_pool": [{"element": p["element"], "name": p["name"], "captain_score": p["captain_score"], "start_probability": p["start_probability"], "dnp_probability": p["dnp_probability"]} for p in safe_pool],
        "bench": {
            "gk": {"element": bench_gk["element"], "name": bench_gk["name"], "position": bench_gk["position"], "bench_score": bench_gk["bench_score"]},
            "order": [{"element": p["element"], "name": p["name"], "position": p["position"], "bench_score": p["bench_score"]} for p in outfield_bench],
        },
        "lineup_score": {"robust": best["score"], "xpts_mean": best["xpts_mean"], "xpts_std": best["xpts_std"]},
        "main_starting_xi_battle": _battle(best, candidates[1] if len(candidates) > 1 else None, pmap),
        "alternatives": alternatives,
        "chip_context": _chip_context(lock, chips, planning_gw, policy),
        "governance": {
            "all_legal_xi_enumerated": True,
            "manual_squad_authority_preserved": True,
            "optimizer_does_not_mutate_locked_composition": True,
            "captain_dnp_guard_applied": True,
            "bench_order_is_model_output_not_manual_lock": True,
        },
    }
    return decision


def build_package_decision(package_optimizer: dict[str, Any], projections: dict[str, Any], lock: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    policy = load_policy()
    package_cfg = policy.get("package_governance") or {}
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    ledger_by_id = {int(p.get("element") or -1): p for p in team.get("team_value_ledger") or []}
    current = []
    for locked in lock.get("players") or []:
        element = int(locked.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        ledger = ledger_by_id.get(element) or {}
        current.append({
            "element": element,
            "name": proj.get("name"),
            "position": proj.get("position"),
            "team_id": int(proj.get("team_id") or -1),
            "now_cost": int(proj.get("now_cost") or 0),
            "sell_cost": int(ledger.get("sell_cost") or proj.get("now_cost") or 0),
        })
    current_legal = legal_squad(current)
    authoritative = lock.get("authoritative_phase") in set(package_cfg.get("authoritative_phases") or [])
    freeze = bool(package_cfg.get("freeze_locked_composition_when_authoritative")) and authoritative
    optimizer_packages = list(package_optimizer.get("packages") or [])
    optimizer_best = optimizer_packages[0] if optimizer_packages else package_optimizer.get("hold")
    selected = package_optimizer.get("hold") if freeze or not package_cfg.get("auto_accept_optimizer_package") else optimizer_best
    if not selected:
        raise RuntimeError("package optimizer did not provide a selectable package")
    selected_is_hold = selected.get("id") == "HOLD"
    selected_legal = bool(selected.get("legal")) and bool((selected.get("score") or {}).get("valid"))
    gate0_revalidated = current_legal and selected_legal and (selected_is_hold if freeze else True)
    return {
        "generated_at": _now(),
        "model": "package_governance_v1",
        "ruleset_id": RULESET_ID,
        "planning_gw": int(projections.get("planning_gw") or 1),
        "selected_package": selected,
        "selected_package_id": selected.get("id"),
        "optimizer_best_candidate_id": (optimizer_best or {}).get("id"),
        "manual_authority_override": freeze,
        "current_squad_legal": current_legal,
        "gate0_revalidated": gate0_revalidated,
        "governance": {
            "optimizer_is_candidate_generator_only": bool(package_cfg.get("optimizer_is_candidate_generator_only", True)),
            "locked_composition_frozen": freeze,
            "auto_accept_optimizer_package": bool(package_cfg.get("auto_accept_optimizer_package", False)),
            "manual_lock_overrides_optimizer_candidate": bool((policy.get("governance") or {}).get("manual_lock_overrides_optimizer_candidate", True)),
        },
    }


def run() -> dict[str, Any]:
    projections = read_json(DATA / "projections.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    lock = read_json(CONFIG / "locked_squad.json", {})
    chips = read_json(DATA / "chips.json", {})
    team = read_json(DATA / "team.json", {})
    if not projections.get("players") or package_optimizer.get("status") != "READY":
        raise RuntimeError("prediction/package artifacts unavailable for lineup governance")

    lineup = build_lineup_decision(projections, lock, chips)
    package = build_package_decision(package_optimizer, projections, lock, team)
    atomic_json(LINEUP_OUT, lineup)
    atomic_json(PACKAGE_DECISION_OUT, package)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({
        "lineup_decision": "data/lineup_decision.json",
        "package_decision": "data/package_decision.json",
    })
    latest["lineup_decision_summary"] = {
        "model": lineup.get("model"),
        "planning_gw": lineup.get("planning_gw"),
        "formation": lineup.get("formation"),
        "captain": lineup.get("captain"),
        "vice_captain": lineup.get("vice_captain"),
        "main_starting_xi_battle": lineup.get("main_starting_xi_battle"),
        "chip_context": lineup.get("chip_context"),
    }
    latest["package_decision_summary"] = {
        "selected_package_id": package.get("selected_package_id"),
        "optimizer_best_candidate_id": package.get("optimizer_best_candidate_id"),
        "manual_authority_override": package.get("manual_authority_override"),
        "gate0_revalidated": package.get("gate0_revalidated"),
    }
    atomic_json(DATA / "latest.json", latest)
    return {"lineup": lineup, "package": package}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "formation": out["lineup"].get("formation"),
        "captain": (out["lineup"].get("captain") or {}).get("name"),
        "vice": (out["lineup"].get("vice_captain") or {}).get("name"),
        "package": out["package"].get("selected_package_id"),
        "gate0_revalidated": out["package"].get("gate0_revalidated"),
    }, ensure_ascii=False))
