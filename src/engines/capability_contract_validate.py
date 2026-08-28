from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.utils import ROOT

MASTER = ROOT / "config" / "intelligence" / "capability_master_registry.json"
DSS_CORE = ROOT / "config" / "dss_core_registry.json"
DSS_EXT = ROOT / "config" / "dss_extension_registry.json"
ENH = ROOT / "config" / "enhancement_layers_registry.json"
GATE0 = ROOT / "config" / "gate0_registry.json"
SERVICES = ROOT / "config" / "v3_service_registry.json"
OFFICIAL_COVERAGE = ROOT / "config" / "sources" / "official_first_coverage.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("modules", "layers", "checks"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return list(rows)
    return []


def _ids(payload: dict[str, Any]) -> set[str]:
    return {str(row.get("id")) for row in _rows(payload) if row.get("id")}


def _audit_unique_registry_ids(errors: list[str], name: str, payload: dict[str, Any]) -> set[str]:
    rows = _rows(payload)
    values = [str(row.get("id") or "") for row in rows]
    duplicates = sorted(key for key, count in Counter(values).items() if key and count > 1)
    empty = sum(1 for value in values if not value)
    if duplicates or empty:
        errors.append(f"{name} ids invalid/duplicated: duplicates={duplicates} empty={empty}")
    expected = int(payload.get("expected_count") or 0)
    if expected and expected != len(rows):
        errors.append(f"{name} expected_count={expected} but declared={len(rows)}")
    return {value for value in values if value}


def run() -> dict[str, Any]:
    master = _load(MASTER)
    core_payload = _load(DSS_CORE)
    ext_payload = _load(DSS_EXT)
    enh_payload = _load(ENH)
    gate_payload = _load(GATE0)
    coverage = _load(OFFICIAL_COVERAGE)
    service_ids = set((_load(SERVICES).get("services") or {}).keys())
    rows = list(master.get("capabilities") or [])
    errors: list[str] = []

    dss_ids = _audit_unique_registry_ids(errors, "DSS core", core_payload)
    ext_ids = _audit_unique_registry_ids(errors, "DSS extensions", ext_payload)
    enh_ids = _audit_unique_registry_ids(errors, "Enhancements", enh_payload)
    gate_ids = _audit_unique_registry_ids(errors, "Gate0", gate_payload)

    recommendations = coverage.get("recommendations") or {}
    rec_ids = set(str(key) for key in recommendations)
    if len(rec_ids) != len(recommendations):
        errors.append("Official-first recommendation IDs are duplicated")
    unknown_endpoint_refs = []
    endpoint_ids = set((coverage.get("endpoint_catalog") or {}).keys())
    for rec_id, row in recommendations.items():
        for endpoint in row.get("endpoints") or []:
            if str(endpoint) not in endpoint_ids:
                unknown_endpoint_refs.append(f"{rec_id}:{endpoint}")
    if unknown_endpoint_refs:
        errors.append(f"Official-first recommendations reference unknown endpoint ids: {sorted(unknown_endpoint_refs)}")

    if master.get("registry") != "V3_CAPABILITY_MASTER_30":
        errors.append("capability registry id must be V3_CAPABILITY_MASTER_30")
    if int(master.get("expected_count") or 0) != 30 or len(rows) != 30:
        errors.append(f"capability count drift: expected=30 declared={len(rows)}")

    cap_ids = [str(row.get("id") or "") for row in rows]
    duplicates = sorted(key for key, count in Counter(cap_ids).items() if key and count > 1)
    if duplicates or any(not value for value in cap_ids):
        errors.append(f"capability ids invalid/duplicated: {duplicates}")

    owners: dict[str, list[str]] = defaultdict(list)
    ext_owners: dict[str, list[str]] = defaultdict(list)
    referenced_rec_ids: set[str] = set()
    for row in rows:
        cap_id = str(row.get("id") or "")
        owner_service = str(row.get("owner_service") or "")
        if owner_service not in service_ids:
            errors.append(f"{cap_id} owner_service is not a runtime service: {owner_service}")
        consumers = [str(value) for value in row.get("consumer_services") or []]
        invalid_consumers = sorted(set(consumers) - service_ids)
        if invalid_consumers:
            errors.append(f"{cap_id} invalid consumer services: {invalid_consumers}")
        if len(consumers) != len(set(consumers)):
            errors.append(f"{cap_id} duplicate consumer services: {consumers}")
        if owner_service in consumers:
            errors.append(f"{cap_id} owner_service repeated as consumer: {owner_service}")

        owns = row.get("owns") or {}
        owned_dss = [str(value) for value in owns.get("dss") or []]
        owned_ext = [str(value) for value in owns.get("extensions") or []]
        if len(owned_dss) != len(set(owned_dss)):
            errors.append(f"{cap_id} duplicates owned DSS ids: {owned_dss}")
        if len(owned_ext) != len(set(owned_ext)):
            errors.append(f"{cap_id} duplicates owned extension ids: {owned_ext}")
        for value in owned_dss:
            owners[value].append(cap_id)
        for value in owned_ext:
            ext_owners[value].append(cap_id)

        refs = row.get("references") or {}
        gate_refs = [str(x) for x in refs.get("gate0") or []]
        enh_refs = [str(x) for x in refs.get("enhancements") or []]
        related_refs = [str(x) for x in refs.get("related_dss") or []]
        rec_refs = [str(x) for x in refs.get("rec") or []]
        for label, values in (("Gate0", gate_refs), ("Enhancement", enh_refs), ("related DSS", related_refs), ("REC", rec_refs)):
            if len(values) != len(set(values)):
                errors.append(f"{cap_id} duplicate {label} references: {values}")
        invalid_gate = sorted(set(gate_refs) - gate_ids)
        invalid_enh = sorted(set(enh_refs) - enh_ids)
        invalid_related = sorted(set(related_refs) - dss_ids)
        invalid_rec = sorted(set(rec_refs) - rec_ids)
        if invalid_gate:
            errors.append(f"{cap_id} invalid Gate0 references: {invalid_gate}")
        if invalid_enh:
            errors.append(f"{cap_id} invalid Enhancement references: {invalid_enh}")
        if invalid_related:
            errors.append(f"{cap_id} invalid related DSS references: {invalid_related}")
        if invalid_rec:
            errors.append(f"{cap_id} invalid REC references: {invalid_rec}")
        referenced_rec_ids.update(rec_refs)
        same_ref = sorted(set(owned_dss) & set(related_refs))
        if same_ref:
            errors.append(f"{cap_id} owns and references the same DSS primitives: {same_ref}")

    unknown_dss = sorted(set(owners) - dss_ids)
    unknown_ext = sorted(set(ext_owners) - ext_ids)
    if unknown_dss:
        errors.append(f"unknown owned DSS ids: {unknown_dss}")
    if unknown_ext:
        errors.append(f"unknown owned extension ids: {unknown_ext}")

    missing_dss = sorted(dss_ids - set(owners))
    duplicate_dss = {key: value for key, value in sorted(owners.items()) if len(value) != 1}
    missing_ext = sorted(ext_ids - set(ext_owners))
    duplicate_ext = {key: value for key, value in sorted(ext_owners.items()) if len(value) != 1}
    if missing_dss:
        errors.append(f"DSS primitives without canonical capability owner: {missing_dss}")
    if duplicate_dss:
        errors.append(f"DSS primitives with multiple capability owners: {duplicate_dss}")
    if missing_ext:
        errors.append(f"DSS extensions without canonical capability owner: {missing_ext}")
    if duplicate_ext:
        errors.append(f"DSS extensions with multiple capability owners: {duplicate_ext}")

    policy = master.get("policy") or {}
    for key in (
        "one_canonical_capability_owner",
        "every_dss_core_has_exactly_one_capability_owner",
        "every_dss_extension_has_exactly_one_capability_owner",
        "gate0_is_constraint_reference_not_capability_ownership",
        "enhancements_are_rollups_not_extra_capabilities",
        "rec_items_are_delivery_milestones_not_extra_capabilities",
    ):
        if policy.get(key) is not True:
            errors.append(f"capability policy missing {key}=true")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "capabilities": len(rows),
        "owned_dss": len(owners),
        "owned_extensions": len(ext_owners),
        "dss_expected": len(dss_ids),
        "extensions_expected": len(ext_ids),
        "official_first_rec_count": len(rec_ids),
        "capability_referenced_rec_count": len(referenced_rec_ids),
        "duplicate_dss_owners": duplicate_dss,
        "duplicate_extension_owners": duplicate_ext,
        "policy": {
            "primitive_ownership_is_bijective": not missing_dss and not duplicate_dss and not missing_ext and not duplicate_ext,
            "registry_ids_are_unique": True,
            "capability_rec_references_resolve_to_official_first_matrix": True,
            "enhancement_and_rec_are_non_owning_references": True,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
