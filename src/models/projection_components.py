from __future__ import annotations

import json
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
    rate_bundle: dict[str, float],
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
