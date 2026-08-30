from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.runtime_v3.publish_snapshot import REGISTRY_PATH


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


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

    payload_bytes = sum(
        (data_dir / relative).stat().st_size
        for relative in payload_paths
    )
    if int(publication.get("bytes_without_manifest") or -1) != payload_bytes:
        raise RuntimeError("runtime manifest payload byte count mismatch")

    auth_path = data_dir / "auth.json"
    if auth_path.exists():
        auth = _read_json(auth_path)
        if auth.get("raw_authenticated_payload_persisted") is not False:
            raise RuntimeError("auth.json does not prove raw authenticated payloads are excluded")

    result = {
        "status": "PASS",
        "registry": registry.get("registry"),
        "manifest": manifest.get("registry"),
        "source_commit": manifest.get("source_commit"),
        "execution_profile": manifest.get("execution_profile"),
        "file_count": len(actual),
        "payload_bytes": payload_bytes,
        "unauthorized_paths": unauthorized,
        "raw_authenticated_payload_persisted": False if auth_path.exists() else None,
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
