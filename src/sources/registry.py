from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.sources.base import SourceSpec
from src.utils import ROOT

REGISTRY_PATH = ROOT / "config" / "sources" / "registry.json"


@lru_cache(maxsize=1)
def load_source_registry() -> dict:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("source registry has no sources")
    ids = [str(row.get("id") or "") for row in rows]
    if any(not source_id for source_id in ids) or len(ids) != len(set(ids)):
        raise RuntimeError("source registry ids must be non-empty and unique")
    if not any(row.get("id") == "official_fpl" and row.get("class") == "AUTHORITATIVE" for row in rows):
        raise RuntimeError("official_fpl authoritative source is required")
    return payload


def source_specs() -> tuple[SourceSpec, ...]:
    payload = load_source_registry()
    specs = []
    for row in payload["sources"]:
        specs.append(SourceSpec(
            source_id=str(row["id"]),
            name=str(row.get("name") or row["id"]),
            source_class=str(row.get("class") or "ENRICHMENT"),
            tier=int(row.get("tier") or 99),
            enabled=bool(row.get("enabled", True)),
            critical=bool(row.get("critical", False)),
            adapter=str(row.get("adapter") or "disabled"),
            capabilities=tuple(str(x) for x in row.get("capabilities") or ()),
            config=dict(row),
        ))
    return tuple(specs)


def registry_integrity() -> dict:
    payload = load_source_registry()
    specs = source_specs()
    return {
        "registry": payload.get("registry"),
        "schema_version": payload.get("schema_version"),
        "declared": len(specs),
        "enabled": sum(1 for spec in specs if spec.enabled),
        "authoritative": [spec.source_id for spec in specs if spec.source_class == "AUTHORITATIVE"],
        "challengers": [spec.source_id for spec in specs if spec.source_class == "CHALLENGER"],
        "enrichment": [spec.source_id for spec in specs if spec.source_class == "ENRICHMENT"],
        "integrity_ok": True,
    }
