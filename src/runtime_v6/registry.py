from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "v6" / "source_registry.json"

EXPECTED_SOURCE_IDS = (
    "official_fpl", "official_price_predictor", "understat", "statmuse", "onside",
    "ben_crellin", "fffix", "ffhub", "onefpl", "livefpl", "ffscout", "statsbomb",
    "rotowire", "premierleague_stats", "football_data_uk", "api_football",
    "transfermarkt", "vaastav_fpl",
)

class RegistryError(ValueError):
    pass

def load_registry(path: Path = CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(payload)
    return payload

def validate_registry(payload: dict[str, Any]) -> None:
    if payload.get("engine") != "V6_FRESH_DATA_PLATFORM":
        raise RegistryError("unexpected V6 engine contract")
    policy = payload.get("policy") or {}
    forbidden_authorities = ("decision_authority", "prediction_authority", "optimizer_authority")
    if any(policy.get(key) != "NONE" for key in forbidden_authorities):
        raise RegistryError("V6 must have zero decision/prediction/optimizer authority")
    if policy.get("data_only") is not True:
        raise RegistryError("V6 must remain data-only")
    if policy.get("no_fabrication") is not True:
        raise RegistryError("V6 must prohibit fabricated values")
    sources = list(payload.get("sources") or [])
    ids = tuple(str(row.get("id")) for row in sources)
    if ids != EXPECTED_SOURCE_IDS:
        raise RegistryError(f"V6 source set/order mismatch: {ids!r}")
    if len(set(ids)) != len(ids):
        raise RegistryError("duplicate V6 source ids")
    for source in sources:
        if not source.get("name") or not source.get("category") or not source.get("adapter"):
            raise RegistryError(f"incomplete source metadata: {source.get('id')}")
        if source["adapter"] == "http" and not source.get("requests"):
            raise RegistryError(f"http source has no requests: {source['id']}")
        auth = source.get("auth")
        if auth:
            if auth.get("mode") not in {"header", "query"}:
                raise RegistryError(f"unsupported auth mode: {source['id']}")
            if not auth.get("env") or not auth.get("name"):
                raise RegistryError(f"incomplete auth configuration: {source['id']}")

def source_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(source["id"]): source for source in payload["sources"]}
