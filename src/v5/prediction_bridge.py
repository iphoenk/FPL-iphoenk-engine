from __future__ import annotations

from typing import Any

from src.engines.v4_runner import build_predictions as build_v4_predictions
from src.v5.config_cache import load_json_config

REGISTRY_CONFIG = "config/v5_prediction_bridge_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(REGISTRY_CONFIG)
    if not isinstance(data.get("contract"), dict):
        raise RuntimeError("invalid V5 prediction bridge registry")
    return data


def enabled() -> bool:
    return bool(_cfg().get("runtime", {}).get("enabled", True))


def build_predictions(
    bootstrap: dict,
    fixtures: list[dict],
    generated_at: str,
    *,
    stats_gw: int | None = None,
) -> dict:
    if not enabled():
        return {"status": "DISABLED", "players": [], "v5_bridge": {"enabled": False}}
    upstream = build_v4_predictions(bootstrap, fixtures, generated_at, stats_gw=stats_gw)
    contract = _cfg()["contract"]
    if not isinstance(upstream, dict):
        raise RuntimeError("V4 prediction bridge returned invalid payload")
    return {
        **upstream,
        "v5_bridge": {
            "enabled": True,
            "upstream_entrypoint": _cfg()["upstream"]["entrypoint"],
            "upstream_model_version": upstream.get("model_version"),
            "point_in_time_required": bool(contract.get("require_point_in_time_inputs", True)),
            "leakage_guard_required": bool(contract.get("require_leakage_guard", True)),
        },
    }
