from __future__ import annotations

import math
from typing import Any

from src.models.projection_components import (
    _blended_rate,
    _f,
    _project_fixture,
    load_projection_config,
    poisson_threshold_probability,
)
from src.models.xmins_v3 import estimate_xmins
from src.rules import DC_RULES, ELEMENT_TYPE_TO_POSITION, RULESET_ID


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rate_prior(position_prior: float, historical: dict[str, Any], field: str) -> tuple[float, str, float]:
    weight = _clamp(_f(historical.get("attacking_prior_weight")), 0.0, 1.0)
    if not historical or weight <= 0 or historical.get(field) is None:
        return max(0.0, position_prior), "position_prior", 0.0
    historical_rate = max(0.0, _f(historical.get(field)))
    return position_prior * (1.0 - weight) + historical_rate * weight, "historical_player_prior+position_prior", weight


def _defensive_contribution_model(
    element_type: int,
    position: str,
    feature: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    rule = dict(DC_RULES.get(element_type, DC_RULES[4]))
    eligible = bool(rule.get("eligible"))
    threshold = rule.get("threshold")
    points_when_hit = int(rule.get("points") or 0)
    prior_rates = policy.get("position_count_rate90_prior") or {}
    prior_rate90 = max(0.0, _f(prior_rates.get(position), 0.0))
    shrink_minutes = max(0.0, _f(policy.get("shrinkage_minutes"), 450.0))
    advanced = feature.get("advanced_current") or {}
    evidence_minutes = max(0.0, _f(advanced.get("minutes")))
    observed_rate = advanced.get("dc_reconstructed_per90")

    if not eligible or threshold is None:
        count_rate90 = 0.0
        source = "official_rule_ineligible"
    elif observed_rate is not None and evidence_minutes > 0:
        count_rate90 = (
            max(0.0, _f(observed_rate)) * evidence_minutes + prior_rate90 * shrink_minutes
        ) / max(1e-6, evidence_minutes + shrink_minutes)
        source = "player_feature_shrunk_to_position_prior"
    else:
        count_rate90 = prior_rate90
        source = "position_count_rate_prior_fallback"

    expected_points90 = (
        points_when_hit * poisson_threshold_probability(count_rate90, 90.0, int(threshold))
        if eligible and threshold is not None else 0.0
    )
    return {
        "model": "player_dc_poisson_threshold_v1",
        "eligible": eligible,
        "threshold": int(threshold) if threshold is not None else None,
        "points_when_hit": points_when_hit,
        "count_rate90": round(count_rate90, 6),
        "prior_count_rate90": round(prior_rate90, 6),
        "observed_count_rate90": round(_f(observed_rate), 6) if observed_rate is not None else None,
        "evidence_minutes": round(evidence_minutes, 1),
        "sample_quality": advanced.get("sample_quality"),
        "observed_threshold_hits": advanced.get("dc_threshold_hits"),
        "observed_threshold_hit_rate": advanced.get("dc_threshold_hit_rate"),
        "expected_points90": round(expected_points90, 6),
        "source": source,
        "distribution": str(policy.get("distribution") or "poisson_count_threshold"),
        "official_threshold_rule": True,
    }


def build(
    bootstrap: dict[str, Any],
    strength: dict[str, Any],
    planning_gw: int,
    prior_payload: dict[str, Any],
    horizon: int | None = None,
    player_features_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_projection_config()
    published_horizons = [int(value) for value in cfg.get("published_horizons") or []]
    if not published_horizons or any(value <= 0 for value in published_horizons):
        raise RuntimeError("projection published_horizons must be configured as positive integers")
    horizon = int(horizon or max(published_horizons))
    if horizon < max(published_horizons):
        raise RuntimeError("projection runtime horizon cannot be shorter than published horizons")
    model_id = str(cfg.get("historical_model_id") or "").strip()
    if not model_id:
        raise RuntimeError("projection historical_model_id missing from config")

    player_features_payload = player_features_payload or {}
    feature_map = player_features_payload.get("players") or {}
    dc_policy = player_features_payload.get("defensive_contribution_policy") or {}

    teams = {int(team["id"]): team.get("name") for team in bootstrap.get("teams") or []}
    positions = dict(ELEMENT_TYPE_TO_POSITION)
    team_rows = {int(team["team_id"]): team for team in strength.get("teams") or []}
    historical_map = prior_payload.get("players") or {}
    matchups_by_team: dict[int, list[dict[str, Any]]] = {}
    for matchup in strength.get("matchups") or []:
        for team_id in (int(matchup["team_h"]), int(matchup["team_a"])):
            matchups_by_team.setdefault(team_id, []).append(matchup)
    for rows in matchups_by_team.values():
        rows.sort(key=lambda row: (int(row.get("event") or 999), row.get("kickoff_time") or ""))

    shrink = float(cfg.get("rate_shrinkage_minutes") or 0)
    if shrink <= 0:
        raise RuntimeError("projection rate_shrinkage_minutes must be positive")
    position_priors = cfg.get("position_priors") or {}
    players = []
    historical_used = 0
    player_dc_evidence_used = 0
    for player in bootstrap.get("elements") or []:
        element = int(player["id"])
        element_type = int(player.get("element_type") or 0)
        position = positions.get(element_type)
        if not position:
            raise RuntimeError(f"unsupported Official element_type: {element_type}")
        base = position_priors.get(position)
        if not isinstance(base, dict):
            raise RuntimeError(f"projection prior missing for position {position}")
        historical = historical_map.get(str(element)) or {}
        historical_used += int(bool(historical))
        xg_prior, xg_prior_source, attack_weight = _rate_prior(_f(base.get("xg90")), historical, "xg90")
        xa_prior, xa_prior_source, _ = _rate_prior(_f(base.get("xa90")), historical, "xa90")
        xg90, xg_source = _blended_rate(player, "expected_goals", xg_prior, shrink)
        xa90, xa_source = _blended_rate(player, "expected_assists", xa_prior, shrink)
        bonus90, bonus_source = _blended_rate(player, "bonus", _f(base.get("bonus90")), shrink)
        saves90, saves_source = _blended_rate(player, "saves", _f(base.get("saves90")), shrink)

        feature = feature_map.get(str(element)) or {}
        dc_model = _defensive_contribution_model(element_type, position, feature, dc_policy)
        player_dc_evidence_used += int(
            dc_model.get("eligible") is True
            and _f(dc_model.get("evidence_minutes")) > 0
            and dc_model.get("observed_count_rate90") is not None
        )
        rates = {
            "xg90": xg90,
            "xa90": xa90,
            "bonus90": bonus90,
            "saves90": saves90,
            "dc90": _f(dc_model.get("expected_points90")),
        }
        fixture_rates: dict[str, Any] = {**rates, "dc_model": dc_model}

        team_id = int(player.get("team") or -1)
        matches_played = int((team_rows.get(team_id) or {}).get("matches_played") or 0)
        context: dict[str, Any] = {"team_matches_played": matches_played}
        if historical:
            context.update({
                "prior_start_probability": historical.get("start_probability"),
                "starter_minutes_prior": historical.get("avg_minutes_when_start"),
                "prior_evidence_minutes": historical.get("minutes"),
                "prior_source": historical.get("source"),
                "prior_identity_match": historical.get("identity_match"),
            })
        xmins = estimate_xmins(player, context)
        fixtures = [
            matchup
            for matchup in matchups_by_team.get(team_id, [])
            if planning_gw <= int(matchup.get("event") or -1) < planning_gw + horizon
        ]
        by_gw = []
        for gw in range(planning_gw, planning_gw + horizon):
            details = []
            for matchup in (row for row in fixtures if int(row.get("event") or -1) == gw):
                details.append(
                    _project_fixture(
                        player,
                        xmins,
                        matchup,
                        int(matchup["team_h"]) == team_id,
                        fixture_rates,
                        bool(xmins.get("small_sample_guard")),
                    )
                )
            mean = sum(_f(row.get("mean")) for row in details)
            std = math.sqrt(sum(_f(row.get("std")) ** 2 for row in details)) if details else 0.0
            no_clean_sheet = 1.0
            for row in details:
                no_clean_sheet *= 1.0 - _f(row.get("clean_sheet_probability"))
            by_gw.append({
                "gw": gw,
                "mean": round(mean, 3),
                "std": round(std, 3),
                "clean_sheet_probability": round(1.0 - no_clean_sheet, 4) if details else 0.0,
                "fixtures": details,
            })

        horizons = {}
        for published in published_horizons:
            subset = by_gw[:published]
            horizons[str(published)] = {
                "mean": round(sum(_f(row["mean"]) for row in subset), 3),
                "std": round(math.sqrt(sum(_f(row["std"]) ** 2 for row in subset)), 3),
            }
        players.append({
            "element": element,
            "name": player.get("web_name"),
            "team_id": team_id,
            "team": teams.get(team_id),
            "position": position,
            "element_type": element_type,
            "now_cost": int(player.get("now_cost") or 0),
            "status": player.get("status"),
            "ownership_pct": _f(player.get("selected_by_percent")),
            "current_season": {"starts": int(player.get("starts") or 0), "minutes": int(player.get("minutes") or 0)},
            "historical_prior": historical or None,
            "xmins": xmins,
            "rates": {
                **{key: round(value, 4) for key, value in rates.items()},
                "sources": {
                    "xg90": f"{xg_source}|prior={xg_prior_source}",
                    "xa90": f"{xa_source}|prior={xa_prior_source}",
                    "bonus90": bonus_source,
                    "saves90": saves_source,
                    "dc90": str(dc_model.get("source")),
                },
                "historical_attacking_prior_weight": round(attack_weight, 4),
                "defensive_contribution_model": dc_model,
            },
            "xpts_by_gw": by_gw,
            "horizons": horizons,
            "projection_confidence": xmins.get("confidence"),
        })
    return {
        "model": model_id,
        "ruleset_id": RULESET_ID,
        "planning_gw": planning_gw,
        "horizon_gws": horizon,
        "published_horizons": published_horizons,
        "historical_prior_model": prior_payload.get("model"),
        "historical_prior_season": prior_payload.get("season"),
        "historical_prior_players_used": historical_used,
        "player_feature_contract": player_features_payload.get("contract"),
        "player_feature_model_opt_in": (player_features_payload.get("policy") or {}).get("model_opt_in"),
        "player_dc_evidence_used": player_dc_evidence_used,
        "defensive_contribution_model": "player_dc_poisson_threshold_v1",
        "players": players,
    }
