from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


NATURAL_SCHEDULE_KIND = "chatgpt_scheduler"
NATURAL_EVENT_NAME = "issues"
CORE_STAGES = (
    "TRIGGERED",
    "ACQUIRED",
    "STAGED",
    "FROZEN",
    "INTEGRITY_PASS",
    "VALIDATED",
    "PROMOTED",
)
OPTIONAL_STAGES = ("PREFETCHED", "DELIVERED")


class Wave3ProofError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise Wave3ProofError(f"missing_or_invalid:{path}") from exc
    if not isinstance(payload, dict):
        raise Wave3ProofError(f"not_object:{path}")
    return payload


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise Wave3ProofError(f"invalid_timestamp:{value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Wave3ProofError(f"timestamp_without_timezone:{value}")
    return parsed.astimezone(timezone.utc)


def _stage(state: str, *, at: str | None, evidence: str) -> dict[str, Any]:
    return {"state": state, "at": at, "evidence": evidence}


def build_slot_proof(
    root: Path,
    *,
    source_commit: str,
    production_validated: bool,
    promotion_verified: bool,
    run_id: str | None = None,
    run_attempt: str | None = None,
    verified_at: datetime | None = None,
    published_runtime_sha: str | None = None,
) -> dict[str, Any]:
    """Build immutable post-publish evidence without mutating the frozen runtime tree."""
    manifest = _read_json(root / "manifest.json")
    integrity = _read_json(root / "health" / "publish_integrity.json")
    freeze = _read_json(root / "health" / "candidate_freeze.lock")
    control = dict(manifest.get("runtime_control") or {})

    actual_run_id = str(run_id or os.getenv("GITHUB_RUN_ID") or "")
    actual_run_attempt = str(run_attempt or os.getenv("GITHUB_RUN_ATTEMPT") or "1")
    if not actual_run_id:
        raise Wave3ProofError("run_id_required")
    if control.get("event_name") != NATURAL_EVENT_NAME:
        raise Wave3ProofError("not_genuine_natural_core_transport")
    if control.get("schedule_kind") != NATURAL_SCHEDULE_KIND:
        raise Wave3ProofError("not_genuine_natural_core_slot")
    if control.get("chatgpt_scheduler_proof") is not True:
        raise Wave3ProofError("scheduler_proof_missing")
    if control.get("counts_as_completed_operational_slot") is not True:
        raise Wave3ProofError("not_operational_slot")
    if integrity.get("status") != "PASS":
        raise Wave3ProofError("publish_integrity_not_pass")
    if freeze.get("candidate_state") != "FROZEN":
        raise Wave3ProofError("candidate_not_frozen")
    if str(freeze.get("run_id")) != actual_run_id:
        raise Wave3ProofError("candidate_run_id_mismatch")
    if str(freeze.get("run_attempt")) != actual_run_attempt:
        raise Wave3ProofError("candidate_run_attempt_mismatch")
    if not production_validated:
        raise Wave3ProofError("production_validation_not_proven")
    if not promotion_verified:
        raise Wave3ProofError("promotion_not_proven")
    if not source_commit or len(source_commit) < 7:
        raise Wave3ProofError("source_commit_required")

    logical_slot = control.get("expected_cycle_at") or freeze.get("logical_slot")
    observed_at = control.get("cycle_observed_at") or freeze.get("observed_at")
    _parse_time(str(logical_slot) if logical_slot else None)
    _parse_time(str(observed_at) if observed_at else None)
    verified = (verified_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    candidate_generation_id = freeze.get("candidate_generation_id")
    if not candidate_generation_id:
        raise Wave3ProofError("candidate_generation_id_missing")
    publication_generation_id = (
        f"v6-publication:{actual_run_id}:{actual_run_attempt}:{candidate_generation_id}"
    )

    stages = {
        "TRIGGERED": _stage("PASS", at=observed_at, evidence="runtime_control.issue-title scheduler proof"),
        "ACQUIRED": _stage("PASS", at=manifest.get("generated_at"), evidence="source publication artifact manifest"),
        "STAGED": _stage("PASS", at=freeze.get("frozen_at"), evidence="candidate_freeze.manifest_input_sha256"),
        "FROZEN": _stage("PASS", at=freeze.get("frozen_at"), evidence="candidate_freeze.lock"),
        "INTEGRITY_PASS": _stage("PASS", at=integrity.get("validated_at") or freeze.get("frozen_at"), evidence="publish_integrity.json"),
        "VALIDATED": _stage("PASS", at=verified, evidence="source workflow publishable validation + publisher revalidation"),
        "PROMOTED": _stage("PASS", at=verified, evidence="source workflow publish job + exact-tree verification succeeded"),
        "PREFETCHED": _stage("N/A", at=None, evidence="not_required_for_core_slot"),
        "DELIVERED": _stage("N/A", at=None, evidence="report_delivery_is_separate_from_core_slot"),
    }

    proof = {
        "schema_version": 1,
        "proof_kind": "WAVE3_NATURAL_CORE_SLOT",
        "natural_slot": True,
        "natural_transport": "FPL_MASTER_SLOT_ISSUE_TITLE",
        "logical_slot": logical_slot,
        "observed_at": observed_at,
        "verified_at": verified,
        "run_id": actual_run_id,
        "run_attempt": actual_run_attempt,
        "source_commit": source_commit,
        "published_runtime_sha": published_runtime_sha,
        "candidate_generation_id": candidate_generation_id,
        "publication_generation_id": publication_generation_id,
        "registry_fingerprint": freeze.get("registry_fingerprint"),
        "registry_epoch": freeze.get("registry_epoch"),
        "candidate_tree_sha256": freeze.get("candidate_tree_sha256"),
        "published_tree_sha256": integrity.get("tree_sha256"),
        "publisher_mode": "dedicated_v6_github_app",
        "stages": stages,
        "core_chain_pass": all(stages[name]["state"] == "PASS" for name in CORE_STAGES),
        "governance": {
            "manual_or_controlled_recovery_counts": False,
            "issue_comment_master_acquire_counts": False,
            "report_prefetch_counts_as_natural_core_slot": False,
            "failed_candidate_can_be_counted": False,
            "source_publish_job_success_required": True,
            "proof_created_post_publish_without_runtime_tree_mutation": True,
            "production_green_requires_rolling_48_of_48": True,
            "production_green_requires_controlled_chaos_acceptance": True,
        },
    }
    if not proof["registry_fingerprint"]:
        raise Wave3ProofError("registry_fingerprint_missing")
    if not proof["core_chain_pass"]:
        raise Wave3ProofError("core_chain_not_pass")
    return proof


def _proof_slot(proof: dict[str, Any]) -> datetime:
    parsed = _parse_time(str(proof.get("logical_slot") or ""))
    if parsed is None:
        raise Wave3ProofError("logical_slot_missing")
    return parsed


def proof_is_countable(proof: dict[str, Any]) -> bool:
    if proof.get("proof_kind") != "WAVE3_NATURAL_CORE_SLOT":
        return False
    if proof.get("natural_slot") is not True or proof.get("core_chain_pass") is not True:
        return False
    if proof.get("natural_transport") != "FPL_MASTER_SLOT_ISSUE_TITLE":
        return False
    stages = dict(proof.get("stages") or {})
    return all((stages.get(name) or {}).get("state") == "PASS" for name in CORE_STAGES)


def evaluate_proof_window(
    proofs: Iterable[dict[str, Any]],
    *,
    chaos_acceptance_pass: bool = False,
) -> dict[str, Any]:
    """Evaluate genuine natural proofs and keep Production Green gated by chaos acceptance."""
    rows = [dict(proof) for proof in proofs if proof_is_countable(proof)]
    rows.sort(key=_proof_slot)
    duplicate_slots: list[str] = []
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _proof_slot(row).isoformat()
        if key in unique:
            duplicate_slots.append(key)
        unique[key] = row
    ordered = [unique[key] for key in sorted(unique)]

    consecutive = 0
    expected: datetime | None = None
    for row in reversed(ordered):
        slot = _proof_slot(row)
        if expected is None or slot == expected:
            consecutive += 1
            expected = slot - timedelta(hours=1)
        else:
            break

    last_48 = ordered[-48:]
    rolling_48 = len(last_48) == 48 and not duplicate_slots
    if rolling_48:
        for left, right in zip(last_48, last_48[1:]):
            if _proof_slot(right) - _proof_slot(left) != timedelta(hours=1):
                rolling_48 = False
                break

    if consecutive < 6:
        phase = "6/6_IN_PROGRESS"
    elif not rolling_48:
        phase = "48/48_IN_PROGRESS"
    else:
        phase = "48/48_COMPLETE"

    natural_window_eligible = rolling_48 and not duplicate_slots
    chaos_pass = bool(chaos_acceptance_pass)
    return {
        "schema_version": 1,
        "phase": phase,
        "countable_proof_count": len(ordered),
        "consecutive_successful_natural_slots": consecutive,
        "six_of_six_complete": consecutive >= 6,
        "rolling_48_of_48_complete": rolling_48,
        "duplicate_logical_slots": sorted(set(duplicate_slots)),
        "natural_window_eligible": natural_window_eligible,
        "chaos_acceptance_pass": chaos_pass,
        "production_green_eligible": natural_window_eligible and chaos_pass,
        "latest_logical_slot": _proof_slot(ordered[-1]).isoformat() if ordered else None,
    }


def assert_rejected_candidate_did_not_move_runtime(
    *,
    runtime_sha_before: str,
    runtime_sha_after: str,
    candidate_accepted: bool,
) -> None:
    if not candidate_accepted and runtime_sha_before != runtime_sha_after:
        raise Wave3ProofError("rejected_candidate_moved_runtime_pointer")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Wave 3 post-publish natural-slot proof")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-run-attempt", required=True)
    parser.add_argument("--published-runtime-sha")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--production-validated", action="store_true")
    parser.add_argument("--promotion-verified", action="store_true")
    args = parser.parse_args()
    proof = build_slot_proof(
        args.root,
        source_commit=args.source_commit,
        production_validated=args.production_validated,
        promotion_verified=args.promotion_verified,
        run_id=args.source_run_id,
        run_attempt=args.source_run_attempt,
        published_runtime_sha=args.published_runtime_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "logical_slot": proof["logical_slot"], "publication_generation_id": proof["publication_generation_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
