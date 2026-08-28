from __future__ import annotations

import math
from statistics import mean, pstdev

from src.engines.fpl_rules_2026 import DEFCON

POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {1: 10, 2: 6, 3: 5, 4: 4}
CS_PTS = {1: 4, 2: 4, 3: 1, 4: 0}
XG_PRIOR = {1: 0.01, 2: 0.06, 3: 0.18, 4: 0.30}
XA_PRIOR = {1: 0.005, 2: 0.08, 3: 0.16, 4: 0.11}
DEF_ACTION_PRIOR = {1: 0.0, 2: 7.0, 3: 6.0, 4: 3.0}
GK_SAVE_PRIOR = 2.7


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def f(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def availability(player):
    if player.get("status") in {"s", "u"}:
        return 0.0
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        return clamp(f(chance) / 100)
    return 0.35 if player.get("status") == "i" else 0.75 if player.get("status") == "d" else 1.0


def workload_factor(ctx):
    return clamp(
        1
        - 0.025 * max(0, 5 - f(ctx.get("rest_days"), 7))
        - 0.0008 * f(ctx.get("cup_minutes_last7"))
        - 0.00045 * f(ctx.get("international_minutes_last10"))
        - 0.000015 * f(ctx.get("travel_km_last10")),
        0.65,
        1,
    )


def competition_adjustment(ctx, current_start_rate=None):
    """Return the canonical role-competition factor and uncertainty.

    Priors and fixture projections share this helper so health evidence cannot
    claim an adjustment that the prediction model did not actually apply.
    """
    ctx = ctx or {}
    start_rate = clamp(f(current_start_rate, f(ctx.get("current_start_rate"))))
    uncertainty = clamp(1 - 0.75 * start_rate, 0.25, 1)
    factor = clamp(
        1
        - f(ctx.get("competition_start_weight"), 0.16) * f(ctx.get("competition_pressure")) * uncertainty
        - f(ctx.get("squad_depth_weight"), 0.08) * f(ctx.get("squad_depth_pressure")),
        0.72,
        1,
    )
    return factor, uncertainty


def lineup_distribution(player, ctx=None):
    """Estimate start, substitute and DNP probabilities from direct player evidence.

    Broad FPL positions are deliberately not used as role competition. They mix
    materially different tactical jobs and caused nailed starters to be penalised
    by every midfielder or defender in the same squad in V4.7.0.
    """
    ctx = ctx or {}
    available = availability(player)
    minutes = f(player.get("minutes"))
    starts = f(player.get("starts"))
    appearances = max(1, math.ceil(minutes / 90), int(starts))
    current_start_rate = clamp(f(ctx.get("current_start_rate"), starts / appearances))
    current_minutes_rate = clamp(f(ctx.get("current_minutes_rate"), minutes / (90 * appearances)))
    nailed_prior = clamp(f(ctx.get("nailed_prior"), current_start_rate))

    # Direct current and prior-season evidence drives the probability. The old
    # mechanical 28% floor is removed, so players with no evidence can be DNP.
    base_start = clamp(
        0.04
        + 0.54 * nailed_prior
        + 0.32 * current_start_rate
        + 0.10 * current_minutes_rate,
        0.02,
        0.97,
    )
    # Proven current starts are direct evidence against a purely inferred peer
    # competition signal. Competition therefore has full force for unknown
    # players and is progressively attenuated for established starters.
    competition_factor, competition_uncertainty = competition_adjustment(ctx, current_start_rate)
    start_probability = clamp(
        base_start
        * available
        * clamp(f(ctx.get("injury_return_ramp"), 1), 0.25, 1)
        * workload_factor(ctx)
        * competition_factor
    )

    # Substitute probability requires substitute or prior evidence. It is no
    # longer assigned to most of the residual availability by default.
    sub_signal = clamp(f(ctx.get("sub_appearance_signal")))
    prior_only_signal = max(0.0, nailed_prior - current_start_rate)
    bench_propensity = clamp(0.10 + 0.50 * sub_signal + 0.18 * prior_only_signal, 0.08, 0.70)
    bench_probability = clamp(
        (available - start_probability) * bench_propensity,
        0,
        1 - start_probability,
    )
    dnp_probability = clamp(1 - start_probability - bench_probability)

    default_start_minutes = minutes / starts if starts > 0 else 72
    start_minutes = clamp(f(ctx.get("avg_minutes_when_start"), default_start_minutes), 45, 90)
    substitute_minutes = clamp(f(ctx.get("avg_minutes_when_sub"), 18), 1, 35)
    expected_minutes = start_probability * start_minutes + bench_probability * substitute_minutes
    p60 = start_probability * clamp((start_minutes - 50) / 18, 0, 1)
    return {
        "start_probability": round(start_probability, 4),
        "bench_probability": round(bench_probability, 4),
        "dnp_probability": round(dnp_probability, 4),
        "expected_minutes": round(expected_minutes, 1),
        "p60": round(p60, 4),
        "availability_probability": round(available, 4),
        "workload_factor": round(workload_factor(ctx), 4),
        "competition_factor": round(competition_factor, 4),
        "competition_uncertainty": round(competition_uncertainty, 4),
    }


def team_strength(team_id, players):
    rows = [player for player in players if player.get("team") == team_id]
    xg = sum(f(player.get("expected_goals")) for player in rows)
    xa = sum(f(player.get("expected_assists")) for player in rows)
    gc = sum(f(player.get("goals_conceded")) for player in rows)
    return {
        "attack": round(1 + xg + 0.55 * xa, 3),
        "defence": round(1 / (1 + gc / max(1, len(rows))), 3),
    }


def fixture_adjustment(fixture, home=True, team_attack=1, opp_defence=0.5):
    return (1.06 if home else 0.95) * clamp(
        0.82
        + 0.10 * (3 - f(fixture.get("difficulty"), 3))
        + 0.04 * (team_attack - 1)
        - 0.10 * (opp_defence - 0.5),
        0.72,
        1.28,
    )


def shrink_rate(observed, minutes, prior, prior_minutes=720):
    sample_minutes = max(0, f(minutes))
    weight = sample_minutes / (sample_minutes + max(90, f(prior_minutes, 720)))
    return prior * (1 - weight) + max(0, f(observed)) * weight, weight


def rates(player, advanced=None, ctx=None):
    advanced = advanced or {}
    ctx = ctx or {}
    minutes = max(1, f(player.get("minutes")))
    position = int(player.get("element_type", 3))
    raw_xg = f(advanced.get("xg_per90"), f(player.get("expected_goals")) * 90 / minutes)
    raw_xa = f(advanced.get("xa_per90"), f(player.get("expected_assists")) * 90 / minutes)
    xg, current_weight = shrink_rate(
        raw_xg, minutes, f(ctx.get("xg90_prior"), XG_PRIOR[position]), f(ctx.get("attacking_prior_minutes"), 720)
    )
    xa, _ = shrink_rate(
        raw_xa, minutes, f(ctx.get("xa90_prior"), XA_PRIOR[position]), f(ctx.get("attacking_prior_minutes"), 720)
    )
    raw_def_actions = max(
        0,
        f(advanced.get("defensive_contribution_per90"), f(player.get("defensive_contribution")) * 90 / minutes),
    )
    def_actions, defcon_weight = shrink_rate(
        raw_def_actions,
        minutes,
        f(ctx.get("def_actions90_prior"), DEF_ACTION_PRIOR[position]),
        f(ctx.get("defcon_prior_minutes"), 720),
    )
    raw_saves = max(0, f(player.get("saves")) * 90 / minutes) if position == 1 else 0.0
    saves, save_weight = (
        shrink_rate(
            raw_saves,
            minutes,
            f(ctx.get("gk_saves90_prior"), GK_SAVE_PRIOR),
            f(ctx.get("gk_save_prior_minutes"), 900),
        )
        if position == 1
        else (0.0, 0.0)
    )
    return {
        "xg90": xg,
        "xa90": xa,
        "raw_xg90": max(0, raw_xg),
        "raw_xa90": max(0, raw_xa),
        "current_season_weight": current_weight,
        "saves90": saves,
        "raw_saves90": raw_saves,
        "save_weight": save_weight,
        "bps90": f(player.get("bps")) * 90 / minutes,
        "def_actions90": def_actions,
        "raw_def_actions90": raw_def_actions,
        "defcon_weight": defcon_weight,
    }


def defcon_expected_points(actions90, expected_minutes, position, p60=1.0):
    rule = DEFCON[POS.get(position)]
    if not rule["eligible"] or expected_minutes < 1:
        return 0.0
    threshold = float(rule["threshold"])
    expected_actions = max(0, actions90) * expected_minutes / 90
    probability = 1 / (1 + math.exp(-(expected_actions - threshold) / max(2.2, threshold * 0.22)))
    return 2 * probability * clamp(p60, 0, 1)


def clean_sheet_probability(fixture, ctx):
    prior = clamp(f(ctx.get("team_cs_prior"), 0.30), 0.15, 0.50)
    difficulty = f(fixture.get("difficulty"), 3)
    home_adjustment = 0.025 if fixture.get("home", True) else -0.02
    return clamp(prior + 0.045 * (3 - difficulty) + home_adjustment, 0.08, 0.55)


def bonus_expected(rate, share, minutes):
    weight = max(0, min(1, minutes / (minutes + 900)))
    observed = clamp(rate["bps90"] / 30, 0, 3)
    return ((1 - weight) * 0.15 + weight * observed) * share


def goalkeeper_save_points(saves90, expected_minutes):
    return 0.27 * max(0, saves90) * expected_minutes / 90


def project_fixture(player, fixture, ctx=None, advanced=None):
    ctx = ctx or {}
    distribution = lineup_distribution(player, ctx)
    minutes_share = distribution["expected_minutes"] / 90
    rate = rates(player, advanced, ctx)
    position = int(player.get("element_type", 3))
    opponent_defence = f(fixture.get("opponent_defence"), f(ctx.get("opponent_defence"), 0.5))
    fixture_factor = fixture_adjustment(
        fixture, fixture.get("home", True), f(ctx.get("team_attack"), 1), opponent_defence
    )

    # Current xG/xA already includes set pieces and penalties. Official taker
    # orders remain metadata until empirical event shares can be separated.
    role_multiplier = clamp(f(ctx.get("role_attack_multiplier"), 1), 0.85, 1.25)
    attack = (
        rate["xg90"] * GOAL_PTS[position] + rate["xa90"] * 3
    ) * minutes_share * fixture_factor * role_multiplier
    # p60 is already an unconditional probability (start_probability times the
    # conditional chance of reaching 60 minutes). Multiplying it by the start
    # probability again systematically undervalues rotation-risk players.
    appearance = distribution["start_probability"] + distribution["p60"] + distribution["bench_probability"]
    clean_sheet_probability_value = clean_sheet_probability(fixture, ctx)
    clean_sheet = CS_PTS[position] * clean_sheet_probability_value * distribution["p60"]
    saves = goalkeeper_save_points(rate["saves90"], distribution["expected_minutes"]) if position == 1 else 0
    defcon = defcon_expected_points(
        rate["def_actions90"], distribution["expected_minutes"], position, distribution["p60"]
    )
    bonus = bonus_expected(rate, minutes_share, f(player.get("minutes")))
    expected_points = max(0, appearance + attack + clean_sheet + saves + defcon + bonus)
    sigma = max(0.9, math.sqrt(expected_points + 0.8) * (1.15 - distribution["start_probability"] * 0.25))
    return {
        "event": fixture.get("event"),
        "xpts": round(expected_points, 3),
        "lower80": round(max(0, expected_points - 1.282 * sigma), 3),
        "upper80": round(expected_points + 1.282 * sigma, 3),
        "xmins": distribution,
        "components": {
            "appearance": round(appearance, 3),
            "attack": round(attack, 3),
            "clean_sheet": round(clean_sheet, 3),
            "saves": round(saves, 3),
            "defcon": round(defcon, 3),
            "bonus": round(bonus, 3),
            "set_piece_penalty_adjustment": round(attack - attack / role_multiplier, 3) if role_multiplier else 0.0,
        },
        "rates": {
            "xg90": round(rate["xg90"], 4),
            "xa90": round(rate["xa90"], 4),
            "raw_xg90": round(rate["raw_xg90"], 4),
            "raw_xa90": round(rate["raw_xa90"], 4),
            "current_season_weight": round(rate["current_season_weight"], 4),
            "def_actions90": round(rate["def_actions90"], 4),
            "raw_def_actions90": round(rate["raw_def_actions90"], 4),
            "defcon_weight": round(rate["defcon_weight"], 4),
            "saves90": round(rate["saves90"], 4),
            "raw_saves90": round(rate["raw_saves90"], 4),
            "save_weight": round(rate["save_weight"], 4),
        },
        "calibration": {
            "clean_sheet_probability": round(clean_sheet_probability_value, 4),
            "premium_prior": round(f(ctx.get("premium_prior")), 4),
            "role_prior": round(f(ctx.get("role_prior")), 4),
            "nailed_prior": round(f(ctx.get("nailed_prior")), 4),
            "current_start_rate": round(f(ctx.get("current_start_rate")), 4),
            "current_minutes_rate": round(f(ctx.get("current_minutes_rate")), 4),
            "competition_pressure": round(f(ctx.get("competition_pressure")), 4),
            "squad_depth_pressure": round(f(ctx.get("squad_depth_pressure")), 4),
            "competition_adjustment_applied": bool(ctx.get("competition_adjustment_applied")),
            "competition_factor": distribution.get("competition_factor"),
            "tactical_role": ctx.get("tactical_role"),
            "tactical_role_source": ctx.get("tactical_role_source"),
            "set_piece_share": ctx.get("set_piece_share"),
            "penalty_share": ctx.get("penalty_share"),
            "set_piece_order_weight": round(f(ctx.get("set_piece_order_weight")), 4),
            "penalty_order_weight": round(f(ctx.get("penalty_order_weight")), 4),
            "role_attack_multiplier": round(role_multiplier, 4),
            "role_prior_adjustment_applied": bool(ctx.get("role_prior_adjustment_applied")),
            "last_season_weight": round(f(ctx.get("last_season_weight")), 4),
            "historical_weight": round(f(ctx.get("historical_weight")), 4),
            "historical_prior_consumed": bool(ctx.get("historical_prior_consumed")),
            "opponent_defence_resistance": round(opponent_defence, 4),
            "fixture_adjustment": round(fixture_factor, 4),
        },
        "provenance": {
            "model": "v4.9.2-truthful-health",
            "fixture_source": "official_fpl",
            "advanced_source": ctx.get("advanced_source", "official_fpl_current_state"),
            "advanced_identity_match": ctx.get("advanced_identity_match"),
            "advanced_materially_distinct": bool(ctx.get("advanced_materially_distinct")),
            "point_in_time": ctx.get("point_in_time"),
            "official_rules_source": "src.engines.fpl_rules_2026",
            "xmins_prior_source": ctx.get("xmins_prior_source"),
            "competition_source": ctx.get("competition_source"),
            "last_season_source": ctx.get("last_season_source"),
            "historical_source": ctx.get("historical_source"),
            "historical_seasons": ctx.get("historical_seasons") or [],
            "historical_prior_consumed": bool(ctx.get("historical_prior_consumed")),
            "set_piece_source": ctx.get("set_piece_source"),
            "role_scoring_mode": ctx.get("role_scoring_mode", "prior_reallocation_no_direct_double_count"),
            "opponent_defence_source": fixture.get("opponent_defence_source"),
            "opponent_defence_scoring_mode": fixture.get("opponent_defence_scoring_mode"),
            "opponent_defence_raw": fixture.get("opponent_defence_raw"),
            "opponent_defence_diagnostic": fixture.get("opponent_defence_diagnostic"),
            "attacking_rate_shrinkage": True,
            "defcon_rate_shrinkage": True,
            "gk_save_shrinkage": True,
            "cs_prior_calibration": True,
            "p60_scoring_gate": True,
            "bonus_regression": True,
        },
    }


def fixture_run_summary(rows, window=5):
    """Summarize the canonical fixture-adjustment path without re-scoring fixtures."""
    adjustments = [f((row.get("calibration") or {}).get("fixture_adjustment"), 1.0) for row in rows]
    windows = []
    for start in range(0, len(adjustments), window):
        chunk = adjustments[start:start + window]
        if not chunk:
            continue
        windows.append({
            "start_offset": start + 1,
            "end_offset": start + len(chunk),
            "average_adjustment": round(mean(chunk), 4),
        })
    first = windows[0]["average_adjustment"] if windows else None
    second = windows[1]["average_adjustment"] if len(windows) > 1 else None
    final = windows[2]["average_adjustment"] if len(windows) > 2 else (windows[-1]["average_adjustment"] if windows else None)
    delta = round(second - first, 4) if first is not None and second is not None else None
    if delta is None:
        direction = "UNKNOWN"
    elif delta >= 0.03:
        direction = "IMPROVING"
    elif delta <= -0.03:
        direction = "WORSENING"
    else:
        direction = "STABLE"
    best = max(windows, key=lambda row: row["average_adjustment"]) if windows else None
    worst = min(windows, key=lambda row: row["average_adjustment"]) if windows else None
    return {
        "source": "official_fpl_fixture_adjustment",
        "window_size": window,
        "windows": windows,
        "first5_average_adjustment": first,
        "next5_average_adjustment": second,
        "final5_average_adjustment": final,
        "swing_next5_vs_first5": delta,
        "direction": direction,
        "best_window": best,
        "worst_window": worst,
        "decision_usage": "multi_horizon_projection_context",
    }


def project_horizon(player, fixtures, ctx=None, advanced=None, n=15):
    rows = [project_fixture(player, fixture, ctx, advanced) for fixture in fixtures[:n]]
    expected_points = [row["xpts"] for row in rows]
    return {
        "element": player.get("id"),
        "name": player.get("web_name"),
        "position": POS.get(player.get("element_type")),
        "fixtures": rows,
        "fixture_run": fixture_run_summary(rows),
        "xpts_3": round(sum(expected_points[:3]), 2),
        "xpts_5": round(sum(expected_points[:5]), 2),
        "xpts_10": round(sum(expected_points[:10]), 2),
        "xpts_15": round(sum(expected_points[:15]), 2),
        "mean_xpts": round(mean(expected_points), 3) if expected_points else 0,
        "uncertainty": round(pstdev(expected_points), 3) if len(expected_points) > 1 else None,
        "model": "v4.9.2-truthful-health",
    }
