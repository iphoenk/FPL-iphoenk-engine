from __future__ import annotations

import json
import os
from typing import Any

from src.intelligence.understat_tactical import build_understat_tactical
from src.sources import understat
from src.utils import DATA, atomic_json, read_json

OUT = DATA / "understat_tactical_v3.json"
HEALTH_OUT = DATA / "understat_tactical_health_v3.json"
RAW_CACHE = DATA / "stats" / "understat_epl_2026.json"


def _official_universe() -> list[dict[str, Any]]:
    universe = read_json(DATA / "universe.json", {})
    rows = universe.get("players") if isinstance(universe, dict) else []
    return [dict(row) for row in (rows or []) if isinstance(row, dict) and row.get("element") is not None]


def _raw_snapshot() -> tuple[dict[str, Any], str]:
    profile = str(os.getenv("FPL_EXECUTION_PROFILE") or "").strip().lower()
    # The FAST decision lane has a hard 3s contract. Understat is optional
    # enrichment, so network I/O is forbidden there; hydrate/reuse LKG only.
    if profile == "fast_decision":
        raw = understat.load()
        mode = "FAST_CACHE_ONLY"
        if raw.get("source_availability") == "UNAVAILABLE":
            raw["refresh_error"] = "network_refresh_deferred_in_fast_decision"
        return raw, mode
    return understat.sync(), "GOVERNED_REFRESH_OR_CACHE"


def build() -> dict[str, Any]:
    official = read_json(DATA / "official_snapshot.json", {})
    universe = _official_universe()
    raw, acquisition_mode = _raw_snapshot()
    # Always persist a truthfully shaped cache artifact so an optional source
    # outage cannot turn a declared runtime artifact into an integrity failure.
    atomic_json(RAW_CACHE, raw)

    snapshot = {"official": {"fixtures": list(official.get("fixtures") or [])}}
    tactical = build_understat_tactical(raw, snapshot, universe)
    tactical["engine"] = "V3"
    tactical["native_integration"] = {
        "architecture": "V3_CANONICAL_DOMAIN_PIPELINE",
        "owner": "tactical_context",
        "acquisition_mode": acquisition_mode,
        "official_fpl_identity_and_fixture_authority_preserved": True,
        "existing_tactical_decision_consumption_extended": True,
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
        "captaincy_semantics_unchanged": True,
    }
    for matchup in (tactical.get("tactical_matchups") or {}).values():
        if not isinstance(matchup, dict):
            continue
        interaction = matchup.get("player_role_interaction")
        if isinstance(interaction, dict):
            interaction["xmins_authority"] = "V3_PREDICTION_NOT_UNDERSTAT"

    health = {
        "schema_version": 1,
        "contract": "V3_UNDERSTAT_TACTICAL_HEALTH_V1",
        "generated_at": tactical.get("generated_at"),
        "status": (tactical.get("health") or {}).get("status") or "UNAVAILABLE",
        "optional_enrichment": True,
        "source": tactical.get("source") or {},
        "coverage": tactical.get("health") or {},
        "acquisition_mode": acquisition_mode,
        "production_blocking": False,
        "governance": {
            "official_fpl_authority_preserved": True,
            "missing_is_unknown_not_zero": True,
            "stale_never_labeled_fresh": True,
            "fast_decision_network_io_forbidden": True,
            "understat_failure_does_not_block_unrelated_v3": True,
            "ppda_direct_xpts_conversion_forbidden": True,
        },
    }
    return {"tactical": tactical, "health": health}


def run() -> dict[str, Any]:
    out = build()
    atomic_json(OUT, out["tactical"])
    atomic_json(HEALTH_OUT, out["health"])
    latest = read_json(DATA / "latest.json", {})
    if latest:
        latest.setdefault("files", {}).update({
            "understat_tactical": "data/understat_tactical_v3.json",
            "understat_tactical_health": "data/understat_tactical_health_v3.json",
        })
        health = out["health"]
        coverage = health.get("coverage") or {}
        latest["understat_tactical_summary"] = {
            "status": health.get("status"),
            "source_availability": (health.get("source") or {}).get("availability"),
            "freshness": (health.get("source") or {}).get("freshness"),
            "player_mapping_coverage": coverage.get("player_mapping_coverage"),
            "tactical_matchup_coverage": coverage.get("tactical_matchup_coverage"),
            "full_universe_count": coverage.get("official_universe_count"),
            "optional_enrichment": True,
        }
        atomic_json(DATA / "latest.json", latest)
    print(json.dumps({"status": out["health"].get("status"), "coverage": out["health"].get("coverage"), "acquisition_mode": out["health"].get("acquisition_mode")}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
