from __future__ import annotations

from typing import Any

from src.v5.config_cache import load_json_config

SOURCE_CONFIG = "config/intelligence/source_fusion.json"


def season_authority() -> dict[str, Any]:
    source_cfg = load_json_config(SOURCE_CONFIG)
    authority = source_cfg.get("season_authority")
    if not isinstance(authority, dict):
        raise RuntimeError("source fusion season_authority registry missing")
    registry_path = str(authority.get("registry_path") or "")
    season_field = str(authority.get("season_field") or "season")
    if not registry_path:
        raise RuntimeError("source fusion season authority registry_path missing")
    registry = load_json_config(registry_path)
    season = str(registry.get(season_field) or "").strip()
    start = season.split("/", 1)[0]
    if len(start) != 4 or not start.isdigit():
        raise RuntimeError(f"invalid authoritative FPL season value: {season!r}")
    return {
        "season": season,
        "start_year": int(start),
        "authority": registry.get("authority"),
        "registry": registry_path,
        "ruleset_id": registry.get("active_ruleset"),
    }
