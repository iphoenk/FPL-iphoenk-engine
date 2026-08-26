from __future__ import annotations

from typing import Any

from src.v5.intelligence.projection import build_predictions

CAPABILITIES = [
    "xmins",
    "xmins_distribution",
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
]


def handle(operation: str, payload: dict[str, Any]) -> Any:
    if operation not in {"build", "build_full", "status"}:
        raise KeyError(f"unsupported prediction operation: {operation}")
    if operation == "status":
        return {
            "status": "ACTIVE",
            "model_family": "P0_NATIVE_V310",
            "bridge_only": False,
            "capabilities": list(CAPABILITIES),
        }
    bootstrap = payload.get("bootstrap")
    fixtures = payload.get("fixtures")
    rules = payload.get("rules")
    if not isinstance(bootstrap, dict) or not isinstance(fixtures, list) or not isinstance(rules, dict):
        raise ValueError("prediction service requires bootstrap, fixtures and truth-service rules")
    planning_gw = int(payload.get("planning_gw") or 1)
    result = build_predictions(
        bootstrap,
        fixtures,
        rules,
        planning_gw,
        horizon=int(payload.get("horizon") or 15),
    )
    if operation == "build_full":
        return {**result, "capabilities": list(CAPABILITIES)}
    compact_players = []
    for player in result.get("players") or []:
        compact_players.append(
            {
                "element": player["element"],
                "name": player.get("name"),
                "team_id": player.get("team_id"),
                "position": player.get("position"),
                "now_cost": player.get("now_cost"),
                "status": player.get("status"),
                "ownership_pct": player.get("ownership_pct"),
                "xmins": player.get("xmins"),
                "xpts_by_gw": player.get("xpts_by_gw"),
                "horizons": player.get("horizons"),
                "xpts_3": player.get("xpts_3"),
                "xpts_5": player.get("xpts_5"),
                "xpts_10": player.get("xpts_10"),
                "xpts_15": player.get("xpts_15"),
                "mean_xpts": player.get("mean_xpts"),
                "uncertainty": player.get("uncertainty"),
                "fixtures": player.get("fixtures"),
                "rates": player.get("rates"),
                "projection_confidence": player.get("projection_confidence"),
            }
        )
    return {
        "generated_at": result.get("generated_at"),
        "schema_version": result.get("schema_version"),
        "model_version": result.get("model_version"),
        "ruleset_id": result.get("ruleset_id"),
        "planning_gw": result.get("planning_gw"),
        "horizon_gws": result.get("horizon_gws"),
        "team_strength": result.get("team_strength"),
        "players": compact_players,
        "network_contract": result.get("network_contract"),
        "capabilities": list(CAPABILITIES),
    }
