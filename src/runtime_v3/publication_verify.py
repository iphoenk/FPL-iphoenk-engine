from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.runtime_v3.publish_snapshot import (
    ATTESTATION_DIGEST_CONTRACT,
    ATTESTATION_REGISTRY,
    ATTESTATION_REGISTRY_V1,
    AUTHORIZED_SNAPSHOT_WORKFLOWS,
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
EXHAUSTIVE_PROFILE = "exhaustive_precompute"
WATCHLIST_POSITIONS = ("GK", "DEF", "MID", "FWD")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _required_json(data_dir: Path, relative: str) -> dict[str, Any]:
    path = data_dir / relative
    if not path.is_file():
        raise RuntimeError(f"exhaustive publication missing required artifact: {relative}")
    return _read_json(path)


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


def _verify_exhaustive_precompute_contract(data_dir: Path) -> dict[str, Any]:
    optimizer = _required_json(data_dir, "package_optimizer.json")
    diagnostics = optimizer.get("search_diagnostics") or {}
    required_false = (
        "lossy_pruning",
        "candidate_pruning_applied",
        "single_budget_applied",
        "pair_budget_applied",
        "exact_package_limit_applied",
    )
    if optimizer.get("status") != "READY":
        raise RuntimeError("exhaustive publication optimizer is not READY")
    if diagnostics.get("search_authority") != "FULL":
        raise RuntimeError("exhaustive publication optimizer is not FULL authority")
    if any(diagnostics.get(key) is not False for key in required_false):
        raise RuntimeError("exhaustive publication contains pruning/budget/cap authority")
    if diagnostics.get("all_step_legal_packages_scored") is not True:
        raise RuntimeError("exhaustive publication did not score every sequentially legal package")
    if diagnostics.get("watchlist_used_as_optimizer_input") is not False:
        raise RuntimeError("exhaustive publication used watchlist as optimizer input")

    package = _required_json(data_dir, "package_decision.json")
    if package.get("gate0_revalidated") is not True or package.get("current_squad_legal") is not True:
        raise RuntimeError("exhaustive publication package decision failed Gate0 revalidation")
    selectable_ids = {str((optimizer.get("hold") or {}).get("id") or "")}
    selectable_ids.update(str(row.get("id") or "") for row in optimizer.get("packages") or [] if isinstance(row, dict))
    if str(package.get("selected_package_id") or "") not in selectable_ids:
        raise RuntimeError("exhaustive publication package decision is not derived from published FULL optimizer")

    framework = _required_json(data_dir, "framework_health.json")
    gate0 = framework.get("gate0") or {}
    if framework.get("overall") != "GREEN" or framework.get("decision_engine") != "HEALTHY":
        raise RuntimeError("exhaustive publication framework/decision health is not GREEN/HEALTHY")
    if gate0.get("pass") is not True or int((gate0.get("counts") or {}).get("PASS") or 0) != 16:
        raise RuntimeError("exhaustive publication Gate0 is not 16/16 PASS")

    team = _required_json(data_dir, "team.json")
    owned = {
        int(row.get("element") or -1)
        for row in (team.get("squad") or team.get("team_value_ledger") or [])
        if isinstance(row, dict) and int(row.get("element") or -1) > 0
    }
    watchlist = _required_json(data_dir, "dss_watchlist.json")
    positions = watchlist.get("positions") or {}
    counts = {position: len(positions.get(position) or []) for position in WATCHLIST_POSITIONS}
    if counts != {position: 5 for position in WATCHLIST_POSITIONS}:
        raise RuntimeError(f"exhaustive publication watchlist is not exact 5x4: {counts}")
    watch_ids = [
        int(row.get("element") or -1)
        for position in WATCHLIST_POSITIONS
        for row in (positions.get(position) or [])
        if isinstance(row, dict)
    ]
    if len(watch_ids) != 20 or len(set(watch_ids)) != 20 or any(element <= 0 for element in watch_ids):
        raise RuntimeError("exhaustive publication watchlist does not contain 20 unique valid elements")
    overlap = sorted(set(watch_ids) & owned)
    if overlap:
        raise RuntimeError(f"exhaustive publication watchlist contains owned players: {overlap}")

    latest = _required_json(data_dir, "latest.json")
    intelligence = latest.get("decision_intelligence") or {}
    package_summary = latest.get("package_decision_summary") or {}
    if intelligence.get("package_optimizer_search_authority") != "FULL":
        raise RuntimeError("latest.json does not propagate FULL optimizer authority")
    if intelligence.get("package_optimizer_execution_profile") != EXHAUSTIVE_PROFILE:
        raise RuntimeError("latest.json does not propagate exhaustive execution profile")
    if package_summary.get("selected_package_id") != package.get("selected_package_id"):
        raise RuntimeError("latest.json package decision summary is inconsistent with package_decision.json")
    if package_summary.get("gate0_revalidated") is not True:
        raise RuntimeError("latest.json package decision summary lost Gate0 proof")

    return {
        "search_authority": "FULL",
        "lossy_pruning": False,
        "all_step_legal_packages_scored": True,
        "gate0_pass": 16,
        "framework": "GREEN",
        "decision_engine": "HEALTHY",
        "watchlist_counts": counts,
        "watchlist_non_owned_unique": True,
        "selected_package_id": package.get("selected_package_id"),
    }


def _verify_embedded_attestation(data_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    schema = int(manifest.get("schema_version") or 0)
    attestation = manifest.get("attestation")
    if schema < 3:
        if attestation is not None:
            raise RuntimeError("legacy runtime manifest may not carry an unversioned attestation")
        return None
    if not isinstance(attestation, dict):
        raise RuntimeError("runtime manifest requires workflow attestation")

    registry = attestation.get("registry")
    if schema == 3:
        if registry != ATTESTATION_REGISTRY_V1:
            raise RuntimeError("runtime workflow attestation registry mismatch")
        if attestation.get("workflow_run_attempt") is not None:
            raise RuntimeError("runtime manifest v3 may not carry attempt-aware attestation")
        if attestation.get("workflow_name") != "V3 Runtime":
            raise RuntimeError("runtime legacy workflow attestation workflow mismatch")
    else:
        if registry != ATTESTATION_REGISTRY:
            raise RuntimeError("runtime workflow attestation registry mismatch")
        run_attempt = attestation.get("workflow_run_attempt")
        if not isinstance(run_attempt, int) or run_attempt <= 0:
            raise RuntimeError("runtime manifest workflow attempt invalid")
        if attestation.get("workflow_name") not in AUTHORIZED_SNAPSHOT_WORKFLOWS:
            raise RuntimeError("runtime workflow attestation workflow mismatch")

    if attestation.get("digest_contract") != ATTESTATION_DIGEST_CONTRACT:
        raise RuntimeError("runtime workflow attestation digest contract mismatch")
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

    effective_profile = str(profile or manifest.get("execution_profile") or "")
    exhaustive_assurance = _verify_exhaustive_precompute_contract(data_dir) if effective_profile == EXHAUSTIVE_PROFILE else None

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
        "workflow_run_attempt": attestation.get("workflow_run_attempt") if attestation else None,
        "exhaustive_precompute_assurance": exhaustive_assurance,
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
