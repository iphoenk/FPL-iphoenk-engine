from __future__ import annotations

"""Production P4 scenario package materializer.

The package is generated only from the canonical V12 integrated evaluator.
Scenario overrides enter through the authorized P1.1 availability path; no
post-hoc xPts/xMins/Pstart mutation is permitted here.
"""

import argparse
from datetime import datetime
import gzip
import json
from pathlib import Path
from typing import Any, Mapping

from .v12_integrated_report_runner import run_deep
from .v12_p6_runtime import _identity
from .v12_scenario_package import (
    P4_SCENARIO_SURFACES,
    build_scenario_package,
)


class P4ScenarioProductionError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise P4ScenarioProductionError(f"expected JSON object: {path}")
    return payload


def _decision_result(bundle: Mapping[str, Any]) -> dict[str, Any]:
    report = dict(bundle.get("report") or {})
    sections = report.get("sections") or []
    surfaces: dict[str, Any] = {}
    if isinstance(sections, list):
        for row in sections:
            if not isinstance(row, Mapping):
                continue
            sid = str(row.get("section_id") or row.get("id") or "").upper()
            if sid in P4_SCENARIO_SURFACES:
                surfaces[sid] = row.get("content", row)
    elif isinstance(sections, Mapping):
        for sid in P4_SCENARIO_SURFACES:
            if sid in sections:
                surfaces[sid] = sections[sid]
    missing = [sid for sid in P4_SCENARIO_SURFACES if sid not in surfaces]
    if missing:
        raise P4ScenarioProductionError(
            f"canonical DEEP bundle missing P4 decision surfaces: {missing}"
        )
    return {"decision_surfaces": surfaces}


def _owned_context(private_root: Path) -> tuple[list[int], int | None, int | None]:
    current = _read_json(private_root / "personal/current_team.json")
    players = [row for row in current.get("players") or [] if isinstance(row, Mapping)]
    owned = [int(row.get("element_id") or 0) for row in players]
    if len(owned) != 15 or len(set(owned)) != 15 or any(value <= 0 for value in owned):
        raise P4ScenarioProductionError(
            "private current_team must contain exactly 15 unique owned elements"
        )
    captain = next(
        (
            int(row.get("element_id") or 0)
            for row in players
            if row.get("captain") is True
        ),
        None,
    )
    vice = next(
        (
            int(row.get("element_id") or 0)
            for row in players
            if row.get("vice_captain") is True
        ),
        None,
    )
    return owned, captain, vice


def materialize_p4_package(
    *,
    app_root: Path,
    runtime_data_root: Path,
    private_root: Path,
    report_slot: str,
    workspace: Path,
) -> dict[str, Any]:
    identity = _identity(app_root, runtime_data_root, private_root)
    owned, captain, vice = _owned_context(private_root)
    workspace.mkdir(parents=True, exist_ok=True)

    sequence = 0

    def evaluate(overrides: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
        nonlocal sequence
        output = workspace / f"scenario-{sequence:03d}"
        sequence += 1
        bundle = run_deep(
            runtime_data_root=runtime_data_root,
            report_slot=report_slot,
            output_dir=output,
            private_data_root=private_root,
            allow_legacy_private_sources=False,
            require_private_personal=True,
            scenario_overrides=overrides,
        )
        if str(bundle.get("runner_status") or "").upper() != "PASS":
            raise P4ScenarioProductionError("canonical scenario evaluator did not PASS")
        proof = dict(bundle.get("execution_proof") or {})
        p4 = dict(proof.get("p4_scenario_override") or {})
        if overrides:
            if p4.get("applied") is not True:
                raise P4ScenarioProductionError(
                    "canonical evaluator did not acknowledge P4 override"
                )
            if p4.get("stage2_cache_bypassed") is not True:
                raise P4ScenarioProductionError(
                    "P4 override must bypass Stage2 derived cache"
                )
        return _decision_result(bundle)

    base = evaluate({})
    package = build_scenario_package(
        dependencies=identity.p4_dependencies(),
        base_result=base,
        owned_elements=owned,
        evaluate=evaluate,
        generated_at=datetime.now().astimezone().isoformat(),
        captain_element=captain,
        vice_element=vice,
    )
    if int(package.get("scenario_count") or 0) < 16:
        raise P4ScenarioProductionError("P4 package scenario coverage is incomplete")
    if package.get("private_only") is not True:
        raise P4ScenarioProductionError("P4 package lost private-only governance")
    return package


MAX_P4_SHARD_BYTES = 95 * 1024 * 1024


def write_sharded_package(package: Mapping[str, Any], output: Path) -> dict[str, Any]:
    """Persist a tiny manifest plus independently compressed scenario shards."""
    output.parent.mkdir(parents=True, exist_ok=True)
    package_fingerprint = str(package.get("package_fingerprint") or "").strip()
    if not package_fingerprint:
        raise P4ScenarioProductionError("P4 package fingerprint unavailable")
    shard_root = output.parent / "shards" / package_fingerprint
    shard_root.mkdir(parents=True, exist_ok=True)

    index: list[dict[str, Any]] = []
    total_compressed = 0
    for raw in package.get("scenarios") or []:
        if not isinstance(raw, Mapping):
            raise P4ScenarioProductionError("P4 scenario row is not an object")
        row = dict(raw)
        scenario_id = str(row.get("scenario_id") or "").strip()
        if not scenario_id or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for ch in scenario_id):
            raise P4ScenarioProductionError(f"unsafe P4 scenario id: {scenario_id!r}")

        # delta_vs_base duplicated the already-authoritative base and scenario
        # surfaces and is not consumed by serving. Exclude it from persisted
        # storage while preserving the canonical output fingerprint.
        shard_payload = dict(row)
        shard_payload.pop("delta_vs_base", None)
        relative = Path("shards") / package_fingerprint / f"{scenario_id}.json.gz"
        shard_path = output.parent / relative
        with gzip.open(shard_path, "wt", encoding="utf-8", compresslevel=9) as fh:
            json.dump(
                shard_payload,
                fh,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            fh.write("\n")
        compressed_bytes = shard_path.stat().st_size
        if compressed_bytes >= MAX_P4_SHARD_BYTES:
            raise P4ScenarioProductionError(
                f"P4 shard exceeds governed GitHub-safe limit: {scenario_id}={compressed_bytes}"
            )
        total_compressed += compressed_bytes
        index.append(
            {
                "scenario_id": scenario_id,
                "base_fingerprint": row.get("base_fingerprint"),
                "override_type": row.get("override_type"),
                "override_input": row.get("override_input"),
                "output_fingerprint": row.get("output_fingerprint"),
                "storage_path": relative.as_posix(),
                "storage_encoding": "gzip-json-v1",
                "compressed_bytes": compressed_bytes,
            }
        )

    manifest = {k: v for k, v in dict(package).items() if k != "scenarios"}
    manifest["scenarios"] = index
    manifest["storage"] = {
        "format": "SHARDED_GZIP_JSON_V1",
        "scenario_count": len(index),
        "total_compressed_bytes": total_compressed,
        "max_shard_bytes": max((int(row["compressed_bytes"]) for row in index), default=0),
        "monolithic_package_persisted": False,
        "git_lfs_required": False,
    }
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize governed private P4 package")
    parser.add_argument("--app-root", default=".")
    parser.add_argument("--runtime-data-root", required=True)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--report-slot", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    package = materialize_p4_package(
        app_root=Path(args.app_root).resolve(),
        runtime_data_root=Path(args.runtime_data_root).resolve(),
        private_root=Path(args.private_root).resolve(),
        report_slot=args.report_slot,
        workspace=Path(args.workspace).resolve(),
    )
    output = Path(args.output)
    manifest = write_sharded_package(package, output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "scenario_count": manifest["scenario_count"],
                "package_fingerprint": manifest["package_fingerprint"],
                "private_only": manifest["private_only"],
                "storage_format": manifest["storage"]["format"],
                "total_compressed_bytes": manifest["storage"]["total_compressed_bytes"],
                "max_shard_bytes": manifest["storage"]["max_shard_bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
