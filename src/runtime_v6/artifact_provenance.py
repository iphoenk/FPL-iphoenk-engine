from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SUCCESS_STATUSES = {"AVAILABLE", "NOT_MODIFIED"}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ENFORCED_ARTIFACT_CLASSES = {
    "CURRENT_SOURCE",
    "SOURCE_NATIVE_NORMALIZED",
    "CANONICAL_DATASET",
}


def _record_count(payload: dict[str, Any]) -> int | None:
    for key in (
        "record_count",
        "player_count",
        "team_count",
        "fixture_count",
        "collected_manager_count",
        "source_count",
    ):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    for key in ("players", "teams", "fixtures", "managers", "elements", "entries"):
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            return len(value)
    return None


def _digest_from_snapshot_id(value: str) -> str | None:
    for token in reversed(value.split(":")):
        if _SHA256_RE.fullmatch(token):
            return token.lower()
    return None


def is_immutable_snapshot_id(value: str) -> bool:
    return _digest_from_snapshot_id(str(value)) is not None


def _row_snapshot_id(source_id: str, row: dict[str, Any]) -> str | None:
    digest = str(row.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        return None
    request_id = str(row.get("request_id") or "payload").strip() or "payload"
    return f"{source_id}:{request_id}:{digest}"


def source_snapshot_ids_for_payload(payload: dict[str, Any]) -> list[str]:
    """Return immutable payload identities without inventing cross-source joins."""
    source_id = str(payload.get("source_id") or payload.get("authority") or "source").strip() or "source"
    candidates: set[str] = set()

    explicit = payload.get("source_snapshot_ids")
    if isinstance(explicit, list):
        for raw in explicit:
            value = str(raw).strip()
            if value and is_immutable_snapshot_id(value):
                candidates.add(value)

    for row in payload.get("attempts") or []:
        if not isinstance(row, dict) or row.get("status") not in _SUCCESS_STATUSES:
            continue
        snapshot_id = _row_snapshot_id(source_id, row)
        if snapshot_id:
            candidates.add(snapshot_id)

    data = payload.get("data") or {}
    if isinstance(data, dict):
        for row in data.values():
            if not isinstance(row, dict):
                continue
            snapshot_id = _row_snapshot_id(source_id, row)
            if snapshot_id:
                candidates.add(snapshot_id)

    stack: list[Any] = [payload.get("lineage")]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            source = value.get("source_id") or value.get("authority")
            digest = str(value.get("payload_digest") or "").strip().lower()
            if source and _SHA256_RE.fullmatch(digest):
                candidates.add(f"{source}:{digest}")
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)

    return sorted(candidates)


def _resolve_explicit_source_references(
    root: Path,
    payload: dict[str, Any],
    snapshot_ids: list[str],
) -> list[str]:
    resolved = set(snapshot_ids)
    explicit = payload.get("source_snapshot_ids")
    if not isinstance(explicit, list):
        return sorted(resolved)

    own_source = str(payload.get("source_id") or "")
    for raw in explicit:
        reference = str(raw).strip()
        if not reference or is_immutable_snapshot_id(reference) or reference == own_source:
            continue
        candidate = root / "current" / f"{reference}.json"
        try:
            upstream = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(upstream, dict):
            resolved.update(source_snapshot_ids_for_payload(upstream))
    return sorted(resolved)


def classify_artifact(relative_path: str, payload: dict[str, Any] | None = None) -> str:
    relative = relative_path.removeprefix("data/v6/")
    if relative.startswith("current/"):
        return "CURRENT_SOURCE"
    if relative.startswith("normalized/sources/"):
        return "SOURCE_NATIVE_NORMALIZED"
    if relative.startswith("normalized/canonical_"):
        return "CANONICAL_DATASET"
    if relative == "manifest.json":
        return "MANIFEST"
    if relative.startswith("evidence/"):
        return "EVIDENCE"
    if relative.startswith("health/"):
        return "HEALTH_CONTROL"
    if relative.startswith("personal/") or relative.startswith("mini_leagues/"):
        return "REPORT_PREFETCH"
    configured = str((payload or {}).get("artifact_class") or "").strip()
    return configured or "AUXILIARY"


def _is_present(meta: dict[str, Any], field: str) -> bool:
    value = meta.get(field)
    if field == "canonical":
        return value is True
    if field == "record_count":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if field in {"primary_keys", "source_snapshot_ids"}:
        return isinstance(value, list) and bool(value)
    return value is not None and value != ""


def artifact_completeness(
    artifact_class: str,
    meta: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    if artifact_class not in _ENFORCED_ARTIFACT_CLASSES or meta.get("canonical") is False:
        return {
            "status": "NOT_APPLICABLE",
            "required_fields": [],
            "missing_fields": [],
            "provenance_basis": "NON_ENFORCED_ARTIFACT_CLASS",
        }

    if artifact_class == "CURRENT_SOURCE":
        required = ["schema_version", "source_id", "effective_at", "current_run_action"]
        availability = str(payload.get("availability") or "")
        if availability in {"AVAILABLE", "PARTIAL"}:
            required.append("source_snapshot_ids")
            basis = "IMMUTABLE_SOURCE_PAYLOAD_DIGESTS"
        else:
            basis = "FAILURE_EVENT_PROVENANCE_NO_USABLE_PAYLOAD"
    elif artifact_class == "SOURCE_NATIVE_NORMALIZED":
        required = [
            "schema_version",
            "source_id",
            "generated_at",
            "effective_at",
            "normalization_version",
            "authority",
            "semantic_class",
            "record_count",
            "source_snapshot_ids",
        ]
        basis = "NORMALIZED_SOURCE_WITH_IMMUTABLE_INPUT_DIGESTS"
    else:
        required = [
            "schema_version",
            "canonical",
            "generated_at",
            "effective_at",
            "normalization_version",
            "authority",
            "semantic_class",
            "record_count",
            "primary_keys",
            "source_snapshot_ids",
        ]
        basis = "CANONICAL_DATASET_WITH_IMMUTABLE_OFFICIAL_INPUT_DIGESTS"

    missing = [field for field in required if not _is_present(meta, field)]
    return {
        "status": "INCOMPLETE" if missing else "COMPLETE",
        "required_fields": required,
        "missing_fields": missing,
        "provenance_basis": basis,
    }


def publication_provenance(*, published_at: str | None = None) -> dict[str, Any]:
    timestamp = published_at or datetime.now(timezone.utc).isoformat()
    return {
        "publication_sha": os.getenv("GITHUB_SHA"),
        "publication_run_id": os.getenv("GITHUB_RUN_ID"),
        "publication_workflow": os.getenv("GITHUB_WORKFLOW"),
        "publication_logical_slot": os.getenv("V6_MASTER_LOGICAL_SLOT") or os.getenv("V6_REPORT_LOGICAL_SLOT"),
        "published_at": timestamp,
    }


def execution_provenance() -> dict[str, Any]:
    """Backward-compatible execution view.

    New callers should use publication_provenance(). Generic producer fields are
    intentionally no longer attached to artifact metadata because they cannot
    distinguish origin from a later publication/re-catalog execution.
    """
    publication = publication_provenance()
    return {
        "producer_sha": publication["publication_sha"],
        "producer_run_id": publication["publication_run_id"],
        "producer_workflow": publication["publication_workflow"],
        "logical_slot": publication["publication_logical_slot"],
    }


def _unknown_origin(status: str, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "origin_producer_sha": None,
        "origin_run_id": None,
        "origin_workflow": None,
        "origin_logical_slot": None,
        "origin_generated_at": None,
        "reason": reason,
    }


def _origin_from_publication(publication: dict[str, Any]) -> dict[str, Any]:
    required = (
        publication.get("publication_sha"),
        publication.get("publication_run_id"),
        publication.get("publication_workflow"),
    )
    if not all(required):
        return _unknown_origin(
            "LOCAL_UNKNOWN",
            "EXECUTION_IDENTITY_UNAVAILABLE_OUTSIDE_GITHUB_RUNTIME",
        )
    return {
        "status": "PROVEN",
        "origin_producer_sha": publication.get("publication_sha"),
        "origin_run_id": publication.get("publication_run_id"),
        "origin_workflow": publication.get("publication_workflow"),
        "origin_logical_slot": publication.get("publication_logical_slot"),
        "origin_generated_at": publication.get("published_at"),
        "reason": "ARTIFACT_FIRST_OBSERVED_OR_CONTENT_CHANGED_IN_THIS_EXECUTION",
    }


def _origin_for_artifact(
    digest: str,
    previous_meta: dict[str, Any] | None,
    publication: dict[str, Any],
) -> dict[str, Any]:
    previous = dict(previous_meta or {})
    if previous and str(previous.get("sha256") or "") == digest:
        explicit = previous.get("origin_provenance")
        if isinstance(explicit, dict) and explicit.get("status") in {
            "PROVEN",
            "LEGACY_UNKNOWN",
            "LOCAL_UNKNOWN",
        }:
            return dict(explicit)
        return _unknown_origin(
            "LEGACY_UNKNOWN",
            "PRE_ORIGIN_CONTRACT_ARTIFACT_REUSED_WITH_UNCHANGED_DIGEST",
        )
    return _origin_from_publication(publication)


def build_artifact_meta(
    output_root: Path,
    relative_path: str,
    *,
    previous_meta: dict[str, Any] | None = None,
    publication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = output_root / relative_path
    publication_meta = dict(publication or publication_provenance())
    if not path.exists():
        return {
            "path": f"data/v6/{relative_path}",
            "canonical": False,
            "omitted": True,
            "artifact_class": "DEPRECATED_REMOVED",
            "bytes": 0,
            "sha256": None,
            "provenance_status": "NOT_APPLICABLE",
            "origin_provenance": _unknown_origin("LEGACY_UNKNOWN", "ARTIFACT_NOT_PRESENT"),
            "publication_provenance": publication_meta,
            **publication_meta,
        }

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    origin = _origin_for_artifact(digest, previous_meta, publication_meta)
    meta: dict[str, Any] = {
        "path": f"data/v6/{relative_path}",
        "sha256": digest,
        "bytes": len(raw),
        "canonical": True,
        "origin_provenance": origin,
        "publication_provenance": publication_meta,
        **origin,
        **publication_meta,
    }
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    meta["canonical"] = payload.get("canonical") is not False
    if payload.get("deprecated") is not None:
        meta["deprecated"] = bool(payload.get("deprecated"))
    if payload.get("semantic_class") is not None:
        meta["semantic_class"] = payload.get("semantic_class")
    if payload.get("authority") is not None:
        meta["authority"] = payload.get("authority")
    meta["source_id"] = payload.get("source_id")
    meta["schema_version"] = payload.get("schema_version")
    meta["generated_at"] = payload.get("generated_at")
    meta["effective_at"] = payload.get("effective_at") or payload.get("checked_at")
    meta["record_count"] = _record_count(payload)
    meta["primary_keys"] = payload.get("primary_keys")
    snapshot_ids = source_snapshot_ids_for_payload(payload)
    meta["source_snapshot_ids"] = _resolve_explicit_source_references(output_root, payload, snapshot_ids)
    meta["normalization_version"] = payload.get("normalization_version")
    meta["freshness_class"] = payload.get("freshness_class") or payload.get("effective_state")
    meta["current_run_action"] = payload.get("current_run_action")
    artifact_class = classify_artifact(relative_path, payload)
    meta["artifact_class"] = artifact_class
    completeness = artifact_completeness(artifact_class, meta, payload)
    meta["provenance_status"] = completeness["status"]
    meta["completeness"] = completeness
    return meta
