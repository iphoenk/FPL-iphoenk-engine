from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from .source_policy import (
    SourcePolicyError,
    materialize_config_request_params,
    normalize_addition_admission,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "v6" / "source_registry.json"
ADDITIONS = ROOT / "config" / "v6" / "source_additions.json"
OVERRIDES = ROOT / "config" / "v6" / "source_overrides.json"
ACTIVATION = ROOT / "config" / "v6" / "source_activation.json"

_LAYER_SCHEMA_VERSIONS = {
    CONFIG: 3,
    ADDITIONS: 1,
    OVERRIDES: 3,
    ACTIVATION: 4,
}
_ALLOWED_ACQUISITION_KINDS = {"derived", "rest_json", "rest_csv", "html_scrape", "rss", "generic_http"}
_ALLOWED_VERIFICATION_STATUSES = {"PENDING", "VERIFIED", "FAILED"}
_ALLOWED_SOURCE_TIERS = {"core", "pilot", "reference_only"}
ZERO_AUTHORITY_KEYS = (
    "decision_authority",
    "prediction_authority",
    "optimizer_authority",
    "tactical_authority",
    "transfer_authority",
    "captain_authority",
    "chip_authority",
    "formation_authority",
)


class RegistryError(ValueError):
    pass


def _read_json(path: Path, *, expected_schema_version: int | None = None) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if expected_schema_version is not None:
        actual = payload.get("schema_version")
        if actual != expected_schema_version:
            raise RegistryError(
                f"V6 config schema mismatch for {path.name}: expected {expected_schema_version}, got {actual!r}"
            )
    return payload


def _read_layer(path: Path) -> dict[str, Any]:
    expected = _LAYER_SCHEMA_VERSIONS.get(path)
    return _read_json(path, expected_schema_version=expected)


def config_layer_metadata() -> dict[str, dict[str, Any]]:
    return {
        "registry": {"path": "config/v6/source_registry.json", "schema_version": _LAYER_SCHEMA_VERSIONS[CONFIG]},
        "additions": {"path": "config/v6/source_additions.json", "schema_version": _LAYER_SCHEMA_VERSIONS[ADDITIONS]},
        "overrides": {"path": "config/v6/source_overrides.json", "schema_version": _LAYER_SCHEMA_VERSIONS[OVERRIDES]},
        "activation": {"path": "config/v6/source_activation.json", "schema_version": _LAYER_SCHEMA_VERSIONS[ACTIVATION]},
    }


def _configured_source_ids() -> tuple[str, ...]:
    base = list((_read_layer(CONFIG).get("sources") or []))
    additions = list((_read_layer(ADDITIONS).get("sources") or []))
    ids = tuple(str(row.get("id")) for row in [*base, *additions])
    if len(set(ids)) != len(ids):
        raise RegistryError("duplicate V6 configured source ids")
    return ids


def _activation_id_set(key: str) -> set[str]:
    payload = _read_layer(ACTIVATION)
    return {str(source_id) for source_id in dict(payload.get(key) or {})}


# Compatibility exports used by tests and downstream diagnostics. These are
# intentionally derived from configuration rather than hard-coded source lists.
BASE_SOURCE_IDS = _configured_source_ids()
_DISABLED_IDS = _activation_id_set("disabled_sources")
_REFERENCE_ONLY_IDS = _activation_id_set("reference_only_sources")
DROPPED_SOURCE_IDS = tuple(source_id for source_id in BASE_SOURCE_IDS if source_id in _DISABLED_IDS)
REFERENCE_ONLY_SOURCE_IDS = tuple(source_id for source_id in BASE_SOURCE_IDS if source_id in _REFERENCE_ONLY_IDS)
EXPECTED_SOURCE_IDS = tuple(
    source_id
    for source_id in BASE_SOURCE_IDS
    if source_id not in _DISABLED_IDS and source_id not in _REFERENCE_ONLY_IDS
)


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


def _apply_additions(payload: dict[str, Any], path: Path = ADDITIONS) -> dict[str, Any]:
    additions_payload = _read_json(path, expected_schema_version=1)
    try:
        additions_payload = normalize_addition_admission(additions_payload)
    except SourcePolicyError as exc:
        raise RegistryError(str(exc)) from exc
    additions = list(additions_payload.get("sources") or [])
    if not additions:
        return payload

    out = deepcopy(payload)
    known = {str(source.get("id")) for source in out.get("sources") or []}
    addition_ids = [str(source.get("id")) for source in additions]
    duplicates = sorted(known.intersection(addition_ids))
    if duplicates:
        raise RegistryError(f"duplicate V6 source additions: {duplicates!r}")
    if len(set(addition_ids)) != len(addition_ids):
        raise RegistryError("duplicate ids inside V6 source additions")

    out["sources"] = [*(out.get("sources") or []), *deepcopy(additions)]
    out["source_additions_applied"] = addition_ids
    out["source_addition_admission_policy"] = deepcopy(additions_payload.get("admission_policy") or {})
    return out


def _validate_base_source_set(payload: dict[str, Any]) -> None:
    ids = tuple(str(row.get("id")) for row in payload.get("sources") or [])
    if ids != BASE_SOURCE_IDS:
        raise RegistryError(f"V6 configured source definition set/order mismatch: {ids!r}")
    if len(set(ids)) != len(ids):
        raise RegistryError("duplicate V6 configured source ids")


def _override_lifecycle_summary(override_payload: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    policy = dict(override_payload.get("policy") or {})
    lifecycle = dict(override_payload.get("lifecycle") or {})
    if policy.get("role") != "TEMPORARY_REPAIR_ONLY":
        raise RegistryError("V6 source overrides must be TEMPORARY_REPAIR_ONLY")
    if policy.get("stable_repairs_should_be_promoted_to_canonical_registry") is not True:
        raise RegistryError("V6 source override policy must require canonical promotion")
    if policy.get("inactive_sources_must_not_have_overrides") is not True:
        raise RegistryError("V6 source override policy must reject inactive-source overrides")

    try:
        max_active = int(policy.get("max_active_overrides"))
    except (TypeError, ValueError) as exc:
        raise RegistryError("V6 source override max_active_overrides must be an integer") from exc
    if max_active <= 0 or len(overrides) > max_active:
        raise RegistryError(f"V6 source override count exceeds governed maximum: {len(overrides)} > {max_active}")

    if set(lifecycle) != set(overrides):
        missing = sorted(set(overrides) - set(lifecycle))
        orphaned = sorted(set(lifecycle) - set(overrides))
        raise RegistryError(f"V6 source override lifecycle mismatch: missing={missing!r} orphaned={orphaned!r}")

    inactive = set(overrides).intersection(_DISABLED_IDS | _REFERENCE_ONLY_IDS)
    if inactive:
        raise RegistryError(f"inactive/reference-only V6 sources must not retain overrides: {sorted(inactive)!r}")

    review_by: dict[str, str] = {}
    for source_id, metadata_raw in lifecycle.items():
        metadata = dict(metadata_raw or {})
        if metadata.get("temporary") is not True:
            raise RegistryError(f"V6 source override must be temporary: {source_id}")
        if not str(metadata.get("reason") or "").strip():
            raise RegistryError(f"V6 source override requires lifecycle reason: {source_id}")
        review = str(metadata.get("review_by") or "").strip()
        try:
            review_date = date.fromisoformat(review)
        except ValueError as exc:
            raise RegistryError(f"V6 source override requires ISO review_by date: {source_id}") from exc
        if review_date < date.today():
            raise RegistryError(f"V6 source override review_by is overdue: {source_id} -> {review}")
        review_by[source_id] = review

    return {
        "role": "TEMPORARY_REPAIR_ONLY",
        "active_override_count": len(overrides),
        "max_active_overrides": max_active,
        "inactive_source_overrides": [],
        "temporary_override_ids": sorted(overrides),
        "review_by": review_by,
        "stable_repairs_should_be_promoted_to_canonical_registry": True,
        "effective_registry_is_published_for_drift_review": policy.get("effective_registry_is_published_for_drift_review") is True,
    }


def _apply_overrides(payload: dict[str, Any], path: Path = OVERRIDES) -> dict[str, Any]:
    override_payload = _read_json(path, expected_schema_version=3)
    overrides = dict(override_payload.get("sources") or {})
    lifecycle_summary = _override_lifecycle_summary(override_payload, overrides)
    if not overrides:
        out = deepcopy(payload)
        out["source_overrides_applied"] = []
        out["override_lifecycle"] = lifecycle_summary
        return out

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
    out["override_lifecycle"] = lifecycle_summary
    return out


def _apply_activation(payload: dict[str, Any], path: Path = ACTIVATION) -> dict[str, Any]:
    if not path.exists():
        return payload

    activation = _read_json(path, expected_schema_version=4)
    disabled = dict(activation.get("disabled_sources") or {})
    reference_only = dict(activation.get("reference_only_sources") or {})
    constraints = dict(activation.get("constraints") or {})
    tiers = dict(activation.get("tiers") or {})
    out = deepcopy(payload)
    configured = list(out.get("sources") or [])
    known = {str(source.get("id")) for source in configured}
    unknown = sorted((set(disabled) | set(reference_only) | set(constraints) | set(tiers)) - known)
    if unknown:
        raise RegistryError(f"unknown V6 source activation ids: {unknown!r}")

    overlap = sorted(set(disabled).intersection(reference_only))
    if overlap:
        raise RegistryError(f"V6 source cannot be both disabled and reference-only: {overlap!r}")

    required = {
        str(source.get("id"))
        for source in configured
        if source.get("required_for_platform") is True
    }
    pruned_required = sorted(required.intersection(set(disabled) | set(reference_only)))
    if pruned_required:
        raise RegistryError(f"required V6 platform sources cannot be pruned: {pruned_required!r}")

    sources: list[dict[str, Any]] = []
    for source in configured:
        source_id = str(source.get("id"))
        if source_id in disabled or source_id in reference_only:
            continue
        row = deepcopy(source)
        if source_id in constraints:
            row["activation_constraint"] = str(constraints[source_id])
        if source_id in tiers:
            row["source_tier"] = str(tiers[source_id])
        sources.append(row)

    out["sources"] = sources
    out["activation"] = {
        "policy": str(activation.get("policy") or "explicit_active_source_pruning"),
        "base_source_count": len(known),
        "active_source_count": len(sources),
        "disabled_source_count": len(disabled),
        "reference_only_source_count": len(reference_only),
        "required_active_source_count": len(required),
        "required_active_sources": sorted(required),
        "disabled_sources": disabled,
        "reference_only_sources": reference_only,
        "constraints": constraints,
        "tiers": tiers,
    }
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


def dependency_layers(payload: dict[str, Any]) -> list[list[str]]:
    sources = list(payload.get("sources") or [])
    ordered_ids = [str(source["id"]) for source in sources]
    dependencies = {
        str(source["id"]): [str(dependency) for dependency in source.get("depends_on") or []]
        for source in sources
    }
    active = set(ordered_ids)
    for source_id, required in dependencies.items():
        missing = [dependency for dependency in required if dependency not in active]
        if missing:
            raise RegistryError(f"active V6 dependency missing: {source_id} -> {missing!r}")

    remaining = set(ordered_ids)
    completed: set[str] = set()
    layers: list[list[str]] = []
    while remaining:
        layer = [
            source_id
            for source_id in ordered_ids
            if source_id in remaining and all(dependency in completed for dependency in dependencies[source_id])
        ]
        if not layer:
            cycle = [source_id for source_id in ordered_ids if source_id in remaining]
            raise RegistryError(f"cyclic V6 source dependency graph: {cycle!r}")
        layers.append(layer)
        completed.update(layer)
        remaining.difference_update(layer)
    return layers


def resolved_registry_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine": payload["engine"],
        "season": payload["season"],
        "config_layers": config_layer_metadata(),
        "source_additions_applied": list(payload.get("source_additions_applied") or []),
        "source_addition_admission_policy": deepcopy(payload.get("source_addition_admission_policy") or {}),
        "source_overrides_applied": list(payload.get("source_overrides_applied") or []),
        "override_lifecycle": deepcopy(payload.get("override_lifecycle") or {}),
        "cadence": deepcopy(payload.get("cadence") or {}),
        "policy": deepcopy(payload.get("policy") or {}),
        "identity": deepcopy(payload.get("identity") or {}),
        "activation": deepcopy(payload.get("activation") or {}),
        "dependency_layers": dependency_layers(payload),
        "source_count": len(payload.get("sources") or []),
        "sources": deepcopy(payload.get("sources") or []),
    }


def load_registry(path: Path = CONFIG) -> dict[str, Any]:
    payload = _read_json(path, expected_schema_version=3)
    payload = _apply_additions(payload)
    _validate_base_source_set(payload)
    payload = _apply_overrides(payload)
    try:
        payload = materialize_config_request_params(payload)
    except SourcePolicyError as exc:
        raise RegistryError(str(exc)) from exc
    payload = _normalize_ingestion_policy(payload)
    payload = _apply_activation(payload)
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
    if any(policy.get(key) != "NONE" for key in ZERO_AUTHORITY_KEYS):
        raise RegistryError(f"V6 must have zero authority for: {', '.join(ZERO_AUTHORITY_KEYS)}")
    if policy.get("data_only") is not True:
        raise RegistryError("V6 must remain data-only")
    if policy.get("no_fabrication") is not True:
        raise RegistryError("V6 must prohibit fabricated values")

    sources = list(payload.get("sources") or [])
    ids = tuple(str(row.get("id")) for row in sources)
    active_ids = set(ids)
    if ids != EXPECTED_SOURCE_IDS:
        raise RegistryError(f"V6 active source set/order mismatch: {ids!r}")
    if len(active_ids) != len(ids):
        raise RegistryError("duplicate V6 active source ids")

    override_lifecycle = dict(payload.get("override_lifecycle") or {})
    override_ids = set(payload.get("source_overrides_applied") or [])
    if override_lifecycle.get("role") != "TEMPORARY_REPAIR_ONLY":
        raise RegistryError("V6 effective registry missing temporary override lifecycle contract")
    if set(override_lifecycle.get("temporary_override_ids") or []) != override_ids:
        raise RegistryError("V6 effective registry override lifecycle does not match applied overrides")
    if override_ids.intersection(_DISABLED_IDS | _REFERENCE_ONLY_IDS):
        raise RegistryError("V6 effective registry contains inactive-source overrides")

    activation = payload.get("activation") or {}
    if activation:
        disabled = tuple(source_id for source_id in BASE_SOURCE_IDS if source_id in activation.get("disabled_sources", {}))
        reference_only = tuple(
            source_id for source_id in BASE_SOURCE_IDS if source_id in activation.get("reference_only_sources", {})
        )
        if disabled != DROPPED_SOURCE_IDS:
            raise RegistryError(f"V6 dropped source set/order mismatch: {disabled!r}")
        if reference_only != REFERENCE_ONLY_SOURCE_IDS:
            raise RegistryError(f"V6 reference-only source set/order mismatch: {reference_only!r}")
        if activation.get("active_source_count") != len(EXPECTED_SOURCE_IDS):
            raise RegistryError("V6 active source count mismatch")
        if activation.get("base_source_count") != len(BASE_SOURCE_IDS):
            raise RegistryError("V6 configured source count mismatch")
        required_active = set(activation.get("required_active_sources") or [])
        if not required_active.issubset(active_ids):
            raise RegistryError("V6 required platform source missing from active set")

    for source in sources:
        if not source.get("name") or not source.get("category") or not source.get("adapter"):
            raise RegistryError(f"incomplete source metadata: {source.get('id')}")
        if source.get("critical") not in {True, False}:
            raise RegistryError(f"critical flag must be boolean: {source['id']}")
        if source.get("required_for_platform") not in {None, True, False}:
            raise RegistryError(f"required_for_platform flag must be boolean: {source['id']}")
        if source["adapter"] == "http" and not source.get("requests"):
            raise RegistryError(f"http source has no requests: {source['id']}")
        if source.get("acquisition_kind") not in _ALLOWED_ACQUISITION_KINDS:
            raise RegistryError(f"unsupported acquisition kind: {source['id']}")
        for key in ("poll_interval_minutes", "poll_interval_minutes_deadline_window", "daily_request_budget"):
            _positive_int(source, key)
        if source.get("content_hash_dedup") not in {None, True, False}:
            raise RegistryError(f"invalid content_hash_dedup: {source['id']}")
        tier = source.get("source_tier")
        if tier is not None and str(tier) not in _ALLOWED_SOURCE_TIERS:
            raise RegistryError(f"invalid source tier: {source['id']}")
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

    dependency_layers(payload)


def source_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(source["id"]): source for source in payload["sources"]}
