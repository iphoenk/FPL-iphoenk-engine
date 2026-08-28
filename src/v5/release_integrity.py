from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

REGISTRY = "config/v5_release_integrity_registry.json"


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"release-integrity registry must be an object: {path}")
    return data


def _root_and_cfg(
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> tuple[Path, dict[str, Any]]:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    registry_file = Path(registry_path)
    if not registry_file.is_absolute():
        registry_file = root / registry_file
    return root, _load(registry_file)


def canonical_json_bytes(payload: Any) -> bytes:
    """Canonical JSON representation used by all V5 execution/input hashes."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def payload_fingerprint(payload: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"


def runtime_fingerprint(repo_root: str | Path | None = None, registry_path: str | Path = REGISTRY) -> dict[str, Any]:
    root, cfg = _root_and_cfg(repo_root, registry_path)
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
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_sha.encode("ascii"))
        digest.update(b"\n")
        entries.append({"path": rel, "sha256": content_sha})
    return {
        "contract": cfg.get("contract"),
        "registry_version": int(cfg.get("version") or 0),
        "algorithm": "sha256",
        "fingerprint": f"sha256:{digest.hexdigest()}",
        "files_hashed": len(entries),
        "entries": entries,
    }


def code_revision(
    *,
    environ: dict[str, str] | None = None,
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> dict[str, Any]:
    _, cfg = _root_and_cfg(repo_root, registry_path)
    exact = cfg.get("exact_execution") if isinstance(cfg.get("exact_execution"), dict) else {}
    env = os.environ if environ is None else environ
    for name in exact.get("code_revision_env") or []:
        value = str(env.get(str(name)) or "").strip()
        if value:
            return {"status": "AVAILABLE", "value": value, "source": f"env:{name}"}
    return {
        "status": "UNAVAILABLE",
        "value": None,
        "source": None,
        "reason": "NO_CONFIGURED_CODE_REVISION_ENV",
    }


def build_replay_fingerprint(
    replay_inputs: dict[str, Any],
    *,
    runtime_release_fingerprint: str,
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> dict[str, Any]:
    _, cfg = _root_and_cfg(repo_root, registry_path)
    exact = cfg.get("exact_execution") if isinstance(cfg.get("exact_execution"), dict) else {}
    required = [str(value) for value in exact.get("required_replay_inputs") or []]
    missing = [name for name in required if name not in replay_inputs]
    if missing:
        raise RuntimeError(f"V5 replay fingerprint missing required inputs: {missing}")
    if not runtime_release_fingerprint:
        raise RuntimeError("V5 replay fingerprint requires runtime release fingerprint")

    component_hashes = {
        name: payload_fingerprint(replay_inputs[name])
        for name in sorted(replay_inputs)
    }
    basis = {
        "contract": exact.get("replay_contract"),
        "runtime_release_fingerprint": str(runtime_release_fingerprint),
        "component_hashes": component_hashes,
    }
    return {
        "contract": exact.get("replay_contract"),
        "runtime_release_fingerprint": str(runtime_release_fingerprint),
        "component_hashes": component_hashes,
        "replay_fingerprint": payload_fingerprint(basis),
        "deterministic_across_execution_identity": True,
    }


def build_exact_execution_fingerprint(
    replay_inputs: dict[str, Any],
    *,
    correlation_id: str,
    captured_at: str,
    runtime_release_fingerprint: str | None = None,
    environ: dict[str, str] | None = None,
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> dict[str, Any]:
    _, cfg = _root_and_cfg(repo_root, registry_path)
    exact = cfg.get("exact_execution") if isinstance(cfg.get("exact_execution"), dict) else {}
    release_fp = str(runtime_release_fingerprint or runtime_fingerprint(repo_root, registry_path)["fingerprint"])
    replay = build_replay_fingerprint(
        replay_inputs,
        runtime_release_fingerprint=release_fp,
        repo_root=repo_root,
        registry_path=registry_path,
    )
    revision = code_revision(environ=environ, repo_root=repo_root, registry_path=registry_path)
    execution_basis = {
        "contract": exact.get("contract"),
        "runtime_release_fingerprint": release_fp,
        "replay_fingerprint": replay["replay_fingerprint"],
        "code_revision": revision.get("value"),
        "correlation_id": str(correlation_id),
        "captured_at": str(captured_at),
    }
    revision_required = bool(exact.get("require_code_revision_for_promotion", True))
    return {
        "contract": exact.get("contract"),
        "schema_version": 1,
        "algorithm": "sha256",
        "runtime_release_fingerprint": release_fp,
        "code_revision": revision,
        "replay_fingerprint": replay["replay_fingerprint"],
        "execution_fingerprint": payload_fingerprint(execution_basis),
        "captured_at": str(captured_at),
        "correlation_id": str(correlation_id),
        "component_hashes": replay["component_hashes"],
        "promotion_fingerprint_complete": (revision.get("status") == "AVAILABLE" or not revision_required),
        "governance": {
            "replay_fingerprint_excludes_execution_identity": bool(
                exact.get("replay_fingerprint_excludes_execution_identity", True)
            ),
            "execution_fingerprint_binds_correlation_and_capture_time": bool(
                exact.get("execution_fingerprint_binds_correlation_and_capture_time", True)
            ),
            "raw_authenticated_payload_forbidden": bool(exact.get("raw_authenticated_payload_forbidden", True)),
            "replay_boundary": exact.get("replay_boundary"),
            "code_revision_required_for_promotion": revision_required,
        },
    }


def _normalize_output(value: Any, volatile_fields: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_output(item, volatile_fields)
            for key, item in sorted(value.items(), key=lambda row: str(row[0]))
            if str(key) not in volatile_fields
        }
    if isinstance(value, list):
        return [_normalize_output(item, volatile_fields) for item in value]
    if isinstance(value, tuple):
        return [_normalize_output(item, volatile_fields) for item in value]
    return value


def replay_output_fingerprint(
    payload: Any,
    *,
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> str:
    _, cfg = _root_and_cfg(repo_root, registry_path)
    exact = cfg.get("exact_execution") if isinstance(cfg.get("exact_execution"), dict) else {}
    volatile = {str(value) for value in exact.get("replay_output_volatile_fields") or []}
    return payload_fingerprint(_normalize_output(payload, volatile))


def verify_replay_outputs(
    expected_hashes: dict[str, str],
    outputs: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
    registry_path: str | Path = REGISTRY,
) -> dict[str, Any]:
    actual = {
        name: replay_output_fingerprint(outputs.get(name), repo_root=repo_root, registry_path=registry_path)
        for name in sorted(expected_hashes)
    }
    mismatches = {
        name: {"expected": expected_hashes[name], "actual": actual[name]}
        for name in sorted(expected_hashes)
        if actual[name] != expected_hashes[name]
    }
    return {
        "status": "MATCH" if not mismatches else "MISMATCH",
        "match": not mismatches,
        "actual_hashes": actual,
        "mismatches": mismatches,
    }
