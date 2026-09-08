from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_migration import migrate_legacy_canonical_provenance
from .artifact_provenance import build_artifact_meta, publication_provenance
from .store import OUT, write_json

CATALOG_RELATIVE_PATH = "evidence/artifact_catalog.json"
PUBLISH_INTEGRITY_RELATIVE_PATH = "health/publish_integrity.json"
_ORIGIN_STATUSES = {"PROVEN", "LEGACY_UNKNOWN", "LOCAL_UNKNOWN"}


def _catalog_digest(artifacts: list[dict[str, Any]]) -> str:
    raw = json.dumps(artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _iter_catalogued_files(root: Path) -> list[Path]:
    excluded = {
        root / CATALOG_RELATIVE_PATH,
        root / PUBLISH_INTEGRITY_RELATIVE_PATH,
    }
    return sorted(
        path
        for path in root.rglob("*.json")
        if path.is_file() and path not in excluded and not path.name.endswith(".tmp")
    )


def _completeness_summary(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0}
    incomplete_paths: list[str] = []
    for meta in artifacts:
        status = str(meta.get("provenance_status") or "INCOMPLETE")
        counts[status] = counts.get(status, 0) + 1
        if status == "INCOMPLETE":
            incomplete_paths.append(str(meta.get("path") or ""))
    return {
        "status": "PASS" if not incomplete_paths else "FAIL",
        "counts": counts,
        "incomplete_count": len(incomplete_paths),
        "incomplete_paths": sorted(incomplete_paths),
    }


def _previous_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    path = root / CATALOG_RELATIVE_PATH
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    artifacts = catalog.get("artifacts") or []
    return {
        str(meta.get("path") or ""): dict(meta)
        for meta in artifacts
        if isinstance(meta, dict) and meta.get("path")
    }


def _origin_errors(meta: dict[str, Any], relative: str) -> list[str]:
    errors: list[str] = []
    origin = meta.get("origin_provenance")
    if not isinstance(origin, dict):
        return [f"artifact_origin_provenance_missing:{relative}"]
    status = str(origin.get("status") or "")
    if status not in _ORIGIN_STATUSES:
        errors.append(f"artifact_origin_status_invalid:{relative}:{status or 'MISSING'}")
        return errors
    if status == "PROVEN":
        for field in (
            "origin_producer_sha",
            "origin_run_id",
            "origin_workflow",
            "origin_generated_at",
        ):
            if not origin.get(field):
                errors.append(f"artifact_origin_field_missing:{relative}:{field}")
    elif any(
        origin.get(field)
        for field in (
            "origin_producer_sha",
            "origin_run_id",
            "origin_workflow",
            "origin_generated_at",
        )
    ):
        errors.append(f"artifact_unknown_origin_must_not_be_fabricated:{relative}")
    return errors


def build_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    publication = publication_provenance(published_at=generated_at)
    previous = _previous_artifacts(root)
    artifacts = [
        build_artifact_meta(
            root,
            path.relative_to(root).as_posix(),
            previous_meta=previous.get(f"data/v6/{path.relative_to(root).as_posix()}"),
            publication=publication,
        )
        for path in _iter_catalogued_files(root)
    ]
    return {
        "schema_version": 3,
        "canonical": True,
        "semantic_class": "CONTROL_TELEMETRY",
        "authority": "V6_DATA_PLATFORM",
        "generated_at": generated_at,
        "effective_at": generated_at,
        "normalization_version": "V6_ARTIFACT_CATALOG_3",
        "primary_keys": ["path"],
        "record_count": len(artifacts),
        "catalog_sha256": _catalog_digest(artifacts),
        **publication,
        "publication_provenance": publication,
        "execution_provenance": publication,
        "completeness": _completeness_summary(artifacts),
        "excluded_paths": [
            f"data/v6/{CATALOG_RELATIVE_PATH}",
            f"data/v6/{PUBLISH_INTEGRITY_RELATIVE_PATH}",
        ],
        "artifacts": artifacts,
        "governance": {
            "data_only": True,
            "decision_authority": "NONE",
            "prediction_authority": "NONE",
            "optimizer_authority": "NONE",
            "catalog_is_non_recursive": True,
            "publish_integrity_is_excluded_to_avoid_digest_cycle": True,
            "artifact_provenance_contract": "V6_ARTIFACT_PROVENANCE_2",
            "origin_provenance_is_immutable_while_content_digest_is_unchanged": True,
            "publication_provenance_changes_per_publication_execution": True,
            "pre_contract_reused_origin_is_explicitly_legacy_unknown": True,
            "legacy_origin_is_never_inferred_from_republisher_execution": True,
            "class_aware_completeness": True,
            "immutable_source_snapshot_ids_required_for_usable_current_sources": True,
            "canonical_dataset_provenance_fail_closed": True,
            "legacy_canonical_migration_is_count_guarded": True,
        },
    }


def refresh_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    migration = migrate_legacy_canonical_provenance(root)
    catalog = build_artifact_catalog(root)
    catalog["legacy_provenance_migration"] = migration
    write_json(root / CATALOG_RELATIVE_PATH, catalog)
    return catalog


def validate_artifact_catalog(root: Path = OUT) -> dict[str, Any]:
    path = root / CATALOG_RELATIVE_PATH
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "valid": False,
            "errors": ["artifact_catalog_missing_or_invalid"],
            "checked": 0,
            "provenance_complete": False,
            "incomplete_count": 0,
        }

    errors: list[str] = []
    artifacts = list(catalog.get("artifacts") or [])
    if catalog.get("schema_version") != 3:
        errors.append("artifact_catalog_schema_version_mismatch")
    if int(catalog.get("record_count") or -1) != len(artifacts):
        errors.append("artifact_catalog_record_count_mismatch")
    if catalog.get("catalog_sha256") != _catalog_digest(artifacts):
        errors.append("artifact_catalog_digest_mismatch")

    publication = catalog.get("publication_provenance")
    if not isinstance(publication, dict):
        errors.append("artifact_catalog_publication_provenance_missing")
        publication = {}

    migration = catalog.get("legacy_provenance_migration")
    if isinstance(migration, dict) and migration.get("valid") is False:
        errors.extend(
            f"artifact_provenance_migration:{error}"
            for error in migration.get("errors") or []
        )

    expected_paths = {path.relative_to(root).as_posix() for path in _iter_catalogued_files(root)}
    catalog_paths: set[str] = set()
    incomplete_paths: list[str] = []
    status_counts = {"COMPLETE": 0, "INCOMPLETE": 0, "NOT_APPLICABLE": 0}

    for meta in artifacts:
        if not isinstance(meta, dict):
            errors.append("artifact_catalog_non_object_entry")
            continue
        configured = str(meta.get("path") or "")
        relative = configured.removeprefix("data/v6/")
        if not relative:
            errors.append("artifact_catalog_entry_missing_path")
            continue
        if relative in catalog_paths:
            errors.append(f"artifact_catalog_duplicate_path:{relative}")
            continue
        catalog_paths.add(relative)
        artifact_path = root / relative
        if not artifact_path.is_file():
            errors.append(f"artifact_catalog_missing_file:{relative}")
            continue

        errors.extend(_origin_errors(meta, relative))
        if meta.get("publication_provenance") != publication:
            errors.append(f"artifact_publication_provenance_mismatch:{relative}")

        expected_meta = build_artifact_meta(
            root,
            relative,
            previous_meta=meta,
            publication=publication,
        )
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != meta.get("sha256"):
            errors.append(f"artifact_catalog_sha_mismatch:{relative}")
        if artifact_path.stat().st_size != meta.get("bytes"):
            errors.append(f"artifact_catalog_size_mismatch:{relative}")
        if meta.get("artifact_class") != expected_meta.get("artifact_class"):
            errors.append(f"artifact_catalog_class_mismatch:{relative}")
        if meta.get("source_snapshot_ids") != expected_meta.get("source_snapshot_ids"):
            errors.append(f"artifact_catalog_snapshot_provenance_mismatch:{relative}")
        if meta.get("completeness") != expected_meta.get("completeness"):
            errors.append(f"artifact_catalog_completeness_mismatch:{relative}")

        status = str((expected_meta.get("completeness") or {}).get("status") or "INCOMPLETE")
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "INCOMPLETE":
            incomplete_paths.append(configured)
            missing_fields = ",".join(
                str(field)
                for field in (expected_meta.get("completeness") or {}).get("missing_fields") or []
            )
            errors.append(f"artifact_provenance_incomplete:{relative}:{missing_fields}")

    missing = sorted(expected_paths - catalog_paths)
    extra = sorted(catalog_paths - expected_paths)
    if missing:
        errors.append(f"artifact_catalog_missing_paths:{','.join(missing)}")
    if extra:
        errors.append(f"artifact_catalog_extra_paths:{','.join(extra)}")

    expected_completeness = {
        "status": "PASS" if not incomplete_paths else "FAIL",
        "counts": status_counts,
        "incomplete_count": len(incomplete_paths),
        "incomplete_paths": sorted(incomplete_paths),
    }
    if catalog.get("completeness") != expected_completeness:
        errors.append("artifact_catalog_completeness_summary_mismatch")

    return {
        "valid": not errors,
        "errors": errors,
        "checked": len(artifacts),
        "schema_version": catalog.get("schema_version"),
        "provenance_complete": not incomplete_paths,
        "complete_count": status_counts.get("COMPLETE", 0),
        "incomplete_count": len(incomplete_paths),
        "not_applicable_count": status_counts.get("NOT_APPLICABLE", 0),
        "incomplete_paths": sorted(incomplete_paths),
        "legacy_provenance_migration_valid": not (
            isinstance(migration, dict) and migration.get("valid") is False
        ),
        "origin_publication_provenance_separated": True,
    }


def main() -> int:
    catalog = refresh_artifact_catalog(OUT)
    report = validate_artifact_catalog(OUT)
    print(json.dumps({"record_count": catalog["record_count"], "validation": report}, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
