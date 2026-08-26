from __future__ import annotations

import json

from src.utils import DATA, atomic_json, read_json


def run() -> dict:
    framework = read_json(DATA / "framework_health.json", {})
    source_health = read_json(DATA / "source_health.json", {})
    if not framework:
        raise RuntimeError("framework_health.json missing")
    if not source_health:
        framework["external_sources"] = {
            "status": "UNAVAILABLE",
            "decision_blocking": False,
            "detail": {"reason": "source layer artifact unavailable"},
        }
    else:
        rows = source_health.get("sources") or []
        capabilities = source_health.get("capability_health") or []
        framework["external_sources"] = {
            "status": source_health.get("overall"),
            "decision_blocking": bool(source_health.get("decision_blocking")),
            "registry": source_health.get("registry"),
            "challenger_live": source_health.get("challenger_live") or [],
            "structured_observations": {
                "fresh": source_health.get("structured_observation_count", 0),
                "cached_last_known_good": source_health.get("structured_cached_count", 0),
                "stale": source_health.get("structured_stale_count", 0),
                "disagreements": source_health.get("disagreement_count", 0),
            },
            "capability_health": capabilities,
            "sources": {
                str(row.get("id")): {
                    "class": row.get("class"),
                    "status": row.get("status"),
                    "reachable": row.get("reachable"),
                    "observation_count": row.get("observation_count"),
                }
                for row in rows
            },
            "policy": source_health.get("policy"),
        }
        if source_health.get("decision_blocking"):
            framework["overall"] = "RED"
            framework["decision_engine"] = "BLOCKED"
            framework["recommendation_allowed"] = False
            framework["go_allowed"] = False
            framework.setdefault("critical_failed", []).append("SOURCE_LAYER_AUTHORITATIVE")
    atomic_json(DATA / "framework_health.json", framework)
    latest = read_json(DATA / "latest.json", {})
    latest["source_health_summary"] = {
        "status": (framework.get("external_sources") or {}).get("status"),
        "decision_blocking": (framework.get("external_sources") or {}).get("decision_blocking"),
        "challenger_live": (framework.get("external_sources") or {}).get("challenger_live", []),
        "structured_observations": (framework.get("external_sources") or {}).get("structured_observations", {}),
    }
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["source_health_summary"], ensure_ascii=False))
    return framework


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
