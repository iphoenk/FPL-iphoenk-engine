from __future__ import annotations

import importlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.sources.base import SourceResult, SourceSpec
from src.sources.observations import OBSERVATION_CONTRACT, OBSERVATION_SCHEMA_VERSION, normalize_subject_key
from src.sources.registry import load_source_registry, registry_integrity, source_specs
from src.utils import read_json

OBSERVATION_FILE = "challenger_observations.json"


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _official_result(spec: SourceSpec, data_dir: Path) -> SourceResult:
    health = read_json(data_dir / "health.json", {})
    critical = ("bootstrap", "fixtures", "entry", "history", "transfers")
    states = {name: (health.get(name) or {}).get("status") for name in critical}
    live = all(states.get(name) == "LIVE" for name in critical)
    latencies = [(health.get(name) or {}).get("latency_ms") for name in critical]
    numeric = [float(x) for x in latencies if x is not None]
    return SourceResult(spec.source_id, "LIVE" if live else "DEGRADED", live, round(max(numeric), 3) if numeric else None, 0, {cap: "AUTHORITATIVE_NATIVE" if live else "DEGRADED" for cap in spec.capabilities}, {"critical_endpoints": states, "authority": "Official FPL", "reused_collector_health": True})


def _artifact_result(spec: SourceSpec, data_dir: Path) -> SourceResult:
    paths = [str(x) for x in spec.config.get("artifact_paths") or []]
    states = {path: (data_dir / path).exists() and (data_dir / path).stat().st_size > 2 for path in paths}
    live = bool(paths) and all(states.values())
    return SourceResult(spec.source_id, "LIVE" if live else "PARTIAL", live, 0.0, sum(1 for ok in states.values() if ok), {cap: "INGESTED" if live else "PARTIAL" for cap in spec.capabilities}, {"artifacts": states, "artifact_backed": True})


def _weather_artifact_result(spec: SourceSpec, data_dir: Path) -> SourceResult:
    payload = read_json(data_dir / "fixture_weather.json", {})
    exists = bool(payload)
    available = int(payload.get("available_count") or 0)
    fixtures = int(payload.get("fixture_count") or 0)
    material = int(payload.get("material_count") or 0)
    if not exists:
        status = "PARTIAL"
        state = "UNAVAILABLE"
    elif available > 0:
        status = "LIVE"
        state = "AVAILABLE"
    else:
        status = "LIVE"
        state = "NO_FORECAST_IN_WINDOW"
    return SourceResult(
        spec.source_id,
        status,
        exists,
        0.0,
        available,
        {cap: state for cap in spec.capabilities},
        {
            "artifact": "fixture_weather.json",
            "fixture_count": fixtures,
            "available_count": available,
            "material_count": material,
            "advisory_only": bool((payload.get("governance") or {}).get("advisory_only")),
        },
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
    if spec.adapter == "weather_artifact":
        return _weather_artifact_result(spec, data_dir)
    return _web_result(spec, timeout_seconds)


def _structured_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in payload.get("observations") or [] if isinstance(row, dict) and row.get("contract") == OBSERVATION_CONTRACT]


def _legacy_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in payload.get("observations") or [] if isinstance(row, dict) and row.get("contract") != OBSERVATION_CONTRACT]


def _age_seconds(row: dict[str, Any], now: datetime) -> float | None:
    observed = _parse_dt(row.get("observed_at") or row.get("fetched_at"))
    if observed is None:
        return None
    return max(0.0, (now - observed).total_seconds())


def _reconcile_observations(previous: dict[str, Any], fresh: list[dict[str, Any]], now: datetime) -> tuple[list[dict[str, Any]], dict[str, int]]:
    fresh_by_key = {str(row.get("observation_key")): dict(row) for row in fresh if row.get("observation_key")}
    reconciled = list(fresh_by_key.values())
    counts = {"fresh": len(reconciled), "cached_last_known_good": 0, "stale": 0, "legacy": 0}
    for prior in _structured_rows(previous):
        key = str(prior.get("observation_key") or "")
        if not key or key in fresh_by_key:
            continue
        row = dict(prior)
        ttl = max(1, int(row.get("ttl_seconds") or 1))
        age = _age_seconds(row, now)
        row["stale"] = True
        if age is not None and age <= ttl:
            row["status"] = "CACHED_LAST_KNOWN_GOOD"
            counts["cached_last_known_good"] += 1
        else:
            row["status"] = "STALE"
            counts["stale"] += 1
        reconciled.append(row)
    legacy = _legacy_rows(previous)
    counts["legacy"] = len(legacy)
    return legacy + reconciled, counts


def _fresh_price_direction(row: dict[str, Any]) -> str | None:
    if row.get("contract") != OBSERVATION_CONTRACT or row.get("capability") != "price_prediction":
        return None
    if row.get("status") != "AVAILABLE" or row.get("stale"):
        return None
    value = row.get("value") or {}
    if not isinstance(value, dict):
        return None
    direction = str(value.get("direction") or "").upper()
    return direction if direction in {"RISE", "FALL", "STABLE"} else None


def _disagreement_states(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        direction = _fresh_price_direction(row)
        if direction is None:
            continue
        subject = normalize_subject_key((row.get("subject") or {}).get("player") or row.get("subject_key"))
        if subject:
            grouped.setdefault(subject, []).append(row)
    out = []
    for subject, items in grouped.items():
        directions = {str((item.get("value") or {}).get("direction")).upper() for item in items}
        providers = sorted({str(item.get("source_id") or item.get("provider")) for item in items})
        state = "SINGLE_SOURCE" if len(providers) == 1 else ("AGREEMENT" if len(directions) == 1 else "DISAGREEMENT")
        out.append({"subject_key": subject, "player": (items[0].get("subject") or {}).get("player"), "capability": "price_prediction", "state": state, "providers": providers, "directions": sorted(directions)})
    out.sort(key=lambda row: (row["state"] != "DISAGREEMENT", row.get("player") or row["subject_key"]))
    return out


def _capability_health(specs: list[SourceSpec], results: dict[str, SourceResult], reconciled: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        result = results[spec.source_id]
        for capability in spec.capabilities:
            state = result.capabilities.get(capability, "UNAVAILABLE")
            fallback = [row for row in reconciled if row.get("contract") == OBSERVATION_CONTRACT and row.get("source_id") == spec.source_id and row.get("capability") == capability and row.get("status") in {"CACHED_LAST_KNOWN_GOOD", "STALE"}]
            if state not in {"AVAILABLE", "AUTHORITATIVE_NATIVE", "INGESTED", "NO_FORECAST_IN_WINDOW"} and fallback:
                state = "CACHED_LAST_KNOWN_GOOD" if any(row.get("status") == "CACHED_LAST_KNOWN_GOOD" for row in fallback) else "STALE"
            rows.append({"source_id": spec.source_id, "source_class": spec.source_class, "capability": capability, "source_status": result.status, "source_reachable": result.reachable, "data_state": state, "fresh_observations": sum(1 for row in reconciled if row.get("contract") == OBSERVATION_CONTRACT and row.get("source_id") == spec.source_id and row.get("capability") == capability and row.get("status") == "AVAILABLE" and not row.get("stale"))})
    return rows


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
                results[spec.source_id] = SourceResult(spec.source_id, "UNAVAILABLE", False, None, 0, {cap: "UNAVAILABLE" for cap in spec.capabilities}, {"error": type(exc).__name__, "isolated_failure": True})
    rows = []
    fresh_observations: list[dict[str, Any]] = []
    for spec in specs:
        result = results[spec.source_id]
        fresh_observations.extend(dict(row) for row in result.observations)
        rows.append({"id": spec.source_id, "name": spec.name, "class": spec.source_class, "tier": spec.tier, "critical": spec.critical, "enabled": spec.enabled, **result.as_dict()})
    now = datetime.now(timezone.utc)
    prior = read_json(data_dir / OBSERVATION_FILE, {"schema_version": OBSERVATION_SCHEMA_VERSION, "observations": []})
    observations, observation_counts = _reconcile_observations(prior, fresh_observations, now)
    disagreement = _disagreement_states(observations)
    capabilities = _capability_health(specs, results, observations)
    enabled = [row for row in rows if row["enabled"]]
    critical_failed = [row["id"] for row in enabled if row["critical"] and row["status"] not in {"LIVE"}]
    challengers = [row for row in enabled if row["class"] == "CHALLENGER"]
    challenger_live = [row["id"] for row in challengers if row["status"] == "LIVE"]
    overall = "RED" if critical_failed else ("GREEN" if all(row["status"] == "LIVE" for row in enabled) else "AMBER")
    observation_payload = {"schema_version": OBSERVATION_SCHEMA_VERSION, "contract": OBSERVATION_CONTRACT, "generated_at": now.isoformat(), "observations": observations, "counts": observation_counts, "cross_source": disagreement, "policy": {"official_native_fields_win": True, "missing_observations_are_not_fabricated": True, "source_reachability_is_separate_from_capability_health": True, "cached_or_stale_rows_are_not_current": True}}
    return {
        "schema_version": 2,
        "registry": registry_integrity(),
        "overall": overall,
        "decision_blocking": bool(critical_failed),
        "critical_failed": critical_failed,
        "source_count": len(rows),
        "enabled_count": len(enabled),
        "challenger_live": challenger_live,
        "challenger_live_count": len(challenger_live),
        "structured_observation_count": observation_counts["fresh"],
        "structured_cached_count": observation_counts["cached_last_known_good"],
        "structured_stale_count": observation_counts["stale"],
        "disagreement_count": sum(1 for row in disagreement if row["state"] == "DISAGREEMENT"),
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "sources": rows,
        "capability_health": capabilities,
        "challenger_observations_payload": observation_payload,
        "policy": {"official_native_fields_win": True, "challenger_failure_does_not_block": True, "missing_observations_are_not_fabricated": True, "public_probe_does_not_equal_data_ingestion": True, "source_reachability_is_separate_from_capability_health": True, "stale_observations_are_never_silently_current": True, "weather_is_advisory_enrichment_only": True},
    }
