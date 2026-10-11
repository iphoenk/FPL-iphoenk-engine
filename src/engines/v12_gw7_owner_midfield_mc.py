from __future__ import annotations

"""Owner-controlled GW7 two-midfield what-if on unmodified canonical P1.7/P1.4.

Never submits transfers, changes CURRENT15, changes natural scheduling, or
claims future mini-league rank probabilities without a rival simulation.
"""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.engines.v12_gw6_forward_mc import _element, _lineup_route

MC_PATHS = 500_000
TARGET_GW = 7
HORIZONS = (1, 3, 5)
OUR_TEAM = 3462711
COMPETITIVE_LEAGUE = 9477

ROUTES = {
    "HOLD": {},
    "PALMER_MBEUMO": {426: 154, 15: 427},
    "SAKA_MBEUMO": {426: 12, 15: 427},
}


class OwnerMidfieldMCError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OwnerMidfieldMCError("input is not a JSON object")
    return value


def _team(row: Mapping[str, Any]) -> int:
    return int(row.get("team_id") or row.get("team") or 0)


def _pos(row: Mapping[str, Any]) -> int:
    value = row.get("element_type") or row.get("position_id") or row.get("position")
    if isinstance(value, str):
        return {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}.get(value.upper(), 0)
    return int(value or 0)


def _verify_roster(ids: list[int], pmap: Mapping[int, Mapping[str, Any]]) -> None:
    if len(ids) != 15 or len(set(ids)) != 15:
        raise OwnerMidfieldMCError("CURRENT15 partition invalid")
    clubs: dict[int, int] = {}
    positions: dict[int, int] = {}
    for pid in ids:
        if pid not in pmap:
            raise OwnerMidfieldMCError("missing canonical full-universe player")
        t = _team(pmap[pid])
        pos = _pos(pmap[pid])
        if not t or pos not in (1, 2, 3, 4):
            raise OwnerMidfieldMCError("canonical club or position missing")
        clubs[t] = clubs.get(t, 0) + 1
        positions[pos] = positions.get(pos, 0) + 1
    if any(n > 3 for n in clubs.values()):
        raise OwnerMidfieldMCError("more than three players from one club")
    if positions != {1: 2, 2: 5, 3: 5, 4: 3}:
        raise OwnerMidfieldMCError("FPL position quota invalid")


def _league_counts(picks: Mapping[str, Any], standings: Mapping[str, Any]) -> dict[str, Any]:
    managers = list(standings.get("managers") or [])
    if len(managers) != 58 or int(picks.get("collected_manager_count") or 0) != 58:
        raise OwnerMidfieldMCError("mini-league 58/58 coverage unavailable")
    owned = next((row for row in managers if int(row.get("entry_id") or 0) == OUR_TEAM), None)
    if not owned:
        raise OwnerMidfieldMCError("owner not in mini-league")
    rank = int(owned["league_rank"])
    # Existing Competitive Window policy: 9 nearest rivals, TOP10 when our rank <10.
    rivals = [r for r in managers if int(r["entry_id"]) != OUR_TEAM and int(r["league_rank"]) <= 10] if rank < 10 else []
    if not rivals:
        higher = [r for r in managers if int(r["league_rank"]) < rank]
        lower = [r for r in managers if int(r["league_rank"]) >= rank and int(r["entry_id"]) != OUR_TEAM]
        rivals = higher[-9:] + lower[:5]
    if len(rivals) < 1:
        raise OwnerMidfieldMCError("competitive rival window empty")

    def count(rows: list[Mapping[str, Any]], element: int) -> dict[str, int]:
        result = {"owned": 0, "starting": 0, "captain": 0, "eo_numerator": 0, "denominator": len(rows)}
        for manager in rows:
            entry = (picks.get("entries") or {}).get(str(manager["entry_id"])) or {}
            item = next((v for v in (entry.get("picks") or []) if int(v.get("element_id") or 0) == element), None)
            if item is None:
                continue
            result["owned"] += 1
            multiplier = int(item.get("multiplier") or 0)
            result["starting"] += int(multiplier > 0)
            result["captain"] += int(bool(item.get("captain")))
            result["eo_numerator"] += multiplier
        return result

    return {
        "league_rank": rank,
        "league_total": int(owned["league_total"]),
        "top3_gap": int(next(r["league_total"] for r in managers if int(r["league_rank"]) == 3)) - int(owned["league_total"]),
        "competitive_rivals": len(rivals),
        "ownership_gw6_baseline_only": {
            name: {"league": count(managers, eid), "competitive": count(rivals, eid)}
            for name, eid in (("Palmer", 154), ("Saka", 12), ("Mbeumo", 427))
        },
        "future_rival_transfer_assumptions": "NOT_MODELLED",
        "probability_of_future_top3": None,
        "probability_of_future_top3_status": "NOT_EXECUTED_NO_FUTURE_RIVAL_ROUTES",
    }


def evaluate(
    warm: Mapping[str, Any],
    *,
    report_slot: str,
    league_picks: Mapping[str, Any],
    standings: Mapping[str, Any],
    optimizer: Any = None,
    simulator: Any = None,
) -> dict[str, Any]:
    if warm.get("schema") != "FPL_MASTER_V12_PRIVATE_WARM_STATE_V1":
        raise OwnerMidfieldMCError("private canonical warm state required")
    if int(warm.get("planning_gw") or 0) != TARGET_GW:
        raise OwnerMidfieldMCError("planning GW is not 7")
    if str(warm.get("report_slot") or "") != report_slot:
        raise OwnerMidfieldMCError("same occurrence slot mismatch")
    projections = warm.get("projections")
    if not isinstance(projections, Mapping) or int(projections.get("planning_gw") or 0) != TARGET_GW:
        raise OwnerMidfieldMCError("canonical P1.1/P1.3 GW7 projections not bound")
    pmap = {int(row.get("element") or 0): row for row in projections.get("players") or []}
    owned = [_element(row) for row in warm.get("owned") or []]
    _verify_roster(owned, pmap)
    if 426 not in owned or 15 not in owned:
        raise OwnerMidfieldMCError("Bruno and Odegaard must both be owned")
    if any(x in owned for x in (154, 12, 427)):
        raise OwnerMidfieldMCError("scenario incoming player already owned")
    if any(_pos(pmap[x]) != 3 for x in (426, 15, 154, 12, 427)):
        raise OwnerMidfieldMCError("two-MID transfer position invalid")

    if optimizer is None:
        from src.engines.v12_lineup_optimizer import optimize_lineup
        optimizer = optimize_lineup
    if simulator is None:
        from src.engines.v12_monte_carlo import run_correlated_monte_carlo
        simulator = run_correlated_monte_carlo

    definitions = []
    lineup_proof = {}
    for name, replacements in ROUTES.items():
        ids = [replacements.get(x, x) for x in owned]
        _verify_roster(ids, pmap)
        per_gw = []
        for offset in range(max(HORIZONS)):
            result = optimizer(projections, sorted(ids), planning_gw=TARGET_GW + offset)
            per_gw.append(_lineup_route(result, TARGET_GW + offset))
            if offset == 0:
                forms = list(result.get("formation_comparison") or [])
                if len(forms) != 8 or len({x.get("formation") for x in forms}) != 8:
                    raise OwnerMidfieldMCError("P1.7 eight legal formation comparisons missing")
                lineup_proof[name] = {
                    "formation": result.get("formation"),
                    "captain": per_gw[0]["captain"],
                    "vice": per_gw[0]["vice_captain"],
                    "xi": per_gw[0]["starting_xi"],
                    "bench_order": per_gw[0]["bench_order"],
                    "formation_comparison": forms,
                }
        is_hold = name == "HOLD"
        definitions.append({
            "route_id": name,
            "classification": "CURRENT15" if is_hold else "OWNER_TWO_MID_WHAT_IF",
            "per_gw": per_gw,
            "execution_cost_points": 0.0 if is_hold else 4.0,
            "execution_cost_status": "HOLD_ZERO" if is_hold else "ASSUMED_ONE_FT_ONE_HIT",
            "decision_net_supported": is_hold,
        })
    binding = str((projections.get("model_evidence_binding") or {}).get("output_fingerprint") or "")
    if not binding:
        binding = hashlib.sha256(json.dumps(projections, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(definitions, sort_keys=True, default=str).encode()).hexdigest()
    seed = int(hashlib.sha256((binding + digest).encode()).hexdigest()[:8], 16)
    mc = simulator(
        projections, definitions, actual_paths=MC_PATHS, seed=seed,
        input_snapshot_id="GW7_OWNER_TWO_MID_WHAT_IF:" + binding,
        canonical=True, horizons=HORIZONS,
        selected_route_id="PALMER_MBEUMO",
        factual_snapshot_timestamps={"canonical_warm_slot": report_slot},
        factual_artifact_fingerprints={"canonical_projection": binding, "route_definitions": digest},
    )
    if mc.get("execution_state") != "EXECUTED" or mc.get("canonical_pass") is not True or int(mc.get("actual_paths") or 0) < MC_PATHS:
        raise OwnerMidfieldMCError("P1.4 canonical execution/convergence not PASS")
    metrics = mc.get("metrics") or {}
    if any(name not in metrics for name in ROUTES):
        raise OwnerMidfieldMCError("a route lacks canonical MC metrics")
    return {
        "contract": "GW7_OWNER_TWO_MID_CANONICAL_PAIRED_MC_V1",
        "status": "PASS",
        "decision_authority": "ADVISORY_WHAT_IF_NOT_TRANSFER_EXECUTION",
        "report_slot": report_slot,
        "planning_gw": TARGET_GW,
        "horizons": HORIZONS,
        "actual_paths_each_route": MC_PATHS,
        "correlated_common_random_worlds": True,
        "route_definitions_sha256": digest,
        "projection_binding": binding,
        "seed": seed,
        "mc_output_fingerprint": mc.get("output_fingerprint"),
        "lineup_proof": lineup_proof,
        "metrics": {name: metrics[name] for name in ROUTES},
        "pairwise": mc.get("paired_outputs"),
        "convergence": mc.get("convergence_evidence"),
        "mini_league": _league_counts(league_picks, standings),
        "finance": {
            "transfers": 2, "ft_assumption": 1, "hit_points_assumed": 4,
            "authenticated_current_selling_values_required_before_execution": True,
            "route_decision_net_supported": False,
        },
        "official_current15_unchanged": True,
        "private_publisher_called_by_runner": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--warm-state", required=True)
    p.add_argument("--report-slot", required=True)
    p.add_argument("--league-picks", required=True)
    p.add_argument("--league-standings", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = evaluate(
        _read(Path(args.warm_state)),
        report_slot=args.report_slot,
        league_picks=_read(Path(args.league_picks)),
        standings=_read(Path(args.league_standings)),
    )
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "paths": MC_PATHS, "routes": sorted(ROUTES), "fingerprint": result["mc_output_fingerprint"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
