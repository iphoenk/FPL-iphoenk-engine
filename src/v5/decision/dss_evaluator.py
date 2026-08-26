from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from src.v5.config_cache import load_json_config

CORE = "config/dss_core_registry.json"
EXT = "config/dss_extension_registry.json"


def _registry(path: str) -> list[dict[str, Any]]:
    data = load_json_config(path)
    rows = data.get("modules")
    if not isinstance(rows, list):
        raise RuntimeError(f"invalid DSS registry: {path}")
    return rows


def _capability_sources(
    truth: dict[str, Any],
    price: dict[str, Any],
    prediction: dict[str, Any],
    local_capabilities: Iterable[str],
    external_capability_sources: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, list[str]]:
    sources: dict[str, list[str]] = {}
    for service_name, payload in (("truth", truth), ("price", price), ("prediction", prediction)):
        for capability in payload.get("capabilities") or []:
            sources.setdefault(str(capability), []).append(service_name)
    for capability in local_capabilities:
        sources.setdefault(str(capability), []).append("decision")
    for service_name, capabilities in (external_capability_sources or {}).items():
        for capability in capabilities:
            sources.setdefault(str(capability), []).append(str(service_name))
    return {key: sorted(set(values)) for key, values in sources.items()}


def _audit(rows: list[dict[str, Any]], capability_sources: dict[str, list[str]], expected: int) -> dict[str, Any]:
    ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    integrity_ok = len(rows) == expected and not duplicates
    items = []
    for row in rows:
        probe = str(row.get("operational_probe") or row.get("probe") or "")
        active = bool(probe and probe in capability_sources)
        items.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "category": row.get("category"),
                "critical": bool(row.get("critical")),
                "probe": probe,
                "status": "ACTIVE" if active else "PARTIAL",
                "evidence_services": capability_sources.get(probe, []),
                "detail": (
                    "capability advertised by bounded-context owner"
                    if active
                    else "registered capability has no active runtime evidence contract yet"
                ),
            }
        )
    counts = Counter(item["status"] for item in items)
    active_count = counts.get("ACTIVE", 0)
    critical_partial = [item for item in items if item["critical"] and item["status"] != "ACTIVE"]
    return {
        "expected": expected,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "integrity_ok": integrity_ok,
        "counts": dict(counts),
        "coverage_ratio": round(active_count / max(1, len(rows)), 4),
        "critical_partial": critical_partial,
        "items": items,
    }


def evaluate_dss(
    truth: dict[str, Any],
    price: dict[str, Any],
    prediction: dict[str, Any],
    *,
    local_capabilities: Iterable[str] = (),
    external_capability_sources: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    sources = _capability_sources(
        truth,
        price,
        prediction,
        local_capabilities,
        external_capability_sources=external_capability_sources,
    )
    core = _audit(_registry(CORE), sources, expected=50)
    extensions = _audit(_registry(EXT), sources, expected=16)
    critical_partial = core["critical_partial"] + extensions["critical_partial"]
    return {
        "schema_version": 2,
        "evaluation_model": "capability_contract_dss_v2",
        "core": core,
        "extensions": extensions,
        "capability_sources": sources,
        "registry_integrity": bool(core["integrity_ok"] and extensions["integrity_ok"]),
        "critical_partial_count": len(critical_partial),
        "critical_partial": critical_partial,
        "unqualified_go_allowed": bool(core["integrity_ok"] and extensions["integrity_ok"] and not critical_partial),
    }
