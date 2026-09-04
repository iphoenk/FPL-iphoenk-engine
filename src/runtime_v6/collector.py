from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .adapters import collect_source
from .health import build_source_health
from .http_client import AcquisitionClient, utc_now
from .normalizer import build_canonical_fixtures, build_canonical_players, build_canonical_teams, build_evidence_index, build_lineage_catalog
from .registry import load_registry, source_map
from .store import EVIDENCE, HEALTH, MANIFEST, NORMALIZED, load_previous_sources, write_json, write_source

def _isolated_failure(source: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {"schema_version": 2, "source_id": source["id"], "source_name": source["name"], "category": source["category"], "adapter": source["adapter"], "critical": bool(source.get("critical")), "independence_group": source.get("independence_group"), "checked_at": utc_now(), "health": "RED" if source.get("critical") else "AMBER", "availability": "UNAVAILABLE", "effective_state": "MISSING", "changed": None, "error": type(exc).__name__, "governance": {"data_only": True, "decision_authority": "NONE", "prediction_authority": "NONE", "optimizer_authority": "NONE", "isolated_failure": True, "values_not_invented": True}}

def run() -> dict[str, Any]:
    config = load_registry()
    sources = list(config["sources"])
    by_id = source_map(config)
    previous = load_previous_sources()
    client = AcquisitionClient(config["policy"])
    results: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    official = collect_source(by_id["official_fpl"], client, previous=previous.get("official_fpl"))
    results["official_fpl"] = official
    results["official_price_predictor"] = collect_source(by_id["official_price_predictor"], client, previous=previous.get("official_price_predictor"), official_payload=official)
    remaining = [source for source in sources if source["id"] not in {"official_fpl", "official_price_predictor"}]
    workers = max(1, int(config["policy"].get("max_workers") or 12))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect_source, source, client, previous=previous.get(source["id"])): source for source in remaining}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results[source["id"]] = future.result()
            except Exception as exc:
                results[source["id"]] = _isolated_failure(source, exc)
    for source in sources:
        write_source(source["id"], results[source["id"]])
    source_ids = [source["id"] for source in sources]
    write_json(NORMALIZED / "canonical_players.json", build_canonical_players(official, source_ids))
    write_json(NORMALIZED / "canonical_teams.json", build_canonical_teams(official))
    write_json(NORMALIZED / "canonical_fixtures.json", build_canonical_fixtures(official))
    write_json(EVIDENCE / "lineage.json", build_lineage_catalog(config))
    write_json(EVIDENCE / "latest_index.json", build_evidence_index(results))
    health = build_source_health(config, results)
    write_json(HEALTH / "source_health.json", health)
    elapsed = round((time.perf_counter() - started) * 1000.0, 3)
    critical_failures = [source["id"] for source in sources if source.get("critical") and results[source["id"]].get("health") == "RED"]
    manifest = {"schema_version": 2, "engine": config["engine"], "season": config["season"], "generated_at": utc_now(), "elapsed_ms": elapsed, "source_count": len(sources), "source_ids": source_ids, "overall": "RED" if critical_failures else health["overall"], "health_counts": health["counts"], "critical_failures": critical_failures, "paths": {"current_sources": "data/v6/current/", "health": "data/v6/health/source_health.json", "canonical_players": "data/v6/normalized/canonical_players.json", "canonical_teams": "data/v6/normalized/canonical_teams.json", "canonical_fixtures": "data/v6/normalized/canonical_fixtures.json", "lineage": "data/v6/evidence/lineage.json", "evidence_index": "data/v6/evidence/latest_index.json"}, "governance": {"decision_authority": "NONE", "prediction_authority": "NONE", "optimizer_authority": "NONE", "data_only": True, "no_cross_source_averaging": True, "no_fabrication": True, "source_failures_are_isolated": True, "unchanged_upstream_is_not_degraded": True}}
    write_json(MANIFEST, manifest)
    return manifest

def main() -> int:
    print(json.dumps(run(), ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
