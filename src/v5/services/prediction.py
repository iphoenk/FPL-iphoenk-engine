from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.intelligence.advanced_prediction import enrich_prediction
from src.v5.intelligence.fixture_congestion_overlay import build_fixture_congestion_overlay
from src.v5.intelligence.full_core_enrichment import build_full_core_enrichment
from src.v5.intelligence.historical_prior import resolve_prior
from src.v5.intelligence.native_feature_trace import build_native_feature_trace
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
    "uncertainty_decomposition",
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
    "player_specific_defcon_probability",
    "sustainability",
    "team_defensive_risk",
    "regression_risk",
    "probabilistic_return_overlay",
    "truthful_feature_bundle",
    "native_authoritative_feature_trace",
    "fixture_specific_congestion_shadow",
]


def _capabilities(enrichment: dict[str, Any] | None = None) -> list[str]:
    role_cfg = load_json_config(ROLE_CONFIG)
    enrichment_caps = enrichment.get("capabilities") if isinstance(enrichment, dict) else []
    return sorted(
        {
            *BASE_CAPABILITIES,
            *(str(x) for x in role_cfg.get("capabilities") or []),
            *(str(x) for x in enrichment_caps or []),
        }
    )


def _quality_degraded_context(quality: dict[str, Any]) -> dict[str, Any] | None:
    if quality.get("status") == "HEALTHY":
        return None
    failed = [str(v) for v in quality.get("failed_checks") or []]
    return {
        "service_id": "prediction",
        "operation": "build",
        "behavior": "prediction remains available for review but quality guard blocks unqualified GO",
        "blocks_unqualified_go": True,
        "error_type": "PredictionQualityDegraded",
        "error": ",".join(failed) if failed else "prediction quality guard not healthy",
    }


def _source_fusion(payload: dict[str, Any]) -> dict[str, Any]:
    supplied = payload.get("source_fusion")
    if isinstance(supplied, dict):
        return supplied
    return {
        "status": "UNAVAILABLE",
        "sources": {},
        "reason": "NOT_SUPPLIED_BY_ORCHESTRATOR",
        "governance": {
            "fail_neutral": True,
            "missing_enrichment_is_unavailable_not_zero": True,
            "prediction_network_fetch_forbidden": True,
        },
    }


def _compact_enrichment(enrichment: dict[str, Any]) -> dict[str, Any]:
    advanced = enrichment.get("advanced_stats") if isinstance(enrichment.get("advanced_stats"), dict) else {}
    schedule = enrichment.get("schedule") if isinstance(enrichment.get("schedule"), dict) else {}
    preseason = enrichment.get("preseason") if isinstance(enrichment.get("preseason"), dict) else {}
    current_form = enrichment.get("current_form") if isinstance(enrichment.get("current_form"), dict) else {}
    fusion = enrichment.get("source_fusion") if isinstance(enrichment.get("source_fusion"), dict) else {}
    fusion_sources = fusion.get("sources") if isinstance(fusion.get("sources"), dict) else {}
    fusion_health = fusion.get("health") if isinstance(fusion.get("health"), dict) else {}
    api_football = fusion_sources.get("api_football") if isinstance(fusion_sources.get("api_football"), dict) else {}
    understat = fusion_sources.get("understat") if isinstance(fusion_sources.get("understat"), dict) else {}
    api_observability = api_football.get("observability") if isinstance(api_football.get("observability"), dict) else {}
    return {
        "status": enrichment.get("status"),
        "model": enrichment.get("model"),
        "advanced_stats": {
            k: advanced.get(k)
            for k in (
                "status",
                "source",
                "shots_rows",
                "match_rows",
                "coverage_players",
                "defensive_contribution_coverage_players",
                "missing_player_behavior",
                "understat_status",
                "understat_players",
            )
        },
        "schedule": {
            "status": schedule.get("status"),
            "european_competitions": sorted((schedule.get("european") or {}).keys()),
            "league_rest_team_count": len(schedule.get("league_rest_days") or {}),
            "cross_competition_rest_team_count": len(schedule.get("cross_competition_rest_days") or {}),
            "cross_competition_fixture_count": len(schedule.get("cross_competition_fixtures") or []),
            "domestic_cup_source": (schedule.get("domestic_cup") or {}).get("source"),
            "international_source": (schedule.get("international") or {}).get("source"),
            "api_football_status": api_football.get("status"),
            "governance": schedule.get("governance"),
        },
        "preseason": preseason,
        "current_form": {
            "status": current_form.get("status"),
            "source": current_form.get("source"),
            "players": len(current_form.get("players") or {}),
        },
        "source_fusion": {
            "status": fusion.get("status"),
            "season": fusion.get("season"),
            "health": fusion_health,
            "understat": {
                "status": understat.get("status"),
                "fetch_mode": understat.get("fetch_mode"),
                "player_count": understat.get("player_count", len(understat.get("players") or [])),
            },
            "api_football": {
                "status": api_football.get("status"),
                "evidence_status": api_football.get("evidence_status"),
                "fixture_count": len(api_football.get("fixtures") or []),
                "resolved_competition_count": len(
                    [v for v in (api_football.get("resolved_competitions") or {}).values() if v]
                ),
                "credential_present": api_observability.get("credential_present"),
                "network_requests": api_observability.get("network_requests"),
                "cache_hits": api_observability.get("cache_hits"),
                "quota_remaining": api_observability.get("quota_remaining"),
                "quota_limit": api_observability.get("quota_limit"),
            },
        },
        "governance": enrichment.get("governance"),
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation not in {"build", "build_full", "status"}:
        raise KeyError(f"unsupported prediction operation: {operation}")
    if operation == "status":
        return {
            "status": "ACTIVE",
            "model_family": "P0_NATIVE_V5_HISTORICAL_PRIOR_ADVANCED_OVERLAY",
            "bridge_only": False,
            "capabilities": _capabilities(
                {
                    "capabilities": [
                        "advanced_stats_sync",
                        "player_defensive_contribution_evidence",
                        "european_congestion",
                        "domestic_cup_congestion",
                        "international_load",
                        "rest_days",
                        "preseason_prior",
                        "current_form",
                        "source_fusion",
                    ]
                }
            ),
        }

    bootstrap = payload.get("bootstrap")
    fixtures = payload.get("fixtures")
    rules = payload.get("rules")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list) or not isinstance(rules, dict):
        raise ValueError("prediction service requires bootstrap, fixtures and truth-service rules")

    source_fusion = _source_fusion(payload)
    enrichment = build_full_core_enrichment(bootstrap, fixtures, source_fusion=source_fusion)
    capabilities = _capabilities(enrichment)
    planning_gw = int(payload.get("planning_gw") or 1)
    previous_prior = payload.get("historical_prior") if isinstance(payload.get("historical_prior"), dict) else {}
    prior = resolve_prior(
        bootstrap,
        rules,
        previous_prior=previous_prior,
        allow_network_refresh=bool(payload.get("allow_historical_prior_refresh", False)),
    )
    base = build_predictions(
        bootstrap,
        fixtures,
        rules,
        planning_gw,
        horizon=int(payload.get("horizon") or 15),
        historical_prior=prior,
        full_enrichment=enrichment,
    )

    congestion_overlay = build_fixture_congestion_overlay(base, bootstrap, fixtures, enrichment)
    player_congestion = congestion_overlay.get("players") if isinstance(congestion_overlay.get("players"), dict) else {}
    for player in base.get("players") or []:
        if isinstance(player, dict) and player.get("element") is not None:
            player["fixture_congestion_overlay"] = player_congestion.get(str(int(player["element"])))
    base["fixture_congestion_overlay"] = {
        key: value for key, value in congestion_overlay.items() if key != "players"
    }

    native_feature_trace = build_native_feature_trace(base, enrichment)
    player_feature_trace = native_feature_trace.get("players") if isinstance(native_feature_trace.get("players"), dict) else {}
    for player in base.get("players") or []:
        if isinstance(player, dict) and player.get("element") is not None:
            player["feature_use"] = player_feature_trace.get(str(int(player["element"])))
    base["native_feature_use"] = {
        key: value for key, value in native_feature_trace.items() if key != "players"
    }

    quality = evaluate_prediction_quality(base, prior, owned_ids=payload.get("owned_ids") or ())
    degraded_context = _quality_degraded_context(quality)
    result = enrich_prediction(
        {
            **base,
            "historical_prior_artifact": prior,
            "prediction_quality": quality,
            **({"degraded_context": degraded_context} if degraded_context else {}),
        },
        enrichment,
    )
    if operation == "build_full":
        return {**result, "full_core_enrichment": enrichment, "capabilities": capabilities}

    compact = []
    for player in result.get("players") or []:
        compact.append(
            {
                "element": player["element"],
                "name": player.get("name"),
                "team_id": player.get("team_id"),
                "position": player.get("position"),
                "now_cost": player.get("now_cost"),
                "status": player.get("status"),
                "ownership_pct": player.get("ownership_pct"),
                "current_season": player.get("current_season"),
                "historical_prior": player.get("historical_prior"),
                "xmins": player.get("xmins"),
                "role": player.get("role"),
                "xpts_by_gw": player.get("xpts_by_gw"),
                "horizons": player.get("horizons"),
                "xpts_3": player.get("xpts_3"),
                "xpts_5": player.get("xpts_5"),
                "xpts_10": player.get("xpts_10"),
                "xpts_15": player.get("xpts_15"),
                "mean_xpts": player.get("mean_xpts"),
                "uncertainty": player.get("uncertainty"),
                "fixtures": player.get("fixtures"),
                "projection_confidence": player.get("projection_confidence"),
                "defensive_contribution": player.get("defensive_contribution"),
                "fixture_congestion_overlay": player.get("fixture_congestion_overlay"),
                "feature_use": player.get("feature_use"),
                "advanced": player.get("advanced"),
            }
        )
    return {
        "generated_at": result.get("generated_at"),
        "schema_version": result.get("schema_version"),
        "model_version": result.get("model_version"),
        "ruleset_id": result.get("ruleset_id"),
        "planning_gw": result.get("planning_gw"),
        "horizon_gws": result.get("horizon_gws"),
        "historical_prior": result.get("historical_prior"),
        "historical_prior_artifact": prior,
        "prediction_quality": quality,
        **({"degraded_context": degraded_context} if degraded_context else {}),
        "defensive_contribution": result.get("defensive_contribution"),
        "team_strength": result.get("team_strength"),
        "role_intelligence": result.get("role_intelligence"),
        "players": compact,
        "fixture_congestion_overlay": result.get("fixture_congestion_overlay"),
        "native_feature_use": result.get("native_feature_use"),
        "advanced_prediction": result.get("advanced_prediction"),
        "full_core_enrichment": _compact_enrichment(enrichment),
        "network_contract": result.get("network_contract"),
        "capabilities": capabilities,
    }
