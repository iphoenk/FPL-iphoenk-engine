from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.runtime_v3.publish_snapshot import (
    ATTESTATION_DIGEST_CONTRACT,
    ATTESTATION_REGISTRY,
    PUBLIC_AUTH_PROJECTION,
    REGISTRY_PATH,
    snapshot_digest,
)

PUBLIC_AUTH_ALLOWED_KEYS = {
    "public_projection",
    "checked_at",
    "expected_entry",
    "state",
    "mode",
    "verified_entry",
    "raw_authenticated_payload_persisted",
    "production_readiness",
    "enhancement_health",
    "policy",
    "failure_reason",
}
PRIVATE_AUTH_FORBIDDEN_KEYS = {
    "safe_finance",
    "draft_integrity",
    "chip_state",
    "transfers_latest",
    "endpoint_health",
    "prices_for_private_squad",
    "prices_for_authoritative_squad",
    "private_exact_sell_total",
    "private_exact_purchase_total",
    "exact_sell_total",
    "exact_purchase_total",
    "bank",
    "value",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _verify_public_auth_projection(payload: Any, *, location: str) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError(f"{location} authenticated state must be an object")
    if payload.get("raw_authenticated_payload_persisted") is not False:
        raise RuntimeError(f"{location} does not prove raw authenticated payloads are excluded")
    if payload.get("public_projection") != PUBLIC_AUTH_PROJECTION:
        raise RuntimeError(f"{location} is not the governed public auth projection")
    extras = sorted(set(payload) - PUBLIC_AUTH_ALLOWED_KEYS)
    if extras:
        raise RuntimeError(f"{location} contains non-public authenticated fields: {extras}")
    forbidden = sorted(set(payload) & PRIVATE_AUTH_FORBIDDEN_KEYS)
    if forbidden:
        raise RuntimeError(f"{location} contains private authenticated fields: {forbidden}")


def _verify_embedded_attestation(data_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    schema = int(manifest.get("schema_version") or 0)
    attestation = manifest.get("attestation")
    if schema < 3:
        if attestation is not None:
            raise RuntimeError("legacy runtime manifest may not carry an unversioned attestation")
        return None
    if not isinstance(attestation, dict):
        raise RuntimeError("runtime manifest v3 requires workflow attestation")
    if attestation.get("registry") != ATTESTATION_REGISTRY:
        raise RuntimeError("runtime workflow attestation registry mismatch")
    if attestation.get("digest_contract") != ATTESTATION_DIGEST_CONTRACT:
        raise RuntimeError("runtime workflow attestation digest contract mismatch")
    if attestation.get("workflow_name") != "V3 Runtime":
        raise RuntimeError("runtime workflow attestation workflow mismatch")
    run_id = attestation.get("workflow_run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RuntimeError("runtime workflow attestation run id invalid")
    if attestation.get("source_commit") != manifest.get("source_commit"):
        raise RuntimeError("runtime workflow attestation source commit mismatch")
    claimed = str(attestation.get("snapshot_sha256") or "").lower()
    if not _SHA256_RE.fullmatch(claimed):
        raise RuntimeError("runtime workflow attestation digest invalid")
    actual = snapshot_digest(data_dir, manifest)
    if claimed != actual:
        raise RuntimeError("runtime workflow attestation content digest mismatch")
    return attestation


def verify_publication(
    data_dir: Path,
    *,
    source_commit: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    if not data_dir.is_dir():
        raise RuntimeError(f"publication data directory does not exist: {data_dir}")

    registry = _read_json(REGISTRY_PATH)
    if registry.get("registry") != "RUNTIME_PUBLISH_REGISTRY_V1":
        raise RuntimeError("unexpected runtime publish registry")

    declared = {str(path) for path in registry.get("publish_paths") or []}
    if "runtime_manifest.json" not in declared:
        raise RuntimeError("runtime manifest is not declared for publication")

    files = sorted(path for path in data_dir.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in files):
        raise RuntimeError("runtime publication may not contain symlinks")

    actual = {path.relative_to(data_dir).as_posix() for path in files}
    unauthorized = sorted(actual - declared)
    if unauthorized:
        raise RuntimeError(f"unauthorized runtime publication paths: {unauthorized}")
    if "runtime_manifest.json" not in actual:
        raise RuntimeError("runtime publication is missing runtime_manifest.json")

    manifest = _read_json(data_dir / "runtime_manifest.json")
    if manifest.get("registry") != "RUNTIME_MANIFEST_V1":
        raise RuntimeError("unexpected runtime manifest registry")
    if source_commit is not None and manifest.get("source_commit") != source_commit:
        raise RuntimeError(
            f"runtime manifest source_commit mismatch: expected={source_commit} actual={manifest.get('source_commit')}"
        )
    if profile is not None and manifest.get("execution_profile") != profile:
        raise RuntimeError(
            f"runtime manifest execution_profile mismatch: expected={profile} actual={manifest.get('execution_profile')}"
        )

    publication = manifest.get("publication") or {}
    payload_paths = sorted(actual - {"runtime_manifest.json"})
    manifest_paths = sorted(str(path) for path in publication.get("paths") or [])
    if manifest_paths != payload_paths:
        raise RuntimeError(
            f"runtime manifest path set mismatch: manifest={manifest_paths} actual={payload_paths}"
        )
    if int(publication.get("file_count_without_manifest") or -1) != len(payload_paths):
        raise RuntimeError("runtime manifest payload file count mismatch")
    if int(publication.get("file_count") or -1) != len(actual):
        raise RuntimeError("runtime manifest total file count mismatch")

    payload_bytes = sum((data_dir / relative).stat().st_size for relative in payload_paths)
    if int(publication.get("bytes_without_manifest") or -1) != payload_bytes:
        raise RuntimeError("runtime manifest payload byte count mismatch")

    attestation = _verify_embedded_attestation(data_dir, manifest)

    auth_path = data_dir / "auth.json"
    if auth_path.exists():
        _verify_public_auth_projection(_read_json(auth_path), location="auth.json")

    latest_path = data_dir / "latest.json"
    if latest_path.exists():
        latest = _read_json(latest_path)
        if "authenticated_official" in latest:
            _verify_public_auth_projection(
                latest.get("authenticated_official"),
                location="latest.json.authenticated_official",
            )

    result = {
        "status": "PASS",
        "registry": registry.get("registry"),
        "manifest": manifest.get("registry"),
        "manifest_schema_version": manifest.get("schema_version"),
        "source_commit": manifest.get("source_commit"),
        "execution_profile": manifest.get("execution_profile"),
        "file_count": len(actual),
        "payload_bytes": payload_bytes,
        "unauthorized_paths": unauthorized,
        "raw_authenticated_payload_persisted": False if auth_path.exists() else None,
        "public_authenticated_projection_verified": auth_path.exists() or (
            latest_path.exists() and "authenticated_official" in _read_json(latest_path)
        ),
        "embedded_attestation_verified": attestation is not None,
        "snapshot_sha256": attestation.get("snapshot_sha256") if attestation else None,
        "workflow_run_id": attestation.get("workflow_run_id") if attestation else None,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a materialized or published V3 runtime snapshot")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--profile")
    args = parser.parse_args()

    result = verify_publication(
        Path(args.data_dir),
        source_commit=args.source_commit,
        profile=args.profile,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
