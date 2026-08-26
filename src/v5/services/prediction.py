from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.intelligence.historical_prior import resolve_prior
from src.v5.intelligence.prediction_quality import evaluate_prediction_quality
from src.v5.intelligence.projection import build_predictions

ROLE_CONFIG = "config/intelligence/role_intelligence.json"
BASE_CAPABILITIES = [
    "xmins",
    "xmins_distribution",
    "historical_prior",
    "last_season_integration",
    "prediction_quality_guard",
    "small_sample_guard",
    "projection_uncertainty",
    "team_attacking_strength",
    "team_defensive_strength",
    "opponent_defence_dynamic",
    "clean_sheet_probability",
    "fixture_context",
    "fixture_swing",
    "horizon_3",
    "horizon_5",
    "horizon_10",
    "horizon_15",
    "price_value",
    "ownership_context",
    "bonus_route",
    "advanced_stats_integration",
    "sustainability",
    "team_defensive_risk",
    "regression_risk",
]


def _capabilities() -> list[str]:
    role_cfg = load_json_config(ROLE_CONFIG)
    return sorted({*BASE_CAPABILITIES, *(str(x) for x in role_cfg.get("capabilities") or [])})


def _quality_degraded_context(quality: dict[str, Any]) -> dict[str, Any] | None:
    if quality.get("status") == "HEALTHY":
        return None
    failed = [str(value) for value in quality.get("failed_checks") or []]
    return {
        "service_id": "prediction",
        "operation": "build",
        "behavior": "prediction remains available for review but quality guard blocks unqualified GO",
        "blocks_unqualified_go": True,
        "error_type": "PredictionQualityDegraded",
        "error": ",".join(failed) if failed else "prediction quality guard not healthy",
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation not in {"build", "build_full", "status"}:
        raise KeyError(f"unsupported prediction operation: {operation}")
    capabilities = _capabilities()
    if operation == "status":
        return {"status": "ACTIVE", "model_family": "P0_NATIVE_V5_HISTORICAL_PRIOR", "bridge_only": False, "capabilities": capabilities}
    bootstrap = payload.get("bootstrap")
    fixtures = payload.get("fixtures")
    rules = payload.get("rules")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list) or not isinstance(rules, dict):
        raise ValueError("prediction service requires bootstrap, fixtures and truth-service rules")
    planning_gw = int(payload.get("planning_gw") or 1)
    previous_prior = payload.get("historical_prior") if isinstance(payload.get("historical_prior"), dict) else {}
    prior = resolve_prior(bootstrap, rules, previous_prior=previous_prior, allow_network_refresh=bool(payload.get("allow_historical_prior_refresh", False)))
    result = build_predictions(bootstrap, fixtures, rules, planning_gw, horizon=int(payload.get("horizon") or 15), historical_prior=prior)
    quality = evaluate_prediction_quality(result, prior, owned_ids=payload.get("owned_ids") or ())
    degraded_context = _quality_degraded_context(quality)
    result = {**result, "historical_prior_artifact": prior, "prediction_quality": quality, **({"degraded_context": degraded_context} if degraded_context else {})}
    if operation == "build_full":
        return {**result, "capabilities": capabilities}
    compact_players = []
    for player in result.get("players") or []:
        compact_players.append({
            "element": player["element"], "name": player.get("name"), "team_id": player.get("team_id"), "position": player.get("position"),
            "now_cost": player.get("now_cost"), "status": player.get("status"), "ownership_pct": player.get("ownership_pct"),
            "current_season": player.get("current_season"), "historical_prior": player.get("historical_prior"), "xmins": player.get("xmins"),
            "role": player.get("role"), "xpts_by_gw": player.get("xpts_by_gw"), "horizons": player.get("horizons"),
            "xpts_3": player.get("xpts_3"), "xpts_5": player.get("xpts_5"), "xpts_10": player.get("xpts_10"), "xpts_15": player.get("xpts_15"),
            "mean_xpts": player.get("mean_xpts"), "uncertainty": player.get("uncertainty"), "fixtures": player.get("fixtures"),
            "projection_confidence": player.get("projection_confidence"),
        })
    return {
        "generated_at": result.get("generated_at"), "schema_version": result.get("schema_version"), "model_version": result.get("model_version"),
        "ruleset_id": result.get("ruleset_id"), "planning_gw": result.get("planning_gw"), "horizon_gws": result.get("horizon_gws"),
        "historical_prior": result.get("historical_prior"), "historical_prior_artifact": prior, "prediction_quality": quality,
        **({"degraded_context": degraded_context} if degraded_context else {}),
        "team_strength": result.get("team_strength"), "role_intelligence": result.get("role_intelligence"), "players": compact_players,
        "network_contract": result.get("network_contract"), "capabilities": capabilities,
    }
