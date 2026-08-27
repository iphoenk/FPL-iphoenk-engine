from __future__ import annotations

from collections import defaultdict

from src.models.player_identity import build_identity_index
from src.models.v4_prediction import XA_PRIOR, XG_PRIOR, clamp, competition_adjustment, project_horizon, team_strength
from src.models.v4_prediction_inputs import load_prediction_enrichment
from src.utils import CONFIG, read_json


def f(value, default=0.0):
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _strength_scale(value, values):
    values = [f(x) for x in values if x is not None]
    if not values:
        return 0.5
    lo, hi = min(values), max(values)
    return 0.5 if hi == lo else clamp(0.2 + 0.6 * (f(value) - lo) / (hi - lo), 0.2, 0.8)


def _quality_config():
    return read_json(CONFIG / "prediction_quality_registry.json", {})


def opponent_defence_ratings(teams, fixtures=None, quality=None):
    # Overall strength substantially overlaps official FDR. When the dedicated
    # defence split is zeroed, retain overall strength for diagnostics only and
    # use a neutral scoring value to avoid counting the same fixture signal twice.
    venue_values = {
        venue: [f(team.get(f"strength_defence_{venue}")) for team in teams.values()]
        for venue in ("home", "away")
    }
    defence_ready = {
        venue: sum(value > 0 for value in values) >= max(4, len(teams) // 2)
        for venue, values in venue_values.items()
    }
    overall_values = {
        venue: [f(team.get(f"strength_overall_{venue}"), 3) for team in teams.values()]
        for venue in ("home", "away")
    }
    quality = quality or _quality_config()
    params = quality.get("opponent_defence") or {}
    finished = [row for row in (fixtures or []) if row.get("finished") and row.get("team_h_score") is not None and row.get("team_a_score") is not None]
    results = defaultdict(lambda: {"games": 0, "conceded": 0.0, "home_games": 0, "home_conceded": 0.0, "away_games": 0, "away_conceded": 0.0})
    for fixture in finished:
        home, away = int(fixture["team_h"]), int(fixture["team_a"])
        home_score, away_score = f(fixture["team_h_score"]), f(fixture["team_a_score"])
        results[home]["games"] += 1; results[home]["conceded"] += away_score
        results[home]["home_games"] += 1; results[home]["home_conceded"] += away_score
        results[away]["games"] += 1; results[away]["conceded"] += home_score
        results[away]["away_games"] += 1; results[away]["away_conceded"] += home_score
    league_conceded = sum(row["conceded"] for row in results.values()) / max(1, sum(row["games"] for row in results.values()))
    result_weight = f(params.get("result_weight"), 0.7)
    diagnostic_weight = f(params.get("official_diagnostic_weight"), 0.3)
    prior_matches = max(1.0, f(params.get("prior_matches"), 5))
    minimum = f(params.get("minimum_rating"), 0.2)
    maximum = f(params.get("maximum_rating"), 0.8)
    ratings = {}
    for team_id, team in teams.items():
        row = {}
        modes = []
        for venue in ("home", "away"):
            raw_defence = f(team.get(f"strength_defence_{venue}"))
            raw_overall = f(team.get(f"strength_overall_{venue}"), 3)
            result_row = results.get(team_id) or {}
            venue_games = int(result_row.get(f"{venue}_games") or 0)
            games = venue_games or int(result_row.get("games") or 0)
            venue_conceded = f(result_row.get(f"{venue}_conceded")) if venue_games else f(result_row.get("conceded"))
            if finished:
                # Shrink sparse venue/team results to the league mean. Teams
                # without a result remain at the explicit league prior rather
                # than an opaque hardcoded opponent default.
                conceded_rate = (venue_conceded + prior_matches * league_conceded) / (games + prior_matches)
                result_rating = clamp(0.5 + (league_conceded - conceded_rate) / 3.0, minimum, maximum)
                diagnostic = _strength_scale(raw_overall, overall_values[venue])
                row[venue] = clamp(result_weight * result_rating + diagnostic_weight * diagnostic, minimum, maximum)
                modes.append("dynamic_bayesian_results")
            elif defence_ready[venue] and raw_defence > 0:
                row[venue] = _strength_scale(raw_defence, venue_values[venue])
                modes.append("defence")
            else:
                row[venue] = 0.5
                modes.append("overall_fallback_diagnostic_only")
            row[f"raw_{venue}"] = raw_defence if raw_defence > 0 else None
            row[f"diagnostic_{venue}"] = _strength_scale(raw_overall, overall_values[venue])
            row[f"result_games_{venue}"] = games
        row["metric"] = (
            "dynamic_bayesian_results" if all(mode == "dynamic_bayesian_results" for mode in modes)
            else "defence" if modes == ["defence", "defence"]
            else "overall_fallback_diagnostic_only"
        )
        ratings[team_id] = row
    return ratings


def fixture_map(fixtures, team_id, defence_ratings=None, n=15):
    out = []
    defence_ratings = defence_ratings or {}
    for fixture in fixtures:
        if fixture.get("finished") or team_id not in {fixture.get("team_h"), fixture.get("team_a")}:
            continue
        home = fixture.get("team_h") == team_id
        opponent = fixture.get("team_a") if home else fixture.get("team_h")
        opponent_venue = "away" if home else "home"
        rating = defence_ratings.get(opponent, {})
        out.append({
            "event": fixture.get("event"),
            "kickoff_time": fixture.get("kickoff_time"),
            "home": home,
            "opponent": opponent,
            "difficulty": fixture.get("team_h_difficulty") if home else fixture.get("team_a_difficulty"),
            "opponent_defence": rating.get(opponent_venue, 0.5),
            "opponent_defence_raw": rating.get(f"raw_{opponent_venue}"),
            "opponent_defence_diagnostic": rating.get(f"diagnostic_{opponent_venue}"),
            "opponent_defence_source": f"official_fpl_{rating.get('metric', 'unavailable')}",
            "opponent_defence_scoring_mode": "dynamic" if rating.get("metric") in {"defence", "dynamic_bayesian_results"} else "neutral_fallback",
        })
    return out[:n]


def set_piece_priors(player):
    order_weight = {1: 1.0, 2: 0.45, 3: 0.2}

    def weight(field, tail=0.08):
        order = int(f(player.get(field)))
        return order_weight.get(order, tail if order > 0 else 0.0)

    corners = weight("corners_and_indirect_freekicks_order")
    direct = weight("direct_freekicks_order")
    penalty_order = int(f(player.get("penalties_order")))
    penalty = {1: 1.0, 2: 0.25, 3: 0.08}.get(penalty_order, 0.02 if penalty_order > 0 else 0.0)
    return {
        # Orders identify likely takers but are not empirical event shares.
        "set_piece_share": None,
        "penalty_share": None,
        "set_piece_order_weight": clamp(0.65 * corners + 0.35 * direct),
        "penalty_order_weight": clamp(penalty),
        "corners_order": int(f(player.get("corners_and_indirect_freekicks_order"))) or None,
        "direct_freekicks_order": int(f(player.get("direct_freekicks_order"))) or None,
        "penalties_order": penalty_order or None,
        "source": "official_fpl_bootstrap_orders_inferred_metadata",
        "role_data_mode": "inferred_order_metadata_only",
    }


def tactical_role(player, advanced=None):
    """Infer a bounded tactical peer group from deep match evidence.

    This is deliberately labelled as an inference. It is more specific than an
    FPL position and is used only for competition and prior allocation.
    """
    advanced = advanced or {}
    position = int(player.get("element_type", 3))
    if position == 1:
        return "goalkeeper", "official_position"
    shots = f(advanced.get("shots_per90"))
    chances = f(advanced.get("chances_created_per90"))
    crosses = f(advanced.get("accurate_crosses_per90"))
    box = f(advanced.get("box_touches_per90"))
    clearances = f(advanced.get("clearances_per90"))
    aerials = f(advanced.get("aerials_won_per90"))
    tackles = f(advanced.get("tackles_per90"))
    recoveries = f(advanced.get("recoveries_per90"))
    attack_signal = shots + chances + crosses + 0.5 * box
    defence_signal = clearances + aerials + tackles + 0.35 * recoveries
    source = "deep_match_metrics" if advanced.get("decision_metrics_used") else "official_role_proxy"
    if position == 2:
        if attack_signal > max(1.0, 0.75 * defence_signal):
            return "attacking_fullback", source
        if defence_signal > max(1.0, 1.5 * attack_signal):
            return "central_defender", source
        return "hybrid_defender", source
    if position == 3:
        if shots + box > chances + crosses and shots + box > tackles + recoveries:
            return "attacking_midfielder", source
        if chances + crosses > shots + box and chances + crosses > tackles:
            return "creator_midfielder", source
        if tackles + recoveries > shots + chances + box:
            return "holding_midfielder", source
        return "balanced_midfielder", source
    if chances + crosses > shots + box:
        return "support_forward", source
    return "striker", source


def team_role_priors(elements, advanced, quality=None):
    quality = quality or _quality_config()
    params = quality.get("role_priors") or {}
    official_weight = f(params.get("official_order_weight"), 0.65)
    observed_weight = f(params.get("observed_event_weight"), 0.35)
    by_team = defaultdict(list)
    for player in elements:
        role = set_piece_priors(player)
        deep = advanced.get(player["id"], {})
        by_team[player["team"]].append((player, role, deep))
    result = {}
    for rows in by_team.values():
        team_sp = sum(f(deep.get("set_piece_xg")) for _, _, deep in rows)
        team_pen = sum(f(deep.get("penalty_events")) for _, _, deep in rows)
        sp_scores, pen_scores = {}, {}
        for player, role, deep in rows:
            sp_observed = f(deep.get("set_piece_xg")) / team_sp if team_sp > 0 else 0.0
            pen_observed = f(deep.get("penalty_events")) / team_pen if team_pen > 0 else 0.0
            sp_scores[player["id"]] = official_weight * f(role.get("set_piece_order_weight")) + observed_weight * sp_observed
            pen_scores[player["id"]] = official_weight * f(role.get("penalty_order_weight")) + observed_weight * pen_observed
        sp_total, pen_total = sum(sp_scores.values()), sum(pen_scores.values())
        sp_shares = {key: value / sp_total if sp_total else 0.0 for key, value in sp_scores.items()}
        pen_shares = {key: value / pen_total if pen_total else 0.0 for key, value in pen_scores.items()}
        sp_centre = sum(sp_shares.values()) / max(1, len(rows))
        pen_centre = sum(pen_shares.values()) / max(1, len(rows))
        for player, role, deep in rows:
            sp_share = sp_shares[player["id"]]
            pen_share = pen_shares[player["id"]]
            multiplier = clamp(
                1
                + f(params.get("set_piece_uplift"), 0.12) * (sp_share - sp_centre)
                + f(params.get("penalty_uplift"), 0.18) * (pen_share - pen_centre),
                0.9,
                1.2,
            )
            result[player["id"]] = {
                **role,
                "set_piece_share": sp_share,
                "penalty_share": pen_share,
                "role_attack_multiplier": multiplier,
                "role_prior_adjustment_applied": abs(multiplier - 1) > 1e-6,
                "source": "bayesian_official_order_plus_deep_events",
                "role_data_mode": "posterior_team_share",
                "role_scoring_mode": "prior_reallocation_no_direct_double_count",
                "observed_set_piece_xg": f(deep.get("set_piece_xg")),
                "observed_penalty_events": f(deep.get("penalty_events")),
            }
    return result


def player_priors(player, last_season=None):
    pos = int(player.get("element_type", 3))
    price = f(player.get("now_cost")) / 10
    ownership = f(player.get("selected_by_percent"))
    creativity = f(player.get("creativity"))
    threat = f(player.get("threat"))
    premium = clamp((price - 6.0) / 9.5)
    role = clamp((ownership / 35) * 0.25 + (threat / 100) * 0.45 + (creativity / 100) * 0.30)
    base_xg = XG_PRIOR[pos] * (1 + 0.75 * premium + 0.35 * role)
    base_xa = XA_PRIOR[pos] * (1 + 0.45 * premium + 0.45 * role)
    prior_weight = min(0.65, f((last_season or {}).get("minutes")) / 1800 * 0.65)
    xg = base_xg * (1 - prior_weight) + f((last_season or {}).get("xg_per90"), base_xg) * prior_weight
    xa = base_xa * (1 - prior_weight) + f((last_season or {}).get("xa_per90"), base_xa) * prior_weight
    return {
        "xg90_prior": xg,
        "xa90_prior": xa,
        "premium_prior": premium,
        "role_prior": role,
        "last_season_weight": prior_weight,
        "last_season_minutes": f((last_season or {}).get("minutes")),
        "last_season_source": (last_season or {}).get("source"),
        "last_season_identity_match": (last_season or {}).get("identity_match"),
    }


def team_defence_prior(team):
    strength = (f(team.get("strength_defence_home"), 1000) + f(team.get("strength_defence_away"), 1000)) / 2
    return clamp(0.30 + (strength - 1000) / 4000, 0.18, 0.48)


def minutes_contexts(elements, last_season, finished_events, advanced=None, quality=None):
    advanced = advanced or {}
    quality = quality or _quality_config()
    competition_cfg = quality.get("competition") or {}
    roles = {player["id"]: tactical_role(player, advanced.get(player["id"])) for player in elements}
    by_group = defaultdict(list)
    for player in elements:
        by_group[(player.get("team"), roles[player["id"]][0])].append(player)

    credible_by_team = defaultdict(int)
    for player in elements:
        previous = last_season.get(player["id"], {})
        current_rate = f(player.get("starts")) / max(1, finished_events)
        if f(previous.get("starts")) >= 8 or current_rate >= 0.5:
            credible_by_team[player.get("team")] += 1

    typical_slots = {1: 1.0, 2: 4.0, 3: 4.0, 4: 2.0}
    contexts = {}
    for player in elements:
        previous = last_season.get(player["id"], {})
        pos = int(player.get("element_type", 3))
        current_starts = f(player.get("starts"))
        current_minutes = f(player.get("minutes"))
        current_rate = clamp(current_starts / max(1, finished_events))
        current_minutes_rate = clamp(current_minutes / (90 * max(1, finished_events)))
        price_role = clamp((f(player.get("now_cost")) / 10 - 4) / 8)
        if previous:
            nailed = 0.65 * f(previous.get("start_rate")) + 0.35 * current_rate
            source = "current_starts+last_season_starts"
        else:
            nailed = 0.7 * current_rate + 0.3 * price_role
            source = "current_starts+weak_price_role_fallback"

        role_name, role_source = roles[player["id"]]
        group = by_group[(player.get("team"), role_name)]
        credible_peers = sum(
            1 for peer in group if peer["id"] != player["id"] and (
                f(last_season.get(peer["id"], {}).get("starts")) >= 8
                or f(peer.get("starts")) / max(1, finished_events) >= 0.5
            )
        )
        role_slots = f((competition_cfg.get("role_slots") or {}).get(role_name), typical_slots[pos])
        competition = clamp(max(0.0, credible_peers - (role_slots - 1)) / max(1.0, role_slots))
        squad_depth = clamp(max(0.0, credible_by_team[player.get("team")] - 11) / 20, 0.0, 0.3)
        prior_start_minutes = f(previous.get("avg_minutes_when_start"), 0)
        current_start_minutes = current_minutes / current_starts if current_starts > 0 else 0
        if prior_start_minutes and current_start_minutes:
            average_start_minutes = 0.7 * prior_start_minutes + 0.3 * current_start_minutes
        elif prior_start_minutes:
            average_start_minutes = prior_start_minutes
        elif current_start_minutes:
            average_start_minutes = 0.3 * current_start_minutes + 0.7 * 72
        else:
            average_start_minutes = 68
        context = {
            "nailed_prior": clamp(nailed),
            "current_start_rate": current_rate,
            "current_minutes_rate": current_minutes_rate,
            "last_season_start_rate": f(previous.get("start_rate")),
            "prior_season_available": bool(previous),
            "sub_appearance_signal": float(current_starts == 0 and current_minutes > 0),
            "competition_pressure": competition,
            "competition_source": "inferred_tactical_role_peer_group",
            "competition_start_weight": f(competition_cfg.get("start_probability_weight"), 0.16),
            "squad_depth_weight": f(competition_cfg.get("squad_depth_weight"), 0.08),
            "tactical_role": role_name,
            "tactical_role_source": role_source,
            "squad_depth_pressure": squad_depth,
            "squad_depth_source": "credible_squad_count_diagnostic_only",
            "avg_minutes_when_start": average_start_minutes,
            "xmins_prior_source": source,
        }
        competition_factor, competition_uncertainty = competition_adjustment(context, current_rate)
        context["competition_factor"] = round(competition_factor, 4)
        context["competition_uncertainty"] = round(competition_uncertainty, 4)
        context["competition_adjustment_applied"] = context["competition_factor"] < 1
        contexts[player["id"]] = context
    return contexts


def advanced_materially_distinct(player, advanced):
    if not advanced or "fpl_core_insights:playermatchstats" not in advanced.get("sources", []):
        return False
    minutes = max(1.0, f(player.get("minutes")))
    official_xg90 = f(player.get("expected_goals")) * 90 / minutes
    official_xa90 = f(player.get("expected_assists")) * 90 / minutes
    official_def90 = f(player.get("defensive_contribution")) * 90 / minutes
    return (
        abs(f(advanced.get("xg_per90")) - official_xg90) > 0.01
        or abs(f(advanced.get("xa_per90")) - official_xa90) > 0.01
        or abs(f(advanced.get("defensive_contribution_per90")) - official_def90) > 0.1
    )


def build_predictions(bootstrap, fixtures, generated_at, stats_gw=None):
    elements = bootstrap.get("elements", [])
    teams = {team["id"]: team for team in bootstrap.get("teams", [])}
    strengths = {team_id: team_strength(team_id, elements) for team_id in teams}
    identity = build_identity_index(elements, "2026-27")
    enrichment = load_prediction_enrichment(elements, stats_gw)
    advanced = enrichment["advanced"]
    last_season = enrichment["last_season"]
    quality = _quality_config()
    finished_events = sum(bool(event.get("finished")) for event in bootstrap.get("events", []))
    xmins_context = minutes_contexts(elements, last_season, max(1, finished_events), advanced, quality)
    role_priors = team_role_priors(elements, advanced, quality)
    defence_ratings = opponent_defence_ratings(teams, fixtures, quality)
    rows = []
    materially_distinct = 0
    advanced_decision_used = 0
    for player in elements:
        priors = player_priors(player, last_season.get(player["id"]))
        role = role_priors[player["id"]]
        player_advanced = advanced.get(player["id"])
        material_advanced = advanced_materially_distinct(player, player_advanced)
        materially_distinct += int(material_advanced)
        advanced_decision_used += int(bool((player_advanced or {}).get("decision_metrics_used")))
        fixtures_for_player = fixture_map(fixtures, player["team"], defence_ratings, 15)
        context = {
            "team_attack": strengths.get(player["team"], {}).get("attack", 1),
            "team_cs_prior": team_defence_prior(teams[player["team"]]),
            "point_in_time": generated_at,
            "advanced_source": "+".join((player_advanced or {}).get("sources", [])) or "official_fpl_current_state",
            "advanced_identity_match": (player_advanced or {}).get("identity_match"),
            "advanced_materially_distinct": material_advanced,
            "xg90_prior": priors["xg90_prior"],
            "xa90_prior": priors["xa90_prior"],
            "premium_prior": priors["premium_prior"],
            "role_prior": priors["role_prior"],
            "last_season_weight": priors["last_season_weight"],
            "last_season_source": priors["last_season_source"],
            "set_piece_share": role["set_piece_share"],
            "penalty_share": role["penalty_share"],
            "set_piece_order_weight": role["set_piece_order_weight"],
            "penalty_order_weight": role["penalty_order_weight"],
            "set_piece_source": role["source"],
            "role_attack_multiplier": role["role_attack_multiplier"],
            "role_prior_adjustment_applied": role["role_prior_adjustment_applied"],
            "role_scoring_mode": role["role_scoring_mode"],
            **xmins_context[player["id"]],
        }
        row = project_horizon(player, fixtures_for_player, context, player_advanced, n=15)
        row["stable_key"] = identity["by_element"][player["id"]]["key"]
        row["priors"] = {
            **{key: round(value, 4) if isinstance(value, (int, float)) else value for key, value in priors.items()},
            **role,
            **xmins_context[player["id"]],
        }
        price_millions = max(0.1, f(player.get("now_cost")) / 10)
        row["value"] = {
            "price_millions": round(price_millions, 1),
            "xpts5_per_million": round(row["xpts_5"] / price_millions, 4),
            "xpts15_per_million": round(row["xpts_15"] / price_millions, 4),
            "decision_usage": "optimizer_objective_bounded_value_term",
        }
        rows.append(row)
    rows.sort(key=lambda row: row["xpts_5"], reverse=True)
    return {
        "schema_version": 492,
        "model_version": "v4.9.2-truthful-health",
        "generated_at": generated_at,
        "point_in_time": True,
        "input_coverage": {
            "players": len(elements),
            "advanced_matched": len(advanced),
            "advanced_materially_distinct": materially_distinct,
            "advanced_decision_used": advanced_decision_used,
            "advanced_decision_used_ratio": round(advanced_decision_used / max(1, len(elements)), 4),
            "last_season_matched": len(last_season),
            **enrichment["meta"],
        },
        "capability_evidence": {
            "tactical_role_coverage": sum(bool((row.get("priors") or {}).get("tactical_role")) for row in rows),
            "role_competition_adjustments": sum(bool((row.get("priors") or {}).get("competition_adjustment_applied")) for row in rows),
            "role_competition_factor_variants": len({
                round(f((row.get("priors") or {}).get("competition_factor"), 1), 4) for row in rows
            }),
            "dynamic_opponent_fixtures": sum(
                (fixture.get("provenance") or {}).get("opponent_defence_scoring_mode") == "dynamic"
                for row in rows for fixture in (row.get("fixtures") or [])[:3]
            ),
            "value_coverage": sum(bool(row.get("value")) for row in rows),
            "advanced_decision_coverage": advanced_decision_used,
        },
        "players": rows,
    }
