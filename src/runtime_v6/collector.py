from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .adapters import collect_source
from .health import build_source_health
from .http_client import AcquisitionClient, utc_now
from .normalizer import (
    build_canonical_fixtures,
    build_canonical_players,
    build_canonical_teams,
    build_evidence_index,
    build_lineage_catalog,
)
from .polling import attach_poll_result, carry_forward_skipped, deadline_window_active, poll_decision
from .registry import load_registry, source_map
from .store import EVIDENCE, HEALTH, MANIFEST, NORMALIZED, load_previous_sources, write_json, write_source


def _isolated_failure(source: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "source_id": source["id"],
        "source_name": source["name"],
        "category": source["category"],
        "adapter": source["adapter"],
        "critical": bool(source.get("critical")),
        "independence_group": source.get("independence_group"),
        "checked_at": utc_now(),
        "health": "RED" if source.get("critical") else "AMBER",
        "availability": "UNAVAILABLE",
        "effective_state": "MISSING",
        "changed": None,
        "error": type(exc).__name__,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "isolated_failure": True,
            "values_not_invented": True,
        },
    }


def run() -> dict[str, Any]:
    config = load_registry()
    sources = list(config["sources"])
    by_id = source_map(config)
    previous = load_previous_sources()
    client = AcquisitionClient(config["policy"])
    results: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()

    scheduler_interval_minutes = max(
        1,
        int((config.get("cadence") or {}).get("scheduler_interval_minutes") or 60),
    )
    deadline_window = deadline_window_active(
        previous,
        hours=int(config["policy"].get("deadline_window_hours") or 48),
    )

    # Only the derived Official price source has a dependency. All network-backed
    # sources that are due start together so one slow authority does not block
    # unrelated acquisition. Sources not due are carried forward explicitly.
    runnable = [source for source in sources if source["id"] != "official_price_predictor"]
    decisions = {
        source["id"]: poll_decision(
            source,
            previous.get(source["id"]),
            deadline_window=deadline_window,
            max_attempts_per_request=client.retry_attempts,
            scheduler_interval_minutes=scheduler_interval_minutes,
        )
        for source in runnable
    }
    due_sources = [source for source in runnable if decisions[source["id"]]["due"]]
    for source in runnable:
        decision = decisions[source["id"]]
        if not decision["due"]:
            results[source["id"]] = carry_forward_skipped(
                source,
                previous.get(source["id"]),
                decision,
            )

    source_workers = max(
        1,
        min(
            max(1, len(due_sources)),
            int(config["policy"].get("source_workers") or config["policy"].get("max_workers") or 12),
        ),
    )

    if due_sources:
        with ThreadPoolExecutor(max_workers=source_workers) as pool:
            futures = {
                pool.submit(
                    collect_source,
                    source,
                    client,
                    previous=previous.get(source["id"]),
                ): source
                for source in due_sources
            }
            for future in as_completed(futures):
                source = futures[future]
                decision = decisions[source["id"]]
                try:
                    payload = future.result()
                except Exception as exc:
                    payload = _isolated_failure(source, exc)
                results[source["id"]] = attach_poll_result(
                    source,
                    payload,
                    previous.get(source["id"]),
                    decision,
                )

    official = results.get("official_fpl") or _isolated_failure(
        by_id["official_fpl"],
        RuntimeError("official_fpl_missing_from_results"),
    )
    price_source = by_id["official_price_predictor"]
    try:
        results["official_price_predictor"] = collect_source(
            price_source,
            client,
            previous=previous.get("official_price_predictor"),
            official_payload=official,
        )
    except Exception as exc:
        results["official_price_predictor"] = _isolated_failure(price_source, exc)

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
    critical_failures = [
        source["id"]
        for source in sources
        if source.get("critical") and results[source["id"]].get("health") == "RED"
    ]
    durations = {
        source_id: payload.get("duration_ms")
        for source_id, payload in results.items()
        if payload.get("duration_ms") is not None
    }
    skipped = {
        source_id: (payload.get("polling") or {}).get("reason")
        for source_id, payload in results.items()
        if (payload.get("polling") or {}).get("skipped") is True
    }

    manifest = {
        "schema_version": 3,
        "engine": config["engine"],
        "season": config["season"],
        "generated_at": utc_now(),
        "elapsed_ms": elapsed,
        "source_count": len(sources),
        "source_ids": source_ids,
        "overall": "RED" if critical_failures else health["overall"],
        "health_counts": health["counts"],
        "critical_failures": critical_failures,
        "performance": {
            "source_workers": source_workers,
            "request_workers_per_source": client.request_workers,
            "source_duration_ms": durations,
            "slowest_source_ms": max(durations.values()) if durations else None,
            "official_blocks_unrelated_sources": False,
        },
        "polling": {
            "adaptive": True,
            "scheduler_interval_minutes": scheduler_interval_minutes,
            "deadline_window_active": deadline_window,
            "deadline_window_hours": int(config["policy"].get("deadline_window_hours") or 48),
            "due_source_count": len(due_sources),
            "skipped_source_count": len(skipped),
            "skipped_sources": skipped,
        },
        "paths": {
            "current_sources": "data/v6/current/",
            "health": "data/v6/health/source_health.json",
            "canonical_players": "data/v6/normalized/canonical_players.json",
            "canonical_teams": "data/v6/normalized/canonical_teams.json",
            "canonical_fixtures": "data/v6/normalized/canonical_fixtures.json",
            "lineage": "data/v6/evidence/lineage.json",
            "evidence_index": "data/v6/evidence/latest_index.json",
        },
        "governance": {
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "data_only": True,
            "no_cross_source_averaging": True,
            "no_fabrication": True,
            "source_failures_are_isolated": True,
            "request_failures_are_isolated": True,
            "unchanged_upstream_is_not_degraded": True,
            "last_good_cache_hydrated_by_workflow": True,
            "adaptive_polling_is_registry_driven": True,
            "daily_budget_timezone": "Asia/Jakarta",
        },
    }
    write_json(MANIFEST, manifest)
    return manifest


def main() -> int:
    print(json.dumps(run(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
