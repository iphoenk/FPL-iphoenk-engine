from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.intelligence.role_intelligence import build_role_intelligence
from src.v5.intelligence.team_strength import build_team_strength
from src.v5.intelligence.xmins import estimate_xmins

CONFIG = "config/intelligence/projection.json"
DEFENSIVE_COMPONENTS = ("clean_sheet", "saves", "defensive_contribution", "bonus")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _blended_rate(player: dict[str, Any], field: str, prior: float, shrink: float) -> tuple[float, str]:
    minutes = max(0.0, _f(player.get("minutes")))
    cumulative = max(0.0, _f(player.get(field)))
    observed = cumulative * 90.0 / minutes if minutes > 0 else prior
    value = (observed * minutes + prior * shrink) / max(1e-6, minutes + shrink)
    return max(0.0, value), ("observed_shrunk_to_prior" if minutes > 0 else "prior_only")


def _historical_rate_prior(position_prior: float, historical: dict[str, Any], field: str) -> tuple[float, str, float]:
    if not historical or historical.get(field) is None:
        return max(0.0, position_prior), "position_prior", 0.0
    weight = clamp(_f(historical.get("attacking_prior_weight")), 0.0, 1.0)
    if weight <= 0:
        return max(0.0, position_prior), "position_prior", 0.0
    historical_rate = max(0.0, _f(historical.get(field)))
    return (
        position_prior * (1.0 - weight) + historical_rate * weight,
        "historical_player_prior+position_prior",
        weight,
    )


def _p60(xmins: dict[str, Any], cfg: dict[str, Any]) -> float:
    transition = cfg.get("appearance_60_probability_transition") or {}
    low = _f(transition.get("start_minutes_low"), 55.0)
    high = max(low + 1.0, _f(transition.get("start_minutes_high"), 70.0))
    conditional = clamp((_f(xmins.get("starter_minutes_if_start"), 72.0) - low) / (high - low), 0.0, 1.0)
    return clamp(_f(xmins.get("start_probability")) * conditional, 0.0, 1.0)


def _position_projection_diagnostics(players: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "players": set(),
            "fixture_rows": 0,
            "xpts": 0.0,
            "appearance": 0.0,
            "attack": 0.0,
            "clean_sheet": 0.0,
            "saves": 0.0,
            "defensive_contribution": 0.0,
            "bonus": 0.0,
        }
    )
    for player in players:
        position = str(player.get("position") or "UNKNOWN")
        bucket = buckets[position]
        bucket["players"].add(int(player.get("element") or -1))
        for gw_row in player.get("xpts_by_gw") or []:
            for fixture in gw_row.get("fixtures") or []:
                components = fixture.get("components") if isinstance(fixture.get("components"), dict) else {}
                bucket["fixture_rows"] += 1
                bucket["xpts"] += _f(fixture.get("mean"))
                for key in ("appearance", "attack", *DEFENSIVE_COMPONENTS):
                    bucket[key] += _f(components.get(key))

    positions: dict[str, Any] = {}
    for position, bucket in sorted(buckets.items()):
        count = int(bucket["fixture_rows"])
        divisor = max(1, count)
        total = _f(bucket["xpts"])
        defensive_total = sum(_f(bucket[key]) for key in DEFENSIVE_COMPONENTS)
        positions[position] = {
            "player_count": len(bucket["players"]),
            "fixture_rows": count,
            "mean_xpts_per_fixture": round(total / divisor, 4),
            "mean_components_per_fixture": {
                key: round(_f(bucket[key]) / divisor, 4)
                for key in ("appearance", "attack", *DEFENSIVE_COMPONENTS)
            },
            "defensive_component_share": round(defensive_total / total, 4) if total > 0 else 0.0,
            "ablation_mean_xpts_per_fixture": {
                f"without_{key}": round((total - _f(bucket[key])) / divisor, 4)
                for key in DEFENSIVE_COMPONENTS
            },
        }
    return {
        "status": "READY" if positions else "NO_FIXTURE_SAMPLE",
        "mutates_xpts": False,
        "positions": positions,
        "governance": {
            "diagnostics_are_observational_only": True,
            "component_observability_does_not_change_projection_formula": True,
            "tactical_enrichment_may_not_mutate_xpts": True,
            "clean_sheet_probability_consumed_once": True,
        },
    }


def build_predictions(
    bootstrap: dict[str, Any],
    fixtures: list[dict[str, Any]],
    rules: dict[str, Any],
    planning_gw: int,
    horizon: int = 15,
    *,
    historical_prior: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    strength = build_team_strength(bootstrap, fixtures)
    teams = {int(t["id"]): t.get("name") for t in bootstrap.get("teams") or []}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    team_rows = {int(t["team_id"]): t for t in strength.get("teams") or []}
    team_matches = {team_id: int(row.get("matches_played") or 0) for team_id, row in team_rows.items()}
    roles = build_role_intelligence(bootstrap, team_matches)
    role_rows = roles.get("players") or {}
    role_adjustment = roles.get("projection_adjustment") or {}
    matchups_by_team: dict[int, list[dict[str, Any]]] = {}
    for matchup in strength.get("matchups") or []:
        for tid in (int(matchup["team_h"]), int(matchup["team_a"])):
            matchups_by_team.setdefault(tid, []).append(matchup)
    for rows in matchups_by_team.values():
        rows.sort(key=lambda x: (int(x.get("event") or 999), x.get("kickoff_time") or ""))

    goal_points = {int(k): int(v) for k, v in (rules.get("goal_points") or {}).items()}
    cs_points = {int(k): int(v) for k, v in (rules.get("clean_sheet_points") or {}).items()}
    assist_points = int(rules.get("assist_points") or 3)
    shrink = max(1.0, _f(cfg.get("rate_shrinkage_minutes"), 450.0))
    priors = cfg.get("position_priors") or {}
    historical_map = (
        historical_prior.get("players")
        if isinstance(historical_prior, dict) and isinstance(historical_prior.get("players"), dict)
        else {}
    )
    historical_enabled = bool((cfg.get("historical_prior") or {}).get("enabled", True))
    league_baseline = strength.get("baseline") or {}
    players = []
    historical_used = 0

    for player in bootstrap.get("elements") or []:
        element_id = int(player["id"])
        element_type = int(player.get("element_type") or 4)
        position = positions.get(element_type, "FWD")
        position_prior = priors.get(position) or priors.get("FWD") or {}
        historical = historical_map.get(str(element_id)) if historical_enabled else None
        historical = historical if isinstance(historical, dict) else {}
        historical_used += int(bool(historical))

        xg_prior, xg_prior_source, attack_weight = _historical_rate_prior(
            _f(position_prior.get("xg90")), historical, "xg90"
        )
        xa_prior, xa_prior_source, _ = _historical_rate_prior(
            _f(position_prior.get("xa90")), historical, "xa90"
        )
        xg90, xg_source = _blended_rate(player, "expected_goals", xg_prior, shrink)
        xa90, xa_source = _blended_rate(player, "expected_assists", xa_prior, shrink)
        bonus90, bonus_source = _blended_rate(player, "bonus", _f(position_prior.get("bonus90")), shrink)
        saves90, saves_source = _blended_rate(player, "saves", _f(position_prior.get("saves90")), shrink)
        dc90 = _f(position_prior.get("dc90"))
        rates = {"xg90": xg90, "xa90": xa90, "bonus90": bonus90, "saves90": saves90, "dc90": dc90}
        team_id = int(player.get("team") or -1)
        role = role_rows.get(element_id) if isinstance(role_rows, dict) else None
        role = role if isinstance(role, dict) else {}
        xmins_context = {
            "team_matches_played": int((team_rows.get(team_id) or {}).get("matches_played") or 0),
            "role_start_probability": role.get("role_start_probability"),
            "rotation_risk": role.get("rotation_risk"),
        }
        if historical:
            xmins_context.update(
                {
                    "prior_start_probability": historical.get("start_probability"),
                    "starter_minutes_prior": historical.get("avg_minutes_when_start"),
                    "prior_evidence_minutes": historical.get("minutes"),
                    "prior_source": historical.get("source"),
                    "prior_identity_match": historical.get("identity_match"),
                }
            )
        xmins = estimate_xmins(player, xmins_context)
        p60 = _p60(xmins, cfg)
        share = clamp(_f(xmins.get("expected_minutes")) / 90.0, 0.0, 1.0)
        team_matchups = [
            m
            for m in matchups_by_team.get(team_id, [])
            if planning_gw <= int(m.get("event") or -1) < planning_gw + horizon
        ]
        by_gw = []
        network_fixtures = []
        for gw in range(planning_gw, planning_gw + horizon):
            details = []
            for matchup in [m for m in team_matchups if int(m.get("event") or -1) == gw]:
                home = int(matchup["team_h"]) == team_id
                team_xg = _f(matchup.get("home_expected_goals") if home else matchup.get("away_expected_goals"), 1.3)
                league_base = _f(league_baseline.get("home_goals" if home else "away_goals"), 1.3)
                attack_multiplier = clamp(
                    team_xg / max(0.2, league_base),
                    _f(cfg.get("attack_multiplier_min"), 0.55),
                    _f(cfg.get("attack_multiplier_max"), 1.75),
                )
                cs_prob = clamp(
                    _f(matchup.get("home_clean_sheet_probability") if home else matchup.get("away_clean_sheet_probability")),
                    0.0,
                    1.0,
                )
                appearance = _f(xmins.get("start_probability")) * (1.0 + p60) + _f(xmins.get("bench_probability"))
                set_piece_multiplier = 1.0 + _f(role_adjustment.get("set_piece_assist_uplift"), 0.08) * _f(role.get("set_piece_share"))
                penalty_multiplier = 1.0 + _f(role_adjustment.get("penalty_goal_uplift"), 0.18) * _f(role.get("penalty_share"))
                attack = (
                    xg90 * penalty_multiplier * goal_points.get(element_type, 4)
                    + xa90 * set_piece_multiplier * assist_points
                ) * share * attack_multiplier
                clean = cs_points.get(element_type, 0) * cs_prob * p60
                saves = (saves90 / 3.0) * share if position == "GK" else 0.0
                defensive_contribution = dc90 * share
                bonus = bonus90 * share
                components = {
                    "appearance": appearance,
                    "attack": attack,
                    "clean_sheet": clean,
                    "saves": saves,
                    "defensive_contribution": defensive_contribution,
                    "bonus": bonus,
                }
                raw_mean = sum(components.values())
                mean = max(0.0, raw_mean)
                if abs(mean - raw_mean) > 1e-9:
                    raise RuntimeError("V5 projection component sum became negative before non-negative clamp")
                unc = cfg.get("uncertainty") or {}
                std = max(
                    _f(unc.get("minimum_points_std"), 1.15),
                    mean * _f(unc.get("coefficient_of_variation"), 0.42)
                    + _f(xmins.get("minutes_std")) * _f(unc.get("xmins_std_points_multiplier"), 0.035)
                    + (_f(unc.get("small_sample_extra_std"), 0.45) if xmins.get("small_sample_guard") else 0.0),
                )
                row = {
                    "gw": gw,
                    "event": gw,
                    "kickoff_time": matchup.get("kickoff_time"),
                    "opponent": matchup.get("team_a") if home else matchup.get("team_h"),
                    "home": home,
                    "xpts": round(mean, 3),
                    "mean": round(mean, 3),
                    "std": round(std, 3),
                    "clean_sheet_probability": round(cs_prob, 4),
                    "components": {key: round(value, 4) for key, value in components.items()},
                    "component_sum": round(raw_mean, 4),
                }
                details.append(row)
                if len(network_fixtures) < 5:
                    network_fixtures.append(
                        {
                            "event": gw,
                            "xpts": row["xpts"],
                            "lower80": round(max(0.0, mean - 1.28 * std), 3),
                            "upper80": round(mean + 1.28 * std, 3),
                            "xmins": {
                                key: xmins.get(key)
                                for key in ("start_probability", "bench_probability", "dnp_probability", "expected_minutes")
                            },
                        }
                    )
            gw_mean = sum(_f(x.get("mean")) for x in details)
            gw_std = math.sqrt(sum(_f(x.get("std")) ** 2 for x in details)) if details else 0.0
            by_gw.append(
                {
                    "gw": gw,
                    "mean": round(gw_mean, 3),
                    "std": round(gw_std, 3),
                    "clean_sheet_probability": round(
                        1 - math.prod(1 - _f(x.get("clean_sheet_probability")) for x in details), 4
                    ) if details else 0.0,
                    "fixtures": details,
                }
            )
        horizons = {}
        for h in (3, 5, 10, 15):
            subset = by_gw[:h]
            horizons[str(h)] = {
                "mean": round(sum(_f(x["mean"]) for x in subset), 3),
                "std": round(math.sqrt(sum(_f(x["std"]) ** 2 for x in subset)), 3),
            }
        players.append(
            {
                "element": element_id,
                "name": player.get("web_name"),
                "team_id": team_id,
                "team": teams.get(team_id),
                "position": position,
                "element_type": element_type,
                "now_cost": int(player.get("now_cost") or 0),
                "status": player.get("status"),
                "ownership_pct": _f(player.get("selected_by_percent")),
                "current_season": {
                    "starts": int(player.get("starts") or 0),
                    "minutes": int(player.get("minutes") or 0),
                },
                "historical_prior": historical or None,
                "xmins": xmins,
                "xpts_by_gw": by_gw,
                "horizons": horizons,
                "xpts_3": horizons["3"]["mean"],
                "xpts_5": horizons["5"]["mean"],
                "xpts_10": horizons["10"]["mean"],
                "xpts_15": horizons["15"]["mean"],
                "mean_xpts": by_gw[0]["mean"] if by_gw else 0.0,
                "uncertainty": by_gw[0]["std"] if by_gw else 0.0,
                "fixtures": network_fixtures,
                "role": {
                    "role_start_probability": role.get("role_start_probability"),
                    "competition_pressure": role.get("competition_pressure"),
                    "rotation_risk": role.get("rotation_risk"),
                    "set_piece_share": role.get("set_piece_share"),
                    "penalty_share": role.get("penalty_share"),
                    "set_piece_source": role.get("source"),
                },
                "rates": {
                    **{key: round(value, 4) for key, value in rates.items()},
                    "sources": {
                        "xg90": f"{xg_source}|prior={xg_prior_source}",
                        "xa90": f"{xa_source}|prior={xa_prior_source}",
                        "bonus90": bonus_source,
                        "saves90": saves_source,
                        "dc90": "position_prior",
                    },
                    "historical_attacking_prior_weight": round(attack_weight, 4),
                },
                "projection_confidence": xmins.get("confidence"),
            }
        )
    return {
        "generated_at": _now(),
        "schema_version": 513,
        "model_version": str(cfg.get("model_id") or "player_projection_v5_historical_prior"),
        "ruleset_id": rules.get("ruleset_id"),
        "planning_gw": planning_gw,
        "horizon_gws": horizon,
        "historical_prior": {
            "model": historical_prior.get("model") if isinstance(historical_prior, dict) else None,
            "season": historical_prior.get("season") if isinstance(historical_prior, dict) else None,
            "status": historical_prior.get("status") if isinstance(historical_prior, dict) else "UNAVAILABLE",
            "fetch_mode": historical_prior.get("fetch_mode") if isinstance(historical_prior, dict) else None,
            "coverage": historical_prior.get("coverage") if isinstance(historical_prior, dict) else None,
            "players_used": historical_used,
        },
        "team_strength": strength,
        "role_intelligence": {
            "model": roles.get("model"),
            "capabilities": roles.get("capabilities"),
            "non_claims": roles.get("non_claims"),
        },
        "projection_diagnostics": _position_projection_diagnostics(players),
        "players": players,
        "network_contract": {
            "bounded": True,
            "max_fixture_rows_per_player": 5,
            "full_provenance_omitted": True,
        },
    }
