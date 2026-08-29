from __future__ import annotations

import json

from src.engines.competitive_load import run as run_competitive_load
from src.engines.external_consensus import run as run_external_consensus
from src.utils import DATA, atomic_json, read_json


def run() -> dict:
    framework = read_json(DATA / "framework_health.json", {})
    source_health = read_json(DATA / "source_health.json", {})
    if not framework:
        raise RuntimeError("framework_health.json missing")

    external_consensus = run_external_consensus()
    competitive_load = run_competitive_load()

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

    framework["external_consensus"] = {
        "status": external_consensus.get("overall"),
        "owner": external_consensus.get("owner"),
        "observation_count": len(external_consensus.get("observations") or []),
        "requires_official_refresh": bool(external_consensus.get("requires_official_refresh")),
        "decision_blocking": False,
        "advisory_only": True,
        "outage_fail_neutral": bool((external_consensus.get("governance") or {}).get("outage_fail_neutral", True)),
        "native_truth_mutated": bool((external_consensus.get("governance") or {}).get("native_truth_mutated", False)),
        "majority_vote_used": bool((external_consensus.get("governance") or {}).get("majority_vote_used", False)),
    }
    framework["competitive_load"] = {
        "status": competitive_load.get("status"),
        "owner": competitive_load.get("owner"),
        "player_count": competitive_load.get("player_count"),
        "state_counts": competitive_load.get("state_counts") or {},
        "source_gw": competitive_load.get("source_gw"),
        "advisory_only": True,
        "decision_blocking": False,
        "direct_xpts_mutation": False,
        "direct_xmins_mutation": False,
    }

    atomic_json(DATA / "framework_health.json", framework)
    latest = read_json(DATA / "latest.json", {})
    latest["source_health_summary"] = {
        "status": (framework.get("external_sources") or {}).get("status"),
        "decision_blocking": (framework.get("external_sources") or {}).get("decision_blocking"),
        "challenger_live": (framework.get("external_sources") or {}).get("challenger_live", []),
        "structured_observations": (framework.get("external_sources") or {}).get("structured_observations", {}),
    }
    latest["external_consensus_summary"] = {
        "overall": external_consensus.get("overall"),
        "observation_count": len(external_consensus.get("observations") or []),
        "requires_official_refresh": bool(external_consensus.get("requires_official_refresh")),
        "advisory_only": True,
        "owner": external_consensus.get("owner"),
    }
    latest["competitive_load_summary"] = {
        "status": competitive_load.get("status"),
        "player_count": competitive_load.get("player_count"),
        "state_counts": competitive_load.get("state_counts") or {},
        "source_gw": competitive_load.get("source_gw"),
        "advisory_only": True,
        "owner": competitive_load.get("owner"),
    }
    latest.setdefault("files", {})["external_consensus"] = "data/external_consensus.json"
    latest["files"]["recent_competitive_load"] = "data/recent_competitive_load.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps({
        "source_health": latest["source_health_summary"],
        "external_consensus": latest["external_consensus_summary"],
        "competitive_load": latest["competitive_load_summary"],
    }, ensure_ascii=False))
    return framework


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
