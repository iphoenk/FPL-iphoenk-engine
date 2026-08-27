from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json
from src.version import ENGINE_VERSION, SCHEMA_VERSION

REGISTRY_PATH = ROOT / "config" / "runtime" / "runtime_publish_registry.json"


def _registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("registry") != "RUNTIME_PUBLISH_REGISTRY_V1":
        raise RuntimeError("unexpected runtime publish registry")
    paths = payload.get("publish_paths")
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("runtime publish registry has no publish_paths")
    return payload


def _copy_declared(source_root: Path, output_root: Path, paths: list[str]) -> tuple[list[str], int]:
    copied: list[str] = []
    total_bytes = 0
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
        total_bytes += target.stat().st_size
    return copied, total_bytes


def materialize(source_root: Path, output_dir: Path, profile: str, source_commit: str | None = None) -> dict[str, Any]:
    registry = _registry()
    output_data = output_dir / "data"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_data.mkdir(parents=True, exist_ok=True)

    declared = [str(path) for path in registry.get("publish_paths") or [] if str(path) != "runtime_manifest.json"]
    copied, payload_bytes = _copy_declared(source_root, output_data, declared)
    performance = read_json(source_root / "runtime_performance.json", {})
    manifest = {
        "schema_version": 1,
        "registry": "RUNTIME_MANIFEST_V1",
        "engine_version": ENGINE_VERSION,
        "engine_schema_version": SCHEMA_VERSION,
        "execution_profile": profile,
        "source_commit": source_commit or os.getenv("GITHUB_SHA"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
        },
    }
    atomic_json(source_root / "runtime_manifest.json", manifest)
    atomic_json(output_data / "runtime_manifest.json", manifest)
    manifest_bytes = (output_data / "runtime_manifest.json").stat().st_size
    manifest["publication"]["file_count"] = len(copied) + 1
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
    args = parser.parse_args()
    manifest = materialize(Path(args.source_data), Path(args.output_dir), args.profile, args.source_commit)
    print(json.dumps({
        "profile": manifest["execution_profile"],
        "files": manifest["publication"]["file_count"],
        "bytes": manifest["publication"]["bytes"],
        "source_commit": manifest.get("source_commit"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
