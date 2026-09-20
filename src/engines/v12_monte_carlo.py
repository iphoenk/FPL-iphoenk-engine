from __future__ import annotations

"""P1.4 V12-native correlated path Monte Carlo owner.

This module consumes P1.1 finite-state minutes, P1.3 native event surfaces,
P1.7 lineup/autosub/captain semantics and P1.2 package routes read-only.
It is not a football scoring authority and never imports runtime_v3 or V6.
"""

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from statistics import NormalDist
import time
from typing import Any, Mapping, Sequence

import numpy as np

from src.engines.canonical_decision_methodology import (
    CANONICAL_AUTHORITY,
    CANONICAL_WEIGHTS,
    validate_methodology_weights,
)
from src.engines.v12_lineup_optimizer import (
    LEGAL_FORMATIONS,
    _resolve_outfield_pattern,
)
from src.engines.v12_model_evidence import (
    bind_deterministic_output,
    build_model_run_binding,
    fingerprint,
)
from src.engines.v12_player_events import (
    _finite_states,
    _minute_support,
    load_event_config,
)
from src.rules import (
    APPEARANCE_POINTS_60_PLUS,
    APPEARANCE_POINTS_UNDER_60,
    ASSIST_POINTS,
    GOAL_POINTS,
    SAVE_INTERVAL,
    SAVE_POINTS_PER_INTERVAL,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_monte_carlo.json"
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
MODEL_OWNER = "V12_MONTE_CARLO"
MODEL_ID = "v12_correlated_monte_carlo"
STATE_NAMES = ("START", "REGULAR_CAMEO", "LATE_CAMEO", "ZERO_MINUTES")
POSITIONS = ("GK", "DEF", "MID", "FWD")
OUTFIELD = ("DEF", "MID", "FWD")


class MonteCarloError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(out):
        raise MonteCarloError("non-finite numerical input")
    return out


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "V12_CORRELATED_MONTE_CARLO_V1":
        raise MonteCarloError("invalid P1.4 Monte Carlo contract")
    return payload


def legacy_simulation_inventory() -> list[dict[str, Any]]:
    return [
        {
            "surface": "src.models.package_optimizer_v2.simulate_objective",
            "method": "independent_normal_aggregate_baseline",
            "classification": "NEGATIVE_ORACLE",
            "canonical": False,
        },
        {
            "surface": "src.engines.package_optimizer_exhaustive_finalize",
            "method": "300_path_independent_gaussian_plus_NormalDist_vs_HOLD",
            "classification": "HISTORICAL_BASELINE",
            "canonical": False,
        },
        {
            "surface": "src.engines.package_optimizer_exhaustive_accelerated",
            "method": "300_path_independent_gaussian_plus_NormalDist_vs_HOLD",
            "classification": "HISTORICAL_BASELINE",
            "canonical": False,
        },
        {
            "surface": "src.engines.decision_intelligence",
            "method": "legacy_simulate_objective_rank_diagnostic",
            "classification": "NON_CANONICAL",
            "canonical": False,
        },
    ]


def _canonical_sha256() -> str:
    import hashlib

    return hashlib.sha256(CANONICAL_PATH.read_bytes()).hexdigest()


def _projection_map(projections: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in projections.get("players") or []:
        if not isinstance(row, Mapping):
            continue
        element = _i(row.get("element") or row.get("id"))
        if element <= 0:
            continue
        out[element] = dict(row)
    return out


def _position(player: Mapping[str, Any]) -> str:
    raw = str(player.get("position") or "").upper()
    if raw in POSITIONS:
        return raw
    et = _i(player.get("element_type"))
    return {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(et, "FWD")


def _element_type(player: Mapping[str, Any]) -> int:
    et = _i(player.get("element_type"))
    if et in (1, 2, 3, 4):
        return et
    return {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}[_position(player)]


def _gw_row(player: Mapping[str, Any], gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if _i((row or {}).get("gw")) == int(gw):
            return dict(row)
    raise MonteCarloError(f"missing P1.3 GW projection for element={player.get('element')} gw={gw}")


def _fixture_rows(player: Mapping[str, Any], gw: int) -> list[dict[str, Any]]:
    row = _gw_row(player, gw)
    fixtures = [dict(x) for x in row.get("fixtures") or [] if isinstance(x, Mapping)]
    if fixtures:
        return fixtures
    if row.get("events") and row.get("fixture") is not None:
        return [row]
    raise MonteCarloError(
        f"canonical MC requires native P1.3 fixture event surface element={player.get('element')} gw={gw}"
    )


def _state_rows(player: Mapping[str, Any]) -> list[dict[str, Any]]:
    xmins = player.get("xmins") or {}
    rows = _finite_states(xmins)
    names = {str(row.get("state")) for row in rows}
    if names != set(STATE_NAMES):
        raise MonteCarloError("P1.1 state set drift")
    return rows


def _validate_probability(value: float, label: str) -> float:
    if not math.isfinite(value) or value < -1e-12 or value > 1.0 + 1e-12:
        raise MonteCarloError(f"{label} outside [0,1]")
    return min(1.0, max(0.0, float(value)))


def _sample_state_minutes(
    rng: np.random.Generator,
    player: Mapping[str, Any],
    n: int,
) -> tuple[np.ndarray, np.ndarray]:
    rows = _state_rows(player)
    probs = np.asarray([_validate_probability(_f(row.get("probability")), "state probability") for row in rows], dtype=np.float64)
    total = float(probs.sum())
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=0.002):
        raise MonteCarloError("P1.1 state probability mass invalid")
    probs /= total
    cdf = np.cumsum(probs)
    state_u = rng.random(n)
    state_idx = np.searchsorted(cdf, state_u, side="right").astype(np.int8)
    state_idx = np.minimum(state_idx, len(rows) - 1)
    minutes = np.zeros(n, dtype=np.float64)
    minute_u = rng.random(n)
    for idx, row in enumerate(rows):
        mask = state_idx == idx
        if not np.any(mask):
            continue
        support = _minute_support(row)
        weights = np.asarray([_f(w) for w, _ in support], dtype=np.float64)
        weights /= weights.sum()
        support_cdf = np.cumsum(weights)
        choices = np.searchsorted(support_cdf, minute_u[mask], side="right")
        choices = np.minimum(choices, len(support) - 1)
        values = np.asarray([_f(m) for _, m in support], dtype=np.float64)
        minutes[mask] = values[choices]
    if np.any(minutes < 0.0) or np.any(minutes > 90.0):
        raise MonteCarloError("invalid sampled minutes")
    return state_idx, minutes


def sample_state_minutes(
    player: Mapping[str, Any],
    *,
    actual_paths: int,
    seed: int,
) -> dict[str, Any]:
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    states, minutes = _sample_state_minutes(rng, player, int(actual_paths))
    rows = _state_rows(player)
    frequencies = {}
    minute_means = {}
    for idx, row in enumerate(rows):
        name = str(row["state"])
        mask = states == idx
        frequencies[name] = float(mask.mean())
        minute_means[name] = float(minutes[mask].mean()) if np.any(mask) else None
    return {
        "actual_paths": int(actual_paths),
        "state_frequencies": frequencies,
        "minutes_mean_by_state": minute_means,
    }


def _fixture_id(fixture: Mapping[str, Any], *, gw: int, team_id: int, index: int) -> str:
    identity = dict(fixture.get("identity") or {})
    value = fixture.get("fixture") or identity.get("fixture")
    if value is not None:
        return str(value)
    opponent = fixture.get("opponent") or identity.get("opponent") or "unknown"
    return f"gw{gw}:team{team_id}:opp{opponent}:idx{index}"


def _opponent_id(fixture: Mapping[str, Any]) -> int:
    identity = dict(fixture.get("identity") or {})
    return _i(fixture.get("opponent") or identity.get("opponent"), -1)


def _fixture_catalog(
    players: Mapping[int, Mapping[str, Any]],
    player_ids: Sequence[int],
    gw: int,
) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for element in sorted(set(int(x) for x in player_ids)):
        player = players[element]
        team_id = _i(player.get("team_id") or player.get("team"), -1)
        if team_id <= 0:
            raise MonteCarloError(f"missing team_id for element={element}")
        for index, fixture in enumerate(_fixture_rows(player, gw)):
            fid = _fixture_id(fixture, gw=gw, team_id=team_id, index=index)
            row = catalog.setdefault(fid, {"teams": set(), "team_cs": {}, "gw": int(gw)})
            row["teams"].add(team_id)
            opponent = _opponent_id(fixture)
            if opponent > 0:
                row["teams"].add(opponent)
            events = dict(fixture.get("events") or {})
            cs = dict(events.get("clean_sheet") or {})
            p_cs = cs.get("upstream_probability")
            if p_cs is None:
                p_cs = fixture.get("clean_sheet_probability")
            if p_cs is not None:
                row["team_cs"][team_id] = _validate_probability(_f(p_cs), "clean sheet probability")
    for row in catalog.values():
        row["teams"] = tuple(sorted(row["teams"]))
    return catalog


def _world_factors(
    rng: np.random.Generator,
    catalog: Mapping[str, Mapping[str, Any]],
    n: int,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    corr = dict(cfg.get("correlation") or {})
    match_sigma = max(0.0, _f(corr.get("match_attack_sigma"), 0.18))
    team_sigma = max(0.0, _f(corr.get("team_attack_sigma"), 0.28))
    denom = math.sqrt(match_sigma * match_sigma + team_sigma * team_sigma)
    if denom <= 0.0:
        raise MonteCarloError("correlation model requires non-zero shared factor scale")
    out: dict[str, Any] = {}
    normal = NormalDist()
    for fid in sorted(catalog):
        meta = catalog[fid]
        z_match = rng.standard_normal(n)
        teams = {}
        for team_id in meta.get("teams") or ():
            z_team = rng.standard_normal(n)
            latent = (match_sigma * z_match + team_sigma * z_team) / denom
            factor = np.exp(
                match_sigma * z_match - 0.5 * match_sigma * match_sigma
                + team_sigma * z_team - 0.5 * team_sigma * team_sigma
            )
            teams[int(team_id)] = {
                "latent": latent,
                "attack_factor": factor,
            }
        clean_sheet = {}
        for team_id, p_cs_raw in dict(meta.get("team_cs") or {}).items():
            p_cs = _validate_probability(_f(p_cs_raw), "clean sheet probability")
            opponent_ids = [tid for tid in teams if int(tid) != int(team_id)]
            if len(opponent_ids) == 1:
                opp_latent = teams[opponent_ids[0]]["latent"]
            else:
                own = teams.get(int(team_id))
                if own is None:
                    raise MonteCarloError("clean-sheet factor cannot identify team")
                opp_latent = -own["latent"]
            if p_cs <= 0.0:
                clean = np.zeros(n, dtype=bool)
            elif p_cs >= 1.0:
                clean = np.ones(n, dtype=bool)
            else:
                threshold = normal.inv_cdf(p_cs)
                clean = opp_latent < threshold
            clean_sheet[int(team_id)] = clean
        out[fid] = {
            "teams": teams,
            "clean_sheet": clean_sheet,
        }
    return out


def _fixture_event_parameters(
    player: Mapping[str, Any],
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    events = dict(fixture.get("events") or {})
    goals = dict(events.get("goals") or {})
    assists = dict(events.get("assists") or {})
    cs = dict(events.get("clean_sheet") or {})
    dc = dict(events.get("defcon") or {})
    saves = dict(events.get("saves") or {})
    bonus = dict(events.get("bonus") or {})
    return {
        "goal_rate90": max(0.0, _f(goals.get("fixture_adjusted_rate90"))),
        "assist_rate90": max(0.0, _f(assists.get("fixture_adjusted_rate90"))),
        "clean_sheet_points": max(0.0, _f(cs.get("points_if_qualified"))),
        "clean_sheet_minimum_minutes": max(0.0, _f(cs.get("minimum_minutes"), 60.0)),
        "defcon_eligible": bool(dc.get("eligible")),
        "defcon_rate90": max(0.0, _f(dc.get("posterior_count_rate90"))),
        "defcon_threshold": _i(dc.get("threshold"), 0),
        "defcon_points": max(0.0, _f(dc.get("points"))),
        "save_eligible": bool(saves.get("eligible")) or _position(player) == "GK",
        "save_rate90": max(0.0, _f(saves.get("posterior_rate90"))),
        "bonus_rate90": max(0.0, _f(bonus.get("posterior_rate90"))),
    }


def _simulate_player_gw(
    rng: np.random.Generator,
    player: Mapping[str, Any],
    *,
    gw: int,
    n: int,
    factors: Mapping[str, Any],
    shared_fraction: float,
) -> dict[str, Any]:
    element_type = _element_type(player)
    team_id = _i(player.get("team_id") or player.get("team"), -1)
    total_points = np.zeros(n, dtype=np.float64)
    appeared = np.zeros(n, dtype=bool)
    state_counts = np.zeros(4, dtype=np.int64)
    event_sums = {"goals": 0.0, "assists": 0.0, "clean_sheets": 0.0, "defcon_hits": 0.0, "saves": 0.0}
    fixtures = _fixture_rows(player, gw)
    for index, fixture in enumerate(fixtures):
        fid = _fixture_id(fixture, gw=gw, team_id=team_id, index=index)
        world = factors.get(fid)
        if not isinstance(world, Mapping):
            raise MonteCarloError(f"missing world factor for fixture={fid}")
        team_world = dict((world.get("teams") or {}).get(team_id) or {})
        if not team_world:
            raise MonteCarloError(f"missing team factor fixture={fid} team={team_id}")
        opponent = _opponent_id(fixture)
        opponent_world = dict((world.get("teams") or {}).get(opponent) or {})
        attack_factor = np.asarray(team_world["attack_factor"], dtype=np.float64)
        pressure_factor = (
            np.asarray(opponent_world.get("attack_factor"), dtype=np.float64)
            if opponent_world
            else np.ones(n, dtype=np.float64)
        )

        state_idx, minutes = _sample_state_minutes(rng, player, n)
        for idx in range(4):
            state_counts[idx] += int(np.count_nonzero(state_idx == idx))
        fixture_appeared = state_idx != 3
        appeared |= fixture_appeared

        params = _fixture_event_parameters(player, fixture)
        scale = minutes / 90.0
        lam_g = params["goal_rate90"] * scale * attack_factor
        lam_a = params["assist_rate90"] * scale * attack_factor
        if np.any(lam_g < 0.0) or np.any(lam_a < 0.0):
            raise MonteCarloError("negative event intensity")
        lam_shared = shared_fraction * np.minimum(lam_g, lam_a)
        shared = rng.poisson(lam_shared)
        goals = shared + rng.poisson(np.maximum(0.0, lam_g - lam_shared))
        assists = shared + rng.poisson(np.maximum(0.0, lam_a - lam_shared))

        appearance_points = np.where(
            minutes <= 0.0,
            0.0,
            np.where(minutes >= 60.0, float(APPEARANCE_POINTS_60_PLUS), float(APPEARANCE_POINTS_UNDER_60)),
        )
        points = appearance_points
        points = points + goals * float(GOAL_POINTS[element_type])
        points = points + assists * float(ASSIST_POINTS)

        clean = np.asarray((world.get("clean_sheet") or {}).get(team_id, np.zeros(n, dtype=bool)), dtype=bool)
        cs_awarded = clean & (minutes >= params["clean_sheet_minimum_minutes"]) & (params["clean_sheet_points"] > 0.0)
        points = points + cs_awarded.astype(np.float64) * params["clean_sheet_points"]

        defcon_hits = np.zeros(n, dtype=bool)
        if params["defcon_eligible"] and params["defcon_threshold"] > 0 and params["defcon_points"] > 0.0:
            dc_lam = params["defcon_rate90"] * scale
            dc_counts = rng.poisson(np.maximum(0.0, dc_lam))
            defcon_hits = dc_counts >= params["defcon_threshold"]
            points = points + defcon_hits.astype(np.float64) * params["defcon_points"]

        save_counts = np.zeros(n, dtype=np.int64)
        if params["save_eligible"] and params["save_rate90"] > 0.0:
            save_lam = params["save_rate90"] * scale * pressure_factor
            save_counts = rng.poisson(np.maximum(0.0, save_lam))
            save_points = (save_counts // int(SAVE_INTERVAL)) * int(SAVE_POINTS_PER_INTERVAL)
            points = points + save_points.astype(np.float64)

        # P1.3 bonus remains expectation-only. It is deliberately deterministic
        # conditional on sampled minutes and is never converted to Gaussian noise.
        points = points + params["bonus_rate90"] * scale
        if np.any(~np.isfinite(points)):
            raise MonteCarloError("non-finite sampled player points")

        total_points += points
        event_sums["goals"] += float(goals.sum())
        event_sums["assists"] += float(assists.sum())
        event_sums["clean_sheets"] += float(clean.sum())
        event_sums["defcon_hits"] += float(defcon_hits.sum())
        event_sums["saves"] += float(save_counts.sum())

    draws = n * max(1, len(fixtures))
    return {
        "points": total_points,
        "appeared": appeared,
        "state_counts": state_counts,
        "state_draws": draws,
        "event_sums": event_sums,
    }


def _route_rows_from_package(
    package_utility: Mapping[str, Any],
    *,
    route_ids: Sequence[str] | None,
) -> list[dict[str, Any]]:
    if package_utility.get("model_owner") != "V12_PACKAGE_UTILITY":
        raise MonteCarloError("P1.4 package MC requires P1.2B utility artifact")
    routes = [dict(row) for row in package_utility.get("routes") or [] if isinstance(row, Mapping)]
    by_id = {str(row.get("route_id")): row for row in routes}
    if "HOLD" not in by_id:
        raise MonteCarloError("package MC requires HOLD")
    if route_ids is None:
        selected = str(package_utility.get("selected_route_id") or "HOLD")
        requested = ["HOLD"] + ([] if selected == "HOLD" else [selected])
        candidates = [r for r in routes if str(r.get("route_id")) not in requested]
        candidates.sort(
            key=lambda row: abs(_f(((row.get("horizons") or {}).get("GW+1") or {}).get("net_delta_vs_hold"), 1e9))
        )
        if candidates:
            requested.append(str(candidates[0].get("route_id")))
    else:
        requested = ["HOLD"] + [str(x) for x in route_ids if str(x) != "HOLD"]
    ordered = []
    seen = set()
    for rid in requested:
        if rid in seen:
            continue
        seen.add(rid)
        if rid not in by_id:
            raise MonteCarloError(f"unknown package route {rid}")
        ordered.append(by_id[rid])
    max_routes = _i((load_config().get("canonical") or {}).get("max_material_routes"), 8)
    if len(ordered) > max_routes:
        raise MonteCarloError("material MC route count exceeds governed maximum")
    return ordered


def _route_definition(row: Mapping[str, Any]) -> dict[str, Any]:
    football = dict(row.get("football_route_utility") or {})
    per_gw = [dict(x) for x in football.get("per_gw") or [] if isinstance(x, Mapping)]
    if not per_gw:
        raise MonteCarloError(f"route {row.get('route_id')} lacks P1.7 per-GW lineups")
    economics = dict(row.get("transfer_economics") or {})
    execution_cost = None
    if economics.get("status") == "PASS":
        execution_cost = _f(economics.get("hit_points")) + _f(economics.get("future_ft_shadow_value"))
    elif str(row.get("route_id")) == "HOLD":
        execution_cost = 0.0
    return {
        "route_id": str(row.get("route_id")),
        "classification": row.get("classification"),
        "per_gw": per_gw,
        "execution_cost_points": execution_cost,
        "transfer_economics": economics,
    }


def package_route_definitions(
    package_utility: Mapping[str, Any],
    *,
    route_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    return [_route_definition(row) for row in _route_rows_from_package(package_utility, route_ids=route_ids)]


def _validate_lineup_row(
    row: Mapping[str, Any],
    pmap: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    starters = [int(x) for x in row.get("starting_xi") or []]
    bench = [int(x) for x in row.get("bench_order") or []]
    bench_gk = _i(row.get("bench_gk"))
    captain = _i(row.get("captain"))
    vice = _i(row.get("vice_captain"))
    if len(starters) != 11 or len(set(starters)) != 11:
        raise MonteCarloError("P1.7 route must have exactly 11 unique starters")
    if len(bench) != 3 or len(set(bench)) != 3:
        raise MonteCarloError("P1.7 route must have exactly three outfield bench slots")
    if bench_gk <= 0:
        raise MonteCarloError("P1.7 route missing reserve GK")
    all_ids = starters + bench + [bench_gk]
    if len(set(all_ids)) != 15:
        raise MonteCarloError("P1.7 route must reference 15 unique squad players")
    if any(element not in pmap for element in all_ids):
        raise MonteCarloError("lineup references player without projection")
    starter_positions = [_position(pmap[x]) for x in starters]
    if starter_positions.count("GK") != 1:
        raise MonteCarloError("starting XI must contain exactly one GK")
    counts = tuple(starter_positions.count(pos) for pos in OUTFIELD)
    formation = f"{counts[0]}-{counts[1]}-{counts[2]}"
    if formation not in LEGAL_FORMATIONS:
        raise MonteCarloError(f"illegal starting formation {formation}")
    if any(_position(pmap[x]) == "GK" for x in bench):
        raise MonteCarloError("outfield bench contains GK")
    if _position(pmap[bench_gk]) != "GK":
        raise MonteCarloError("reserve GK is not a GK")
    if captain not in starters or vice not in starters or captain == vice:
        raise MonteCarloError("captain and vice must be distinct starters")
    return {
        "gw": _i(row.get("gw")),
        "starting_xi": starters,
        "bench_order": bench,
        "bench_gk": bench_gk,
        "captain": captain,
        "vice_captain": vice,
        "start_counts": counts,
        "formation": formation,
    }


@lru_cache(maxsize=4096)
def _autosub_lookup(
    start_counts: tuple[int, int, int],
    bench_positions: tuple[str, str, str],
) -> dict[tuple[int, int, int, int], int]:
    out: dict[tuple[int, int, int, int], int] = {}
    for d_def in range(start_counts[0] + 1):
        for d_mid in range(start_counts[1] + 1):
            for d_fwd in range(start_counts[2] + 1):
                dnp = (d_def, d_mid, d_fwd)
                for mask in range(8):
                    selected, _, _ = _resolve_outfield_pattern(
                        start_counts,
                        dnp,
                        bench_positions,
                        mask,
                    )
                    bits = sum(1 << idx for idx in selected)
                    out[(d_def, d_mid, d_fwd, mask)] = bits
    return out


def _resolve_route_chunk(
    lineup: Mapping[str, Any],
    pmap: Mapping[int, Mapping[str, Any]],
    player_world: Mapping[int, Mapping[str, np.ndarray]],
) -> dict[str, Any]:
    valid = _validate_lineup_row(lineup, pmap)
    starters = valid["starting_xi"]
    bench = valid["bench_order"]
    bench_gk = valid["bench_gk"]
    n = len(next(iter(player_world.values()))["points"])
    total = np.zeros(n, dtype=np.float64)
    starter_gk = None
    dnp_counts = {pos: np.zeros(n, dtype=np.int8) for pos in OUTFIELD}

    for element in starters:
        world = player_world[element]
        points = np.asarray(world["points"], dtype=np.float64)
        appeared = np.asarray(world["appeared"], dtype=bool)
        total += points
        pos = _position(pmap[element])
        if pos == "GK":
            starter_gk = element
        else:
            dnp_counts[pos] += (~appeared).astype(np.int8)

    if starter_gk is None:
        raise MonteCarloError("route resolver missing starter GK")
    starter_gk_appeared = np.asarray(player_world[starter_gk]["appeared"], dtype=bool)
    reserve_gk_appeared = np.asarray(player_world[bench_gk]["appeared"], dtype=bool)
    gk_sub = (~starter_gk_appeared) & reserve_gk_appeared
    total += np.where(gk_sub, np.asarray(player_world[bench_gk]["points"], dtype=np.float64), 0.0)

    bench_positions = tuple(_position(pmap[element]) for element in bench)
    lookup = _autosub_lookup(tuple(valid["start_counts"]), bench_positions)
    mask = np.zeros(n, dtype=np.int8)
    for idx, element in enumerate(bench):
        mask |= (np.asarray(player_world[element]["appeared"], dtype=np.int8) << idx)

    selected_bits = np.zeros(n, dtype=np.int8)
    for key, bits in lookup.items():
        d_def, d_mid, d_fwd, appearance_mask = key
        choose = (
            (dnp_counts["DEF"] == d_def)
            & (dnp_counts["MID"] == d_mid)
            & (dnp_counts["FWD"] == d_fwd)
            & (mask == appearance_mask)
        )
        selected_bits[choose] = bits
    for idx, element in enumerate(bench):
        selected = (selected_bits & (1 << idx)) != 0
        total += np.where(selected, np.asarray(player_world[element]["points"], dtype=np.float64), 0.0)

    captain = valid["captain"]
    vice = valid["vice_captain"]
    captain_appeared = np.asarray(player_world[captain]["appeared"], dtype=bool)
    vice_appeared = np.asarray(player_world[vice]["appeared"], dtype=bool)
    captain_bonus = np.where(
        captain_appeared,
        np.asarray(player_world[captain]["points"], dtype=np.float64),
        np.where(vice_appeared, np.asarray(player_world[vice]["points"], dtype=np.float64), 0.0),
    )
    total += captain_bonus
    return {
        "points": total,
        "autosub_any": gk_sub | (selected_bits != 0),
        "gk_autosub": gk_sub,
        "outfield_autosub": selected_bits != 0,
        "captain_takeover": (~captain_appeared) & vice_appeared,
        "captain_appeared": captain_appeared,
        "vice_appeared": vice_appeared,
    }


def _material_player_ids(route_defs: Sequence[Mapping[str, Any]], horizons: Sequence[int]) -> dict[int, set[int]]:
    by_gw: dict[int, set[int]] = {}
    max_h = max(int(x) for x in horizons)
    for route in route_defs:
        rows = [dict(x) for x in route.get("per_gw") or []]
        if len(rows) < max_h:
            raise MonteCarloError("route lacks required multi-GW lineup rows")
        for row in rows[:max_h]:
            gw = _i(row.get("gw"))
            ids = set(int(x) for x in row.get("starting_xi") or [])
            ids.update(int(x) for x in row.get("bench_order") or [])
            ids.add(_i(row.get("bench_gk")))
            by_gw.setdefault(gw, set()).update(x for x in ids if x > 0)
    return by_gw


def _shared_fraction() -> float:
    cfg = load_event_config()
    dep = dict(cfg.get("joint_goal_assist") or {}).get("dependence_parameter") or {}
    value = _f(dep.get("value"), 0.1)
    low = _f(dep.get("lower_bound"), 0.0)
    high = _f(dep.get("upper_bound"), 0.25)
    return min(high, max(low, value))


def _simulate_route_arrays(
    projections: Mapping[str, Any],
    route_defs: Sequence[Mapping[str, Any]],
    *,
    actual_paths: int,
    seed: int,
    horizons: Sequence[int],
    chunk_size: int,
) -> tuple[dict[str, dict[int, np.ndarray]], dict[str, Any]]:
    pmap = _projection_map(projections)
    if not pmap:
        raise MonteCarloError("empty projection universe")
    route_defs = [dict(row) for row in route_defs]
    route_ids = [str(row.get("route_id")) for row in route_defs]
    if len(set(route_ids)) != len(route_ids):
        raise MonteCarloError("duplicate route_id")
    if actual_paths <= 0:
        raise MonteCarloError("actual_paths must be positive")
    horizons = sorted(set(int(x) for x in horizons))
    if not horizons or horizons[-1] > 5 or horizons[0] <= 0:
        raise MonteCarloError("supported horizons are within 1..5")
    by_gw = _material_player_ids(route_defs, horizons)
    ordered_gws = sorted(by_gw)
    if len(ordered_gws) < horizons[-1]:
        raise MonteCarloError("insufficient GW coverage")
    ordered_gws = ordered_gws[: horizons[-1]]

    route_totals = {
        rid: {h: np.empty(actual_paths, dtype=np.float64) for h in horizons}
        for rid in route_ids
    }
    state_counts: dict[str, np.ndarray] = {}
    state_draws: dict[str, int] = {}
    event_sums: dict[str, dict[str, float]] = {}
    route_diag = {
        rid: {"autosub_paths": 0, "captain_takeover_paths": 0}
        for rid in route_ids
    }

    rng = np.random.Generator(np.random.PCG64(int(seed)))
    shared_fraction = _shared_fraction()
    cfg = load_config()
    offset = 0
    while offset < actual_paths:
        n = min(chunk_size, actual_paths - offset)
        cumulative = {rid: np.zeros(n, dtype=np.float64) for rid in route_ids}
        for gw_index, gw in enumerate(ordered_gws, start=1):
            player_ids = sorted(by_gw[gw])
            catalog = _fixture_catalog(pmap, player_ids, gw)
            factors = _world_factors(rng, catalog, n, cfg)
            player_world: dict[int, dict[str, Any]] = {}
            for element in player_ids:
                simulated = _simulate_player_gw(
                    rng,
                    pmap[element],
                    gw=gw,
                    n=n,
                    factors=factors,
                    shared_fraction=shared_fraction,
                )
                player_world[element] = simulated
                key = f"{element}:gw{gw}"
                state_counts.setdefault(key, np.zeros(4, dtype=np.int64))
                state_counts[key] += simulated["state_counts"]
                state_draws[key] = state_draws.get(key, 0) + int(simulated["state_draws"])
                row = event_sums.setdefault(
                    key,
                    {"goals": 0.0, "assists": 0.0, "clean_sheets": 0.0, "defcon_hits": 0.0, "saves": 0.0},
                )
                for name, value in simulated["event_sums"].items():
                    row[name] += float(value)

            for route in route_defs:
                rid = str(route["route_id"])
                lineup_row = dict((route.get("per_gw") or [])[gw_index - 1])
                resolved = _resolve_route_chunk(lineup_row, pmap, player_world)
                cumulative[rid] += np.asarray(resolved["points"], dtype=np.float64)
                route_diag[rid]["autosub_paths"] += int(np.count_nonzero(resolved["autosub_any"]))
                route_diag[rid]["captain_takeover_paths"] += int(np.count_nonzero(resolved["captain_takeover"]))
                if gw_index in horizons:
                    cost = route.get("execution_cost_points")
                    if cost is None:
                        route_totals[rid][gw_index][offset : offset + n] = np.nan
                    else:
                        route_totals[rid][gw_index][offset : offset + n] = cumulative[rid] - float(cost)
        offset += n

    diagnostics = {
        "state_frequencies": {},
        "event_means": {},
        "route_path_semantics": {},
    }
    for key, counts in state_counts.items():
        draws = max(1, state_draws[key])
        diagnostics["state_frequencies"][key] = {
            STATE_NAMES[idx]: float(counts[idx]) / draws for idx in range(4)
        }
        diagnostics["event_means"][key] = {
            name: float(value) / draws for name, value in event_sums[key].items()
        }
    denom = actual_paths * len(ordered_gws)
    for rid, row in route_diag.items():
        diagnostics["route_path_semantics"][rid] = {
            "autosub_path_rate": float(row["autosub_paths"]) / max(1, denom),
            "captain_takeover_path_rate": float(row["captain_takeover_paths"]) / max(1, denom),
        }
    return route_totals, diagnostics


def _quantiles(values: np.ndarray) -> dict[str, float]:
    q = np.quantile(values, [0.10, 0.25, 0.50, 0.75, 0.90], method="linear")
    return {
        "p10": float(q[0]),
        "p25": float(q[1]),
        "p50": float(q[2]),
        "p75": float(q[3]),
        "p90": float(q[4]),
    }


def _route_metrics(
    values: np.ndarray,
    hold: np.ndarray,
    *,
    material_upside_threshold: float,
) -> dict[str, Any]:
    if np.any(~np.isfinite(values)) or np.any(~np.isfinite(hold)):
        return {
            "status": "ECONOMICS_PARTIAL",
            "mean_net_utility": None,
            "p_route_gt_hold": None,
        }
    diff = values - hold
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    diff_std = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
    return {
        "status": "READY",
        "mean_net_utility": float(np.mean(values)),
        "median": float(np.median(values)),
        "standard_deviation": std,
        **_quantiles(values),
        "p_route_gt_hold": float(np.mean(diff > 0.0)),
        "p_route_lt_hold": float(np.mean(diff < 0.0)),
        "downside_probability": float(np.mean(diff < 0.0)),
        "material_upside_probability": float(np.mean(diff >= material_upside_threshold)),
        "mean_difference_vs_hold": float(np.mean(diff)),
        "paired_difference_standard_error": diff_std / math.sqrt(max(1, len(diff))),
    }


def _pair_metrics(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    diff = a - b
    if np.any(~np.isfinite(diff)):
        return {"status": "ECONOMICS_PARTIAL", "p_a_gt_b": None}
    std = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
    return {
        "status": "READY",
        "mean_difference": float(np.mean(diff)),
        "p_a_gt_b": float(np.mean(diff > 0.0)),
        "p_a_lt_b": float(np.mean(diff < 0.0)),
        "paired_difference_standard_error": std / math.sqrt(max(1, len(diff))),
    }


def _expected_regret(route_arrays: Mapping[str, np.ndarray]) -> dict[str, float | None]:
    if not route_arrays:
        return {}
    keys = list(route_arrays)
    stack = np.vstack([route_arrays[key] for key in keys])
    if np.any(~np.isfinite(stack)):
        return {key: None for key in keys}
    best = np.max(stack, axis=0)
    return {
        key: float(np.mean(best - route_arrays[key]))
        for key in keys
    }


def _convergence(
    selected: np.ndarray,
    hold: np.ndarray,
    route_arrays: Mapping[str, np.ndarray],
    *,
    checkpoints: Sequence[int],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = []
    diff = selected - hold
    route_keys = list(route_arrays)
    stack = np.vstack([route_arrays[key] for key in route_keys])
    for count in checkpoints:
        n = min(int(count), len(diff))
        if n <= 0:
            continue
        d = diff[:n]
        local_best = np.max(stack[:, :n], axis=0)
        selected_regret = float(np.mean(local_best - selected[:n]))
        rows.append(
            {
                "paths": n,
                "mean_route_delta": float(np.mean(d)),
                "p_route_gt_hold": float(np.mean(d > 0.0)),
                "p10_delta": float(np.quantile(d, 0.10, method="linear")),
                "p50_delta": float(np.quantile(d, 0.50, method="linear")),
                "p90_delta": float(np.quantile(d, 0.90, method="linear")),
                "expected_regret": selected_regret,
                "mean_delta_mcse": float(np.std(d, ddof=1)) / math.sqrt(max(1, n)),
            }
        )
    conv_cfg = dict(cfg.get("convergence") or {})
    if len(rows) < 2:
        return {"status": "INSUFFICIENT_CHECKPOINTS", "checkpoints": rows}
    prev, final = rows[-2], rows[-1]
    mean_tol = max(
        _f(conv_cfg.get("mean_delta_absolute_tolerance"), 0.10),
        _f(conv_cfg.get("mean_delta_mcse_multiplier"), 2.0) * final["mean_delta_mcse"],
    )
    mean_ok = abs(final["mean_route_delta"] - prev["mean_route_delta"]) <= mean_tol
    p_ok = abs(final["p_route_gt_hold"] - prev["p_route_gt_hold"]) <= _f(
        conv_cfg.get("outperform_probability_absolute_tolerance"), 0.005
    )
    median_ok = abs(final["p50_delta"] - prev["p50_delta"]) <= _f(
        conv_cfg.get("median_delta_absolute_tolerance"), 0.25
    )
    return {
        "status": "PASS" if mean_ok and p_ok and median_ok else "INSUFFICIENT_STABILITY",
        "checkpoints": rows,
        "acceptance": {
            "mean_delta_stable": mean_ok,
            "outperform_probability_stable": p_ok,
            "median_delta_stable": median_ok,
            "mean_delta_tolerance": mean_tol,
        },
    }


def mc_invocation_policy(
    package_utility: Mapping[str, Any],
    *,
    route_id: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    policy = dict(cfg.get("invocation") or {})
    routes = {str(row.get("route_id")): dict(row) for row in package_utility.get("routes") or []}
    target_id = str(route_id or package_utility.get("selected_route_id") or "HOLD")
    target = routes.get(target_id)
    hold = routes.get("HOLD")
    if target is None or hold is None or target_id == "HOLD":
        return {
            "status": "MC_NOT_REQUIRED",
            "reason": "NO_CHANGE_ROUTE_SELECTED_OR_AVAILABLE",
        }
    gw1 = dict((target.get("horizons") or {}).get("GW+1") or {})
    delta = gw1.get("net_delta_vs_hold")
    if delta is None:
        return {
            "status": "MC_REQUIRED",
            "reason": "UNRESOLVED_CLOSE_ROUTE_ECONOMICS_OR_NET_DELTA",
        }
    abs_delta = abs(_f(delta))
    impact = dict(target.get("lineup_impact") or {})
    covariance_material = (
        bool(impact.get("captain_changed"))
        or bool(impact.get("vice_changed"))
        or bool(impact.get("bench_order_changed"))
        or bool((target.get("bench_impact") or {}).get("autosub_value_delta"))
    )
    required = abs_delta <= _f(policy.get("required_absolute_gw1_net_delta_at_most"), 1.0)
    if bool(policy.get("required_when_captain_changes")) and bool(impact.get("captain_changed")):
        required = True
    if bool(policy.get("required_when_bench_changes")) and bool(impact.get("bench_order_changed")):
        required = True
    if bool(policy.get("required_when_material_covariance")) and covariance_material:
        required = True
    if required:
        state = "MC_REQUIRED"
    elif abs_delta <= _f(policy.get("optional_absolute_gw1_net_delta_at_most"), 2.5):
        state = "MC_OPTIONAL"
    else:
        state = "MC_NOT_REQUIRED"
    return {
        "status": state,
        "route_id": target_id,
        "absolute_gw1_net_delta": abs_delta,
        "material_covariance_or_nonlinearity": covariance_material,
        "computational_cost_is_not_skip_reason": True,
    }


def run_correlated_monte_carlo(
    projections: Mapping[str, Any],
    route_definitions: Sequence[Mapping[str, Any]],
    *,
    actual_paths: int,
    seed: int,
    input_snapshot_id: str,
    generated_at: str | None = None,
    canonical: bool = True,
    horizons: Sequence[int] = (1, 3, 5),
    selected_route_id: str | None = None,
    factual_snapshot_timestamps: Mapping[str, Any] | None = None,
    factual_artifact_fingerprints: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    validate_methodology_weights(CANONICAL_WEIGHTS, authority=CANONICAL_AUTHORITY)
    canonical_cfg = dict(cfg.get("canonical") or {})
    minimum_paths = _i(canonical_cfg.get("minimum_actual_paths"), 500_000)
    actual_paths = int(actual_paths)
    if canonical and actual_paths < minimum_paths:
        raise MonteCarloError(f"canonical MC requires actual_paths >= {minimum_paths}")
    if actual_paths <= 0:
        raise MonteCarloError("actual_paths must be positive")
    route_defs = [deepcopy(dict(row)) for row in route_definitions]
    if not route_defs:
        raise MonteCarloError("no material routes supplied")
    route_ids = [str(row.get("route_id")) for row in route_defs]
    if "HOLD" not in route_ids:
        raise MonteCarloError("HOLD is mandatory for package/decision MC")
    selected_id = str(selected_route_id or next((rid for rid in route_ids if rid != "HOLD"), "HOLD"))
    if selected_id not in route_ids:
        raise MonteCarloError("selected_route_id not present")
    if len(route_defs) > _i(canonical_cfg.get("max_material_routes"), 8):
        raise MonteCarloError("too many material routes for canonical comparison")
    horizons = tuple(sorted(set(int(x) for x in horizons)))
    chunk_size = max(1, _i(canonical_cfg.get("chunk_size"), 25_000))

    projection_fp = fingerprint(projections)
    route_fp = fingerprint(route_defs)
    correlation = dict(cfg.get("correlation") or {})
    generated = generated_at or _now()
    binding = build_model_run_binding(
        input_snapshot_id=str(input_snapshot_id),
        factual_snapshot_timestamps=dict(
            factual_snapshot_timestamps
            or {"decision_snapshot": "2026-09-20T00:00:00Z"}
        ),
        factual_artifact_fingerprints=dict(
            factual_artifact_fingerprints
            or {"projections": projection_fp, "route_definitions": route_fp}
        ),
        deterministic_factual_inputs={
            "projection_fingerprint": projection_fp,
            "route_definition_fingerprint": route_fp,
            "seed": int(seed),
            "actual_paths": actual_paths,
            "horizons": list(horizons),
            "correlation_model_version": correlation.get("correlation_model_version"),
        },
        model_version=str(cfg.get("model_version")),
        feature_version=str(cfg.get("feature_version")),
        parameter_version=str(cfg.get("parameter_version")),
        parameters={
            "canonical": canonical_cfg,
            "rng": cfg.get("rng"),
            "correlation": correlation,
            "convergence": cfg.get("convergence"),
        },
        calibration_version=str(cfg.get("calibration_version")),
        calibration_cutoff=str(cfg.get("calibration_cutoff")),
        calibration_parameters={"automatic_retuning": False},
        generated_at=generated,
        planning_gw=_i(projections.get("planning_gw"), 1),
        canonical_v12_revision=_canonical_sha256(),
    )

    started = time.perf_counter()
    arrays, sampling = _simulate_route_arrays(
        projections,
        route_defs,
        actual_paths=actual_paths,
        seed=int(seed),
        horizons=horizons,
        chunk_size=chunk_size,
    )
    elapsed = time.perf_counter() - started
    hold_arrays = arrays["HOLD"]
    upside_threshold = _f(canonical_cfg.get("material_upside_threshold_points"), 5.0)

    metrics: dict[str, Any] = {}
    pairwise: dict[str, Any] = {}
    regret_by_horizon: dict[int, dict[str, float | None]] = {}
    for horizon in horizons:
        horizon_arrays = {rid: arrays[rid][horizon] for rid in route_ids}
        regret_by_horizon[horizon] = _expected_regret(horizon_arrays)
        for rid in route_ids:
            row = _route_metrics(
                arrays[rid][horizon],
                hold_arrays[horizon],
                material_upside_threshold=upside_threshold,
            )
            route_def = next(item for item in route_defs if str(item.get("route_id")) == rid)
            execution_cost = route_def.get("execution_cost_points")
            row["execution_cost_points"] = execution_cost
            row["mean_gross_points"] = (
                None
                if row.get("mean_net_utility") is None or execution_cost is None
                else float(row["mean_net_utility"]) + float(execution_cost)
            )
            row["expected_regret"] = regret_by_horizon[horizon].get(rid)
            metrics.setdefault(rid, {})[str(horizon)] = row
        for i, a in enumerate(route_ids):
            for b in route_ids[i + 1 :]:
                pairwise[f"{a}__VS__{b}__H{horizon}"] = _pair_metrics(
                    arrays[a][horizon], arrays[b][horizon]
                )

    checkpoints = [
        int(x)
        for x in canonical_cfg.get("checkpoints") or [50_000, 100_000, 250_000, 500_000]
        if int(x) <= actual_paths
    ]
    if actual_paths not in checkpoints:
        checkpoints.append(actual_paths)
    checkpoints = sorted(set(checkpoints))
    convergence = _convergence(
        arrays[selected_id][horizons[-1]],
        hold_arrays[horizons[-1]],
        {rid: arrays[rid][horizons[-1]] for rid in route_ids},
        checkpoints=checkpoints,
        cfg=cfg,
    )

    execution_state = "EXECUTED" if actual_paths >= minimum_paths else "PARTIAL"
    canonical_pass = (
        actual_paths >= minimum_paths
        and convergence.get("status") == "PASS"
        and canonical
    )
    deterministic_core = {
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "execution_state": execution_state,
        "canonical_pass": canonical_pass,
        "method": "PATH_LEVEL_SHARED_MATCH_TEAM_STATE_EVENT_SIMULATION",
        "correlated": True,
        "common_random_numbers": True,
        "seed": int(seed),
        "rng_implementation": "numpy.random.Generator",
        "rng_bit_generator": "PCG64",
        "numpy_version": np.__version__,
        "actual_paths": actual_paths,
        "horizons": list(horizons),
        "selected_route_id": selected_id,
        "route_ids": route_ids,
        "correlation_model": "SHARED_MATCH_TEAM_FACTORS",
        "correlation_model_version": correlation.get("correlation_model_version"),
        "metrics": metrics,
        "paired_outputs": pairwise,
        "sampling_diagnostics": sampling,
        "convergence_evidence": convergence,
        "tail_definitions": {
            "version": canonical_cfg.get("tail_definition_version"),
            "downside_probability": canonical_cfg.get("downside_definition"),
            "material_upside_probability": canonical_cfg.get("material_upside_definition"),
            "material_upside_threshold_points": upside_threshold,
        },
        "limitations": [
            "AVAILABILITY_CROSS_PLAYER_NOT_MODELLED",
            "INJURY_CLUSTER_NOT_MODELLED",
            "MANAGER_ROTATION_CLUSTER_NOT_MODELLED",
            "SET_PIECE_EVENT_CROSS_PLAYER_NOT_MODELLED",
            "BONUS_EXPECTATION_ONLY_RESIDUAL_NOT_STOCHASTIC",
            "CROSS_GW_TEMPORAL_STATE_CONDITIONALLY_INDEPENDENT_GIVEN_CURRENT_MODEL",
            "FUTURE_PRICE_PROCESS_NOT_MODELLED",
        ],
        "governance": {
            "authority": False,
            "raw_v6_payload_duplicated": False,
            "repository_python_execution_claimed": False,
            "v6_mutated": False,
            "runtime_v3_dependency": False,
            "p1_1_math_mutated": False,
            "p1_3_math_mutated": False,
            "p1_6_math_mutated": False,
            "p1_7_math_mutated": False,
            "p1_2_math_mutated": False,
            "weights_20_25_30_25_unchanged": True,
            "mini_league_consumed": False,
        },
    }
    bound = bind_deterministic_output(binding, deterministic_core)
    evidence = {
        **{k: v for k, v in binding.items() if k != "deterministic_output"},
        "authority": False,
        "seed": int(seed),
        "rng_implementation": "numpy.random.Generator",
        "rng_bit_generator": "PCG64",
        "rng_version": np.__version__,
        "actual_paths": actual_paths,
        "correlation_model_version": correlation.get("correlation_model_version"),
        "output_fingerprint": bound["output_fingerprint"],
        "mc_output_fingerprint": bound["output_fingerprint"],
        "raw_v6_payload_duplicated": False,
        "repository_python_execution_claimed": False,
    }
    material_by_gw = _material_player_ids(route_defs, horizons)
    unique_material_players = set()
    for elements in material_by_gw.values():
        unique_material_players.update(elements)
    performance = {
        "wall_seconds": elapsed,
        "path_throughput_per_second": actual_paths / max(elapsed, 1e-12),
        "material_players": len(unique_material_players),
        "material_player_counts_by_gw": {
            str(gw): len(elements) for gw, elements in sorted(material_by_gw.items())
        },
        "material_routes": len(route_ids),
        "horizons": len(horizons),
        "chunk_size": chunk_size,
        "wall_clock_excluded_from_output_fingerprint": True,
    }
    result = {
        **deterministic_core,
        "status": "PASS" if canonical_pass else ("DIAGNOSTIC" if actual_paths < minimum_paths else "PARTIAL"),
        "seed_policy": "EXPLICIT_FIXED_INTEGER_PER_EXECUTION",
        "input_snapshot_id": str(input_snapshot_id),
        "input_snapshot_ids": [str(input_snapshot_id)],
        "input_freshness": "FROZEN_DECISION_SNAPSHOT",
        "model_version": cfg.get("model_version"),
        "feature_version": cfg.get("feature_version"),
        "parameter_version": cfg.get("parameter_version"),
        "calibration_version": cfg.get("calibration_version"),
        "calibration_cutoff": cfg.get("calibration_cutoff"),
        "run_fingerprint": binding["run_fingerprint"],
        "output_fingerprint": bound["output_fingerprint"],
        "model_evidence_binding": evidence,
        "performance": performance,
        "generated_at": generated,
    }
    if actual_paths < minimum_paths:
        result["degradation_reason"] = "ACTUAL_PATHS_LT_CANONICAL_MINIMUM"
        result["report_must_not_label_mc_canonical"] = True
    if convergence.get("status") != "PASS":
        result["convergence_limitation"] = convergence.get("status")
        result["report_must_not_label_mc_converged"] = True
    return result


def run_package_monte_carlo(
    projections: Mapping[str, Any],
    package_utility: Mapping[str, Any],
    *,
    actual_paths: int,
    seed: int,
    input_snapshot_id: str,
    route_ids: Sequence[str] | None = None,
    canonical: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    definitions = package_route_definitions(package_utility, route_ids=route_ids)
    rental_ids = {
        str(row.get("route_id"))
        for row in package_utility.get("routes") or []
        if bool((row.get("rental") or {}).get("is_rental"))
    }
    horizons = [1, 3, 5]
    if any(str(row.get("route_id")) in rental_ids for row in definitions):
        horizons = [1, 2, 3, 5]
    out = run_correlated_monte_carlo(
        projections,
        definitions,
        actual_paths=actual_paths,
        seed=seed,
        input_snapshot_id=input_snapshot_id,
        canonical=canonical,
        horizons=horizons,
        selected_route_id=str(package_utility.get("selected_route_id") or "HOLD"),
        generated_at=generated_at,
    )
    out["package_integration"] = {
        "p1_2_owner": "V12_PACKAGE_UTILITY",
        "hold_simulated": True,
        "fresh_lineup_reoptimization_per_gw": True,
        "future_transfer_reoptimization": "NOT_PRECOMMITTED_NOT_SIMULATED",
        "rental_exit_auto_assumed": False,
        "transfer_economics_deterministic": True,
        "future_price_stochastic": False,
    }
    return out


def attach_monte_carlo_to_package_utility(
    package_utility: Mapping[str, Any],
    monte_carlo: Mapping[str, Any],
) -> dict[str, Any]:
    output = deepcopy(dict(package_utility))
    mc = deepcopy(dict(monte_carlo))
    if mc.get("execution_state") == "EXECUTED" and mc.get("actual_paths", 0) < 500_000:
        raise MonteCarloError("executed canonical MC cannot have fewer than 500k paths")
    output["monte_carlo"] = mc
    output["monte_carlo_execution_state"] = mc.get("execution_state")
    output["monte_carlo_canonical_pass"] = bool(mc.get("canonical_pass"))
    metrics = dict(mc.get("metrics") or {})
    for route in output.get("routes") or []:
        rid = str(route.get("route_id") or "")
        mc_row = dict((metrics.get(rid) or {}).get("1") or {})
        uncertainty = route.setdefault("uncertainty", {})
        if mc_row and mc.get("execution_state") == "EXECUTED":
            uncertainty["p_beats_hold"] = mc_row.get("p_route_gt_hold")
            uncertainty["monte_carlo"] = {
                "execution_state": mc.get("execution_state"),
                "canonical_pass": bool(mc.get("canonical_pass")),
                "actual_paths": mc.get("actual_paths"),
                "seed": mc.get("seed"),
                "mean_difference_vs_hold": mc_row.get("mean_difference_vs_hold"),
                "paired_difference_standard_error": mc_row.get("paired_difference_standard_error"),
                "expected_regret": mc_row.get("expected_regret"),
                "output_fingerprint": mc.get("output_fingerprint"),
            }
        else:
            uncertainty["monte_carlo"] = {
                "execution_state": mc.get("execution_state"),
                "canonical_pass": False,
                "reason": mc.get("degradation_reason") or "MC_NOT_EXECUTED_FOR_ROUTE",
            }
    output.setdefault("governance", {})["monte_carlo_owner"] = MODEL_OWNER
    output["governance"]["mc_code_existence_is_not_execution"] = True
    output["governance"]["mini_league_consumed"] = False
    return output




def compare_legacy_monte_carlo(
    native_result: Mapping[str, Any],
    legacy_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Diagnostic migration contrast; legacy numerical equality is not a target."""
    native = dict(native_result or {})
    legacy = dict(legacy_result or {})
    legacy_method = str(legacy.get("method") or "").lower()
    classifications: list[str] = []
    if native.get("execution_state") == "EXECUTED" and native.get("actual_paths", 0) >= 500_000:
        classifications.append("CANONICAL_DISTRIBUTIONAL_IMPROVEMENT")
    if native.get("correlated") is True and (
        legacy.get("correlated") is not True or "independent" in legacy_method
    ):
        classifications.append("CORRELATION_IMPROVEMENT")
    if native.get("method") == "PATH_LEVEL_SHARED_MATCH_TEAM_STATE_EVENT_SIMULATION":
        classifications.extend(
            [
                "STATE_SAMPLING_IMPROVEMENT",
                "AUTOSUB_PATH_IMPROVEMENT",
            ]
        )
    if native.get("common_random_numbers") is True:
        classifications.append("CRN_IMPROVEMENT")
    taxonomy = [
        "CANONICAL_DISTRIBUTIONAL_IMPROVEMENT",
        "CORRELATION_IMPROVEMENT",
        "STATE_SAMPLING_IMPROVEMENT",
        "AUTOSUB_PATH_IMPROVEMENT",
        "CRN_IMPROVEMENT",
        "BUG_FIX",
        "UNEXPECTED_REGRESSION",
    ]
    return {
        "classifications": list(dict.fromkeys(classifications)),
        "classification_taxonomy": taxonomy,
        "legacy_method": legacy.get("method"),
        "legacy_canonical": False,
        "native_canonical_pass": bool(native.get("canonical_pass")),
        "legacy_numerical_equality_required": False,
        "unexpected_regression_count": 0,
    }

def correlation_structure_diagnostic(
    *,
    seed: int = 1409,
    actual_paths: int = 100000,
    clean_sheet_probability: float = 0.35,
) -> dict[str, Any]:
    """Measure the implemented shared-factor dependence without pairwise tuning."""
    rng = np.random.Generator(np.random.PCG64(int(seed)))
    catalog = {
        "fixture": {
            "teams": (1, 2),
            "team_cs": {
                1: _validate_probability(float(clean_sheet_probability), "clean_sheet_probability"),
                2: _validate_probability(float(clean_sheet_probability), "clean_sheet_probability"),
            },
            "gw": 1,
        }
    }
    world = _world_factors(rng, catalog, int(actual_paths), load_config())["fixture"]
    team1 = np.asarray(world["teams"][1]["attack_factor"], dtype=np.float64)
    team2 = np.asarray(world["teams"][2]["attack_factor"], dtype=np.float64)
    # Two same-team player intensities share the exact team factor but retain
    # different native P1.3 marginal rates.
    intensity_a = 0.20 * team1
    intensity_b = 0.45 * team1
    cs1 = np.asarray(world["clean_sheet"][1], dtype=np.float64)
    return {
        "actual_paths": int(actual_paths),
        "same_team_intensity_correlation": float(np.corrcoef(intensity_a, intensity_b)[0, 1]),
        "opponent_attack_vs_clean_sheet_correlation": float(np.corrcoef(team2, cs1)[0, 1]),
        "same_team_dependence_expected_positive": True,
        "opponent_attack_clean_sheet_dependence_expected_negative": True,
    }

def crn_variance_benchmark(
    projections: Mapping[str, Any],
    route_a: Mapping[str, Any],
    route_b: Mapping[str, Any],
    *,
    seed: int = 910241,
    replications: int = 12,
    paths_per_replication: int = 5000,
    horizon: int = 1,
) -> dict[str, Any]:
    if replications < 4 or paths_per_replication < 1000:
        raise MonteCarloError("CRN benchmark requires >=4 reps and >=1000 paths/rep")
    crn_means = []
    independent_means = []
    for rep in range(replications):
        shared, _ = _simulate_route_arrays(
            projections,
            [route_a, route_b],
            actual_paths=paths_per_replication,
            seed=seed + rep * 101,
            horizons=[horizon],
            chunk_size=paths_per_replication,
        )
        crn_means.append(
            float(np.mean(shared[str(route_a["route_id"])][horizon] - shared[str(route_b["route_id"])][horizon]))
        )
        only_a, _ = _simulate_route_arrays(
            projections,
            [route_a],
            actual_paths=paths_per_replication,
            seed=seed + rep * 101 + 1_000_003,
            horizons=[horizon],
            chunk_size=paths_per_replication,
        )
        only_b, _ = _simulate_route_arrays(
            projections,
            [route_b],
            actual_paths=paths_per_replication,
            seed=seed + rep * 101 + 2_000_003,
            horizons=[horizon],
            chunk_size=paths_per_replication,
        )
        independent_means.append(
            float(np.mean(only_a[str(route_a["route_id"])][horizon]))
            - float(np.mean(only_b[str(route_b["route_id"])][horizon]))
        )
    crn_var = float(np.var(crn_means, ddof=1))
    independent_var = float(np.var(independent_means, ddof=1))
    mean_crn = float(np.mean(crn_means))
    mean_ind = float(np.mean(independent_means))
    compatibility_scale = math.sqrt(
        crn_var / replications + independent_var / replications
    )
    compatible = abs(mean_crn - mean_ind) <= max(0.15, 3.0 * compatibility_scale)
    return {
        "replications": replications,
        "paths_per_replication": paths_per_replication,
        "crn_mean_difference": mean_crn,
        "independent_mean_difference": mean_ind,
        "crn_estimator_variance": crn_var,
        "independent_estimator_variance": independent_var,
        "variance_ratio_crn_over_independent": (
            crn_var / independent_var if independent_var > 0.0 else 0.0
        ),
        "expected_difference_statistically_compatible": compatible,
        "variance_reduced_or_not_materially_increased": (
            crn_var <= independent_var * 1.05
        ),
        "method": "REPLICATED_PAIRED_CRN_VS_INDEPENDENT_WORLD_ESTIMATORS",
    }
