from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.sources.api_football import collect as collect_api_football
from src.v5.sources.understat import collect as collect_understat

CONFIG = "config/intelligence/source_fusion.json"


def collect(bootstrap: dict[str, Any]) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    with ThreadPoolExecutor(max_workers=2) as pool:
        understat_future = pool.submit(collect_understat)
        api_football_future = pool.submit(collect_api_football, bootstrap)
        understat = understat_future.result()
        api_football = api_football_future.result()
    return {
        "schema_version": 1,
        "model": cfg.get("model_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTIVE",
        "sources": {
            "understat": understat,
            "api_football": api_football,
        },
        "governance": {
            "official_fpl_remains_native_authority": True,
            "fpl_core_insights_remains_primary_epl_advanced_stats": True,
            "challenger_failure_is_fail_neutral": True,
            "missing_enrichment_is_unavailable_not_zero": True,
        },
    }
