from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "v6" / "source_registry.json"
OVERRIDES = ROOT / "config" / "v6" / "source_overrides.json"

EXPECTED_SOURCE_IDS = (
    "official_fpl", "official_price_predictor", "understat", "opta_the_analyst",
    "statmuse", "onside", "ben_crellin", "fffix", "ffhub", "onefpl", "livefpl",
    "ffscout", "fbref", "fotmob", "sofascore", "statsbomb", "rotowire",
    "premierleague_stats", "clubelo", "football_data_uk", "sportmonks", "api_football",
    "transfermarkt", "whoscored", "espn", "football_data_org", "vaastav_fpl",
)

_ALLOWED_ACQUISITION_KINDS = {"derived", "rest_json", "rest_csv", "html_scrape", "rss", "generic_http"}
_ALLOWED_VERIFICATION_STATUSES = {"PENDING", "VERIFIED", "FAILED"}


class RegistryError(ValueError):
    pass


def _merge_source(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key == "id":
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **deepcopy(value)}
        else:
            merged[key] = deepcopy(value)
    return merged


def _apply_overrides(payload: dict[str, Any], path: Path = OVERRIDES) -> dict[str, Any]:
    if not path.exists():
        return payload
    override_payload = json.loads(path.read_text(encoding="utf-8"))
    overrides = dict(override_payload.get("sources") or {})
    if not overrides:
        return payload

    out = deepcopy(payload)
    known = {str(source.get("id")) for source in out.get("sources") or []}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise RegistryError(f"unknown V6 source override ids: {unknown!r}")

    out["sources"] = [
        _merge_source(source, dict(overrides.get(str(source.get("id"))) or {}))
        for source in out.get("sources") or []
    ]
    out["source_overrides_applied"] = sorted(overrides)
    return out


def _infer_acquisition_kind(source: dict[str, Any]) -> str:
    if source.get("adapter") == "official_price_predictor":
        return "derived"
    if source.get("adapter") == "official_fpl":
        return "rest_json"
    expects = {str(request.get("expect") or "").lower() for request in source.get("requests") or []}
    if expects == {"json"}:
        return "rest_json"
    if expects == {"csv"}:
        return "rest_csv"
    return "generic_http"


def _normalize_ingestion_policy(payload: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(payload)
    normalized = []
    for source in out.get("sources") or []:
        row = deepcopy(source)
        row.setdefault("acquisition_kind", _infer_acquisition_kind(row))
        normalized.append(row)
    out["sources"] = normalized
    return out


def load_registry(path: Path = CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload = _apply_overrides(payload)
    payload = _normalize_ingestion_policy(payload)
    validate_registry(payload)
    return payload


def _positive_int(source: dict[str, Any], key: str) -> None:
    value = source.get(key)
    if value is None:
        return
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RegistryError(f"invalid {key}: {source['id']}") from exc
    if parsed <= 0:
        raise RegistryError(f"invalid {key}: {source['id']}")


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
        if source.get("acquisition_kind") not in _ALLOWED_ACQUISITION_KINDS:
            raise RegistryError(f"unsupported acquisition kind: {source['id']}")
        for key in ("poll_interval_minutes", "poll_interval_minutes_deadline_window", "daily_request_budget"):
            _positive_int(source, key)
        if source.get("content_hash_dedup") not in {None, True, False}:
            raise RegistryError(f"invalid content_hash_dedup: {source['id']}")
        if source.get("verification_required") is True:
            status = str(source.get("verification_status") or "").upper()
            if status not in _ALLOWED_VERIFICATION_STATUSES:
                raise RegistryError(f"verification status required: {source['id']}")
        auth = source.get("auth")
        if auth:
            if auth.get("mode") not in {"header", "query"}:
                raise RegistryError(f"unsupported auth mode: {source['id']}")
            if not auth.get("env") or not auth.get("name"):
                raise RegistryError(f"incomplete auth configuration: {source['id']}")


def source_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(source["id"]): source for source in payload["sources"]}
