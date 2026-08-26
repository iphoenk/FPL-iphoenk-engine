from __future__ import annotations

import json

from src.sources.manager import collect_sources
from src.utils import DATA, atomic_json, iso_now, read_json

OUT = DATA / "source_health.json"
RUNTIME_OUT = DATA / "source_registry_runtime.json"
OBSERVATION_OUT = DATA / "challenger_observations.json"


def run() -> dict:
    payload = collect_sources(DATA)
    observations = payload.pop("challenger_observations_payload", {"schema_version": 2, "observations": []})
    payload["generated_at"] = iso_now()
    atomic_json(OUT, payload)
    atomic_json(OBSERVATION_OUT, observations)

    runtime = {
        "generated_at": payload["generated_at"],
        "registry": payload.get("registry"),
        "sources": [
            {
                "id": row.get("id"),
                "class": row.get("class"),
                "status": row.get("status"),
                "reachable": row.get("reachable"),
                "observation_count": row.get("observation_count"),
            }
            for row in payload.get("sources") or []
        ],
        "capability_health": payload.get("capability_health") or [],
        "structured_observations": {
            "fresh": payload.get("structured_observation_count", 0),
            "cached_last_known_good": payload.get("structured_cached_count", 0),
            "stale": payload.get("structured_stale_count", 0),
            "disagreements": payload.get("disagreement_count", 0),
        },
        "policy": payload.get("policy"),
    }
    atomic_json(RUNTIME_OUT, runtime)

    latest = read_json(DATA / "latest.json", {})
    latest["source_layer_summary"] = {
        "overall": payload.get("overall"),
        "decision_blocking": payload.get("decision_blocking"),
        "enabled": payload.get("enabled_count"),
        "challenger_live": payload.get("challenger_live_count"),
        "challenger_live_ids": payload.get("challenger_live"),
        "structured_observations_fresh": payload.get("structured_observation_count", 0),
        "structured_observations_cached": payload.get("structured_cached_count", 0),
        "structured_observations_stale": payload.get("structured_stale_count", 0),
        "structured_disagreements": payload.get("disagreement_count", 0),
        "capability_count": len(payload.get("capability_health") or []),
        "elapsed_ms": payload.get("elapsed_ms"),
    }
    latest.setdefault("files", {})["source_health"] = "data/source_health.json"
    latest["files"]["source_registry_runtime"] = "data/source_registry_runtime.json"
    latest["files"]["challenger_observations"] = "data/challenger_observations.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["source_layer_summary"], ensure_ascii=False))
    return payload


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
