from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from src.v5.config_cache import load_json_config

POLICY = "config/v5_dss_policy_registry.json"


def _policy() -> dict[str, Any]:
    data = load_json_config(POLICY)
    if not isinstance(data.get("registries"), dict) or not isinstance(data.get("statuses"), dict):
        raise RuntimeError("invalid V5 DSS policy registry")
    return data


def _registry_spec(name: str) -> dict[str, Any]:
    raw = _policy()["registries"].get(name)
    if not isinstance(raw, dict):
        raise KeyError(f"unknown DSS registry policy: {name}")
    return raw


def _registry(name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = _registry_spec(name)
    data = load_json_config(str(spec["path"]))
    rows = data.get("modules")
    if not isinstance(rows, list):
        raise RuntimeError(f"invalid DSS registry: {spec['path']}")
    return rows, spec


def _expected_ids(spec: Mapping[str, Any]) -> set[str]:
    count = int(spec["expected_count"])
    first = int(spec["first_index"])
    width = int(spec["zero_pad"])
    prefix = str(spec["id_prefix"])
    return {f"{prefix}{idx:0{width}d}" for idx in range(first, first + count)}


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


def _audit(
    rows: list[dict[str, Any]],
    spec: Mapping[str, Any],
    capability_sources: dict[str, list[str]],
) -> dict[str, Any]:
    statuses = _policy()["statuses"]
    active_status = str(statuses["active"])
    partial_status = str(statuses["partial"])
    ids = [str(row.get("id")) for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    expected_ids = _expected_ids(spec)
    declared_ids = set(ids)
    expected_count = int(spec["expected_count"])
    integrity_ok = len(rows) == expected_count and not duplicates and declared_ids == expected_ids
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
                "status": active_status if active else partial_status,
                "evidence_services": capability_sources.get(probe, []),
                "detail": (
                    "capability advertised by bounded-context owner"
                    if active
                    else "registered capability has no active runtime evidence contract yet"
                ),
            }
        )
    counts = Counter(item["status"] for item in items)
    active_count = counts.get(active_status, 0)
    critical_partial = [item for item in items if item["critical"] and item["status"] != active_status]
    return {
        "expected": expected_count,
        "declared": len(rows),
        "duplicate_ids": duplicates,
        "missing_ids": sorted(expected_ids - declared_ids),
        "unexpected_ids": sorted(declared_ids - expected_ids),
        "integrity_ok": integrity_ok,
        "counts": dict(counts),
        "coverage_ratio": round(active_count / max(1, len(rows)), 4),
        "all_active": bool(integrity_ok and active_count == expected_count),
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
    core_rows, core_spec = _registry("core")
    extension_rows, extension_spec = _registry("extensions")
    core = _audit(core_rows, core_spec, sources)
    extensions = _audit(extension_rows, extension_spec, sources)
    critical_partial = core["critical_partial"] + extensions["critical_partial"]
    governance = _policy().get("governance") or {}
    registry_integrity = bool(core["integrity_ok"] and extensions["integrity_ok"])
    all_modules_active = bool(core["all_active"] and extensions["all_active"])
    block_on_partial = bool(governance.get("critical_partial_blocks_unqualified_go", True))
    require_integrity = bool(governance.get("registry_integrity_required", True))
    require_all_active = bool(governance.get("all_modules_active_for_unqualified_go", True))
    unqualified_go = (
        (not require_integrity or registry_integrity)
        and (not block_on_partial or not critical_partial)
        and (not require_all_active or all_modules_active)
    )
    return {
        "schema_version": 4,
        "evaluation_model": _policy().get("evaluation_model"),
        "core": core,
        "extensions": extensions,
        "capability_sources": sources,
        "registry_integrity": registry_integrity,
        "all_modules_active": all_modules_active,
        "all_modules_active_required_for_unqualified_go": require_all_active,
        "critical_partial_count": len(critical_partial),
        "critical_partial": critical_partial,
        "unqualified_go_allowed": bool(unqualified_go),
    }
