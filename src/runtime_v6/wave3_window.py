from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .wave3_chaos_acceptance import EXPECTED_SCENARIO_IDS
from .wave3_proof import Wave3ProofError, evaluate_proof_window


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _read_object(path: Path, *, error_prefix: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Wave3ProofError(f"{error_prefix}:{path}") from exc
    if not isinstance(payload, dict):
        raise Wave3ProofError(f"{error_prefix}_not_object:{path}")
    return payload


def _read_proof(path: Path) -> dict[str, Any]:
    return _read_object(path, error_prefix="invalid_wave3_proof")


def _validate_chaos_acceptance(path: Path) -> dict[str, Any]:
    payload = _read_object(path, error_prefix="invalid_wave3_chaos_acceptance")
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version")
    if payload.get("acceptance_kind") != "WAVE3_CONTROLLED_CHAOS_MATRIX":
        errors.append("acceptance_kind")
    if payload.get("status") != "PASS":
        errors.append("status")
    if payload.get("evidence_scope") != "DETERMINISTIC_CI_READ_ONLY":
        errors.append("evidence_scope")
    if payload.get("runtime_write_authorized") is not False:
        errors.append("runtime_write_authorized")
    if payload.get("natural_slot_counter_affected") is not False:
        errors.append("natural_slot_counter_affected")
    if payload.get("canonical_scenario_count") != len(EXPECTED_SCENARIO_IDS):
        errors.append("canonical_scenario_count")
    if payload.get("passed_scenario_count") != len(EXPECTED_SCENARIO_IDS):
        errors.append("passed_scenario_count")
    if payload.get("failed_or_missing_scenario_count") != 0:
        errors.append("failed_or_missing_scenario_count")
    if payload.get("errors") != []:
        errors.append("errors")
    junit_sha256 = str(payload.get("junit_sha256") or "")
    if not _SHA256_RE.fullmatch(junit_sha256):
        errors.append("junit_sha256")

    scenario_rows = payload.get("scenarios")
    if not isinstance(scenario_rows, list):
        errors.append("scenarios")
    else:
        scenario_ids = [str(row.get("scenario_id") or "") for row in scenario_rows if isinstance(row, dict)]
        if len(scenario_rows) != len(EXPECTED_SCENARIO_IDS):
            errors.append("scenario_row_count")
        if set(scenario_ids) != EXPECTED_SCENARIO_IDS or len(scenario_ids) != len(set(scenario_ids)):
            errors.append("scenario_ids")
        if any(not isinstance(row, dict) or row.get("status") != "PASS" for row in scenario_rows):
            errors.append("scenario_status")

    if errors:
        raise Wave3ProofError(f"wave3_chaos_acceptance_not_pass:{','.join(sorted(set(errors)))}")
    return payload


def collect_proofs(proof_dir: Path, current: Path) -> list[dict[str, Any]]:
    proofs: list[dict[str, Any]] = []
    if proof_dir.exists():
        for path in sorted(proof_dir.glob("*.json")):
            proofs.append(_read_proof(path))
    proofs.append(_read_proof(current))
    return proofs


def build_window_summary(
    proof_dir: Path,
    current: Path,
    *,
    chaos_acceptance: Path | None = None,
    chaos_source_run_id: str | None = None,
    chaos_source_head_sha: str | None = None,
    chaos_artifact_name: str | None = None,
) -> dict[str, Any]:
    summary = evaluate_proof_window(collect_proofs(proof_dir, current))
    natural_window_eligible = bool(summary.get("production_green_eligible"))

    chaos_payload: dict[str, Any] | None = None
    chaos_pass = False
    if chaos_acceptance is not None:
        chaos_payload = _validate_chaos_acceptance(chaos_acceptance)
        chaos_pass = True

    if chaos_pass:
        if not chaos_source_run_id:
            raise Wave3ProofError("wave3_chaos_source_run_id_missing")
        if not chaos_source_head_sha or not _COMMIT_SHA_RE.fullmatch(chaos_source_head_sha):
            raise Wave3ProofError("wave3_chaos_source_head_sha_invalid")
        if not chaos_artifact_name or not chaos_artifact_name.startswith("v6-wave3-chaos-acceptance-"):
            raise Wave3ProofError("wave3_chaos_artifact_name_invalid")

    summary["natural_window_eligible"] = natural_window_eligible
    summary["chaos_acceptance_pass"] = chaos_pass
    summary["production_green_eligible"] = natural_window_eligible and chaos_pass
    summary["proof_source"] = "IMMUTABLE_WAVE3_ACTION_ARTIFACTS_PLUS_CURRENT"
    summary["manual_or_controlled_runs_count"] = 0
    summary["future_slots_inferred"] = False
    summary["production_green_policy"] = "ONLY_WHEN_ROLLING_48_OF_48_AND_CHAOS_ACCEPTANCE_PASS"
    summary["chaos_acceptance"] = {
        "status": "PASS" if chaos_pass else "NOT_PROVIDED",
        "source_run_id": chaos_source_run_id if chaos_pass else None,
        "source_head_sha": chaos_source_head_sha if chaos_pass else None,
        "artifact_name": chaos_artifact_name if chaos_pass else None,
        "evaluated_at": chaos_payload.get("evaluated_at") if chaos_payload else None,
        "junit_sha256": chaos_payload.get("junit_sha256") if chaos_payload else None,
        "canonical_scenario_count": chaos_payload.get("canonical_scenario_count") if chaos_payload else None,
        "passed_scenario_count": chaos_payload.get("passed_scenario_count") if chaos_payload else None,
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate Wave 3 immutable natural-slot proofs")
    parser.add_argument("--proof-dir", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--chaos-acceptance", type=Path, required=True)
    parser.add_argument("--chaos-source-run-id", required=True)
    parser.add_argument("--chaos-source-head-sha", required=True)
    parser.add_argument("--chaos-artifact-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = build_window_summary(
        args.proof_dir,
        args.current,
        chaos_acceptance=args.chaos_acceptance,
        chaos_source_run_id=args.chaos_source_run_id,
        chaos_source_head_sha=args.chaos_source_head_sha,
        chaos_artifact_name=args.chaos_artifact_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
