from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from statistics import NormalDist
from typing import Any

from src.models.package_optimizer_v2 import affordable_package, legal_squad, load_config as load_optimizer_config, score_package, simulate_objective
from src.models.team_strength import build_team_strength
from src.models.xmins_v2 import estimate_xmins
from src.rules import ASSIST_POINTS, CLEAN_SHEET_POINTS, GOAL_POINTS, RULESET_ID
from src.sources.official_fpl import get_json
from src.utils import DATA, ROOT, atomic_json, read_json

CONFIG_DIR = ROOT / "config" / "intelligence"
PROJECTION_CONFIG = CONFIG_DIR / "projection.json"
TEAM_STRENGTH_OUT = DATA / "team_strength.json"
PROJECTIONS_OUT = DATA / "projections.json"
PACKAGE_OUT = DATA / "package_optimizer.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@lru_cache(maxsize=1)
def load_projection_config() -> dict[str, Any]:
    return json.loads(PROJECTION_CONFIG.read_text(encoding="utf-8"))


def _blended_rate(player: dict[str, Any], cumulative_field: str, prior: float, shrink_minutes: float) -> tuple[float, str]:
    minutes = max(0.0, _f(player.get("minutes")))
    cumulative = max(0.0, _f(player.get(cumulative_field)))
    observed = cumulative * 90.0 / minutes if minutes > 0 else prior
    blended = (observed * minutes + prior * shrink_minutes) / max(1e-6, minutes + shrink_minutes)
    source = "observed_shrunk_to_position_prior" if minutes > 0 else "position_prior"
    return max(0.0, blended), source


def _p60(xmins: dict[str, Any], cfg: dict[str, Any]) -> float:
    trans = cfg.get("appearance_60_probability_transition") or {}
    low = _f(trans.get("start_minutes_low"), 55.0)
    high = max(low + 1.0, _f(trans.get("start_minutes_high"), 70.0))
    starter_minutes = _f(xmins.get("starter_minutes_if_start"), 72.0)
    conditional = clamp((starter_minutes - low) / (high - low), 0.0, 1.0)
    return clamp(_f(xmins.get("start_probability")) * conditional, 0.0, 1.0)


def _project_fixture(
    player: dict[str, Any],
    xmins: dict[str, Any],
    matchup: dict[str, Any],
    home: bool,
    rate_bundle: dict[str, float],
    small_sample: bool,
) -> dict[str, Any]:
    cfg = load_projection_config()
    position = str(player.get("position") or "FWD")
    element_type = int(player.get("element_type") or 4)
    share = clamp(_f(xmins.get("expected_minutes")) / 90.0, 0.0, 1.0)
    p_start = _f(xmins.get("start_probability"))
    p_bench = _f(xmins.get("bench_probability"))
    p60 = _p60(xmins, cfg)

    team_xg = _f(matchup.get("home_expected_goals") if home else matchup.get("away_expected_goals"), 1.3)
    league_base = _f((read_json(TEAM_STRENGTH_OUT, {}).get("baseline") or {}).get("home_goals" if home else "away_goals"), 1.3)
    attack_multiplier = clamp(
        team_xg / max(0.2, league_base),
        _f(cfg.get("attack_multiplier_min"), 0.55),
        _f(cfg.get("attack_multiplier_max"), 1.75),
    )
    cs_prob = clamp(_f(matchup.get("home_clean_sheet_probability") if home else matchup.get("away_clean_sheet_probability")), 0.0, 1.0)

    appearance = p_start * (1.0 + p60) + p_bench
    attack = (
        rate_bundle["xg90"] * GOAL_POINTS.get(element_type, 4)
        + rate_bundle["xa90"] * ASSIST_POINTS
    ) * share * attack_multiplier
    clean_sheet = CLEAN_SHEET_POINTS.get(element_type, 0) * cs_prob * p60
    saves = (rate_bundle["saves90"] / 3.0) * share if position == "GK" else 0.0
    dc = rate_bundle["dc90"] * share
    bonus = rate_bundle["bonus90"] * share
    mean = max(0.0, appearance + attack + clean_sheet + saves + dc + bonus)

    unc = cfg.get("uncertainty") or {}
    std = max(
        _f(unc.get("minimum_points_std"), 1.15),
        mean * _f(unc.get("coefficient_of_variation"), 0.42)
        + _f(xmins.get("minutes_std")) * _f(unc.get("xmins_std_points_multiplier"), 0.035)
        + (_f(unc.get("small_sample_extra_std"), 0.45) if small_sample else 0.0),
    )
    return {
        "event": matchup.get("event"),
        "kickoff_time": matchup.get("kickoff_time"),
        "opponent": matchup.get("team_a") if home else matchup.get("team_h"),
        "home": home,
        "team_expected_goals": round(team_xg, 4),
        "clean_sheet_probability": round(cs_prob, 4),
        "mean": round(mean, 3),
        "std": round(std, 3),
        "components": {
            "appearance": round(appearance, 3),
            "attack": round(attack, 3),
            "clean_sheet": round(clean_sheet, 3),
            "saves": round(saves, 3),
            "defensive_contribution": round(dc, 3),
            "bonus": round(bonus, 3),
        },
    }


def build_player_projections(bootstrap: dict[str, Any], strength: dict[str, Any], planning_gw: int, horizon: int = 15) -> dict[str, Any]:
    cfg = load_projection_config()
    teams = {int(t["id"]): t.get("name") for t in bootstrap.get("teams") or []}
    pos = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    team_rows = {int(t["team_id"]): t for t in strength.get("teams") or []}
    matchups_by_team: dict[int, list[dict[str, Any]]] = {}
    for matchup in strength.get("matchups") or []:
        for tid in (int(matchup["team_h"]), int(matchup["team_a"])):
            matchups_by_team.setdefault(tid, []).append(matchup)
    for rows in matchups_by_team.values():
        rows.sort(key=lambda x: (int(x.get("event") or 999), x.get("kickoff_time") or ""))

    shrink = max(1.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    priors = cfg.get("position_priors") or {}
    players = []
    for p in bootstrap.get("elements") or []:
        position = pos.get(int(p.get("element_type") or 4), "FWD")
        prior = priors.get(position) or priors.get("FWD") or {}
        xg90, xg_source = _blended_rate(p, "expected_goals", _f(prior.get("xg90")), shrink)
        xa90, xa_source = _blended_rate(p, "expected_assists", _f(prior.get("xa90")), shrink)
        bonus90, bonus_source = _blended_rate(p, "bonus", _f(prior.get("bonus90")), shrink)
        saves90, saves_source = _blended_rate(p, "saves", _f(prior.get("saves90")), shrink)
        dc90 = _f(prior.get("dc90"))
        rate_bundle = {"xg90": xg90, "xa90": xa90, "bonus90": bonus90, "saves90": saves90, "dc90": dc90}
        team_id = int(p.get("team") or -1)
        matches_played = int((team_rows.get(team_id) or {}).get("matches_played") or 0)
        xmins = estimate_xmins(p, {"team_matches_played": matches_played})
        fixtures = [m for m in matchups_by_team.get(team_id, []) if planning_gw <= int(m.get("event") or -1) < planning_gw + horizon]
        by_gw = []
        for gw in range(planning_gw, planning_gw + horizon):
            gw_matches = [m for m in fixtures if int(m.get("event") or -1) == gw]
            details = []
            for matchup in gw_matches:
                home = int(matchup["team_h"]) == team_id
                details.append(_project_fixture(p, xmins, matchup, home, rate_bundle, bool(xmins.get("small_sample_guard"))))
            mean = sum(_f(x.get("mean")) for x in details)
            std = math.sqrt(sum(_f(x.get("std")) ** 2 for x in details)) if details else 0.0
            if details:
                cs_no = 1.0
                for x in details:
                    cs_no *= 1.0 - _f(x.get("clean_sheet_probability"))
                cs_prob = 1.0 - cs_no
            else:
                cs_prob = 0.0
            by_gw.append({"gw": gw, "mean": round(mean, 3), "std": round(std, 3), "clean_sheet_probability": round(cs_prob, 4), "fixtures": details})

        sums = {}
        for h in (3, 5, 10, 15):
            subset = by_gw[:h]
            sums[str(h)] = {
                "mean": round(sum(_f(x["mean"]) for x in subset), 3),
                "std": round(math.sqrt(sum(_f(x["std"]) ** 2 for x in subset)), 3),
            }
        players.append({
            "element": int(p["id"]),
            "name": p.get("web_name"),
            "team_id": team_id,
            "team": teams.get(team_id),
            "position": position,
            "element_type": int(p.get("element_type") or 4),
            "now_cost": int(p.get("now_cost") or 0),
            "status": p.get("status"),
            "ownership_pct": _f(p.get("selected_by_percent")),
            "xmins": xmins,
            "rates": {
                **{k: round(v, 4) for k, v in rate_bundle.items()},
                "sources": {"xg90": xg_source, "xa90": xa_source, "bonus90": bonus_source, "saves90": saves_source, "dc90": "position_prior"},
            },
            "xpts_by_gw": by_gw,
            "horizons": sums,
            "projection_confidence": xmins.get("confidence"),
        })
    return {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "ruleset_id": RULESET_ID,
        "planning_gw": planning_gw,
        "horizon_gws": horizon,
        "players": players,
    }


def _optimizer_row(proj: dict[str, Any], sell_cost_value: int | None = None) -> dict[str, Any]:
    return {
        "element": int(proj["element"]),
        "name": proj.get("name"),
        "position": proj.get("position"),
        "team_id": int(proj.get("team_id") or -1),
        "now_cost": int(proj.get("now_cost") or 0),
        "sell_cost": int(sell_cost_value if sell_cost_value is not None else proj.get("now_cost") or 0),
        "status": proj.get("status"),
        "xpts_by_gw": proj.get("xpts_by_gw") or [],
        "horizons": proj.get("horizons") or {},
    }


def build_package_optimizer(projections: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    cfg = load_optimizer_config()
    planning_gw = int(projections.get("planning_gw") or 1)
    pmap = {int(p["element"]): p for p in projections.get("players") or []}
    ledger = list(team.get("team_value_ledger") or [])
    current = []
    owned_ids = set()
    for row in ledger:
        element = int(row.get("element") or -1)
        proj = pmap.get(element)
        if not proj:
            continue
        owned_ids.add(element)
        current.append(_optimizer_row(proj, row.get("sell_cost")))
    if not legal_squad(current):
        return {
            "generated_at": _now(),
            "model": cfg.get("model_id"),
            "status": "BLOCKED",
            "reason": "current squad failed legality precheck",
            "packages": [],
        }

    itb = int((team.get("totals") or {}).get("itb") or 0)
    allowed = set(cfg.get("allowed_statuses") or ["a", "d"])
    require_available = bool(cfg.get("require_available_status", True))
    candidate_pool: dict[str, list[dict[str, Any]]] = {}
    max_candidates = int(cfg.get("max_candidates_per_position") or 7)
    candidate_risk_aversion = _f(cfg.get("risk_aversion"), 0.12)
    for position in ("GK", "DEF", "MID", "FWD"):
        rows = []
        for proj in projections.get("players") or []:
            if proj.get("position") != position or int(proj["element"]) in owned_ids:
                continue
            if require_available and proj.get("status") not in allowed:
                continue
            row = _optimizer_row(proj)
            row["candidate_score"] = _f((proj.get("horizons") or {}).get("5", {}).get("mean")) - candidate_risk_aversion * _f((proj.get("horizons") or {}).get("5", {}).get("std"))
            rows.append(row)
        rows.sort(key=lambda r: (r["candidate_score"], -r["now_cost"]), reverse=True)
        candidate_pool[position] = rows[:max_candidates]

    hold_score = score_package(current, planning_gw, changes=0)
    packages = [{
        "id": "HOLD",
        "changes": 0,
        "outs": [],
        "ins": [],
        "affordability": {"resulting_itb": itb},
        "score": hold_score,
        "legal": True,
    }]
    single_moves = []
    max_per_out = int(cfg.get("max_single_moves_per_out") or 4)
    for out in current:
        candidate_rows = candidate_pool.get(out["position"], [])[:max_per_out]
        for incoming in candidate_rows:
            ok_cash, finance = affordable_package([out], [incoming], itb)
            if not ok_cash:
                continue
            candidate = [p for p in current if p["element"] != out["element"]] + [incoming]
            if not legal_squad(candidate):
                continue
            score = score_package(candidate, planning_gw, changes=1)
            move = {"out": out, "in": incoming, "candidate": candidate, "finance": finance, "score": score}
            single_moves.append(move)
            packages.append({
                "id": f"1:{out['element']}->{incoming['element']}",
                "changes": 1,
                "outs": [{"element": out["element"], "name": out["name"], "sell_cost": out["sell_cost"]}],
                "ins": [{"element": incoming["element"], "name": incoming["name"], "now_cost": incoming["now_cost"]}],
                "affordability": finance,
                "score": score,
                "legal": True,
            })

    if int(cfg.get("max_changes") or 2) >= 2:
        single_moves.sort(key=lambda x: _f((x.get("score") or {}).get("robust_score")), reverse=True)
        seed_moves = single_moves[: min(40, len(single_moves))]
        seen = set()
        for i, a in enumerate(seed_moves):
            for b in seed_moves[i + 1 :]:
                outs = [a["out"], b["out"]]
                ins = [a["in"], b["in"]]
                if outs[0]["element"] == outs[1]["element"] or ins[0]["element"] == ins[1]["element"]:
                    continue
                key = tuple(sorted([outs[0]["element"], outs[1]["element"]])) + tuple(sorted([ins[0]["element"], ins[1]["element"]]))
                if key in seen:
                    continue
                seen.add(key)
                ok_cash, finance = affordable_package(outs, ins, itb)
                if not ok_cash:
                    continue
                out_ids = {x["element"] for x in outs}
                candidate = [p for p in current if p["element"] not in out_ids] + ins
                if not legal_squad(candidate):
                    continue
                score = score_package(candidate, planning_gw, changes=2)
                packages.append({
                    "id": f"2:{outs[0]['element']},{outs[1]['element']}->{ins[0]['element']},{ins[1]['element']}",
                    "changes": 2,
                    "outs": [{"element": x["element"], "name": x["name"], "sell_cost": x["sell_cost"]} for x in outs],
                    "ins": [{"element": x["element"], "name": x["name"], "now_cost": x["now_cost"]} for x in ins],
                    "affordability": finance,
                    "score": score,
                    "legal": True,
                })
                if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                    break
            if len(packages) >= int(cfg.get("max_deterministic_packages") or 220):
                break

    packages = [p for p in packages if p.get("score", {}).get("valid")]
    packages.sort(key=lambda p: _f((p.get("score") or {}).get("robust_score")), reverse=True)
    mc_top = int(cfg.get("monte_carlo_top_n") or 20)
    simulations = int(cfg.get("monte_carlo_simulations") or 300)
    base_seed = int(cfg.get("monte_carlo_seed") or 1)
    hold_mean = _f(hold_score.get("objective_mean"))
    hold_std = _f(hold_score.get("objective_std"))
    for idx, package in enumerate(packages[:mc_top]):
        mean = _f(package["score"].get("objective_mean"))
        std = _f(package["score"].get("objective_std"))
        package["monte_carlo"] = simulate_objective(mean, std, simulations, base_seed + idx)
        diff_std = math.sqrt(std ** 2 + hold_std ** 2)
        if diff_std > 0:
            p_out = 1.0 - NormalDist(mu=mean - hold_mean, sigma=diff_std).cdf(0.0)
        else:
            p_out = 1.0 if mean > hold_mean else 0.5 if mean == hold_mean else 0.0
        package["monte_carlo"]["p_outperform_hold_independent_baseline"] = round(p_out, 4)

    pool_summary = {
        pos: [
            {"element": p["element"], "name": p["name"], "now_cost": p["now_cost"], "candidate_score": round(p["candidate_score"], 3)}
            for p in rows
        ]
        for pos, rows in candidate_pool.items()
    }
    return {
        "generated_at": _now(),
        "model": cfg.get("model_id"),
        "status": "READY",
        "planning_gw": planning_gw,
        "ruleset_id": RULESET_ID,
        "gate0_prevalidated": True,
        "simulation_assumption": cfg.get("simulation_assumption"),
        "candidate_pool": pool_summary,
        "package_count": len(packages),
        "hold": next((p for p in packages if p["id"] == "HOLD"), None),
        "packages": packages[:mc_top],
        "governance": {
            "candidate_generation_only": True,
            "final_go_requires_framework_governance_and_postflight_gate0": True,
            "price_uses_sell_value_for_outs_and_now_cost_for_ins": True,
        },
    }


def run() -> dict[str, Any]:
    bootstrap, bh = get_json("bootstrap-static/")
    fixtures, fh = get_json("fixtures/")
    if not bootstrap or not fixtures:
        raise RuntimeError(f"Official FPL unavailable for decision intelligence: bootstrap={bh.get('status')} fixtures={fh.get('status')}")
    latest = read_json(DATA / "latest.json", {})
    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 1)
    strength = build_team_strength(bootstrap, fixtures)
    strength["generated_at"] = _now()
    strength["source_health"] = {"bootstrap": bh.get("status"), "fixtures": fh.get("status")}
    atomic_json(TEAM_STRENGTH_OUT, strength)

    projections = build_player_projections(bootstrap, strength, planning_gw, horizon=15)
    atomic_json(PROJECTIONS_OUT, projections)
    packages = build_package_optimizer(projections, read_json(DATA / "team.json", {}))
    atomic_json(PACKAGE_OUT, packages)

    latest.setdefault("files", {}).update({
        "team_strength": "data/team_strength.json",
        "projections": "data/projections.json",
        "package_optimizer": "data/package_optimizer.json",
    })
    latest["decision_intelligence"] = {
        "model": projections.get("model"),
        "planning_gw": planning_gw,
        "projection_players": len(projections.get("players") or []),
        "team_strength_model": strength.get("model"),
        "team_strength_teams": len(strength.get("teams") or []),
        "package_optimizer_status": packages.get("status"),
        "package_count": packages.get("package_count", 0),
        "best_package": (packages.get("packages") or [{}])[0].get("id") if packages.get("packages") else None,
        "candidate_generation_only": True,
    }
    atomic_json(DATA / "latest.json", latest)
    return {"strength": strength, "projections": projections, "packages": packages}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "team_strength_teams": len(out["strength"].get("teams") or []),
        "projection_players": len(out["projections"].get("players") or []),
        "package_count": out["packages"].get("package_count"),
        "best_package": (out["packages"].get("packages") or [{}])[0].get("id") if out["packages"].get("packages") else None,
    }, ensure_ascii=False))
