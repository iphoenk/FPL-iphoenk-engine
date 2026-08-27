from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from src.rules import ASSIST_POINTS, CLEAN_SHEET_POINTS, ELEMENT_TYPE_TO_POSITION, GOAL_POINTS
from src.utils import DATA, ROOT, read_json

CONFIG_DIR = ROOT / "config" / "intelligence"
PROJECTION_CONFIG = CONFIG_DIR / "projection.json"
TEAM_STRENGTH_OUT = DATA / "team_strength.json"


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


def poisson_threshold_probability(rate90: float, minutes: float, threshold: int) -> float:
    if threshold <= 0:
        return 1.0
    lam = max(0.0, _f(rate90)) * clamp(_f(minutes), 0.0, 90.0) / 90.0
    if lam <= 0:
        return 0.0
    term = math.exp(-lam)
    cdf = term
    for k in range(1, threshold):
        term *= lam / k
        cdf += term
    return clamp(1.0 - cdf, 0.0, 1.0)


def expected_defensive_contribution_points(
    xmins: dict[str, Any],
    dc_model: dict[str, Any],
) -> tuple[float, float]:
    if not dc_model or not bool(dc_model.get("eligible")):
        return 0.0, 0.0
    threshold = int(dc_model.get("threshold") or 0)
    if threshold <= 0:
        return 0.0, 0.0
    rate90 = max(0.0, _f(dc_model.get("count_rate90")))
    p_start = clamp(_f(xmins.get("start_probability")), 0.0, 1.0)
    p_bench = clamp(_f(xmins.get("bench_probability")), 0.0, 1.0 - p_start)
    starter_minutes = clamp(_f(xmins.get("starter_minutes_if_start"), 72.0), 0.0, 90.0)
    bench_minutes = clamp(_f(xmins.get("bench_minutes_if_used"), 18.0), 0.0, 90.0)
    p_hit_start = poisson_threshold_probability(rate90, starter_minutes, threshold)
    p_hit_bench = poisson_threshold_probability(rate90, bench_minutes, threshold)
    hit_probability = clamp(p_start * p_hit_start + p_bench * p_hit_bench, 0.0, 1.0)
    points_when_hit = max(0.0, _f(dc_model.get("points_when_hit"), 2.0))
    return points_when_hit * hit_probability, hit_probability


def _p60(xmins: dict[str, Any], cfg: dict[str, Any]) -> float:
    trans = cfg.get("appearance_60_probability_transition") or {}
    low = _f(trans.get("start_minutes_low"), 55.0)
    high = max(low + 1.0, _f(trans.get("start_minutes_high"), 70.0))
    starter_minutes = _f(xmins.get("starter_minutes_if_start"), 72.0)
    conditional = clamp((starter_minutes - low) / (high - low), 0.0, 1.0)
    # Unconditional probability of reaching the 60-minute threshold.
    return clamp(_f(xmins.get("start_probability")) * conditional, 0.0, 1.0)


def _project_fixture(
    player: dict[str, Any],
    xmins: dict[str, Any],
    matchup: dict[str, Any],
    home: bool,
    rate_bundle: dict[str, Any],
    small_sample: bool,
) -> dict[str, Any]:
    cfg = load_projection_config()
    element_type = int(player.get("element_type") or 4)
    position = str(player.get("position") or ELEMENT_TYPE_TO_POSITION.get(element_type) or "FWD")
    share = clamp(_f(xmins.get("expected_minutes")) / 90.0, 0.0, 1.0)
    p_start = clamp(_f(xmins.get("start_probability")), 0.0, 1.0)
    p_bench = clamp(_f(xmins.get("bench_probability")), 0.0, 1.0 - p_start)
    p60 = _p60(xmins, cfg)

    team_xg = _f(matchup.get("home_expected_goals") if home else matchup.get("away_expected_goals"), 1.3)
    league_base = _f((read_json(TEAM_STRENGTH_OUT, {}).get("baseline") or {}).get("home_goals" if home else "away_goals"), 1.3)
    attack_multiplier = clamp(
        team_xg / max(0.2, league_base),
        _f(cfg.get("attack_multiplier_min"), 0.55),
        _f(cfg.get("attack_multiplier_max"), 1.75),
    )
    cs_prob = clamp(_f(matchup.get("home_clean_sheet_probability") if home else matchup.get("away_clean_sheet_probability")), 0.0, 1.0)

    # p60 is already unconditional. Expected appearance points are:
    # 1 * P(plays but <60) + 2 * P(plays >=60)
    # = p_start + p_bench + p60 under the xMins appearance model.
    appearance = p_start + p_bench + p60
    attack = (
        _f(rate_bundle.get("xg90")) * GOAL_POINTS.get(element_type, 4)
        + _f(rate_bundle.get("xa90")) * ASSIST_POINTS
    ) * share * attack_multiplier
    clean_sheet = CLEAN_SHEET_POINTS.get(element_type, 0) * cs_prob * p60
    saves = (_f(rate_bundle.get("saves90")) / 3.0) * share if position == "GK" else 0.0
    if rate_bundle.get("dc_model"):
        dc, dc_hit_probability = expected_defensive_contribution_points(xmins, rate_bundle["dc_model"])
    else:
        # Compatibility only for callers not yet carrying REC-01's explicit model bundle.
        dc = _f(rate_bundle.get("dc90")) * share
        dc_hit_probability = None
    bonus = _f(rate_bundle.get("bonus90")) * share
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
            "defensive_contribution_hit_probability": round(dc_hit_probability, 4) if dc_hit_probability is not None else None,
            "bonus": round(bonus, 3),
        },
    }
