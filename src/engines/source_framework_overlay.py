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
        framework["external_sources"] = {
            "status": source_health.get("overall"),
            "decision_blocking": bool(source_health.get("decision_blocking")),
            "registry": source_health.get("registry"),
            "challenger_live": source_health.get("challenger_live") or [],
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
    }
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["source_health_summary"], ensure_ascii=False))
    return framework


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
