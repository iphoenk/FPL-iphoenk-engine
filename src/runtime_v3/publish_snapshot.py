from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_v3.full_authority_cache import verify_full_authority
from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

REGISTRY_PATH = ROOT / "config" / "runtime" / "runtime_publish_registry.json"
PUBLIC_AUTH_PROJECTION = "PUBLIC_AUTH_HEALTH_V1"
ATTESTATION_REGISTRY_V1 = "V3_RUNTIME_WORKFLOW_ATTESTATION_V1"
ATTESTATION_REGISTRY = "V3_RUNTIME_WORKFLOW_ATTESTATION_V2"
ATTESTATION_DIGEST_CONTRACT = "MANIFEST_CORE_PLUS_DECLARED_PAYLOAD_V1"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "RUNTIME_PUBLISH_REGISTRY_V1":
        raise RuntimeError("unexpected runtime publish registry")
    paths = payload.get("publish_paths")
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("runtime publish registry has no publish_paths")
    return payload


def _copy_declared(source_root: Path, output_root: Path, paths: list[str]) -> list[str]:
    copied: list[str] = []
    for raw in paths:
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe runtime publish path: {raw}")
        source = source_root / relative
        if not source.exists() or not source.is_file():
            continue
        target = output_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative.as_posix())
    return copied


def _public_auth_projection(raw: Any) -> dict[str, Any]:
    """Project private authenticated enrichment to publication-safe health only."""
    payload = raw if isinstance(raw, dict) else {}
    readiness = payload.get("enhancement_health")
    if not isinstance(readiness, dict):
        readiness = payload.get("production_readiness")
    if not isinstance(readiness, dict):
        readiness = {}

    policy = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
    public_policy = {
        key: policy.get(key)
        for key in (
            "role",
            "primary_authority",
            "resource_methods",
            "allowed_endpoints",
            "redirects_followed",
            "redirects_rejected",
            "production_blocking",
            "configured_mode_requires_production_validation",
        )
        if key in policy
    }

    projection = {
        "public_projection": PUBLIC_AUTH_PROJECTION,
        "checked_at": payload.get("checked_at"),
        "expected_entry": payload.get("expected_entry"),
        "state": payload.get("state"),
        "mode": payload.get("mode"),
        "verified_entry": payload.get("verified_entry"),
        "raw_authenticated_payload_persisted": False,
        "production_readiness": dict(readiness),
        "enhancement_health": dict(readiness),
        "policy": public_policy,
    }
    if payload.get("failure_reason"):
        projection["failure_reason"] = str(payload.get("failure_reason"))
    return projection


def _sanitize_public_authenticated_state(output_data: Path) -> None:
    auth_path = output_data / "auth.json"
    if auth_path.is_file():
        auth = read_json(auth_path, {})
        atomic_json(auth_path, _public_auth_projection(auth))

    latest_path = output_data / "latest.json"
    if latest_path.is_file():
        latest = read_json(latest_path, {})
        if isinstance(latest, dict) and "authenticated_official" in latest:
            latest["authenticated_official"] = _public_auth_projection(latest.get("authenticated_official"))
            atomic_json(latest_path, latest)


def _checkpoint_metadata(
    generated_at: datetime,
    *,
    snapshot_role: str | None,
    target_checkpoint: str | None,
    target_visible_mode: str | None,
) -> dict[str, Any]:
    role = str(snapshot_role or "UNSCOPED_REFRESH")
    target_dt = None
    if target_checkpoint:
        try:
            target_dt = datetime.fromisoformat(str(target_checkpoint).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid logical target checkpoint: {target_checkpoint}") from exc
    precompute = role == "PRECOMPUTE_NEXT_CHECKPOINT"
    return {
        "snapshot_role": role,
        "target_checkpoint": target_dt.isoformat() if target_dt else None,
        "target_visible_mode": str(target_visible_mode or "") or None,
        "precomputed": precompute,
        "generated_before_or_at_target": bool(target_dt is not None and generated_at <= target_dt),
        "materialization_complete": True,
        "publication_proof": "PRESENCE_ON_RUNTIME_BRANCH",
    }


def _runtime_workflow_identity() -> tuple[int, int] | None:
    if os.getenv("GITHUB_WORKFLOW") != "V3 Runtime":
        return None
    raw_run_id = str(os.getenv("GITHUB_RUN_ID") or "").strip()
    raw_attempt = str(os.getenv("GITHUB_RUN_ATTEMPT") or "").strip()
    if not raw_run_id.isdigit() or int(raw_run_id) <= 0:
        raise RuntimeError("V3 Runtime publication requires a valid GITHUB_RUN_ID")
    if not raw_attempt.isdigit() or int(raw_attempt) <= 0:
        raise RuntimeError("V3 Runtime publication requires a valid GITHUB_RUN_ATTEMPT")
    return int(raw_run_id), int(raw_attempt)


def snapshot_digest(data_dir: Path, manifest: dict[str, Any]) -> str:
    """Hash immutable manifest semantics plus every declared payload byte.

    The attestation object and derived total-manifest byte count are excluded so
    the digest can be embedded in the manifest without recursion. All authority,
    freshness, checkpoint, runtime, whitelist and payload bytes remain covered.
    """
    core = deepcopy(manifest)
    core.pop("attestation", None)
    publication = core.get("publication")
    if not isinstance(publication, dict):
        raise RuntimeError("runtime manifest publication metadata missing for digest")
    publication.pop("bytes", None)
    paths = publication.get("paths")
    if not isinstance(paths, list):
        raise RuntimeError("runtime manifest publication paths missing for digest")

    digest = hashlib.sha256()
    digest.update(b"V3_RUNTIME_SNAPSHOT_V1\0")
    digest.update(
        json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    for raw in sorted(str(path) for path in paths):
        path = data_dir / raw
        if not path.is_file():
            raise RuntimeError(f"declared runtime payload missing for digest: {raw}")
        digest.update(b"\0PATH\0")
        digest.update(raw.encode("utf-8"))
        digest.update(b"\0DATA\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def materialize(
    source_root: Path,
    output_dir: Path,
    profile: str,
    source_commit: str | None = None,
    *,
    snapshot_role: str | None = None,
    target_checkpoint: str | None = None,
    target_visible_mode: str | None = None,
) -> dict[str, Any]:
    registry = _registry()
    workflow_identity = _runtime_workflow_identity()
    canonical_runtime_source = source_root.resolve() == DATA.resolve()
    authority_assurance = None
    if workflow_identity is not None and canonical_runtime_source:
        authority_assurance = verify_full_authority(profile)

    output_data = output_dir / "data"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_data.mkdir(parents=True, exist_ok=True)

    declared = [str(path) for path in registry.get("publish_paths") or [] if str(path) != "runtime_manifest.json"]
    copied = _copy_declared(source_root, output_data, declared)
    _sanitize_public_authenticated_state(output_data)
    payload_bytes = sum((output_data / relative).stat().st_size for relative in copied)

    performance = read_json(source_root / "runtime_performance.json", {})
    generated_at = datetime.now(timezone.utc)
    manifest = {
        "schema_version": 4 if workflow_identity is not None else 2,
        "registry": "RUNTIME_MANIFEST_V1",
        "engine_version": ENGINE_VERSION,
        "engine_schema_version": SCHEMA_VERSION,
        "execution_profile": profile,
        "source_commit": source_commit or os.getenv("GITHUB_SHA"),
        "generated_at": generated_at.isoformat(),
        "checkpoint": _checkpoint_metadata(
            generated_at,
            snapshot_role=snapshot_role,
            target_checkpoint=target_checkpoint,
            target_visible_mode=target_visible_mode,
        ),
        "runtime": {
            "total_wall_ms": performance.get("total_wall_ms"),
            "target_wall_ms": performance.get("target_wall_ms"),
            "within_target_slo": performance.get("within_target_slo"),
            "within_legacy_ceiling": performance.get("within_legacy_ceiling"),
            "peak_rss_kb": (performance.get("resources") or {}).get("peak_rss_kb"),
            "child_peak_rss_kb": (performance.get("resources") or {}).get("child_peak_rss_kb"),
        },
        "publication": {
            "registry": registry.get("registry"),
            "file_count_without_manifest": len(copied),
            "bytes_without_manifest": payload_bytes,
            "paths": sorted(copied),
            "rolling_snapshot_intended": True,
            "private_authenticated_state_projected_to_public_health": True,
            "full_optimizer_authority_fail_closed": workflow_identity is not None and canonical_runtime_source,
            "file_count": len(copied) + 1,
        },
    }
    if authority_assurance is not None:
        manifest["optimizer_authority"] = authority_assurance

    if workflow_identity is not None:
        run_id, run_attempt = workflow_identity
        digest = snapshot_digest(output_data, manifest)
        manifest["attestation"] = {
            "registry": ATTESTATION_REGISTRY,
            "digest_contract": ATTESTATION_DIGEST_CONTRACT,
            "workflow_name": "V3 Runtime",
            "workflow_run_id": run_id,
            "workflow_run_attempt": run_attempt,
            "source_commit": manifest.get("source_commit"),
            "snapshot_sha256": digest,
        }

    atomic_json(source_root / "runtime_manifest.json", manifest)
    atomic_json(output_data / "runtime_manifest.json", manifest)
    manifest_bytes = (output_data / "runtime_manifest.json").stat().st_size
    manifest["publication"]["bytes"] = payload_bytes + manifest_bytes
    atomic_json(source_root / "runtime_manifest.json", manifest)
    atomic_json(output_data / "runtime_manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-data", default=str(DATA))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--profile", default=os.getenv("FPL_EXECUTION_PROFILE", "full_refresh"))
    parser.add_argument("--source-commit", default=os.getenv("GITHUB_SHA"))
    parser.add_argument("--snapshot-role", default=os.getenv("FPL_SNAPSHOT_ROLE"))
    parser.add_argument("--target-checkpoint", default=os.getenv("FPL_TARGET_CHECKPOINT"))
    parser.add_argument("--target-visible-mode", default=os.getenv("FPL_TARGET_VISIBLE_MODE"))
    args = parser.parse_args()
    manifest = materialize(
        Path(args.source_data),
        Path(args.output_dir),
        args.profile,
        args.source_commit,
        snapshot_role=args.snapshot_role,
        target_checkpoint=args.target_checkpoint,
        target_visible_mode=args.target_visible_mode,
    )
    print(json.dumps({
        "profile": manifest["execution_profile"],
        "files": manifest["publication"]["file_count"],
        "bytes": manifest["publication"]["bytes"],
        "source_commit": manifest.get("source_commit"),
        "checkpoint": manifest.get("checkpoint"),
        "optimizer_authority": manifest.get("optimizer_authority"),
        "attestation": manifest.get("attestation"),
    }, ensure_ascii=False))
    if manifest.get("attestation"):
        print(
            "V3_RUNTIME_SNAPSHOT_ATTESTATION "
            + json.dumps(manifest["attestation"], ensure_ascii=False, sort_keys=True)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
