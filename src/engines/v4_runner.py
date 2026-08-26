from __future__ import annotations

from collections import defaultdict

from src.models.player_identity import build_identity_index
from src.models.v4_prediction import XA_PRIOR, XG_PRIOR, clamp, project_horizon, team_strength
from src.models.v4_prediction_inputs import load_prediction_enrichment


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


def opponent_defence_ratings(teams):
    # The official API can expose zeroed attack/defence splits early in a season.
    # In that case its venue-specific overall band is the truthful dynamic fallback.
    def metric(team, venue):
        defence = f(team.get(f"strength_defence_{venue}"))
        return defence if defence > 0 else f(team.get(f"strength_overall_{venue}"), 3)

    home_values = [metric(team, "home") for team in teams.values()]
    away_values = [metric(team, "away") for team in teams.values()]
    return {
        team_id: {
            "home": _strength_scale(metric(team, "home"), home_values),
            "away": _strength_scale(metric(team, "away"), away_values),
            "raw_home": metric(team, "home"),
            "raw_away": metric(team, "away"),
            "metric": "defence" if f(team.get("strength_defence_home")) > 0 else "overall_fallback",
        }
        for team_id, team in teams.items()
    }


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
            "opponent_defence_source": f"official_fpl_{rating.get('metric', 'venue_strength')}_venue_normalized",
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
        "set_piece_share": clamp(0.65 * corners + 0.35 * direct),
        "penalty_share": clamp(penalty),
        "corners_order": int(f(player.get("corners_and_indirect_freekicks_order"))) or None,
        "direct_freekicks_order": int(f(player.get("direct_freekicks_order"))) or None,
        "penalties_order": penalty_order or None,
        "source": "official_fpl_bootstrap_orders",
    }


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


def minutes_contexts(elements, last_season, finished_events):
    by_group = defaultdict(list)
    for player in elements:
        by_group[(player.get("team"), player.get("element_type"))].append(player)

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
        current_rate = clamp(f(player.get("starts")) / max(1, finished_events))
        price_role = clamp((f(player.get("now_cost")) / 10 - 4) / 8)
        if previous:
            nailed = 0.65 * f(previous.get("start_rate")) + 0.35 * current_rate
            source = "current_starts+last_season_starts"
        else:
            nailed = 0.7 * current_rate + 0.3 * price_role
            source = "current_starts+weak_price_role_fallback"

        group = by_group[(player.get("team"), player.get("element_type"))]
        credible_peers = sum(
            1 for peer in group if peer["id"] != player["id"] and (
                f(last_season.get(peer["id"], {}).get("starts")) >= 8
                or f(peer.get("starts")) / max(1, finished_events) >= 0.5
            )
        )
        competition = clamp(max(0.0, credible_peers - (typical_slots[pos] - 1)) / max(1.0, typical_slots[pos]))
        rotation = clamp(max(0.0, credible_by_team[player.get("team")] - 11) / 20, 0.0, 0.3)
        contexts[player["id"]] = {
            "nailed_prior": clamp(nailed),
            "competition_pressure": competition,
            "manager_rotation_rate": rotation,
            "avg_minutes_when_start": f(previous.get("avg_minutes_when_start"), 78 if current_rate >= 0.5 else 68),
            "xmins_prior_source": source,
        }
    return contexts


def build_predictions(bootstrap, fixtures, generated_at, stats_gw=None):
    elements = bootstrap.get("elements", [])
    teams = {team["id"]: team for team in bootstrap.get("teams", [])}
    strengths = {team_id: team_strength(team_id, elements) for team_id in teams}
    identity = build_identity_index(elements, "2026-27")
    enrichment = load_prediction_enrichment(elements, stats_gw)
    advanced = enrichment["advanced"]
    last_season = enrichment["last_season"]
    finished_events = sum(bool(event.get("finished")) for event in bootstrap.get("events", []))
    xmins_context = minutes_contexts(elements, last_season, max(1, finished_events))
    defence_ratings = opponent_defence_ratings(teams)
    rows = []
    for player in elements:
        priors = player_priors(player, last_season.get(player["id"]))
        role = set_piece_priors(player)
        player_advanced = advanced.get(player["id"])
        fixtures_for_player = fixture_map(fixtures, player["team"], defence_ratings, 15)
        context = {
            "team_attack": strengths.get(player["team"], {}).get("attack", 1),
            "team_cs_prior": team_defence_prior(teams[player["team"]]),
            "point_in_time": generated_at,
            "advanced_source": "+".join((player_advanced or {}).get("sources", [])) or "official_fpl_current_state",
            "advanced_identity_match": (player_advanced or {}).get("identity_match"),
            "xg90_prior": priors["xg90_prior"],
            "xa90_prior": priors["xa90_prior"],
            "premium_prior": priors["premium_prior"],
            "role_prior": priors["role_prior"],
            "last_season_weight": priors["last_season_weight"],
            "last_season_source": priors["last_season_source"],
            "set_piece_share": role["set_piece_share"],
            "penalty_share": role["penalty_share"],
            "set_piece_source": role["source"],
            **xmins_context[player["id"]],
        }
        row = project_horizon(player, fixtures_for_player, context, player_advanced, n=15)
        row["stable_key"] = identity["by_element"][player["id"]]["key"]
        row["priors"] = {
            **{key: round(value, 4) if isinstance(value, (int, float)) else value for key, value in priors.items()},
            **role,
            **xmins_context[player["id"]],
        }
        rows.append(row)
    rows.sort(key=lambda row: row["xpts_5"], reverse=True)
    return {
        "schema_version": 470,
        "model_version": "v4.7-prediction-quality",
        "generated_at": generated_at,
        "point_in_time": True,
        "input_coverage": {
            "players": len(elements),
            "advanced_matched": len(advanced),
            "last_season_matched": len(last_season),
            **enrichment["meta"],
        },
        "players": rows,
    }
