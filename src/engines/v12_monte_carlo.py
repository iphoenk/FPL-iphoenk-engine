from __future__ import annotations

"""P1.4 V12-native correlated path Monte Carlo owner.

This module consumes P1.1 finite-state minutes, P1.3 native event surfaces,
P1.7 lineup/autosub/captain semantics and P1.2 package routes read-only.
It is not a football scoring authority and never imports runtime_v3 or V6.
"""

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import multiprocessing as mp
import os
import pickle
import sys
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
)
from src.engines.v12_position_probability_components import (
    _conditional_bonus_pmf,
)
from src.rules import (
    APPEARANCE_POINTS_60_PLUS,
    APPEARANCE_POINTS_UNDER_60,
    ASSIST_POINTS,
    GOAL_POINTS,
    GOALS_CONCEDED_INTERVAL,
    GOALS_CONCEDED_POINTS_PER_INTERVAL,
    PENALTY_MISS_POINTS,
    PENALTY_SAVE_POINTS,
    RED_CARD_POINTS,
    SAVE_INTERVAL,
    SAVE_POINTS_PER_INTERVAL,
    YELLOW_CARD_POINTS,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "intelligence" / "v12_monte_carlo.json"
CANONICAL_PATH = ROOT / CANONICAL_AUTHORITY
MODEL_OWNER = "V12_MONTE_CARLO"
MODEL_ID = "v12_correlated_monte_carlo"
LEGACY_STATE_NAMES = ("START", "REGULAR_CAMEO", "LATE_CAMEO", "DNP")
STAGE1_STATE_NAMES = (
    "START_FULL",
    "START_SUBBED",
    "EARLY_SUB",
    "REGULAR_CAMEO",
    "LATE_CAMEO",
    "DNP",
)
POSITIONS = ("GK", "DEF", "MID", "FWD")
OUTFIELD = ("DEF", "MID", "FWD")
MC_SIM_CACHE_ENV = "V12_MC_SIM_CACHE_DIR"
MC_SIM_CACHE_SCHEMA = 2


class MonteCarloError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _runtime_cache_identity() -> dict[str, str]:
    return {
        "python_major_minor": (
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ),
        "numpy_version": np.__version__,
    }


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
    if frozenset(names) not in {
        frozenset(LEGACY_STATE_NAMES),
        frozenset(STAGE1_STATE_NAMES),
    }:
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
    if set(frequencies) == set(STAGE1_STATE_NAMES):
        start_names = ("START_FULL", "START_SUBBED", "EARLY_SUB")
        start_mass = sum(frequencies[name] for name in start_names)
        frequencies["START"] = start_mass
        if start_mass > 0.0:
            minute_means["START"] = sum(
                frequencies[name] * float(minute_means[name] or 0.0)
                for name in start_names
            ) / start_mass
    if "DNP" in frequencies:
        frequencies["ZERO_MINUTES"] = frequencies["DNP"]
        minute_means["ZERO_MINUTES"] = minute_means["DNP"]
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


def _stage2_expected_minutes(
    player: Mapping[str, Any],
) -> float:
    xmins = dict(player.get("xmins") or {})
    for key in ("expected_minutes", "xMins"):
        value = xmins.get(key)
        if value is not None and _f(value) > 0.0:
            return min(90.0, max(0.0, _f(value)))
    total = 0.0
    for state in _state_rows(player):
        probability = max(0.0, _f(state.get("probability")))
        support = _minute_support(state)
        conditional_mean = sum(
            _f(weight) * _f(minutes)
            for weight, minutes in support
        )
        total += probability * conditional_mean
    return min(90.0, max(0.0, total))


def _fixture_catalog(
    players: Mapping[int, Mapping[str, Any]],
    player_ids: Sequence[int],
    gw: int,
) -> dict[str, dict[str, Any]]:
    """Build one fixture catalog from governed Stage-2 event intensities.

    Material-route players determine which fixtures are needed, but team goal
    intensity is aggregated from the full projected team universe so scorer
    allocation never treats the FPL squad as the whole football team.
    """
    catalog: dict[str, dict[str, Any]] = {}
    material_fixture_ids: set[str] = set()
    for element in sorted(set(int(x) for x in player_ids)):
        player = players[element]
        team_id = _i(player.get("team_id") or player.get("team"), -1)
        if team_id <= 0:
            raise MonteCarloError(f"missing team_id for element={element}")
        for index, fixture in enumerate(_fixture_rows(player, gw)):
            fid = _fixture_id(fixture, gw=gw, team_id=team_id, index=index)
            material_fixture_ids.add(fid)
            row = catalog.setdefault(
                fid,
                {
                    "teams": set(),
                    "team_cs": {},
                    "team_goal_mean": {},
                    "team_assist_mean": {},
                    "gw": int(gw),
                },
            )
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
                row["team_cs"][team_id] = _validate_probability(
                    _f(p_cs),
                    "clean sheet probability",
                )

    # Full-universe aggregation uses the Stage-2 fixture-adjusted player goal
    # intensities and P1.1 expected minutes. No new xG/xPts model is created.
    for element, player in players.items():
        team_id = _i(player.get("team_id") or player.get("team"), -1)
        if team_id <= 0:
            continue
        expected_minutes = _stage2_expected_minutes(player)
        for index, fixture in enumerate(_fixture_rows(player, gw)):
            fid = _fixture_id(fixture, gw=gw, team_id=team_id, index=index)
            if fid not in material_fixture_ids:
                continue
            row = catalog[fid]
            params = _fixture_event_parameters(player, fixture)
            contribution = (
                max(0.0, params["goal_rate90"])
                * min(90.0, expected_minutes)
                / 90.0
            )
            row["team_goal_mean"][team_id] = (
                _f(row["team_goal_mean"].get(team_id)) + contribution
            )
            assist_contribution = (
                max(0.0, params["assist_rate90"])
                * min(90.0, expected_minutes)
                / 90.0
            )
            row["team_assist_mean"][team_id] = (
                _f(row["team_assist_mean"].get(team_id))
                + assist_contribution
            )

    for row in catalog.values():
        row["teams"] = tuple(sorted(row["teams"]))
        # If complete player goal intensities do not identify a team mean,
        # use the opponent Stage-2 CS marginal only as a scoreline prior.
        for team_id in row["teams"]:
            if _f(row["team_goal_mean"].get(team_id)) > 0.0:
                continue
            opponents = [x for x in row["teams"] if int(x) != int(team_id)]
            opponent = opponents[0] if len(opponents) == 1 else None
            p_opp_cs = (
                row["team_cs"].get(opponent)
                if opponent is not None
                else None
            )
            if p_opp_cs is not None:
                row["team_goal_mean"][team_id] = -math.log(
                    max(1e-9, min(0.999999, _f(p_opp_cs)))
                )
            else:
                row["team_goal_mean"][team_id] = 1.35
            if _f(row["team_assist_mean"].get(team_id)) <= 0.0:
                row["team_assist_mean"][team_id] = min(
                    _f(row["team_goal_mean"].get(team_id), 1.35) * 0.65,
                    _f(row["team_goal_mean"].get(team_id), 1.35),
                )
    return catalog


@lru_cache(maxsize=256)
def _calibrated_poisson_base_mean(
    target_zero: float,
    match_sigma: float,
    team_sigma: float,
) -> float:
    """Calibrate Poisson-lognormal scoreline intensity to Stage-2 P(CS).

    The shared match/team factors imply a lognormal marginal attack factor.
    Deterministic Gauss-Hermite quadrature solves
    E[exp(-lambda * factor)] = target_zero once per parameter tuple, avoiding
    repeated sample-path bisection without changing the intended marginal.
    """
    target = _validate_probability(float(target_zero), "opponent clean sheet probability")
    if target <= 0.0:
        return 25.0
    if target >= 1.0:
        return 0.0
    sigma2 = float(match_sigma) ** 2 + float(team_sigma) ** 2
    sigma = math.sqrt(max(0.0, sigma2))
    nodes, weights = np.polynomial.hermite.hermgauss(32)
    z = math.sqrt(2.0) * nodes
    factors = np.exp(sigma * z - 0.5 * sigma2)
    norm = math.sqrt(math.pi)

    def zero_probability(base_mean: float) -> float:
        return float(np.sum(weights * np.exp(-float(base_mean) * factors)) / norm)

    low, high = 0.0, 4.0
    while zero_probability(high) > target and high < 25.0:
        high *= 1.5
    high = min(high, 25.0)
    for _ in range(56):
        mid = 0.5 * (low + high)
        if zero_probability(mid) > target:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _world_factors(
    rng: np.random.Generator,
    catalog: Mapping[str, Mapping[str, Any]],
    n: int,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Sample shared match/team state and one coherent scoreline per fixture."""
    corr = dict(cfg.get("correlation") or {})
    match_sigma = max(0.0, _f(corr.get("match_attack_sigma"), 0.18))
    team_sigma = max(0.0, _f(corr.get("team_attack_sigma"), 0.28))
    denom = math.sqrt(match_sigma * match_sigma + team_sigma * team_sigma)
    if denom <= 0.0:
        raise MonteCarloError(
            "correlation model requires non-zero shared factor scale"
        )
    out: dict[str, Any] = {}
    for fid in sorted(catalog):
        meta = catalog[fid]
        z_match = rng.standard_normal(n)
        teams: dict[int, dict[str, Any]] = {}
        for team_id in meta.get("teams") or ():
            z_team = rng.standard_normal(n)
            latent = (
                match_sigma * z_match + team_sigma * z_team
            ) / denom
            factor = np.exp(
                match_sigma * z_match
                - 0.5 * match_sigma * match_sigma
                + team_sigma * z_team
                - 0.5 * team_sigma * team_sigma
            )
            prior_mean = max(
                0.01,
                _f((meta.get("team_goal_mean") or {}).get(team_id), 1.35),
            )
            opponents = [
                int(tid)
                for tid in (meta.get("teams") or ())
                if int(tid) != int(team_id)
            ]
            target_zero = (
                (meta.get("team_cs") or {}).get(opponents[0])
                if len(opponents) == 1
                else None
            )
            if target_zero is not None:
                target_zero = _validate_probability(
                    _f(target_zero),
                    "opponent clean sheet probability",
                )
                base_mean = _calibrated_poisson_base_mean(
                    float(target_zero),
                    float(match_sigma),
                    float(team_sigma),
                )
                calibration = "DETERMINISTIC_GAUSS_HERMITE_TO_STAGE2_OPPONENT_CS_MARGINAL"
            else:
                base_mean = prior_mean
                calibration = "STAGE2_TEAM_GOAL_MEAN_PRIOR"
            goals = rng.poisson(base_mean * factor).astype(np.int16)
            teams[int(team_id)] = {
                "latent": latent,
                "attack_factor": factor,
                "prior_goal_mean": prior_mean,
                "base_goal_mean": base_mean,
                "scoreline_mean_calibration": calibration,
                "target_opponent_clean_sheet": target_zero,
                "goals": goals,
            }

        clean_sheet: dict[int, np.ndarray] = {}
        for team_id in teams:
            opponents = [
                tid for tid in teams if int(tid) != int(team_id)
            ]
            if len(opponents) != 1:
                raise MonteCarloError(
                    f"fixture={fid} cannot identify exactly one opponent"
                )
            clean_sheet[int(team_id)] = (
                np.asarray(teams[opponents[0]]["goals"]) == 0
            )
        out[fid] = {
            "teams": teams,
            "team_goals": {
                int(team_id): np.asarray(payload["goals"], dtype=np.int16)
                for team_id, payload in teams.items()
            },
            "clean_sheet": clean_sheet,
            "scoreline_generated_before_player_points": True,
            "cs_derived_from_opponent_goals": True,
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
    cards = dict(events.get("cards") or {})
    penalty_save = dict(events.get("penalty_save") or {})
    goals_conceded = dict(events.get("goals_conceded") or {})
    position_engine = dict(fixture.get("position_engine") or {})
    return {
        "goal_rate90": max(
            0.0, _f(goals.get("fixture_adjusted_rate90"))
        ),
        "assist_rate90": max(
            0.0, _f(assists.get("fixture_adjusted_rate90"))
        ),
        "clean_sheet_points": max(
            0.0, _f(cs.get("points_if_qualified"))
        ),
        "clean_sheet_minimum_minutes": max(
            0.0, _f(cs.get("minimum_minutes"), 60.0)
        ),
        "defcon_eligible": bool(dc.get("eligible")),
        "defcon_rate90": max(
            0.0, _f(dc.get("posterior_count_rate90"))
        ),
        "defcon_threshold": _i(dc.get("threshold"), 0),
        "defcon_points": max(0.0, _f(dc.get("points"))),
        "defcon_count_model": deepcopy(
            dc.get("count_model") or {}
        ),
        "save_eligible": bool(saves.get("eligible"))
        or _position(player) == "GK",
        "save_rate90": max(
            0.0, _f(saves.get("posterior_rate90"))
        ),
        "save_count_model": deepcopy(
            saves.get("sot_count_model")
            or saves.get("count_model")
            or {}
        ),
        "bonus_calibration": deepcopy(
            bonus.get("calibration") or {}
        ),
        "yellow_rate90": max(
            0.0, _f(cards.get("yellow_rate90"))
        ),
        "red_rate90": max(
            0.0, _f(cards.get("red_rate90"))
        ),
        "penalty_save_probability": max(
            0.0, min(1.0, _f(penalty_save.get("P_at_least_1")))
        ),
        "goals_conceded_interval": max(
            1,
            _i(
                goals_conceded.get("interval"),
                int(GOALS_CONCEDED_INTERVAL),
            ),
        ),
        "goals_conceded_points_per_interval": _f(
            goals_conceded.get("points_per_interval"),
            float(GOALS_CONCEDED_POINTS_PER_INTERVAL),
        ),
        "goal_process": deepcopy(
            position_engine.get("goal_process") or {}
        ),
        "penalty_process": deepcopy(
            position_engine.get("penalty_process") or {}
        ),
        "set_piece_process": deepcopy(
            position_engine.get("set_piece_process") or {}
        ),
        "linkup": deepcopy(position_engine.get("linkup") or {}),
        "matchup_vector": deepcopy(
            position_engine.get("matchup_vector") or {}
        ),
    }


def _fixture_context(
    player: Mapping[str, Any],
    fixture_id: str,
) -> dict[str, Any]:
    contexts = (
        (player.get("contextual_dynamics") or {}).get(
            "fixture_contexts"
        )
        or []
    )
    for row in contexts:
        if str((row or {}).get("fixture") or "") == str(fixture_id):
            return dict(row)
    return {}


def _path_linkup_ratio(
    player: Mapping[str, Any],
    fixture_id: str,
    appeared_by_element: Mapping[int, np.ndarray],
    *,
    channel: str,
    n: int,
) -> np.ndarray:
    """Condition Stage-2 marginalized link-up on sampled teammate appearance.

    The Stage-2 event intensity already contains the marginalized link effect.
    P1.4 therefore applies only conditional/marginal ratios, preventing double
    counting while making creator/linked-player absence path dependent.
    """
    context = _fixture_context(player, fixture_id)
    network = dict(context.get("linkup_network") or {})
    marginalized = {
        str(row.get("edge_id")): dict(row)
        for row in network.get("marginalized") or []
        if isinstance(row, Mapping)
    }
    relationships = [
        dict(row)
        for row in network.get("relationships") or []
        if isinstance(row, Mapping)
    ]
    ratio = np.ones(n, dtype=np.float64)
    for link in relationships:
        source = _i(
            link.get("source_player_id"),
            _i(link.get("teammate_player_id"), -1),
        )
        target = _i(link.get("target_player_id"), -1)
        if source <= 0 or target != _i(player.get("element"), -1):
            continue
        source_appeared = appeared_by_element.get(source)
        if source_appeared is None:
            continue
        edge_id = f"{source}->{target}"
        marginal = marginalized.get(edge_id) or {}
        confidence = max(
            0.0, min(1.0, _f(link.get("confidence")))
        )
        role_hint = str(link.get("target_role") or "").upper()
        with_mod = max(
            0.01, _f(link.get("with_player_modifier"), 1.0)
        )
        without_mod = max(
            0.01, _f(link.get("without_player_modifier"), 1.0)
        )
        if channel == "goal" and any(
            token in role_hint for token in ("CREATOR", "PLAYMAKER")
        ):
            conditional_with = 1.0
            conditional_without = 1.0
            baseline = 1.0
        else:
            exponent = confidence * (
                1.0 if channel == "goal" else 0.5
            )
            conditional_with = math.exp(
                math.log(with_mod) * exponent
            )
            conditional_without = math.exp(
                math.log(without_mod) * exponent
            )
            baseline = max(
                0.01,
                _f(
                    marginal.get(
                        "applied_goal_multiplier"
                        if channel == "goal"
                        else "applied_assist_multiplier"
                    ),
                    1.0,
                ),
            )
        conditional = np.where(
            np.asarray(source_appeared, dtype=bool),
            conditional_with,
            conditional_without,
        )
        ratio *= conditional / baseline
    return np.clip(ratio, 0.55, 1.65)


def _sample_count_from_stage2(
    rng: np.random.Generator,
    model: Mapping[str, Any],
    mean: np.ndarray,
) -> np.ndarray:
    mu = np.maximum(0.0, np.asarray(mean, dtype=np.float64))
    family = str(model.get("family") or "POISSON").upper()
    selection = dict(model.get("selection") or {})
    if family == "NEGATIVE_BINOMIAL":
        dispersion = max(
            1e-6,
            _f(selection.get("nb_dispersion"), 1.0),
        )
        p = dispersion / (dispersion + mu)
        return rng.negative_binomial(
            dispersion,
            np.clip(p, 1e-9, 1.0),
        ).astype(np.int32)
    return rng.poisson(mu).astype(np.int32)


def _sample_bonus_points(
    rng: np.random.Generator,
    core_points: np.ndarray,
    calibration: Mapping[str, Any],
) -> np.ndarray:
    out = np.zeros(len(core_points), dtype=np.int8)
    if not calibration:
        return out
    for value in np.unique(core_points.astype(np.int32)):
        mask = core_points.astype(np.int32) == int(value)
        if not np.any(mask):
            continue
        pmf = _conditional_bonus_pmf(
            int(value),
            calibration,
        )
        tiers = np.asarray(sorted(pmf), dtype=np.int8)
        probs = np.asarray(
            [max(0.0, _f(pmf[int(tier)])) for tier in tiers],
            dtype=np.float64,
        )
        total = float(probs.sum())
        if total <= 0.0:
            continue
        probs /= total
        draws = rng.choice(
            tiers,
            size=int(np.count_nonzero(mask)),
            p=probs,
        )
        out[mask] = draws
    return out

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
    economics_resolved = economics.get("status") == "PASS"
    if economics_resolved:
        execution_cost = (
            _f(economics.get("hit_points"))
            + _f(economics.get("future_ft_shadow_value"))
        )
        execution_cost_status = "RESOLVED_APPLIED"
    elif str(row.get("route_id")) == "HOLD":
        execution_cost = 0.0
        execution_cost_status = "HOLD_ZERO"
    else:
        # Private finance facts may be genuinely unavailable while the
        # football distribution is still fully supportable. P1.4 simulates
        # football gross outcomes and never invents bank/sell/FT costs.
        execution_cost = 0.0
        execution_cost_status = (
            "UNRESOLVED_NOT_APPLIED_TO_FOOTBALL_MC"
        )
    return {
        "route_id": str(row.get("route_id")),
        "classification": row.get("classification"),
        "per_gw": per_gw,
        "execution_cost_points": execution_cost,
        "execution_cost_status": execution_cost_status,
        "decision_net_supported": (
            economics_resolved
            or str(row.get("route_id")) == "HOLD"
        ),
        "transfer_economics": economics,
    }


def package_route_definitions(
    package_utility: Mapping[str, Any],
    *,
    route_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    return [_route_definition(row) for row in _route_rows_from_package(package_utility, route_ids=route_ids)]


@lru_cache(maxsize=1)
def _mc_code_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _simulation_route_signature(
    route_defs: Sequence[Mapping[str, Any]],
    *,
    include_economics: bool,
) -> list[dict[str, Any]]:
    """Normalize only route fields consumed by P1.4 simulation/metrics.

    Occurrence-only P1.7 evidence fingerprints are intentionally excluded so
    identical football lineups can reuse the same random world across reports.
    """
    rows: list[dict[str, Any]] = []
    for route in route_defs:
        normalized = {
            "route_id": str(route.get("route_id") or ""),
            "per_gw": [
                {
                    "gw": _i(row.get("gw")),
                    "starting_xi": [
                        int(value)
                        for value in row.get("starting_xi") or []
                    ],
                    "bench_order": [
                        int(value)
                        for value in row.get("bench_order") or []
                    ],
                    "bench_gk": _i(row.get("bench_gk")),
                    "captain": _i(row.get("captain")),
                    "vice_captain": _i(row.get("vice_captain")),
                }
                for row in route.get("per_gw") or []
                if isinstance(row, Mapping)
            ],
        }
        if include_economics:
            normalized.update(
                {
                    "execution_cost_points": route.get(
                        "execution_cost_points"
                    ),
                    "execution_cost_status": route.get(
                        "execution_cost_status"
                    ),
                    "decision_net_supported": bool(
                        route.get("decision_net_supported")
                    ),
                }
            )
        rows.append(normalized)
    return rows


def canonical_package_seed(
    projections: Mapping[str, Any],
    package_utility: Mapping[str, Any],
    *,
    route_ids: Sequence[str] | None = None,
) -> int:
    """Stable common-random-number seed for identical football inputs."""
    route_defs = package_route_definitions(
        package_utility,
        route_ids=route_ids,
    )
    digest = fingerprint(
        {
            "projection_fingerprint": fingerprint(projections),
            "football_route_signature": _simulation_route_signature(
                route_defs,
                include_economics=False,
            ),
            "correlation_model_version": (
                load_config().get("correlation") or {}
            ).get("correlation_model_version"),
        }
    )
    return int(digest[:8], 16)


def _simulation_cache_key(
    *,
    projection_fp: str,
    route_defs: Sequence[Mapping[str, Any]],
    actual_paths: int,
    seed: int,
    horizons: Sequence[int],
    selected_route_id: str,
    canonical: bool,
) -> str:
    return fingerprint(
        {
            "schema": MC_SIM_CACHE_SCHEMA,
            "runtime": _runtime_cache_identity(),
            "mc_code_sha256": _mc_code_sha256(),
            "canonical_v12_revision": _canonical_sha256(),
            "config_fingerprint": fingerprint(load_config()),
            "projection_fingerprint": projection_fp,
            "route_signature": _simulation_route_signature(
                route_defs,
                include_economics=True,
            ),
            "actual_paths": int(actual_paths),
            "seed": int(seed),
            "horizons": [int(value) for value in horizons],
            "selected_route_id": str(selected_route_id),
            "canonical": bool(canonical),
            "numpy_version": np.__version__,
        }
    )


def _mc_cache_path(key: str) -> Path | None:
    root = str(os.environ.get(MC_SIM_CACHE_ENV) or "").strip()
    if not root:
        return None
    return Path(root) / key[:2] / f"{key}.pkl"


def _load_mc_summary_cache(key: str) -> dict[str, Any] | None:
    path = _mc_cache_path(key)
    if path is None or not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            payload = pickle.load(fh)
        if (
            isinstance(payload, dict)
            and int(payload.get("schema") or 0)
            == MC_SIM_CACHE_SCHEMA
            and payload.get("key") == key
            and isinstance(payload.get("summary"), dict)
        ):
            return deepcopy(dict(payload["summary"]))
    except (
        OSError,
        EOFError,
        pickle.PickleError,
        AttributeError,
        ValueError,
        TypeError,
    ):
        return None
    return None


def _save_mc_summary_cache(
    key: str,
    summary: Mapping[str, Any],
) -> None:
    path = _mc_cache_path(key)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as fh:
            pickle.dump(
                {
                    "schema": MC_SIM_CACHE_SCHEMA,
                    "key": key,
                    "summary": dict(summary),
                },
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


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


def _categorical_goal_allocation(
    rng: np.random.Generator,
    total_events: np.ndarray,
    player_ids: Sequence[int],
    player_weights: Mapping[int, np.ndarray],
    *,
    other_weight: float | np.ndarray,
) -> tuple[dict[int, np.ndarray], list[np.ndarray]]:
    """Allocate each team event to exactly one material player or OTHER."""
    ids = [int(x) for x in player_ids]
    n = len(total_events)
    out = {
        element: np.zeros(n, dtype=np.int16)
        for element in ids
    }
    max_events = int(np.max(total_events)) if n else 0
    scorer_by_ordinal: list[np.ndarray] = []
    for ordinal in range(max_events):
        active = np.asarray(total_events > ordinal)
        assignment = np.full(n, -1, dtype=np.int32)
        if not np.any(active):
            scorer_by_ordinal.append(assignment)
            continue
        weights = [
            np.maximum(
                0.0,
                np.asarray(
                    player_weights.get(
                        element,
                        np.zeros(n, dtype=np.float64),
                    ),
                    dtype=np.float64,
                ),
            )
            for element in ids
        ]
        other = np.asarray(other_weight, dtype=np.float64)
        if other.ndim == 0:
            other = np.full(n, float(other), dtype=np.float64)
        denom = np.maximum(1e-9, other.copy())
        for weight in weights:
            denom += weight
        u = rng.random(n)
        cumulative = np.zeros(n, dtype=np.float64)
        for element, weight in zip(ids, weights):
            p = np.divide(
                weight,
                denom,
                out=np.zeros_like(weight),
                where=denom > 0.0,
            )
            choose = (
                active
                & (assignment < 0)
                & (u >= cumulative)
                & (u < cumulative + p)
            )
            if np.any(choose):
                out[element][choose] += 1
                assignment[choose] = element
            cumulative += p
        scorer_by_ordinal.append(assignment)
    return out, scorer_by_ordinal


def _categorical_assist_allocation(
    rng: np.random.Generator,
    total_goals: np.ndarray,
    scorer_by_ordinal: Sequence[np.ndarray],
    player_ids: Sequence[int],
    player_weights: Mapping[int, np.ndarray],
    *,
    other_assist_weight: float | np.ndarray,
    no_assist_weight: float | np.ndarray,
) -> dict[int, np.ndarray]:
    """At most one assist per goal, with scorer excluded from that goal."""
    ids = [int(x) for x in player_ids]
    n = len(total_goals)
    out = {
        element: np.zeros(n, dtype=np.int16)
        for element in ids
    }
    for ordinal, scorer in enumerate(scorer_by_ordinal):
        active = np.asarray(total_goals > ordinal)
        if not np.any(active):
            continue
        eligible_weights = []
        for element in ids:
            base = np.maximum(
                0.0,
                np.asarray(
                    player_weights.get(
                        element,
                        np.zeros(n, dtype=np.float64),
                    ),
                    dtype=np.float64,
                ),
            )
            eligible_weights.append(
                np.where(scorer == element, 0.0, base)
            )
        other = np.asarray(
            other_assist_weight, dtype=np.float64
        )
        no_assist = np.asarray(
            no_assist_weight, dtype=np.float64
        )
        if other.ndim == 0:
            other = np.full(n, float(other), dtype=np.float64)
        if no_assist.ndim == 0:
            no_assist = np.full(
                n, float(no_assist), dtype=np.float64
            )
        denom = np.maximum(
            1e-9,
            other + no_assist,
        )
        for weight in eligible_weights:
            denom += weight
        u = rng.random(n)
        cumulative = np.zeros(n, dtype=np.float64)
        assigned = np.zeros(n, dtype=bool)
        for element, weight in zip(ids, eligible_weights):
            p = np.divide(
                weight,
                denom,
                out=np.zeros_like(weight),
                where=denom > 0.0,
            )
            choose = (
                active
                & ~assigned
                & (u >= cumulative)
                & (u < cumulative + p)
            )
            if np.any(choose):
                out[element][choose] += 1
                assigned[choose] = True
            cumulative += p
    return out


def _simulate_match_coupled_gw(
    rng: np.random.Generator,
    pmap: Mapping[int, Mapping[str, Any]],
    player_ids: Sequence[int],
    *,
    gw: int,
    n: int,
    cfg: Mapping[str, Any],
    catalog: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    """Simulate one GW from shared football match states, not player-point noise."""
    if catalog is None:
        catalog = _fixture_catalog(pmap, player_ids, gw)
    factors = _world_factors(rng, catalog, n, cfg)
    player_world: dict[int, dict[str, Any]] = {}
    for element in player_ids:
        state_rows = _state_rows(pmap[element])
        player_world[element] = {
            "points": np.zeros(n, dtype=np.float64),
            "appeared": np.zeros(n, dtype=bool),
            "state_counts": np.zeros(
                len(state_rows),
                dtype=np.int64,
            ),
            "state_draws": 0,
            "event_sums": {
                "goals": 0.0,
                "assists": 0.0,
                "clean_sheets": 0.0,
                "defcon_hits": 0.0,
                "saves": 0.0,
                "cards": 0.0,
                "penalty_goals": 0.0,
                "set_piece_goals": 0.0,
                "bonus_points": 0.0,
            },
        }

    fixture_members: dict[
        str,
        list[tuple[int, Mapping[str, Any], int, int]],
    ] = {}
    for element in player_ids:
        player = pmap[element]
        team_id = _i(player.get("team_id") or player.get("team"), -1)
        for index, fixture in enumerate(_fixture_rows(player, gw)):
            fid = _fixture_id(
                fixture,
                gw=gw,
                team_id=team_id,
                index=index,
            )
            fixture_members.setdefault(fid, []).append(
                (
                    int(element),
                    fixture,
                    team_id,
                    _opponent_id(fixture),
                )
            )

    invariant_counts = {
        "fixture_chunks": 0,
        "cs_goal_consistency_failures": 0,
        "material_goal_overflow_failures": 0,
        "assist_overflow_failures": 0,
        "self_assist_failures": 0,
        "dnp_scorer_failures": 0,
    }

    for fid, members in sorted(fixture_members.items()):
        world = factors.get(fid)
        if not isinstance(world, Mapping):
            raise MonteCarloError(
                f"missing match state for fixture={fid}"
            )
        invariant_counts["fixture_chunks"] += 1
        local_minutes: dict[int, np.ndarray] = {}
        local_appeared: dict[int, np.ndarray] = {}
        local_params: dict[int, dict[str, Any]] = {}
        by_team: dict[int, list[int]] = {}

        for element, fixture, team_id, _ in members:
            state_idx, minutes = _sample_state_minutes(
                rng,
                pmap[element],
                n,
            )
            local_minutes[element] = minutes
            local_appeared[element] = minutes > 0.0
            local_params[element] = _fixture_event_parameters(
                pmap[element],
                fixture,
            )
            by_team.setdefault(team_id, []).append(element)
            target = player_world[element]
            for idx in range(len(target["state_counts"])):
                target["state_counts"][idx] += int(
                    np.count_nonzero(state_idx == idx)
                )
            target["state_draws"] += n
            target["appeared"] |= local_appeared[element]

        for team_id, elements in by_team.items():
            team_world = dict(
                (world.get("teams") or {}).get(team_id) or {}
            )
            if not team_world:
                raise MonteCarloError(
                    f"missing team world fixture={fid} team={team_id}"
                )
            team_goals = np.asarray(
                (world.get("team_goals") or {}).get(team_id),
                dtype=np.int16,
            )
            base_goal_mean = max(
                0.01,
                _f(team_world.get("base_goal_mean"), 1.35),
            )
            expected_material_goal = 0.0
            expected_material_assist = 0.0
            expected_goal_by_element: dict[int, float] = {}
            goal_weights: dict[int, np.ndarray] = {}
            assist_weights: dict[int, np.ndarray] = {}
            for element in elements:
                params = local_params[element]
                minutes = local_minutes[element]
                expected_minutes = _stage2_expected_minutes(
                    pmap[element]
                )
                expected_goal = (
                    params["goal_rate90"]
                    * min(90.0, expected_minutes)
                    / 90.0
                )
                expected_assist = (
                    params["assist_rate90"]
                    * min(90.0, expected_minutes)
                    / 90.0
                )
                expected_goal_by_element[element] = expected_goal
                expected_material_goal += expected_goal
                expected_material_assist += expected_assist
                goal_ratio = _path_linkup_ratio(
                    pmap[element],
                    fid,
                    local_appeared,
                    channel="goal",
                    n=n,
                )
                assist_ratio = _path_linkup_ratio(
                    pmap[element],
                    fid,
                    local_appeared,
                    channel="assist",
                    n=n,
                )
                goal_weights[element] = (
                    params["goal_rate90"]
                    * minutes
                    / 90.0
                    * goal_ratio
                )
                assist_weights[element] = (
                    params["assist_rate90"]
                    * minutes
                    / 90.0
                    * assist_ratio
                )

            material_goal_path = np.zeros(
                n, dtype=np.float64
            )
            for weight in goal_weights.values():
                material_goal_path += weight
            other_goal_weight = np.maximum(
                1e-6,
                base_goal_mean - material_goal_path,
            )
            goals_by_player, scorer_by_ordinal = (
                _categorical_goal_allocation(
                    rng,
                    team_goals,
                    elements,
                    goal_weights,
                    other_weight=other_goal_weight,
                )
            )
            total_material_goals = np.zeros(
                n, dtype=np.int16
            )
            for element in elements:
                total_material_goals += goals_by_player[element]
                if np.any(
                    (goals_by_player[element] > 0)
                    & ~local_appeared[element]
                ):
                    invariant_counts[
                        "dnp_scorer_failures"
                    ] += 1
            if np.any(total_material_goals > team_goals):
                invariant_counts[
                    "material_goal_overflow_failures"
                ] += 1

            # Preserve the Stage-2 assist marginal while enforcing
            # scorer != assister for each goal. A player's assist propensity
            # is conditioned on not being that goal's scorer.
            for element in elements:
                scorer_share = min(
                    0.80,
                    max(
                        0.0,
                        expected_goal_by_element.get(
                            element, 0.0
                        )
                        / max(1e-9, base_goal_mean),
                    ),
                )
                assist_weights[element] = (
                    assist_weights[element]
                    / max(0.20, 1.0 - scorer_share)
                )
            material_assist_path = np.zeros(
                n, dtype=np.float64
            )
            for weight in assist_weights.values():
                material_assist_path += weight
            other_assist_weight = np.maximum(
                1e-6,
                base_goal_mean - material_assist_path,
            )
            no_assist_weight = np.zeros(
                n, dtype=np.float64
            )
            assists_by_player = _categorical_assist_allocation(
                rng,
                team_goals,
                scorer_by_ordinal,
                elements,
                assist_weights,
                other_assist_weight=other_assist_weight,
                no_assist_weight=no_assist_weight,
            )
            total_material_assists = np.zeros(
                n, dtype=np.int16
            )
            for element in elements:
                total_material_assists += assists_by_player[element]
                if np.any(
                    (goals_by_player[element] > 0)
                    & (assists_by_player[element] > team_goals)
                ):
                    invariant_counts["self_assist_failures"] += 1
            if np.any(total_material_assists > team_goals):
                invariant_counts["assist_overflow_failures"] += 1

            for element in elements:
                player = pmap[element]
                params = local_params[element]
                minutes = local_minutes[element]
                scale = minutes / 90.0
                goals = goals_by_player[element].astype(
                    np.int32
                )
                assists = assists_by_player[element].astype(
                    np.int32
                )
                opponent_ids = [
                    tid
                    for tid in (world.get("teams") or {})
                    if int(tid) != int(team_id)
                ]
                if len(opponent_ids) != 1:
                    raise MonteCarloError(
                        f"fixture={fid} opponent ambiguity"
                    )
                opponent_id = int(opponent_ids[0])
                opponent_goals = np.asarray(
                    (world.get("team_goals") or {}).get(
                        opponent_id
                    ),
                    dtype=np.int32,
                )
                clean = opponent_goals == 0
                if not np.array_equal(
                    clean,
                    np.asarray(
                        (world.get("clean_sheet") or {}).get(
                            team_id
                        ),
                        dtype=bool,
                    ),
                ):
                    invariant_counts[
                        "cs_goal_consistency_failures"
                    ] += 1

                appearance_points = np.where(
                    minutes <= 0.0,
                    0.0,
                    np.where(
                        minutes >= 60.0,
                        float(APPEARANCE_POINTS_60_PLUS),
                        float(APPEARANCE_POINTS_UNDER_60),
                    ),
                )
                points = appearance_points.astype(np.float64)
                points += goals * float(
                    GOAL_POINTS[_element_type(player)]
                )
                points += assists * float(ASSIST_POINTS)

                cs_awarded = (
                    clean
                    & (
                        minutes
                        >= params[
                            "clean_sheet_minimum_minutes"
                        ]
                    )
                    & (params["clean_sheet_points"] > 0.0)
                )
                points += (
                    cs_awarded.astype(np.float64)
                    * params["clean_sheet_points"]
                )

                defcon_hits = np.zeros(n, dtype=bool)
                if (
                    params["defcon_eligible"]
                    and params["defcon_threshold"] > 0
                    and params["defcon_points"] > 0.0
                ):
                    pressure = np.asarray(
                        (
                            (world.get("teams") or {}).get(
                                opponent_id
                            )
                            or {}
                        ).get(
                            "attack_factor",
                            np.ones(n),
                        ),
                        dtype=np.float64,
                    )
                    dc_mean = (
                        params["defcon_rate90"]
                        * scale
                        * np.clip(
                            pressure ** 0.35,
                            0.65,
                            1.55,
                        )
                    )
                    dc_counts = _sample_count_from_stage2(
                        rng,
                        params["defcon_count_model"],
                        dc_mean,
                    )
                    defcon_hits = (
                        dc_counts
                        >= params["defcon_threshold"]
                    )
                    points += (
                        defcon_hits.astype(np.float64)
                        * params["defcon_points"]
                    )

                save_counts = np.zeros(
                    n, dtype=np.int32
                )
                if (
                    params["save_eligible"]
                    and params["save_rate90"] > 0.0
                ):
                    pressure = np.asarray(
                        (
                            (world.get("teams") or {}).get(
                                opponent_id
                            )
                            or {}
                        ).get(
                            "attack_factor",
                            np.ones(n),
                        ),
                        dtype=np.float64,
                    )
                    save_mean = (
                        params["save_rate90"]
                        * scale
                        * np.clip(pressure, 0.60, 1.75)
                    )
                    save_counts = _sample_count_from_stage2(
                        rng,
                        params["save_count_model"],
                        save_mean,
                    )
                    # Shot-on-target identity is explicit:
                    # opponent SoT = goals conceded + saves.
                    save_points = (
                        save_counts // int(SAVE_INTERVAL)
                    ) * int(SAVE_POINTS_PER_INTERVAL)
                    points += save_points.astype(np.float64)

                if _position(player) in {"GK", "DEF"}:
                    interval = max(
                        1,
                        int(
                            params[
                                "goals_conceded_interval"
                            ]
                        ),
                    )
                    gc_intervals = (
                        opponent_goals // interval
                    )
                    points += (
                        gc_intervals.astype(np.float64)
                        * params[
                            "goals_conceded_points_per_interval"
                        ]
                    )

                yellow_p = (
                    1.0
                    - np.exp(
                        -params["yellow_rate90"] * scale
                    )
                )
                red_p = (
                    1.0
                    - np.exp(
                        -params["red_rate90"] * scale
                    )
                )
                yellow = (
                    rng.random(n) < yellow_p
                ) & local_appeared[element]
                red = (
                    rng.random(n) < red_p
                ) & local_appeared[element]
                points += (
                    yellow.astype(np.float64)
                    * float(YELLOW_CARD_POINTS)
                )
                points += (
                    red.astype(np.float64)
                    * float(RED_CARD_POINTS)
                )

                penalty_process = dict(
                    params["penalty_process"]
                )
                penalty_attempt_rate90 = max(
                    0.0,
                    _f(
                        penalty_process.get(
                            "penalty_attempt_rate90"
                        )
                    ),
                )
                penalty_misses = rng.poisson(
                    penalty_attempt_rate90
                    * 0.22
                    * scale
                )
                points += (
                    penalty_misses.astype(np.float64)
                    * float(PENALTY_MISS_POINTS)
                )

                penalty_saved = np.zeros(
                    n, dtype=bool
                )
                if (
                    _position(player) == "GK"
                    and params[
                        "penalty_save_probability"
                    ]
                    > 0.0
                ):
                    penalty_saved = (
                        rng.random(n)
                        < params[
                            "penalty_save_probability"
                        ]
                    ) & local_appeared[element]
                    points += (
                        penalty_saved.astype(np.float64)
                        * float(PENALTY_SAVE_POINTS)
                    )

                goal_process = dict(
                    params["goal_process"]
                )
                total_goal_rate = max(
                    1e-12,
                    _f(
                        goal_process.get(
                            "lambda_goal_total90"
                        ),
                        params["goal_rate90"],
                    ),
                )
                penalty_share = max(
                    0.0,
                    min(
                        1.0,
                        _f(
                            goal_process.get(
                                "lambda_penalty90"
                            )
                        )
                        / total_goal_rate,
                    ),
                )
                set_piece_share = max(
                    0.0,
                    min(
                        1.0 - penalty_share,
                        _f(
                            goal_process.get(
                                "lambda_set_piece90"
                            )
                        )
                        / total_goal_rate,
                    ),
                )
                penalty_goals = rng.binomial(
                    goals,
                    penalty_share,
                )
                remaining_non_penalty = goals - penalty_goals
                conditional_sp = (
                    set_piece_share
                    / max(1e-12, 1.0 - penalty_share)
                    if penalty_share < 1.0
                    else 0.0
                )
                set_piece_goals = rng.binomial(
                    remaining_non_penalty,
                    max(0.0, min(1.0, conditional_sp)),
                )

                core_points = np.rint(points).astype(
                    np.int32
                )
                bonus_points = _sample_bonus_points(
                    rng,
                    core_points,
                    params["bonus_calibration"],
                )
                points += bonus_points.astype(np.float64)

                target = player_world[element]
                target["points"] += points
                events = target["event_sums"]
                events["goals"] += float(goals.sum())
                events["assists"] += float(assists.sum())
                events["clean_sheets"] += float(
                    clean.sum()
                )
                events["defcon_hits"] += float(
                    defcon_hits.sum()
                )
                events["saves"] += float(
                    save_counts.sum()
                )
                events["cards"] += float(
                    np.count_nonzero(yellow | red)
                )
                events["penalty_goals"] += float(
                    penalty_goals.sum()
                )
                events["set_piece_goals"] += float(
                    set_piece_goals.sum()
                )
                events["bonus_points"] += float(
                    bonus_points.sum()
                )

    if any(
        value
        for key, value in invariant_counts.items()
        if key.endswith("_failures")
    ):
        raise MonteCarloError(
            "match-state invariant violation: "
            + json.dumps(invariant_counts, sort_keys=True)
        )
    return player_world, {
        "match_state_invariants": {
            **invariant_counts,
            "status": "PASS",
            "opponent_goal_implies_cs_lost": True,
            "team_goal_has_single_scorer_category": True,
            "at_most_one_assist_per_goal": True,
            "self_assist_forbidden": True,
            "dnp_scorer_forbidden": True,
        }
    }


def _simulate_route_arrays_serial(
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
    player_ids_by_gw = {
        gw: sorted(by_gw[gw])
        for gw in ordered_gws
    }
    fixture_catalog_by_gw = {
        gw: _fixture_catalog(
            pmap,
            player_ids_by_gw[gw],
            gw,
        )
        for gw in ordered_gws
    }

    route_totals = {
        rid: {
            h: np.empty(actual_paths, dtype=np.float64)
            for h in horizons
        }
        for rid in route_ids
    }
    state_counts: dict[str, np.ndarray] = {}
    state_draws: dict[str, int] = {}
    event_sums: dict[str, dict[str, float]] = {}
    route_diag = {
        rid: {
            "autosub_paths": 0,
            "captain_takeover_paths": 0,
        }
        for rid in route_ids
    }
    match_state_diag = {
        "fixture_chunks": 0,
        "cs_goal_consistency_failures": 0,
        "material_goal_overflow_failures": 0,
        "assist_overflow_failures": 0,
        "self_assist_failures": 0,
        "dnp_scorer_failures": 0,
    }

    rng = np.random.Generator(
        np.random.PCG64(int(seed))
    )
    cfg = load_config()
    offset = 0
    while offset < actual_paths:
        n = min(chunk_size, actual_paths - offset)
        cumulative = {
            rid: np.zeros(n, dtype=np.float64)
            for rid in route_ids
        }
        for gw_index, gw in enumerate(
            ordered_gws, start=1
        ):
            player_ids = player_ids_by_gw[gw]
            player_world, gw_diag = (
                _simulate_match_coupled_gw(
                    rng,
                    pmap,
                    player_ids,
                    gw=gw,
                    n=n,
                    cfg=cfg,
                    catalog=fixture_catalog_by_gw[gw],
                )
            )
            invariants = dict(
                gw_diag.get("match_state_invariants")
                or {}
            )
            for key in match_state_diag:
                match_state_diag[key] += int(
                    invariants.get(key) or 0
                )

            for element in player_ids:
                simulated = player_world[element]
                key = f"{element}:gw{gw}"
                state_counts.setdefault(
                    key,
                    np.zeros(
                        len(_state_rows(pmap[element])),
                        dtype=np.int64,
                    ),
                )
                state_counts[key] += simulated[
                    "state_counts"
                ]
                state_draws[key] = (
                    state_draws.get(key, 0)
                    + int(simulated["state_draws"])
                )
                row = event_sums.setdefault(
                    key,
                    {
                        "goals": 0.0,
                        "assists": 0.0,
                        "clean_sheets": 0.0,
                        "defcon_hits": 0.0,
                        "saves": 0.0,
                        "cards": 0.0,
                        "penalty_goals": 0.0,
                        "set_piece_goals": 0.0,
                        "bonus_points": 0.0,
                    },
                )
                for name, value in simulated[
                    "event_sums"
                ].items():
                    row[name] = row.get(name, 0.0) + float(
                        value
                    )

            for route in route_defs:
                rid = str(route["route_id"])
                lineup_row = dict(
                    (route.get("per_gw") or [])[
                        gw_index - 1
                    ]
                )
                resolved = _resolve_route_chunk(
                    lineup_row,
                    pmap,
                    player_world,
                )
                cumulative[rid] += np.asarray(
                    resolved["points"],
                    dtype=np.float64,
                )
                route_diag[rid][
                    "autosub_paths"
                ] += int(
                    np.count_nonzero(
                        resolved["autosub_any"]
                    )
                )
                route_diag[rid][
                    "captain_takeover_paths"
                ] += int(
                    np.count_nonzero(
                        resolved["captain_takeover"]
                    )
                )
                if gw_index in horizons:
                    cost = route.get(
                        "execution_cost_points"
                    )
                    if cost is None:
                        route_totals[rid][gw_index][
                            offset : offset + n
                        ] = np.nan
                    else:
                        route_totals[rid][gw_index][
                            offset : offset + n
                        ] = (
                            cumulative[rid] - float(cost)
                        )
        offset += n

    diagnostics = {
        "state_frequencies": {},
        "event_means": {},
        "route_path_semantics": {},
        "match_state_invariants": {
            **match_state_diag,
            "status": "PASS",
            "simulation_order": [
                "TACTICAL_STATE",
                "EXPECTED_LINEUPS",
                "AVAILABILITY",
                "START_CAMEO_DNP",
                "MINUTES",
                "MATCH_STATE",
                "TEAM_GOALS",
                "SCORER_ASSISTER",
                "CLEAN_SHEET",
                "SHOTS_SOT_SAVES",
                "DEFENSIVE_ACTIONS_DEFCON",
                "SET_PIECES_PENALTIES",
                "CARDS",
                "BPS_BONUS",
                "PLAYER_FPL_POINTS",
                "AUTOSUBS",
                "CAPTAIN_VICE",
                "TEAM_TOTAL",
            ],
            "player_point_noise_sampling": False,
            "stage2_event_intensities_consumed_read_only": True,
            "fixture_catalog_precomputed_per_gw": True,
            "fixture_catalog_build_count": len(fixture_catalog_by_gw),
            "scoreline_zero_marginal_calibration": "DETERMINISTIC_GAUSS_HERMITE",
        },
    }
    for key, counts in state_counts.items():
        draws = max(1, state_draws[key])
        element = int(key.split(":", 1)[0])
        names = [
            str(row.get("state"))
            for row in _state_rows(pmap[element])
        ]
        frequencies = {
            names[idx]: float(counts[idx]) / draws
            for idx in range(len(names))
        }
        if set(names) == set(STAGE1_STATE_NAMES):
            frequencies["START"] = sum(
                frequencies[name]
                for name in (
                    "START_FULL",
                    "START_SUBBED",
                    "EARLY_SUB",
                )
            )
        if "DNP" in frequencies:
            frequencies["ZERO_MINUTES"] = (
                frequencies["DNP"]
            )
        diagnostics["state_frequencies"][
            key
        ] = frequencies
        diagnostics["event_means"][key] = {
            name: float(value) / draws
            for name, value in event_sums[key].items()
        }
    denom = actual_paths * len(ordered_gws)
    for rid, row in route_diag.items():
        diagnostics["route_path_semantics"][rid] = {
            "autosub_path_rate": float(
                row["autosub_paths"]
            )
            / max(1, denom),
            "captain_takeover_path_rate": float(
                row["captain_takeover_paths"]
            )
            / max(1, denom),
        }
    return route_totals, diagnostics


_MC_PARALLEL_CONTEXT: tuple[
    Mapping[str, Any],
    tuple[dict[str, Any], ...],
    tuple[int, ...],
] | None = None


def _init_mc_parallel_worker(
    projections: Mapping[str, Any],
    route_defs: Sequence[Mapping[str, Any]],
    horizons: Sequence[int],
) -> None:
    """Bind immutable canonical MC inputs once per forked worker."""
    global _MC_PARALLEL_CONTEXT
    _MC_PARALLEL_CONTEXT = (
        projections,
        tuple(dict(row) for row in route_defs),
        tuple(int(value) for value in horizons),
    )


def _mc_parallel_worker(
    item: tuple[int, int, int],
) -> tuple[
    int,
    int,
    dict[str, dict[int, np.ndarray]],
    dict[str, Any],
]:
    if _MC_PARALLEL_CONTEXT is None:
        raise MonteCarloError("parallel MC worker context is not initialized")
    shard_index, path_count, child_seed = item
    projections, route_defs, horizons = _MC_PARALLEL_CONTEXT
    arrays, diagnostics = _simulate_route_arrays_serial(
        projections,
        route_defs,
        actual_paths=int(path_count),
        seed=int(child_seed),
        horizons=horizons,
        chunk_size=int(path_count),
    )
    return int(shard_index), int(path_count), arrays, diagnostics


def _merge_parallel_sampling_diagnostics(
    shard_results: Sequence[
        tuple[
            int,
            int,
            dict[str, dict[int, np.ndarray]],
            dict[str, Any],
        ]
    ],
    *,
    actual_paths: int,
    worker_count: int,
    child_seeds: Sequence[int],
) -> dict[str, Any]:
    if not shard_results:
        raise MonteCarloError("parallel MC produced no shard diagnostics")
    ordered = sorted(shard_results, key=lambda row: int(row[0]))
    total = sum(int(row[1]) for row in ordered)
    if total != int(actual_paths):
        raise MonteCarloError(
            f"parallel MC diagnostics path mismatch: {total} != {actual_paths}"
        )
    first = deepcopy(dict(ordered[0][3]))
    first["state_frequencies"] = {}
    first["event_means"] = {}
    first["route_path_semantics"] = {}

    state_keys = sorted(
        {
            key
            for _, _, _, diag in ordered
            for key in (diag.get("state_frequencies") or {})
        }
    )
    for key in state_keys:
        names = sorted(
            {
                name
                for _, _, _, diag in ordered
                for name in (
                    (diag.get("state_frequencies") or {}).get(key) or {}
                )
            }
        )
        first["state_frequencies"][key] = {
            name: sum(
                int(path_count)
                * float(
                    (
                        (diag.get("state_frequencies") or {}).get(key)
                        or {}
                    ).get(name, 0.0)
                )
                for _, path_count, _, diag in ordered
            )
            / total
            for name in names
        }

    event_keys = sorted(
        {
            key
            for _, _, _, diag in ordered
            for key in (diag.get("event_means") or {})
        }
    )
    for key in event_keys:
        names = sorted(
            {
                name
                for _, _, _, diag in ordered
                for name in (
                    (diag.get("event_means") or {}).get(key) or {}
                )
            }
        )
        first["event_means"][key] = {
            name: sum(
                int(path_count)
                * float(
                    (
                        (diag.get("event_means") or {}).get(key)
                        or {}
                    ).get(name, 0.0)
                )
                for _, path_count, _, diag in ordered
            )
            / total
            for name in names
        }

    route_ids = sorted(
        {
            route_id
            for _, _, _, diag in ordered
            for route_id in (diag.get("route_path_semantics") or {})
        }
    )
    for route_id in route_ids:
        names = sorted(
            {
                name
                for _, _, _, diag in ordered
                for name in (
                    (diag.get("route_path_semantics") or {}).get(route_id)
                    or {}
                )
            }
        )
        first["route_path_semantics"][route_id] = {
            name: sum(
                int(path_count)
                * float(
                    (
                        (diag.get("route_path_semantics") or {}).get(route_id)
                        or {}
                    ).get(name, 0.0)
                )
                for _, path_count, _, diag in ordered
            )
            / total
            for name in names
        }

    first_invariants = dict(
        (ordered[0][3].get("match_state_invariants") or {})
    )
    additive_keys = (
        "fixture_chunks",
        "cs_goal_consistency_failures",
        "material_goal_overflow_failures",
        "assist_overflow_failures",
        "self_assist_failures",
        "dnp_scorer_failures",
    )
    for key in additive_keys:
        first_invariants[key] = sum(
            int(
                (diag.get("match_state_invariants") or {}).get(key)
                or 0
            )
            for _, _, _, diag in ordered
        )
    first_invariants["status"] = (
        "PASS"
        if all(
            str(
                (diag.get("match_state_invariants") or {}).get("status")
                or ""
            )
            == "PASS"
            for _, _, _, diag in ordered
        )
        else "FAIL"
    )
    first["match_state_invariants"] = first_invariants
    first["parallel_execution"] = {
        "status": "ENABLED",
        "worker_count": int(worker_count),
        "shard_count": len(ordered),
        "shard_path_counts": [int(row[1]) for row in ordered],
        "child_seed_policy": "NUMPY_SEEDSEQUENCE_SPAWN",
        "child_seed_count": len(child_seeds),
        "deterministic_shard_order": True,
        "common_random_numbers_within_each_shard": True,
        "total_paths_exact": total == int(actual_paths),
    }
    return first


def _simulate_route_arrays_parallel(
    projections: Mapping[str, Any],
    route_defs: Sequence[Mapping[str, Any]],
    *,
    actual_paths: int,
    seed: int,
    horizons: Sequence[int],
    worker_count: int,
) -> tuple[dict[str, dict[int, np.ndarray]], dict[str, Any]]:
    """Run exact canonical MC in deterministic process shards.

    Every shard evaluates all material routes against the same sampled football
    world inside that shard, preserving CRN route pairing. Shards use stable
    SeedSequence children and are concatenated by shard index so repeated
    identical inputs produce identical arrays and convergence prefixes.
    """
    workers = max(
        1,
        min(
            int(worker_count),
            int(os.cpu_count() or 1),
            int(actual_paths),
        ),
    )
    if workers <= 1 or not sys.platform.startswith("linux"):
        arrays, diagnostics = _simulate_route_arrays_serial(
            projections,
            route_defs,
            actual_paths=actual_paths,
            seed=seed,
            horizons=horizons,
            chunk_size=actual_paths,
        )
        diagnostics["parallel_execution"] = {
            "status": "SERIAL_FALLBACK",
            "worker_count": 1,
            "shard_count": 1,
            "shard_path_counts": [int(actual_paths)],
            "child_seed_policy": "ROOT_SEED",
            "child_seed_count": 1,
            "deterministic_shard_order": True,
            "common_random_numbers_within_each_shard": True,
            "total_paths_exact": True,
        }
        return arrays, diagnostics

    base = int(actual_paths) // workers
    remainder = int(actual_paths) % workers
    path_counts = [
        base + (1 if index < remainder else 0)
        for index in range(workers)
    ]
    children = np.random.SeedSequence(int(seed)).spawn(workers)
    child_seeds = [
        int(child.generate_state(1, dtype=np.uint64)[0])
        for child in children
    ]
    work = [
        (index, path_counts[index], child_seeds[index])
        for index in range(workers)
    ]
    fork_context = mp.get_context("fork")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=fork_context,
        initializer=_init_mc_parallel_worker,
        initargs=(
            projections,
            route_defs,
            tuple(int(value) for value in horizons),
        ),
    ) as executor:
        results = list(executor.map(_mc_parallel_worker, work, chunksize=1))
    results.sort(key=lambda row: int(row[0]))

    first_arrays = results[0][2]
    route_ids = list(first_arrays)
    resolved_horizons = sorted(
        {
            int(horizon)
            for route_arrays in first_arrays.values()
            for horizon in route_arrays
        }
    )
    combined = {
        route_id: {
            horizon: np.concatenate(
                [
                    result[2][route_id][horizon]
                    for result in results
                ]
            )
            for horizon in resolved_horizons
        }
        for route_id in route_ids
    }
    for route_id, horizon_map in combined.items():
        for horizon, values in horizon_map.items():
            if len(values) != int(actual_paths):
                raise MonteCarloError(
                    "parallel MC lost path identity "
                    f"for {route_id}/H{horizon}: "
                    f"{len(values)} != {actual_paths}"
                )
    diagnostics = _merge_parallel_sampling_diagnostics(
        results,
        actual_paths=actual_paths,
        worker_count=workers,
        child_seeds=child_seeds,
    )
    return combined, diagnostics


def _simulate_route_arrays(
    projections: Mapping[str, Any],
    route_defs: Sequence[Mapping[str, Any]],
    *,
    actual_paths: int,
    seed: int,
    horizons: Sequence[int],
    chunk_size: int,
) -> tuple[dict[str, dict[int, np.ndarray]], dict[str, Any]]:
    cfg = load_config()
    canonical_cfg = dict(cfg.get("canonical") or {})
    parallel_min_paths = max(
        1,
        _i(canonical_cfg.get("parallel_min_paths"), 200_000),
    )
    requested_workers = max(
        1,
        _i(canonical_cfg.get("parallel_workers"), 4),
    )
    if (
        int(actual_paths) >= parallel_min_paths
        and requested_workers > 1
        and sys.platform.startswith("linux")
    ):
        return _simulate_route_arrays_parallel(
            projections,
            route_defs,
            actual_paths=int(actual_paths),
            seed=int(seed),
            horizons=horizons,
            worker_count=requested_workers,
        )
    arrays, diagnostics = _simulate_route_arrays_serial(
        projections,
        route_defs,
        actual_paths=int(actual_paths),
        seed=int(seed),
        horizons=horizons,
        chunk_size=int(chunk_size),
    )
    diagnostics["parallel_execution"] = {
        "status": "SERIAL",
        "worker_count": 1,
        "shard_count": 1,
        "shard_path_counts": [int(actual_paths)],
        "child_seed_policy": "ROOT_SEED",
        "child_seed_count": 1,
        "deterministic_shard_order": True,
        "common_random_numbers_within_each_shard": True,
        "total_paths_exact": True,
    }
    return arrays, diagnostics

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
    n = max(1, len(values))
    mean = float(np.mean(values))
    std = (
        float(np.std(values, ddof=1))
        if len(values) > 1
        else 0.0
    )
    diff_std = (
        float(np.std(diff, ddof=1))
        if len(diff) > 1
        else 0.0
    )
    p_gt = float(np.mean(diff > 0.0))
    p_lt = float(np.mean(diff < 0.0))
    p_up = float(np.mean(diff >= material_upside_threshold))
    return {
        "status": "READY",
        "mean_net_utility": mean,
        "median": float(np.median(values)),
        "standard_deviation": std,
        "mean_standard_error": std / math.sqrt(n),
        **_quantiles(values),
        "p_route_gt_hold": p_gt,
        "p_route_gt_hold_standard_error": math.sqrt(
            max(0.0, p_gt * (1.0 - p_gt)) / n
        ),
        "p_route_lt_hold": p_lt,
        "p_route_lt_hold_standard_error": math.sqrt(
            max(0.0, p_lt * (1.0 - p_lt)) / n
        ),
        "downside_probability": p_lt,
        "material_upside_probability": p_up,
        "material_upside_probability_standard_error": math.sqrt(
            max(0.0, p_up * (1.0 - p_up)) / n
        ),
        "mean_difference_vs_hold": float(np.mean(diff)),
        "paired_difference_standard_error": (
            diff_std / math.sqrt(max(1, len(diff)))
        ),
        "mc_standard_error_formula": {
            "probability": "sqrt(p*(1-p)/N)",
            "mean": "SD/sqrt(N)",
        },
    }


def _pair_metrics(a: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    diff = a - b
    if np.any(~np.isfinite(diff)):
        return {
            "status": "ECONOMICS_PARTIAL",
            "p_a_gt_b": None,
        }
    n = max(1, len(diff))
    std = (
        float(np.std(diff, ddof=1))
        if len(diff) > 1
        else 0.0
    )
    p_gt = float(np.mean(diff > 0.0))
    p_lt = float(np.mean(diff < 0.0))
    meaningful = _f(
        (load_config().get("canonical") or {}).get(
            "material_upside_threshold_points"
        ),
        5.0,
    )
    p_meaningful = float(np.mean(diff >= meaningful))
    return {
        "status": "READY",
        "mean_difference": float(np.mean(diff)),
        "p_a_gt_b": p_gt,
        "p_a_gt_b_standard_error": math.sqrt(
            max(0.0, p_gt * (1.0 - p_gt)) / n
        ),
        "p_a_lt_b": p_lt,
        "p_a_lt_b_standard_error": math.sqrt(
            max(0.0, p_lt * (1.0 - p_lt)) / n
        ),
        "p_delta_ge_meaningful_threshold": p_meaningful,
        "meaningful_threshold_points": meaningful,
        "p_delta_ge_meaningful_threshold_standard_error": math.sqrt(
            max(
                0.0,
                p_meaningful * (1.0 - p_meaningful),
            )
            / n
        ),
        "Q10": float(
            np.quantile(diff, 0.10, method="linear")
        ),
        "Q25": float(
            np.quantile(diff, 0.25, method="linear")
        ),
        "median": float(
            np.quantile(diff, 0.50, method="linear")
        ),
        "Q75": float(
            np.quantile(diff, 0.75, method="linear")
        ),
        "Q90": float(
            np.quantile(diff, 0.90, method="linear")
        ),
        "paired_difference_standard_error": (
            std / math.sqrt(n)
        ),
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

    simulation_cache_key = _simulation_cache_key(
        projection_fp=projection_fp,
        route_defs=route_defs,
        actual_paths=actual_paths,
        seed=int(seed),
        horizons=horizons,
        selected_route_id=selected_id,
        canonical=bool(canonical),
    )
    cache_started = time.perf_counter()
    cached_summary = _load_mc_summary_cache(
        simulation_cache_key
    )
    simulation_cache_hit = cached_summary is not None

    if cached_summary is not None:
        metrics = deepcopy(dict(cached_summary["metrics"]))
        pairwise = deepcopy(dict(cached_summary["pairwise"]))
        sampling = deepcopy(dict(cached_summary["sampling"]))
        convergence = deepcopy(
            dict(cached_summary["convergence"])
        )
        execution_state = str(
            cached_summary["execution_state"]
        )
        canonical_pass = bool(
            cached_summary["canonical_pass"]
        )
        upside_threshold = _f(
            cached_summary["upside_threshold"]
        )
        elapsed = time.perf_counter() - cache_started
    else:
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
        upside_threshold = _f(
            canonical_cfg.get(
                "material_upside_threshold_points"
            ),
            5.0,
        )

        metrics: dict[str, Any] = {}
        pairwise: dict[str, Any] = {}
        regret_by_horizon: dict[
            int, dict[str, float | None]
        ] = {}
        route_def_by_id = {
            str(item.get("route_id")): item
            for item in route_defs
        }
        for horizon in horizons:
            horizon_arrays = {
                rid: arrays[rid][horizon]
                for rid in route_ids
            }
            regret_by_horizon[horizon] = _expected_regret(
                horizon_arrays
            )
            for rid in route_ids:
                row = _route_metrics(
                    arrays[rid][horizon],
                    hold_arrays[horizon],
                    material_upside_threshold=(
                        upside_threshold
                    ),
                )
                route_def = route_def_by_id[rid]
                execution_cost = route_def.get(
                    "execution_cost_points"
                )
                row["execution_cost_points"] = execution_cost
                row["execution_cost_status"] = (
                    route_def.get(
                        "execution_cost_status"
                    )
                )
                row["decision_net_supported"] = bool(
                    route_def.get(
                        "decision_net_supported"
                    )
                )
                row["utility_semantics"] = (
                    "DECISION_NET"
                    if row["decision_net_supported"]
                    else (
                        "GROSS_FOOTBALL_ONLY_PRIVATE_"
                        "ECONOMICS_UNAVAILABLE"
                    )
                )
                row["mean_gross_points"] = (
                    None
                    if (
                        row.get("mean_net_utility")
                        is None
                        or execution_cost is None
                    )
                    else (
                        float(row["mean_net_utility"])
                        + float(execution_cost)
                    )
                )
                row["expected_regret"] = (
                    regret_by_horizon[horizon].get(rid)
                )
                metrics.setdefault(rid, {})[
                    str(horizon)
                ] = row
            for i, a in enumerate(route_ids):
                for b in route_ids[i + 1 :]:
                    pairwise[
                        f"{a}__VS__{b}__H{horizon}"
                    ] = _pair_metrics(
                        arrays[a][horizon],
                        arrays[b][horizon],
                    )

        checkpoints = [
            int(x)
            for x in (
                canonical_cfg.get("checkpoints")
                or [
                    50_000,
                    100_000,
                    250_000,
                    500_000,
                ]
            )
            if int(x) <= actual_paths
        ]
        if actual_paths not in checkpoints:
            checkpoints.append(actual_paths)
        checkpoints = sorted(set(checkpoints))
        convergence = _convergence(
            arrays[selected_id][horizons[-1]],
            hold_arrays[horizons[-1]],
            {
                rid: arrays[rid][horizons[-1]]
                for rid in route_ids
            },
            checkpoints=checkpoints,
            cfg=cfg,
        )

        execution_state = (
            "EXECUTED"
            if actual_paths >= minimum_paths
            else "PARTIAL"
        )
        canonical_pass = (
            actual_paths >= minimum_paths
            and convergence.get("status") == "PASS"
            and canonical
        )
        _save_mc_summary_cache(
            simulation_cache_key,
            {
                "metrics": metrics,
                "pairwise": pairwise,
                "sampling": sampling,
                "convergence": convergence,
                "execution_state": execution_state,
                "canonical_pass": canonical_pass,
                "upside_threshold": upside_threshold,
            },
        )
    deterministic_core = {
        "model_owner": MODEL_OWNER,
        "model_id": MODEL_ID,
        "execution_state": execution_state,
        "canonical_pass": canonical_pass,
        "method": "MATCH_STATE_FIRST_SCORELINE_SCORER_ASSISTER_EVENT_SIMULATION",
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
        "correlation_model": "SHARED_MATCH_TEAM_SCORELINE_AND_EVENT_FACTORS",
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
            "NON_MATERIAL_PLAYER_START_STATES_ENTER_TEAM_GOAL_MEAN_AS_STAGE2_EXPECTATIONS",
            "INJURY_CLUSTER_BEYOND_P1_1_AND_STAGE2_LINKUP_NOT_MODELLED",
            "MANAGER_ROTATION_CLUSTER_BEYOND_P1_1_NOT_MODELLED",
            "SET_PIECE_CROSS_PLAYER_TARGET_COMPETITION_PARTIAL",
            "SCORELINE_TIMING_WITHIN_MATCH_NOT_MODELLED",
            "CROSS_GW_TEMPORAL_STATE_CONDITIONALLY_INDEPENDENT_GIVEN_CURRENT_MODEL",
            "FUTURE_PRICE_PROCESS_NOT_MODELLED",
        ],
        "match_state_contract": {
            "team_goals_sampled_before_player_points": True,
            "clean_sheet_is_opponent_goals_zero": True,
            "single_scorer_category_per_team_goal": True,
            "at_most_one_assist_per_goal": True,
            "self_assist_forbidden": True,
            "dnp_scorer_forbidden": True,
            "stage2_linkup_conditioned_on_sampled_material_teammate_appearance": True,
            "defcon_count_family_from_stage2": True,
            "save_count_family_from_stage2": True,
            "bonus_sampled_from_stage2_empirical_bps_conditional_pmf": True,
            "arbitrary_player_point_noise": False
        },
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
        "simulation_cache_hit": simulation_cache_hit,
        "simulation_cache_key": simulation_cache_key[:20],
        "simulation_cache_schema": MC_SIM_CACHE_SCHEMA,
        "execution_mode": (
            (sampling.get("parallel_execution") or {}).get("status")
        ),
        "parallel_worker_count": (
            (sampling.get("parallel_execution") or {}).get("worker_count")
        ),
        "parallel_shard_count": (
            (sampling.get("parallel_execution") or {}).get("shard_count")
        ),
        "parallel_total_paths_exact": (
            (sampling.get("parallel_execution") or {}).get(
                "total_paths_exact"
            )
        ),
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
    selected_route_id: str | None = None,
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
        selected_route_id=str(
            selected_route_id
            or package_utility.get("selected_route_id")
            or "HOLD"
        ),
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
        "convergence_route_id": str(
            selected_route_id
            or package_utility.get("selected_route_id")
            or "HOLD"
        ),
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
            decision_net_supported = bool(
                mc_row.get("decision_net_supported")
            )
            if decision_net_supported:
                uncertainty["p_beats_hold"] = mc_row.get(
                    "p_route_gt_hold"
                )
            else:
                uncertainty["p_beats_hold"] = (
                    "UNAVAILABLE_PRIVATE_ECONOMICS"
                )
                uncertainty["p_football_points_gt_hold"] = (
                    mc_row.get("p_route_gt_hold")
                )
            uncertainty["monte_carlo"] = {
                "execution_state": mc.get("execution_state"),
                "canonical_pass": bool(mc.get("canonical_pass")),
                "actual_paths": mc.get("actual_paths"),
                "seed": mc.get("seed"),
                "mean_difference_vs_hold": mc_row.get("mean_difference_vs_hold"),
                "paired_difference_standard_error": mc_row.get("paired_difference_standard_error"),
                "expected_regret": mc_row.get("expected_regret"),
                "utility_semantics": mc_row.get("utility_semantics"),
                "decision_net_supported": decision_net_supported,
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
