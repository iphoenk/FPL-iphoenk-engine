from __future__ import annotations

import json
from datetime import datetime, timezone

from src.engines.decision_intelligence import build_package_optimizer
from src.models.historical_projection import build as build_player_projections
from src.models.prediction_quality import evaluate as evaluate_prediction_quality
from src.models.tactical_matchup import attach_tactical_matchups
from src.models.team_strength import build_team_strength
from src.settings import STRATEGIC_HORIZON_GWS
from src.utils import DATA, atomic_json, read_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run() -> dict:
    official = read_json(DATA / "official_snapshot.json", {})
    bootstrap = official.get("bootstrap") or {}
    fixtures = official.get("fixtures") or []
    health = official.get("endpoint_health") or {}
    if not bootstrap or not fixtures:
        raise RuntimeError("official_snapshot unavailable or incomplete for prediction service")

    prior = read_json(DATA / "prior_season.json", {})
    if not prior.get("players"):
        raise RuntimeError("historical prior artifact unavailable for prediction service")

    player_features = read_json(DATA / "player_features.json", {})
    if player_features.get("contract") != "PLAYER_FEATURE_CONTRACT_V1" or not player_features.get("players"):
        raise RuntimeError("REC-01 player feature artifact unavailable or invalid for prediction service")
    if player_features.get("decision_neutral") is not False or player_features.get("model_opt_in") != "REC-01":
        raise RuntimeError("REC-01 player feature model opt-in is not active")

    latest = read_json(DATA / "latest.json", {})
    planning_gw = int((latest.get("phase") or {}).get("planning_gw") or 1)

    strength = build_team_strength(bootstrap, fixtures)
    strength["generated_at"] = _now()
    strength["source_health"] = {
        "bootstrap": (health.get("bootstrap") or {}).get("status"),
        "fixtures": (health.get("fixtures") or {}).get("status"),
    }
    strength.setdefault("governance", {})["official_snapshot_reused"] = True
    atomic_json(DATA / "team_strength.json", strength)

    projections = build_player_projections(
        bootstrap,
        strength,
        planning_gw,
        prior,
        horizon=STRATEGIC_HORIZON_GWS,
        player_features_payload=player_features,
    )
    projections = attach_tactical_matchups(projections, planning_gw)
    projections["generated_at"] = _now()
    projections.setdefault("governance", {}).update({
        "official_snapshot_reused": True,
        "rec01_player_feature_model_opt_in": True,
        "player_feature_contract": player_features.get("contract"),
        "defensive_contribution_model": projections.get("defensive_contribution_model"),
        "advanced_defensive_evidence_players_used": projections.get("advanced_defensive_evidence_players_used"),
        "tactical_matchup_is_advisory_only": True,
        "tactical_matchup_never_directly_mutates_xpts": True,
    })
    atomic_json(DATA / "projections.json", projections)

    packages = build_package_optimizer(projections, read_json(DATA / "team.json", {}))
    hold_guardrails = (((packages.get("hold") or {}).get("score") or {}).get("guardrails") or {})
    packages.setdefault("governance", {}).update({
        "team_cluster_penalty_enabled": hold_guardrails.get("team_cluster_penalty_enabled") is True,
        "early_season_change_cap_enabled": hold_guardrails.get("early_season_change_cap_enabled") is True,
        "effective_max_changes": hold_guardrails.get("effective_max_changes"),
        "team_cluster_penalty_points": hold_guardrails.get("cluster_penalty_points"),
        "risk_guardrails_are_scored_not_label_only": True,
        "tactical_matchup_is_advisory_only": True,
        "tactical_matchup_never_directly_mutates_xpts": True,
    })
    atomic_json(DATA / "package_optimizer.json", packages)

    quality = evaluate_prediction_quality(projections, prior)
    atomic_json(DATA / "prediction_quality.json", quality)

    tactical = projections.get("tactical_matchup_summary") or {}
    latest.setdefault("files", {}).update({
        "team_strength": "data/team_strength.json",
        "projections": "data/projections.json",
        "package_optimizer": "data/package_optimizer.json",
        "prediction_quality": "data/prediction_quality.json",
    })
    latest["decision_intelligence"] = {
        "service": "prediction_service",
        "model": projections.get("model"),
        "planning_gw": planning_gw,
        "projection_horizon_gws": STRATEGIC_HORIZON_GWS,
        "projection_players": len(projections.get("players") or []),
        "team_strength_model": strength.get("model"),
        "team_strength_teams": len(strength.get("teams") or []),
        "historical_prior_model": projections.get("historical_prior_model"),
        "historical_prior_players_used": projections.get("historical_prior_players_used"),
        "prediction_quality": quality.get("status"),
        "package_optimizer_status": packages.get("status"),
        "package_count": packages.get("package_count", 0),
        "best_package": (packages.get("packages") or [{}])[0].get("id") if packages.get("packages") else None,
        "candidate_generation_only": True,
        "tactical_matchup": {
            "status": "READY" if tactical.get("ready") else ("PARTIAL" if tactical.get("partial") else "UNAVAILABLE"),
            "model": tactical.get("model"),
            "ready_players": tactical.get("ready", 0),
            "partial_players": tactical.get("partial", 0),
            "unavailable_players": tactical.get("unavailable", 0),
            "advisory_only": True,
            "xpts_mutation": False,
            "report_policy": "material-highlights-only",
        },
        "player_feature_model": {
            "contract": projections.get("player_feature_contract"),
            "opt_in": projections.get("player_feature_model_opt_in"),
            "defensive_contribution_model": projections.get("defensive_contribution_model"),
            "advanced_defensive_evidence_players_used": projections.get("advanced_defensive_evidence_players_used"),
        },
        "risk_guardrails": {
            "team_cluster_penalty_enabled": (packages.get("governance") or {}).get("team_cluster_penalty_enabled"),
            "early_season_change_cap_enabled": (packages.get("governance") or {}).get("early_season_change_cap_enabled"),
            "effective_max_changes": (packages.get("governance") or {}).get("effective_max_changes"),
        },
    }
    latest["prediction_quality_summary"] = {
        "status": quality.get("status"),
        "failed_checks": quality.get("failed_checks"),
        "checks": quality.get("checks"),
    }
    atomic_json(DATA / "latest.json", latest)
    return {"strength": strength, "projections": projections, "packages": packages, "quality": quality}


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "projection_players": len(out["projections"].get("players") or []),
        "historical_prior_players": out["projections"].get("historical_prior_players_used"),
        "defensive_contribution_model": out["projections"].get("defensive_contribution_model"),
        "advanced_defensive_evidence_players_used": out["projections"].get("advanced_defensive_evidence_players_used"),
        "prediction_quality": out["quality"].get("status"),
        "package_count": out["packages"].get("package_count"),
        "best_package": (out["packages"].get("packages") or [{}])[0].get("id") if out["packages"].get("packages") else None,
        "risk_guardrails": out["packages"].get("governance"),
        "tactical_matchup": out["projections"].get("tactical_matchup_summary"),
    }, ensure_ascii=False))
