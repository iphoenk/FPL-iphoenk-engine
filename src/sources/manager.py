from __future__ import annotations

import importlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from src.sources.base import SourceResult, SourceSpec
from src.sources.registry import load_source_registry, registry_integrity, source_specs
from src.utils import read_json


def _official_result(spec: SourceSpec, data_dir: Path) -> SourceResult:
    health = read_json(data_dir / "health.json", {})
    critical = ("bootstrap", "fixtures", "entry", "history", "transfers")
    states = {name: (health.get(name) or {}).get("status") for name in critical}
    live = all(states.get(name) == "LIVE" for name in critical)
    latencies = [(health.get(name) or {}).get("latency_ms") for name in critical]
    numeric = [float(x) for x in latencies if x is not None]
    return SourceResult(
        spec.source_id,
        "LIVE" if live else "DEGRADED",
        live,
        round(max(numeric), 3) if numeric else None,
        0,
        {cap: "AUTHORITATIVE_NATIVE" if live else "DEGRADED" for cap in spec.capabilities},
        {"critical_endpoints": states, "authority": "Official FPL", "reused_collector_health": True},
    )


def _artifact_result(spec: SourceSpec, data_dir: Path) -> SourceResult:
    paths = [str(x) for x in spec.config.get("artifact_paths") or []]
    states = {path: (data_dir / path).exists() and (data_dir / path).stat().st_size > 2 for path in paths}
    live = bool(paths) and all(states.values())
    return SourceResult(
        spec.source_id,
        "LIVE" if live else "PARTIAL",
        live,
        0.0,
        sum(1 for ok in states.values() if ok),
        {cap: "INGESTED" if live else "PARTIAL" for cap in spec.capabilities},
        {"artifacts": states, "artifact_backed": True},
    )


def _web_result(spec: SourceSpec, timeout_seconds: float) -> SourceResult:
    module = importlib.import_module(f"src.sources.{spec.adapter}")
    probe: Callable[[SourceSpec, float], SourceResult] = getattr(module, "probe")
    return probe(spec, timeout_seconds)


def _run_one(spec: SourceSpec, data_dir: Path, timeout_seconds: float) -> SourceResult:
    if not spec.enabled or spec.adapter == "disabled":
        return SourceResult(spec.source_id, "DISABLED", False, None, 0, {cap: "DISABLED" for cap in spec.capabilities}, {"reason": "disabled by registry"})
    if spec.adapter == "runtime_official":
        return _official_result(spec, data_dir)
    if spec.adapter == "artifact":
        return _artifact_result(spec, data_dir)
    return _web_result(spec, timeout_seconds)


def collect_sources(data_dir: Path) -> dict[str, Any]:
    registry = load_source_registry()
    policy = registry.get("policy") or {}
    timeout_seconds = float(policy.get("default_timeout_seconds") or 2.5)
    max_workers = max(1, int(policy.get("max_workers") or 6))
    specs = source_specs()
    started = time.perf_counter()
    results: dict[str, SourceResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, spec, data_dir, timeout_seconds): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                results[spec.source_id] = future.result()
            except Exception as exc:
                results[spec.source_id] = SourceResult(
                    spec.source_id,
                    "UNAVAILABLE",
                    False,
                    None,
                    0,
                    {cap: "UNAVAILABLE" for cap in spec.capabilities},
                    {"error": type(exc).__name__, "isolated_failure": True},
                )
    rows = []
    for spec in specs:
        result = results[spec.source_id]
        row = {
            "id": spec.source_id,
            "name": spec.name,
            "class": spec.source_class,
            "tier": spec.tier,
            "critical": spec.critical,
            "enabled": spec.enabled,
            **result.as_dict(),
        }
        rows.append(row)
    enabled = [row for row in rows if row["enabled"]]
    critical_failed = [row["id"] for row in enabled if row["critical"] and row["status"] not in {"LIVE"}]
    challengers = [row for row in enabled if row["class"] == "CHALLENGER"]
    challenger_live = [row["id"] for row in challengers if row["status"] == "LIVE"]
    overall = "RED" if critical_failed else ("GREEN" if all(row["status"] == "LIVE" for row in enabled) else "AMBER")
    return {
        "schema_version": 1,
        "registry": registry_integrity(),
        "overall": overall,
        "decision_blocking": bool(critical_failed),
        "critical_failed": critical_failed,
        "source_count": len(rows),
        "enabled_count": len(enabled),
        "challenger_live": challenger_live,
        "challenger_live_count": len(challenger_live),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "sources": rows,
        "policy": {
            "official_native_fields_win": True,
            "challenger_failure_does_not_block": True,
            "missing_observations_are_not_fabricated": True,
            "public_probe_does_not_equal_data_ingestion": True,
        },
    }
