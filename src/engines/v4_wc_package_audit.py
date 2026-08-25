from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

from src.utils import DATA, CONFIG, atomic_json, read_json
from src.engines.v4_wc_optimizer import (
    BUDGET_TENTHS,
    MAX_PER_CLUB,
    POSITION_COUNTS,
    Candidate,
    build_candidates,
    player_objective,
    squad_metrics,
    validate_squad,
)

OUTFILE = DATA / "wc_package_audit_v4.json"


def _candidate_payload(p: Candidate) -> dict:
    return {
        "element": p.element,
        "name": p.name,
        "position": p.position,
        "team": p.team,
        "team_id": p.team_id,
        "cost": p.cost,
        "xpts_3": round(p.x3, 2),
        "xpts_5": round(p.x5, 2),
        "xpts_10": round(p.x10, 2),
        "xpts_15": round(p.x15, 2),
        "uncertainty": round(p.uncertainty, 3),
        "objective": round(p.objective, 4),
    }


def _package_class(delta_x5: float, delta_obj: float, replacements: int) -> str:
    # Higher evidence burden for larger WC edits. Prevents optimizer churn.
    x5_req = {1: 2.0, 2: 3.5, 3: 5.0, 4: 6.5}[replacements]
    obj_req = {1: 0.25, 2: 0.45, 3: 0.65, 4: 0.85}[replacements]
    if delta_x5 >= x5_req and delta_obj >= obj_req:
        return "MATERIAL_UPGRADE"
    if delta_x5 >= x5_req * 0.55 and delta_obj >= obj_req * 0.55:
        return "OPTIONAL_IMPROVEMENT"
    return "KEEP_BASELINE"


def _legal_after_swap(current: list[Candidate], out_ids: set[int], ins: tuple[Candidate, ...], budget: int) -> bool:
    keep = [p for p in current if p.element not in out_ids]
    squad = keep + list(ins)
    ok, _ = validate_squad(squad, budget)
    return ok


def _frontier(cands: list[Candidate], baseline_ids: set[int], per_position: int = 18) -> list[Candidate]:
    out = []
    for pos in POSITION_COUNTS:
        rows = [p for p in cands if p.position == pos and p.element not in baseline_ids]
        rows.sort(key=lambda p: (p.objective, p.x5, -p.cost), reverse=True)
        out.extend(rows[:per_position])
    return out


def audit_packages(predictions: dict, universe: dict, locked: dict, max_replacements: int = 4,
                   budget: int = BUDGET_TENTHS, per_position_frontier: int = 18,
                   top_per_size: int = 12) -> dict:
    candidates = build_candidates(predictions, universe)
    by_id = {p.element: p for p in candidates}
    baseline_ids = {int(x["element"]) for x in locked.get("players", [])}
    missing = baseline_ids - set(by_id)
    if missing:
        raise RuntimeError(f"baseline players missing from candidate universe: {sorted(missing)}")

    current = [by_id[e] for e in baseline_ids]
    ok, reason = validate_squad(current, budget)
    if not ok:
        raise RuntimeError(f"baseline invalid: {reason}")

    frontier = _frontier(candidates, baseline_ids, per_position_frontier)
    current_metrics = squad_metrics(current)
    baseline_cost = current_metrics["cost"]
    baseline_itb = budget - baseline_cost

    by_pos_frontier = {pos: [p for p in frontier if p.position == pos] for pos in POSITION_COUNTS}
    results = {}

    for k in range(1, max_replacements + 1):
        packages = []
        # OUT choices are only 15Ck, tiny. IN choices are generated position-wise to preserve structure.
        for outs in combinations(current, k):
            out_ids = {p.element for p in outs}
            need = Counter(p.position for p in outs)
            pools = []
            impossible = False
            for pos, n in need.items():
                rows = by_pos_frontier[pos]
                if len(rows) < n:
                    impossible = True
                    break
                pools.append((pos, n, rows))
            if impossible:
                continue

            def build_ins(idx: int, chosen: tuple[Candidate, ...]):
                if idx == len(pools):
                    if len({p.element for p in chosen}) != k:
                        return
                    if not _legal_after_swap(current, out_ids, chosen, budget):
                        return
                    target = [p for p in current if p.element not in out_ids] + list(chosen)
                    tm = squad_metrics(target)
                    d5 = tm["xpts_5"] - current_metrics["xpts_5"]
                    dobj = tm["objective"] - current_metrics["objective"]
                    packages.append({
                        "replacements": k,
                        "out": [_candidate_payload(p) for p in sorted(outs, key=lambda x: (x.position, x.name))],
                        "in": [_candidate_payload(p) for p in sorted(chosen, key=lambda x: (x.position, x.name))],
                        "target_cost": tm["cost"],
                        "target_itb": budget - tm["cost"],
                        "delta_cost": tm["cost"] - baseline_cost,
                        "delta_objective": round(dobj, 4),
                        "delta_xpts_3": round(tm["xpts_3"] - current_metrics["xpts_3"], 2),
                        "delta_xpts_5": round(d5, 2),
                        "delta_xpts_10": round(tm["xpts_10"] - current_metrics["xpts_10"], 2),
                        "delta_xpts_15": round(tm["xpts_15"] - current_metrics["xpts_15"], 2),
                        "classification": _package_class(d5, dobj, k),
                    })
                    return

                pos, n, rows = pools[idx]
                for combo in combinations(rows, n):
                    # Early budget + club pruning.
                    tentative = chosen + combo
                    if len({p.element for p in tentative}) != len(tentative):
                        continue
                    build_ins(idx + 1, tentative)

            build_ins(0, tuple())

        packages.sort(key=lambda r: (r["delta_objective"], r["delta_xpts_5"], r["target_itb"]), reverse=True)
        results[str(k)] = packages[:top_per_size]

    best_each = {k: (rows[0] if rows else None) for k, rows in results.items()}
    material = [x for x in best_each.values() if x and x["classification"] == "MATERIAL_UPGRADE"]
    optional = [x for x in best_each.values() if x and x["classification"] == "OPTIONAL_IMPROVEMENT"]
    if material:
        overall = max(material, key=lambda x: (x["delta_objective"], x["delta_xpts_5"]))
        verdict = "MATERIAL_UPGRADE"
    elif optional:
        overall = max(optional, key=lambda x: (x["delta_objective"], x["delta_xpts_5"]))
        verdict = "OPTIONAL_IMPROVEMENT"
    else:
        overall = None
        verdict = "KEEP_15"

    return {
        "schema_version": 442,
        "engine": "v4.4.2-wc-package-audit",
        "wildcard_active": bool(locked.get("wildcard_active")),
        "baseline": current_metrics | {"itb": baseline_itb},
        "screened_players": len(candidates),
        "frontier_players": len(frontier),
        "max_replacements": max_replacements,
        "best_by_replacement_count": best_each,
        "packages": results,
        "overall_verdict": verdict,
        "recommended_package": overall,
        "guardrails": {
            "max_per_club": MAX_PER_CLUB,
            "budget_tenths": budget,
            "position_counts": POSITION_COUNTS,
            "larger_packages_require_higher_gain": True,
        },
    }


def run() -> dict:
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    locked = read_json(CONFIG / "locked_squad.json", {})
    out = audit_packages(predictions, universe, locked)
    atomic_json(OUTFILE, out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


if __name__ == "__main__":
    run()
