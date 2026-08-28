from __future__ import annotations

"""Validated semantic-reuse state for FAST/LIVE.

The manifest is deliberately separate from runtime_performance.json. Performance
telemetry is observational and may be overwritten by FULL runs; reuse state is a
correctness contract.

Semantic inputs may be declared either as a whole JSON artifact (legacy string
form) or as a field-selective object::

    {"path": "official_snapshot.json", "include_paths": ["bootstrap.elements", "fixtures"]}

Field selectors are config-owned so runtime code does not accumulate ad-hoc lists
of decision-irrelevant metadata. Missing selected fields fail closed.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_v3 import orchestrator as base
from src.version import ENGINE_VERSION, SCHEMA_VERSION

MANIFEST_PATH = base.DATA / "runtime_reuse_manifest.json"
_VOLATILE_SIGNATURE_KEYS = {
    "generated_at",
    "updated_at",
    "fetched_at",
    "captured_at",
    "observed_at",
    "age_minutes",
    "elapsed_ms",
    "latency_ms",
    "performance_ms",
    "queue_wait_ms",
    "seed_input_ms",
    "promotion_ms",
    "validation_ms",
    "cache_age_ms",
}
_MISSING = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def logical_generated_at(path: Path) -> datetime | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    for key in (
        "generated_at",
        "updated_at",
        "captured_at",
        "observed_at",
        "p0_overlay_generated_at",
        "lineup_overlay_generated_at",
        "decision_quality_overlay_generated_at",
    ):
        dt = parse_ts(payload.get(key))
        if dt is not None:
            return dt
    return None


def canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_SIGNATURE_KEYS
        }
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    return value


def _select_path(payload: Any, dotted_path: str) -> Any:
    current = payload
    for part in str(dotted_path).split("."):
        if not part or not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def semantic_file_bytes(path: Path, include_paths: list[str] | None = None) -> bytes | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        if include_paths:
            return None
        return path.read_bytes()

    if include_paths:
        selected: dict[str, Any] = {}
        for dotted in include_paths:
            value = _select_path(payload, dotted)
            if value is _MISSING:
                return None
            selected[str(dotted)] = value
        payload = selected
    normalized = canonicalize(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _input_spec(value: Any) -> tuple[str, list[str] | None] | None:
    if isinstance(value, str) and value:
        return value, None
    if not isinstance(value, dict):
        return None
    path = str(value.get("path") or "").strip()
    include = [str(item).strip() for item in value.get("include_paths") or [] if str(item).strip()]
    if not path or not include:
        return None
    return path, include


def input_signature(service_name: str, reuse_cfg: dict[str, Any], canonical: Path) -> str | None:
    input_specs = list(reuse_cfg.get("signature_inputs") or [])
    configs = [str(value) for value in reuse_cfg.get("signature_config_files") or []]
    if not input_specs and not configs:
        return None
    digest = hashlib.sha256()
    digest.update(f"{ENGINE_VERSION}|{SCHEMA_VERSION}|{service_name}".encode("utf-8"))
    for value in input_specs:
        parsed = _input_spec(value)
        if parsed is None:
            return None
        rel, include = parsed
        raw = semantic_file_bytes(canonical / rel, include)
        if raw is None:
            return None
        digest.update(b"\nINPUT:")
        digest.update(rel.encode("utf-8"))
        if include:
            digest.update(b"[")
            digest.update("|".join(include).encode("utf-8"))
            digest.update(b"]")
        digest.update(b"\n")
        digest.update(raw)
    for rel in configs:
        path = base.ROOT / rel
        if not path.exists() or not path.is_file():
            return None
        digest.update(b"\nCONFIG:")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\n")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def reuse_artifacts(spec: dict[str, Any], reuse_cfg: dict[str, Any]) -> list[str]:
    override = [str(name) for name in reuse_cfg.get("artifacts") or []]
    return override or [str(name) for name in spec.get("artifacts") or []]


def artifact_age_seconds(paths: list[Path]) -> tuple[float, str] | None:
    for path in paths:
        logical_time = logical_generated_at(path)
        if logical_time is not None:
            age = max(0.0, (datetime.now(timezone.utc) - logical_time).total_seconds())
            return age, f"{path.name}:logical_generated_at"
    return None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict[str, Any]:
    payload = base.read_json(MANIFEST_PATH, {})
    if payload.get("registry") != "RUNTIME_REUSE_MANIFEST_V1":
        return {}
    return payload


def capture(profile_name: str = "fast_decision") -> dict[str, Any]:
    profiles = base._load_profiles().get("profiles") or {}
    profile = profiles.get(profile_name) or {}
    services = base._load_registry().get("services") or {}
    performance = base.read_json(base.PERFORMANCE_PATH, {})
    if str(performance.get("engine_version") or "") != ENGINE_VERSION:
        raise RuntimeError("cannot capture reuse manifest from a different engine version")
    if int(performance.get("schema_version") or -1) != SCHEMA_VERSION:
        raise RuntimeError("cannot capture reuse manifest from a different schema version")

    rows: dict[str, Any] = {}
    missing: list[str] = []
    for service_name, reuse_cfg in (profile.get("reuse_services") or {}).items():
        if str((reuse_cfg or {}).get("mode") or "logical_age") != "semantic_signature":
            continue
        spec = services.get(service_name) or {}
        perf_row = ((performance.get("services") or {}).get(service_name) or {})
        signature = perf_row.get("input_signature")
        artifacts = reuse_artifacts(spec, reuse_cfg or {})
        paths = [base.DATA / name for name in artifacts]
        if not signature or not artifacts or not all(path.exists() and path.is_file() for path in paths):
            missing.append(service_name)
            continue
        validations = [base.validate_artifact(path, name) for path, name in zip(paths, artifacts)]
        rows[service_name] = {
            "input_signature": signature,
            "artifacts": artifacts,
            "artifact_sha256": {name: file_sha256(path) for name, path in zip(artifacts, paths)},
            "artifact_validation": validations,
            "captured_from_status": perf_row.get("status"),
            "captured_at": _now(),
        }
    if missing:
        raise RuntimeError(f"semantic reuse manifest capture missing validated service signatures: {sorted(missing)}")

    manifest = {
        "schema_version": 2,
        "registry": "RUNTIME_REUSE_MANIFEST_V1",
        "engine_version": ENGINE_VERSION,
        "engine_schema_version": SCHEMA_VERSION,
        "profile": profile_name,
        "generated_at": _now(),
        "services": rows,
        "policy": {
            "separate_from_performance_telemetry": True,
            "input_signature_captured_while_ephemeral_inputs_exist": True,
            "semantic_field_selection_is_config_owned": True,
            "missing_selected_semantic_field_fails_closed": True,
            "artifact_hash_must_match_before_reuse": True,
            "artifact_contract_validation_required": True,
            "manifest_written_only_after_external_contract_validation": True,
        },
    }
    base.atomic_json(MANIFEST_PATH, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="fast_decision")
    args = parser.parse_args()
    manifest = capture(args.profile)
    print(json.dumps({
        "status": "PASS",
        "registry": manifest["registry"],
        "profile": manifest["profile"],
        "semantic_services": sorted((manifest.get("services") or {}).keys()),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
