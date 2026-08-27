from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REGISTRY = "config/v5_release_integrity_registry.json"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"release-integrity registry must be an object: {path}")
    return data


def runtime_fingerprint(repo_root: str | Path | None = None, registry_path: str | Path = REGISTRY) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    registry_file = Path(registry_path)
    if not registry_file.is_absolute():
        registry_file = root / registry_file
    cfg = _load(registry_file)
    if str(cfg.get("algorithm")) != "sha256":
        raise RuntimeError("unsupported V5 release fingerprint algorithm")
    excluded = {str(value).replace("\\", "/") for value in cfg.get("exclude_paths") or []}
    files: dict[str, Path] = {}
    for item in cfg.get("include_files") or []:
        path = root / str(item)
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if rel not in excluded:
                files[rel] = path
    for item in cfg.get("include_roots") or []:
        base = root / str(item)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in excluded or "/__pycache__/" in f"/{rel}/" or rel.endswith(".pyc"):
                continue
            files[rel] = path
    if not files:
        raise RuntimeError("V5 release fingerprint selected zero runtime files")
    digest = hashlib.sha256()
    entries = []
    for rel in sorted(files):
        raw = files[rel].read_bytes()
        content_sha = hashlib.sha256(raw).hexdigest()
        digest.update(rel.encode("utf-8")); digest.update(b"\0"); digest.update(content_sha.encode("ascii")); digest.update(b"\n")
        entries.append({"path": rel, "sha256": content_sha})
    return {"contract": cfg.get("contract"), "registry_version": int(cfg.get("version") or 0), "algorithm": "sha256", "fingerprint": f"sha256:{digest.hexdigest()}", "files_hashed": len(entries), "entries": entries}
