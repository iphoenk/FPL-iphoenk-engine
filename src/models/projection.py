from __future__ import annotations

import math

from src.rules import (
    ASSIST_POINTS,
    CLEAN_SHEET_POINTS,
    GOAL_POINTS,
    SAVE_INTERVAL,
    SAVE_POINTS_PER_INTERVAL,
)


def clamp(x, a, b):
    return max(a, min(b, x))


def _f(v, default=0.0):
    try:
        return float(v if v is not None else default)
    except (TypeError, ValueError):
        return float(default)


def xmins_distribution(player: dict, advanced: dict | None = None):
    adv = advanced or {}
    status = player.get("status", "a")
    chance = player.get("chance_of_playing_next_round")
    if status in {"s", "u"}:
        return {
            "start_probability": 0.0,
            "bench_probability": 0.0,
            "dnp_probability": 1.0,
            "expected_minutes": 0.0,
        }
    if status == "i" and chance is None:
        chance = 25
    availability = clamp(_f(chance, 100) / 100, 0, 1)
    total_mins = _f(player.get("minutes"))
    starts = _f(player.get("starts"))
    appearances = max(starts, math.ceil(total_mins / 90) if total_mins else 0)
    avg_start_mins = clamp(total_mins / max(1, appearances), 45, 90) if total_mins else 70
    starter_signal = clamp(0.55 + 0.08 * starts + 0.002 * total_mins, 0.35, 0.96)
    starter_signal = clamp(_f(adv.get("start_probability"), starter_signal), 0, 1) * availability
    bench = clamp((availability - starter_signal) * 0.75, 0, 1 - starter_signal)
    dnp = clamp(1 - starter_signal - bench, 0, 1)
    exp = starter_signal * avg_start_mins + bench * min(25, avg_start_mins * 0.3)
    return {
        "start_probability": round(starter_signal, 4),
        "bench_probability": round(bench, 4),
        "dnp_probability": round(dnp, 4),
        "expected_minutes": round(exp, 1),
    }


def simple_xmins(player: dict, advanced: dict | None = None):
    return xmins_distribution(player, advanced)["expected_minutes"] / 90


def project_points(player: dict, advanced: dict | None = None, fixture_difficulty: float = 3.0):
    adv = advanced or {}
    dist = xmins_distribution(player, adv)
    share = dist["expected_minutes"] / 90
    xg90 = _f(adv.get("xg_per90"), adv.get("expected_goals", 0))
    xa90 = _f(adv.get("xa_per90"), adv.get("expected_assists", 0))
    pos = int(player.get("element_type") or 4)

    # V5 single-authority invariant: scoring constants come only from src.rules.
    goal_pts = GOAL_POINTS.get(pos, GOAL_POINTS[4])
    cs_pts = CLEAN_SHEET_POINTS.get(pos, 0)

    appearance = (2 if dist["expected_minutes"] >= 60 else 1) * clamp(share, 0, 1)
    attack = (xg90 * goal_pts + xa90 * ASSIST_POINTS) * share
    cs_prob = clamp(
        _f(adv.get("clean_sheet_probability"), 0.48 - 0.075 * (fixture_difficulty - 2)),
        0.05,
        0.70,
    )
    clean = cs_pts * cs_prob * share
    saves = 0.0
    if pos == 1:
        saves_per90 = _f(
            adv.get("saves_per90"),
            _f(player.get("saves")) / max(1, _f(player.get("minutes")) / 90),
        )
        saves = max(0, saves_per90 / SAVE_INTERVAL) * SAVE_POINTS_PER_INTERVAL * share
    defcon = _f(adv.get("defcon_points_per90")) * share
    bonus = _f(adv.get("bonus_per90"), 0.35) * share
    total = appearance + attack + clean + saves + defcon + bonus
    return {
        "xmins": dist,
        "projected_points": round(total, 3),
        "components": {
            "appearance": round(appearance, 3),
            "attack": round(attack, 3),
            "clean_sheet": round(clean, 3),
            "saves": round(saves, 3),
            "defcon": round(defcon, 3),
            "bonus": round(bonus, 3),
        },
        "model": "interpretable_projection_v5_bootstrap",
        "ruleset_id": "FPL_2026_27",
        "confidence": "MEDIUM-LOW pending multi-GW calibration",
    }
