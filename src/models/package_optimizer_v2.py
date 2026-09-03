from __future__ import annotations

import json
import math
import random
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.models.transfer_state import incremental_hit_cost
from src.rules import LINEUP_RULES, SQUAD_RULES

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "package_optimizer.json"
POSITIONS = ("GK", "DEF", "MID", "FWD")
PARSED_FORMATIONS = tuple(
    (formation, tuple(int(x) for x in str(formation).split("-")))
    for formation in (LINEUP_RULES.get("legal_formations") or [])
)
EXPECTED_XI = int(LINEUP_RULES.get("starting_xi_size") or 11)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _gw_row(player: dict[str, Any], gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) == int(gw):
            return row
    return {"mean": 0.0, "std": 0.0}


def _gw_index(players: list[dict[str, Any]]) -> dict[int, dict[int, dict[str, Any]]]:
    return {
        int(player.get("element") or -1): {
            int(row.get("gw") or -1): row
            for row in (player.get("xpts_by_gw") or [])
        }
        for player in players
    }


def _indexed_row(index: dict[int, dict[int, dict[str, Any]]], player: dict[str, Any], gw: int) -> dict[str, Any]:
    return index.get(int(player.get("element") or -1), {}).get(int(gw), {"mean": 0.0, "std": 0.0})


def legal_squad(players: list[dict[str, Any]]) -> bool:
    expected = {k: int(v) for k, v in (SQUAD_RULES.get("position_counts") or {}).items()}
    if len(players) != int(SQUAD_RULES.get("squad_size") or 0):
        return False
    counts = {k: 0 for k in expected}
    clubs: dict[int, int] = {}
    seen = set()
    for player in players:
        element = int(player.get("element") or -1)
        if element in seen:
            return False
        seen.add(element)
        position = player.get("position")
        if position not in counts:
            return False
        counts[position] += 1
        team_id = int(player.get("team_id") or -1)
        clubs[team_id] = clubs.get(team_id, 0) + 1
    return counts == expected and max(clubs.values(), default=0) <= int(SQUAD_RULES.get("max_players_per_club") or 0)


def _best_lineup_indexed(players: list[dict[str, Any]], gw: int, index: dict[int, dict[int, dict[str, Any]]]) -> dict[str, Any]:
    by_position = {
        pos: sorted(
            [p for p in players if p.get("position") == pos],
            key=lambda p: _f(_indexed_row(index, p, gw).get("mean")),
            reverse=True,
        )
        for pos in POSITIONS
    }
    gks = by_position["GK"]
    if not gks:
        return {"valid": False, "mean": 0.0, "variance": 0.0, "starters": []}
    best: dict[str, Any] | None = None
    for formation, (d, m, f) in PARSED_FORMATIONS:
        selected = [gks[0]]
        ok = True
        for pos, count in (("DEF", d), ("MID", m), ("FWD", f)):
            pool = by_position[pos]
            if len(pool) < count:
                ok = False
                break
            selected.extend(pool[:count])
        if not ok or len(selected) != EXPECTED_XI:
            continue
        mean = sum(_f(_indexed_row(index, p, gw).get("mean")) for p in selected)
        variance = sum(_f(_indexed_row(index, p, gw).get("std")) ** 2 for p in selected)
        candidate = {
            "valid": True,
            "formation": formation,
            "mean": mean,
            "variance": variance,
            "starters": [int(p["element"]) for p in selected],
        }
        if best is None or candidate["mean"] > best["mean"]:
            best = candidate
    return best or {"valid": False, "mean": 0.0, "variance": 0.0, "starters": []}


def best_lineup(players: list[dict[str, Any]], gw: int) -> dict[str, Any]:
    return _best_lineup_indexed(players, gw, _gw_index(players))


def _effective_change_cap(cfg: dict[str, Any], planning_gw: int) -> tuple[int, dict[str, Any]]:
    base = max(0, int(cfg.get("max_changes") or 0))
    guard = cfg.get("early_season_change_cap") or {}
    enabled = bool(guard.get("enabled"))
    through_gw = max(0, int(guard.get("through_gw") or 0))
    early_cap = max(0, int(guard.get("max_changes") if guard.get("max_changes") is not None else base))
    effective = min(base, early_cap) if enabled and int(planning_gw) <= through_gw else base
    return effective, {
        "early_season_change_cap_enabled": enabled,
        "early_season_through_gw": through_gw,
        "configured_max_changes": base,
        "effective_max_changes": effective,
    }


def _cluster_penalty_from_team_ids(team_ids: list[int], cfg: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    guard = cfg.get("team_cluster_penalty") or {}
    enabled = bool(guard.get("enabled"))
    free = max(0, int(guard.get("free_players_per_club") or 0))
    per_extra = max(0.0, _f(guard.get("points_per_extra_player")))
    clubs = Counter(int(team_id) for team_id in team_ids if int(team_id) > 0)
    excess = sum(max(0, count - free) for count in clubs.values()) if enabled else 0
    penalty = excess * per_extra if enabled else 0.0
    return penalty, {
        "team_cluster_penalty_enabled": enabled,
        "free_players_per_club": free,
        "points_per_extra_player": per_extra,
        "cluster_excess_players": excess,
        "cluster_penalty_points": round(penalty, 3),
        "club_counts": dict(sorted(clubs.items())),
    }


def _team_cluster_penalty(players: list[dict[str, Any]], cfg: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    return _cluster_penalty_from_team_ids([int(p.get("team_id") or -1) for p in players], cfg)


def _scoring_context(cfg: dict[str, Any], planning_gw: int, transfer_state: dict[str, Any] | None = None) -> dict[str, Any]:
    horizons = [int(x) for x in cfg.get("horizons") or [3, 5, 10, 15]]
    change_cap, change_guard = _effective_change_cap(cfg, planning_gw)
    return {
        "cfg": cfg,
        "horizons": horizons,
        "horizon_set": set(horizons),
        "max_horizon": max(horizons, default=0),
        "weights": {str(k): _f(v) for k, v in (cfg.get("horizon_weights") or {}).items()},
        "bench_weight": _f(cfg.get("bench_utility_weight"), 0.10),
        "captain_weight": _f(cfg.get("captain_bonus_weight"), 1.0),
        "risk_aversion": _f(cfg.get("risk_aversion"), 0.12),
        "change_penalty_points": _f(cfg.get("change_penalty_points"), 0.20),
        "transfer_state": dict(transfer_state or {}),
        "change_cap": change_cap,
        "change_guard": change_guard,
        "_compiled_player_cache": {},
    }


def _compile_player(player: dict[str, Any], planning_gw: int, max_horizon: int) -> dict[str, Any]:
    index = {
        int(row.get("gw") or -1): row
        for row in (player.get("xpts_by_gw") or [])
    }
    means: list[float] = []
    variances: list[float] = []
    for offset in range(int(max_horizon)):
        row = index.get(int(planning_gw) + offset, {})
        mean = _f(row.get("mean"))
        std = _f(row.get("std"))
        means.append(mean)
        variances.append(std * std)
    xmins = player.get("xmins") or {}
    tactical = player.get("tactical_matchup") or {}
    historical = player.get("historical_prior") or {}
    adaptation = historical.get("transfer_adaptation") or {}
    price = player.get("price_risk_context") or {}
    tactical_confidence = str(tactical.get("evidence_confidence") or tactical.get("tactical_confidence") or "NONE").upper()
    roster_uncertain = bool(adaptation.get("confidence_ceiling"))
    adverse_price = bool(
        price.get("evidence_available") is True
        and price.get("direction") == "FALL"
        and price.get("predicted_change_cycle") not in {None, "", "NONE"}
    )
    return {
        "element": int(player.get("element") or -1),
        "position": str(player.get("position") or ""),
        "team_id": int(player.get("team_id") or -1),
        "means": tuple(means),
        "variances": tuple(variances),
        "xmins_minutes_std": _f(xmins.get("minutes_std"), 90.0),
        "tactical_uncertain": tactical_confidence != "HIGH",
        "tactical_confidence": tactical_confidence,
        "roster_change_uncertain": roster_uncertain,
        "roster_change_state": adaptation.get("state"),
        "price_risk_adverse": adverse_price,
        "price_evidence_available": price.get("evidence_available") is True,
    }


def _compile_players_cached(players: list[dict[str, Any]], planning_gw: int, context: dict[str, Any]) -> list[dict[str, Any]]:
    cache = context.setdefault("_compiled_player_cache", {})
    rows: list[dict[str, Any]] = []
    max_horizon = int(context["max_horizon"])
    for player in players:
        key = id(player)
        cached = cache.get(key)
        if cached is None or cached[0] is not player:
            compiled = _compile_player(player, planning_gw, max_horizon)
            cache[key] = (player, compiled)
        else:
            compiled = cached[1]
        rows.append(compiled)
    return rows


def _compiled_best_lineup(by_position: dict[str, list[dict[str, Any]]], offset: int) -> tuple[bool, float, float, set[int]]:
    ranked = {
        position: sorted(pool, key=lambda row: row["means"][offset], reverse=True)
        for position, pool in by_position.items()
    }
    gks = ranked["GK"]
    if not gks:
        return False, 0.0, 0.0, set()
    best_mean: float | None = None
    best_var = 0.0
    best_ids: set[int] = set()
    for _, (d, m, f) in PARSED_FORMATIONS:
        selected = [gks[0]]
        valid = True
        for position, count in (("DEF", d), ("MID", m), ("FWD", f)):
            pool = ranked[position]
            if len(pool) < count:
                valid = False
                break
            selected.extend(pool[:count])
        if not valid or len(selected) != EXPECTED_XI:
            continue
        mean = sum(row["means"][offset] for row in selected)
        if best_mean is None or mean > best_mean:
            best_mean = mean
            best_var = sum(row["variances"][offset] for row in selected)
            best_ids = {int(row["element"]) for row in selected}
    if best_mean is None:
        return False, 0.0, 0.0, set()
    return True, best_mean, best_var, best_ids


def _package_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clubs = Counter(int(row.get("team_id") or -1) for row in rows if int(row.get("team_id") or -1) > 0)
    max_club = int(SQUAD_RULES.get("max_players_per_club") or 3)
    max_count = max(clubs.values(), default=0)
    return {
        "xmins_uncertainty_mean_minutes_std": round(sum(_f(row.get("xmins_minutes_std"), 90.0) for row in rows) / max(1, len(rows)), 4),
        "tactical_role_uncertainty_count": sum(bool(row.get("tactical_uncertain")) for row in rows),
        "price_risk_adverse_count": sum(bool(row.get("price_risk_adverse")) for row in rows),
        "price_evidence_available_count": sum(bool(row.get("price_evidence_available")) for row in rows),
        "roster_change_uncertainty_count": sum(bool(row.get("roster_change_uncertain")) for row in rows),
        "structural_flexibility_club_slot_headroom": max(0, max_club - max_count),
        "clubs_at_cap": sum(count >= max_club for count in clubs.values()),
    }


def _score_compiled_rows(rows: list[dict[str, Any]], changes: int, context: dict[str, Any]) -> dict[str, Any]:
    cfg = context["cfg"]
    cluster_penalty, cluster_guard = _cluster_penalty_from_team_ids([int(row["team_id"]) for row in rows], cfg)
    guardrails = {**context["change_guard"], **cluster_guard}
    if int(changes) > int(context["change_cap"]):
        return {"valid": False, "reason": "early_season_change_cap_exceeded", "guardrails": guardrails}

    horizons = context["horizons"]
    bench_weight = context["bench_weight"]
    captain_weight = context["captain_weight"]
    by_position = {position: [row for row in rows if row["position"] == position] for position in POSITIONS}
    horizon_results: dict[str, dict[str, Any]] = {}
    total_mean = 0.0
    total_var = 0.0
    valid = True

    for offset in range(context["max_horizon"]):
        lineup_valid, lineup_mean, lineup_var, starter_ids = _compiled_best_lineup(by_position, offset)
        if not lineup_valid:
            valid = False
        if valid:
            all_mean = sum(row["means"][offset] for row in rows)
            all_var = sum(row["variances"][offset] for row in rows)
            bench_mean = all_mean - lineup_mean
            bench_var = all_var - lineup_var
            captain_row: dict[str, Any] | None = None
            captain_mean = float("-inf")
            for row in rows:
                if int(row["element"]) in starter_ids:
                    mean = row["means"][offset]
                    if captain_row is None or mean > captain_mean:
                        captain_row = row
                        captain_mean = mean
            if captain_row is None:
                captain_mean = 0.0
                captain_var = 0.0
            else:
                captain_var = captain_row["variances"][offset]
            total_mean += lineup_mean + bench_weight * bench_mean + captain_weight * captain_mean
            captain_extra_var = ((1.0 + captain_weight) ** 2 - 1.0) * captain_var
            total_var += lineup_var + (bench_weight ** 2) * bench_var + captain_extra_var

        elapsed = offset + 1
        if elapsed in context["horizon_set"]:
            horizon_results[str(elapsed)] = {
                "valid": valid,
                "mean": round(total_mean, 3) if valid else None,
                "std": round(math.sqrt(total_var), 3) if valid else None,
            }

    for horizon in horizons:
        horizon_results.setdefault(str(horizon), {"valid": False, "mean": None, "std": None})
    weights = context["weights"]
    available = [(h, horizon_results[str(h)]) for h in horizons if horizon_results[str(h)]["valid"]]
    weight_sum = sum(weights.get(str(h), 0.0) for h, _ in available)
    if not available or weight_sum <= 0:
        return {"valid": False, "horizons": horizon_results, "guardrails": guardrails}
    objective_mean = sum(weights.get(str(h), 0.0) * row["mean"] for h, row in available) / weight_sum
    objective_var = sum((weights.get(str(h), 0.0) / weight_sum) ** 2 * row["std"] ** 2 for h, row in available)
    objective_std = math.sqrt(objective_var)
    change_penalty = int(changes) * context["change_penalty_points"]
    hit_cost, hit_exact = incremental_hit_cost(int(changes), context.get("transfer_state"))
    robust = objective_mean - context["risk_aversion"] * objective_std - change_penalty - cluster_penalty - hit_cost
    return {
        "valid": True,
        "horizons": horizon_results,
        "objective_mean": round(objective_mean, 3),
        "objective_std": round(objective_std, 3),
        "change_penalty_points": round(change_penalty, 3),
        "hit_cost_points": round(hit_cost, 3),
        "hit_cost_exact": hit_exact,
        "team_cluster_penalty_points": round(cluster_penalty, 3),
        "robust_score": round(robust, 3),
        "package_evidence": _package_evidence(rows),
        "guardrails": guardrails,
    }


class CompiledPackageScorer:
    """Precompiled input adapter for the single canonical exact scoring kernel."""

    def __init__(self, universe: list[dict[str, Any]], planning_gw: int, *, scoring_context: dict[str, Any] | None = None) -> None:
        self.planning_gw = int(planning_gw)
        self.context = scoring_context or _scoring_context(load_config(), planning_gw)
        self.registry = {
            int(player.get("element") or -1): _compile_player(player, planning_gw, self.context["max_horizon"])
            for player in universe
            if int(player.get("element") or -1) > 0
        }

    def score(self, players: list[dict[str, Any]], changes: int = 0) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for player in players:
            element = int(player.get("element") or -1)
            compiled = self.registry.get(element)
            if compiled is None:
                raise KeyError(f"compiled package scorer missing element={element}")
            rows.append(compiled)
        return _score_compiled_rows(rows, changes, self.context)


def score_package(players: list[dict[str, Any]], planning_gw: int, changes: int = 0, *, scoring_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = scoring_context or _scoring_context(load_config(), planning_gw)
    rows = _compile_players_cached(players, planning_gw, context)
    return _score_compiled_rows(rows, changes, context)


def affordable_package(outs: list[dict[str, Any]], ins: list[dict[str, Any]], itb: int) -> tuple[bool, dict[str, int]]:
    cash_available = int(itb) + sum(int(p.get("sell_cost") or 0) for p in outs)
    incoming_cost = sum(int(p.get("now_cost") or 0) for p in ins)
    return incoming_cost <= cash_available, {
        "cash_available": cash_available,
        "incoming_cost": incoming_cost,
        "resulting_itb": cash_available - incoming_cost,
    }


def simulate_objective(mean: float, std: float, simulations: int, seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    samples = sorted(rng.gauss(mean, max(0.0001, std)) for _ in range(max(20, simulations)))

    def pct(q: float) -> float:
        idx = min(len(samples) - 1, max(0, int(round((len(samples) - 1) * q))))
        return samples[idx]

    return {"p25": round(pct(0.25), 3), "p50": round(pct(0.50), 3), "p75": round(pct(0.75), 3)}
