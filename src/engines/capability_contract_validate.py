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


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ids(payload: dict[str, Any]) -> set[str]:
    for key in ("modules", "layers", "checks"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return {str(row.get("id")) for row in rows if row.get("id")}
    return set()


def run() -> dict[str, Any]:
    master = _load(MASTER)
    dss_ids = _ids(_load(DSS_CORE))
    ext_ids = _ids(_load(DSS_EXT))
    enh_ids = _ids(_load(ENH))
    gate_ids = _ids(_load(GATE0))
    service_ids = set((_load(SERVICES).get("services") or {}).keys())
    rows = list(master.get("capabilities") or [])
    errors: list[str] = []

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
    for row in rows:
        cap_id = str(row.get("id") or "")
        owner_service = str(row.get("owner_service") or "")
        if owner_service not in service_ids:
            errors.append(f"{cap_id} owner_service is not a runtime service: {owner_service}")
        consumers = [str(value) for value in row.get("consumer_services") or []]
        invalid_consumers = sorted(set(consumers) - service_ids)
        if invalid_consumers:
            errors.append(f"{cap_id} invalid consumer services: {invalid_consumers}")
        if owner_service in consumers:
            errors.append(f"{cap_id} owner_service repeated as consumer: {owner_service}")

        owns = row.get("owns") or {}
        for value in owns.get("dss") or []:
            owners[str(value)].append(cap_id)
        for value in owns.get("extensions") or []:
            ext_owners[str(value)].append(cap_id)

        refs = row.get("references") or {}
        invalid_gate = sorted(set(str(x) for x in refs.get("gate0") or []) - gate_ids)
        invalid_enh = sorted(set(str(x) for x in refs.get("enhancements") or []) - enh_ids)
        invalid_related = sorted(set(str(x) for x in refs.get("related_dss") or []) - dss_ids)
        if invalid_gate:
            errors.append(f"{cap_id} invalid Gate0 references: {invalid_gate}")
        if invalid_enh:
            errors.append(f"{cap_id} invalid Enhancement references: {invalid_enh}")
        if invalid_related:
            errors.append(f"{cap_id} invalid related DSS references: {invalid_related}")
        # A primitive owned by this capability must never also be presented as a
        # cross-domain related reference within the same capability.
        same_ref = sorted(set(str(x) for x in owns.get("dss") or []) & set(str(x) for x in refs.get("related_dss") or []))
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
        "duplicate_dss_owners": duplicate_dss,
        "duplicate_extension_owners": duplicate_ext,
        "policy": {
            "primitive_ownership_is_bijective": not missing_dss and not duplicate_dss and not missing_ext and not duplicate_ext,
            "enhancement_and_rec_are_non_owning_references": True,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
