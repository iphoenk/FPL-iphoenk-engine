from __future__ import annotations

import math
from typing import Any

from src.models.projection_components import _blended_rate, _f, _project_fixture, defensive_contribution_rate_bundle, load_projection_config, robust_attack_rate
from src.models.xmins_v3 import estimate_xmins
from src.rules import ELEMENT_TYPE_TO_POSITION, RULESET_ID


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rate_prior(position_prior: float, historical: dict[str, Any], field: str) -> tuple[float, str, float]:
    weight = _clamp(_f(historical.get("attacking_prior_weight")), 0.0, 1.0)
    if not historical or weight <= 0 or historical.get(field) is None:
        return max(0.0, position_prior), "position_prior", 0.0
    historical_rate = max(0.0, _f(historical.get(field)))
    return position_prior * (1.0 - weight) + historical_rate * weight, "historical_player_prior+position_prior", weight


def build(bootstrap: dict[str, Any], strength: dict[str, Any], planning_gw: int, prior_payload: dict[str, Any], horizon: int | None = None, player_features_payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
    robust_cfg = cfg.get("early_season_robust_rates") or {}
    if robust_cfg.get("model") != "adaptive_shrinkage_winsor_v1":
        raise RuntimeError("REC-02 robust attack rate model missing from projection config")
    feature_payload = player_features_payload or {}
    feature_map = feature_payload.get("players") or {}
    dc_policy = feature_payload.get("defensive_contribution_policy") or {}
    tactical_policy = feature_payload.get("tactical_role_policy") or {}
    tactical_advisory_only = tactical_policy.get("decision_influence") == "ADVISORY_ONLY"
    if tactical_policy and not tactical_advisory_only:
        raise RuntimeError("REC-41 tactical role evidence must remain advisory-only in this release")
    dc_shrink = float(dc_policy.get("rate_shrinkage_minutes") or cfg.get("rate_shrinkage_minutes") or 0)
    if dc_shrink <= 0:
        raise RuntimeError("defensive contribution shrinkage minutes must be positive")
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
    advanced_dc_used = 0
    tactical_role_used = 0
    system_context_used = 0
    robust_winsorized_players = 0
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
        xg90, xg_source, xg_robust = robust_attack_rate(player, "expected_goals", xg_prior, robust_cfg)
        xa90, xa_source, xa_robust = robust_attack_rate(player, "expected_assists", xa_prior, robust_cfg)
        robust_winsorized_players += int(bool(xg_robust.get("winsorized") or xa_robust.get("winsorized")))
        bonus90, bonus_source = _blended_rate(player, "bonus", _f(base.get("bonus90")), shrink)
        saves90, saves_source = _blended_rate(player, "saves", _f(base.get("saves90")), shrink)
        feature = feature_map.get(str(element)) or {}
        tactical_role = feature.get("tactical_role") or {"profile": "UNASSESSED", "confidence": "NONE", "decision_influence": "ADVISORY_ONLY"}
        system_context = feature.get("system_context") or {"label": "FPL_POSITION_SHAPE", "dominant_shape": None, "confidence": "NONE", "decision_influence": "ADVISORY_ONLY"}
        tactical_role_used += int(tactical_role.get("profile") not in {None, "UNASSESSED"})
        system_context_used += int(bool(system_context.get("dominant_shape")))
        dc_bundle = defensive_contribution_rate_bundle(player, feature, _f(base.get("dc90")), dc_shrink)
        advanced_dc_used += int(_f(dc_bundle.get("dc_evidence_minutes")) > 0)
        rates: dict[str, Any] = {"xg90": xg90, "xa90": xa90, "bonus90": bonus90, "saves90": saves90, **dc_bundle}
        team_id = int(player.get("team") or -1)
        matches_played = int((team_rows.get(team_id) or {}).get("matches_played") or 0)
        context: dict[str, Any] = {"team_matches_played": matches_played}
        if historical:
            context.update({"prior_start_probability": historical.get("start_probability"), "starter_minutes_prior": historical.get("avg_minutes_when_start"), "prior_evidence_minutes": historical.get("minutes"), "prior_source": historical.get("source"), "prior_identity_match": historical.get("identity_match")})
        xmins = estimate_xmins(player, context)
        xmins.setdefault("governance", {}).update({
            "tactical_role_evidence_available": tactical_role.get("profile") not in {None, "UNASSESSED"},
            "team_system_context_available": bool(system_context.get("dominant_shape")),
            "rec41_tactical_adjustment_applied": False,
            "reason": "REC-41 evidence contract is advisory-only until calibrated model opt-in",
        })
        fixtures = [matchup for matchup in matchups_by_team.get(team_id, []) if planning_gw <= int(matchup.get("event") or -1) < planning_gw + horizon]
        by_gw = []
        for gw in range(planning_gw, planning_gw + horizon):
            details = [_project_fixture(player, xmins, matchup, int(matchup["team_h"]) == team_id, rates, bool(xmins.get("small_sample_guard"))) for matchup in fixtures if int(matchup.get("event") or -1) == gw]
            mean = sum(_f(row.get("mean")) for row in details)
            std = math.sqrt(sum(_f(row.get("std")) ** 2 for row in details)) if details else 0.0
            no_clean_sheet = 1.0
            for row in details:
                no_clean_sheet *= 1.0 - _f(row.get("clean_sheet_probability"))
            by_gw.append({"gw": gw, "mean": round(mean, 3), "std": round(std, 3), "clean_sheet_probability": round(1.0 - no_clean_sheet, 4) if details else 0.0, "fixtures": details})
        horizons = {}
        for published in published_horizons:
            subset = by_gw[:published]
            horizons[str(published)] = {"mean": round(sum(_f(row["mean"]) for row in subset), 3), "std": round(math.sqrt(sum(_f(row["std"]) ** 2 for row in subset)), 3)}
        players.append({"element": element, "name": player.get("web_name"), "team_id": team_id, "team": teams.get(team_id), "position": position, "element_type": element_type, "now_cost": int(player.get("now_cost") or 0), "status": player.get("status"), "ownership_pct": _f(player.get("selected_by_percent")), "current_season": {"starts": int(player.get("starts") or 0), "minutes": int(player.get("minutes") or 0)}, "historical_prior": historical or None, "tactical_role": tactical_role, "system_context": system_context, "xmins": xmins, "rates": {"xg90": round(xg90, 4), "xa90": round(xa90, 4), "bonus90": round(bonus90, 4), "saves90": round(saves90, 4), "dc90": round(_f(dc_bundle.get("dc90")), 4), "dc_count90": round(_f(dc_bundle.get("dc_count90")), 4), "dc_threshold": dc_bundle.get("dc_threshold"), "dc_points": dc_bundle.get("dc_points"), "dc_evidence_minutes": round(_f(dc_bundle.get("dc_evidence_minutes")), 1), "dc_sample_quality": dc_bundle.get("dc_sample_quality"), "robust_rate_diagnostics": {"xg90": xg_robust, "xa90": xa_robust}, "sources": {"xg90": f"{xg_source}|prior={xg_prior_source}", "xa90": f"{xa_source}|prior={xa_prior_source}", "bonus90": bonus_source, "saves90": saves_source, "dc90": dc_bundle.get("dc_source")}, "historical_attacking_prior_weight": round(attack_weight, 4)}, "xpts_by_gw": by_gw, "horizons": horizons, "projection_confidence": xmins.get("confidence")})
    return {"model": model_id, "ruleset_id": RULESET_ID, "planning_gw": planning_gw, "horizon_gws": horizon, "published_horizons": published_horizons, "historical_prior_model": prior_payload.get("model"), "historical_prior_season": prior_payload.get("season"), "historical_prior_players_used": historical_used, "player_feature_contract": feature_payload.get("contract"), "player_feature_model_opt_in": feature_payload.get("model_opt_in"), "defensive_contribution_model": dc_policy.get("model") or "poisson_threshold_shrunk_rate_v1", "advanced_defensive_evidence_players_used": advanced_dc_used, "tactical_role_contract": tactical_policy.get("contract"), "tactical_role_model": tactical_policy.get("model_id"), "tactical_role_decision_influence": tactical_policy.get("decision_influence") or "ADVISORY_ONLY", "tactical_role_players_observed": tactical_role_used, "team_system_players_with_observed_shape": system_context_used, "rec41_tactical_adjustment_applied": False, "robust_attack_rate_model": robust_cfg.get("model"), "robust_rate_winsorized_players": robust_winsorized_players, "players": players}
