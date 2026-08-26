from __future__ import annotations

import json

from src.sources.manager import collect_sources
from src.utils import DATA, atomic_json, iso_now, read_json

OUT = DATA / "source_health.json"
RUNTIME_OUT = DATA / "source_registry_runtime.json"


def run() -> dict:
    payload = collect_sources(DATA)
    payload["generated_at"] = iso_now()
    atomic_json(OUT, payload)
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
        "elapsed_ms": payload.get("elapsed_ms"),
    }
    latest.setdefault("files", {})["source_health"] = "data/source_health.json"
    latest["files"]["source_registry_runtime"] = "data/source_registry_runtime.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["source_layer_summary"], ensure_ascii=False))
    return payload


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
