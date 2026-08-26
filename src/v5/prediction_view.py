from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_prediction_service_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    contract = data.get("network_contract")
    if not isinstance(contract, dict):
        raise RuntimeError("invalid V5 prediction service registry")
    return contract


def compact_prediction_view(predictions: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg()
    player_fields = tuple(str(x) for x in cfg["player_fields"])
    fixture_fields = tuple(str(x) for x in cfg["fixture_fields"])
    xmins_fields = tuple(str(x) for x in cfg["xmins_fields"])
    prior_fields = tuple(str(x) for x in cfg["prior_fields"])
    fixture_count = int(cfg["fixture_count"])

    players = []
    for row in predictions.get("players", []) or []:
        item = {field: row.get(field) for field in player_fields}
        compact_fixtures = []
        for fixture in (row.get("fixtures") or [])[:fixture_count]:
            frow = {field: fixture.get(field) for field in fixture_fields}
            xmins = fixture.get("xmins") if isinstance(fixture.get("xmins"), dict) else {}
            frow["xmins"] = {field: xmins.get(field) for field in xmins_fields}
            compact_fixtures.append(frow)
        priors = row.get("priors") if isinstance(row.get("priors"), dict) else {}
        item["fixtures"] = compact_fixtures
        item["priors"] = {field: priors.get(field) for field in prior_fields}
        players.append(item)

    return {
        "schema_version": predictions.get("schema_version"),
        "model_version": predictions.get("model_version"),
        "generated_at": predictions.get("generated_at"),
        "point_in_time": predictions.get("point_in_time"),
        "input_coverage": predictions.get("input_coverage", {}),
        "players": players,
        "network_contract": {
            "compact": True,
            "fixture_count": fixture_count,
            "full_provenance_omitted": True,
        },
    }
