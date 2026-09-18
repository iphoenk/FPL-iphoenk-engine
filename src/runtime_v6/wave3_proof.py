from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


NATURAL_SCHEDULE_KIND = "chatgpt_scheduler"
NATURAL_EVENT_NAME = "issues"
NATURAL_LOGICAL_SLOT_SOURCE = "GOVERNED_TRIGGER_EVENT"
FIRST_GATE_CONSECUTIVE_SLOTS = 6
ROLLING_PRODUCTION_WINDOW = 12
LEGACY_TWO_SLOT_OBSERVATION = 2
PRODUCTION_ROLLING_WINDOW = 12
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
    collect_job_id: str | None = None,
    publish_job_id: str | None = None,
    fulfillment_job_id: str | None = None,
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
    if control.get("authoritative_runtime_snapshot") is not True:
        raise Wave3ProofError("authoritative_runtime_snapshot_missing")
    if control.get("logical_slot_source") != NATURAL_LOGICAL_SLOT_SOURCE:
        raise Wave3ProofError("natural_logical_slot_source_invalid")
    immutable_job_ids = {
        "acquisition_run_id": str(collect_job_id or "").strip(),
        "publication_run_id": str(publish_job_id or "").strip(),
        "orchestration_fulfillment_run_id": str(fulfillment_job_id or "").strip(),
    }
    missing_job_ids = [name for name, value in immutable_job_ids.items() if not value]
    if missing_job_ids:
        raise Wave3ProofError("immutable_source_job_ids_required:" + ",".join(missing_job_ids))

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
        "TRIGGERED": _stage("PASS", at=observed_at, evidence="runtime_control.governed trigger event proof"),
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
        "core_trigger_source": NATURAL_LOGICAL_SLOT_SOURCE,
        "logical_slot_source": NATURAL_LOGICAL_SLOT_SOURCE,
        "audit_transport_required_for_core_proof": False,
        "logical_slot": logical_slot,
        "observed_at": observed_at,
        "verified_at": verified,
        "run_id": actual_run_id,
        "workflow_run_id": actual_run_id,
        "acquisition_run_id": immutable_job_ids["acquisition_run_id"],
        "publication_run_id": immutable_job_ids["publication_run_id"],
        "orchestration_fulfillment_run_id": immutable_job_ids["orchestration_fulfillment_run_id"],
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
            "audit_transport_is_separate_from_core_execution_proof": True,
            "connector_result_is_not_required_when_independent_proof_is_complete": True,
            "initial_natural_gate_consecutive_slots": FIRST_GATE_CONSECUTIVE_SLOTS,
            "production_green_requires_rolling_12_of_12": True,
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


def _proof_ownership_key(proof: dict[str, Any]) -> str:
    publication_generation_id = str(proof.get("publication_generation_id") or "").strip()
    if publication_generation_id:
        return f"publication:{publication_generation_id}"
    run_id = str(proof.get("run_id") or "").strip()
    run_attempt = str(proof.get("run_attempt") or "").strip()
    candidate_generation_id = str(proof.get("candidate_generation_id") or "").strip()
    published_runtime_sha = str(proof.get("published_runtime_sha") or "").strip()
    if run_id or run_attempt or candidate_generation_id or published_runtime_sha:
        return "fallback:" + "|".join((run_id, run_attempt, candidate_generation_id, published_runtime_sha))
    raise Wave3ProofError("proof_publication_ownership_missing")


def proof_is_countable(proof: dict[str, Any]) -> bool:
    if proof.get("proof_kind") != "WAVE3_NATURAL_CORE_SLOT":
        return False
    if proof.get("natural_slot") is not True or proof.get("core_chain_pass") is not True:
        return False
    if proof.get("natural_transport") != "FPL_MASTER_SLOT_ISSUE_TITLE":
        return False
    trigger_source = proof.get("core_trigger_source")
    if trigger_source is not None and trigger_source != NATURAL_LOGICAL_SLOT_SOURCE:
        return False
    stages = dict(proof.get("stages") or {})
    return all((stages.get(name) or {}).get("state") == "PASS" for name in CORE_STAGES)


def evaluate_proof_window(
    proofs: Iterable[dict[str, Any]],
    *,
    chaos_acceptance_pass: bool = False,
) -> dict[str, Any]:
    """Evaluate genuine natural proofs with duplicate-publication checks scoped to active windows."""
    rows = [dict(proof) for proof in proofs if proof_is_countable(proof)]
    rows.sort(key=_proof_slot)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _proof_slot(row).isoformat()
        grouped.setdefault(key, []).append(row)

    duplicate_publication_slots: list[str] = []
    duplicate_evidence_slots: list[str] = []
    unique: dict[str, dict[str, Any]] = {}
    for key, slot_rows in grouped.items():
        ownership_keys = {_proof_ownership_key(row) for row in slot_rows}
        if len(slot_rows) > 1:
            if len(ownership_keys) > 1:
                duplicate_publication_slots.append(key)
            else:
                duplicate_evidence_slots.append(key)
        unique[key] = slot_rows[-1]

    ordered_keys = sorted(unique)
    ordered = [unique[key] for key in ordered_keys]

    consecutive = 0
    expected: datetime | None = None
    for row in reversed(ordered):
        slot = _proof_slot(row)
        if expected is None or slot == expected:
            consecutive += 1
            expected = slot - timedelta(hours=1)
        else:
            break

    active_two_keys = (
        set(ordered_keys[-LEGACY_TWO_SLOT_OBSERVATION:])
        if len(ordered_keys) >= LEGACY_TWO_SLOT_OBSERVATION
        else set(ordered_keys)
    )
    duplicate_in_two = sorted(set(duplicate_publication_slots) & active_two_keys)
    two_complete = consecutive >= LEGACY_TWO_SLOT_OBSERVATION and not duplicate_in_two

    active_first_gate_keys = (
        set(ordered_keys[-FIRST_GATE_CONSECUTIVE_SLOTS:])
        if len(ordered_keys) >= FIRST_GATE_CONSECUTIVE_SLOTS
        else set(ordered_keys)
    )
    duplicate_in_first_gate = sorted(set(duplicate_publication_slots) & active_first_gate_keys)
    first_gate_complete = (
        consecutive >= FIRST_GATE_CONSECUTIVE_SLOTS and not duplicate_in_first_gate
    )

    active_six_keys = set(ordered_keys[-6:]) if len(ordered_keys) >= 6 else set(ordered_keys)
    duplicate_in_six = sorted(set(duplicate_publication_slots) & active_six_keys)
    six_complete = consecutive >= 6 and not duplicate_in_six

    last_window_keys = ordered_keys[-ROLLING_PRODUCTION_WINDOW:]
    last_window = [unique[key] for key in last_window_keys]
    duplicate_in_window = sorted(
        set(duplicate_publication_slots) & set(last_window_keys)
    )
    rolling_12 = (
        len(last_window) == ROLLING_PRODUCTION_WINDOW
        and not duplicate_in_window
    )
    if rolling_12:
        for left, right in zip(last_window, last_window[1:]):
            if _proof_slot(right) - _proof_slot(left) != timedelta(hours=1):
                rolling_12 = False
                break

    if not first_gate_complete:
        phase = "6/6_IN_PROGRESS"
    elif not rolling_12:
        phase = "12/12_IN_PROGRESS"
    else:
        phase = "12/12_COMPLETE"

    natural_window_eligible = rolling_12
    chaos_pass = bool(chaos_acceptance_pass)
    return {
        "schema_version": 1,
        "phase": phase,
        "countable_proof_count": len(ordered),
        "consecutive_successful_natural_slots": consecutive,
        "first_gate_target": FIRST_GATE_CONSECUTIVE_SLOTS,
        "first_gate_complete": first_gate_complete,
        "two_of_two_complete": two_complete,
        "six_of_six_complete": six_complete,
        "rolling_12_of_12_complete": rolling_12,
        "duplicate_logical_slots": sorted(set(duplicate_publication_slots)),
        "duplicate_publication_slots": sorted(set(duplicate_publication_slots)),
        "duplicate_evidence_slots": sorted(set(duplicate_evidence_slots)),
        "duplicate_publication_slots_in_active_two": duplicate_in_two,
        "duplicate_publication_slots_in_active_first_gate": duplicate_in_first_gate,
        "duplicate_publication_slots_in_active_six": duplicate_in_six,
        "duplicate_publication_slots_in_rolling_12": duplicate_in_window,
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
    parser.add_argument("--collect-job-id", required=True)
    parser.add_argument("--publish-job-id", required=True)
    parser.add_argument("--fulfillment-job-id", required=True)
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
        collect_job_id=args.collect_job_id,
        publish_job_id=args.publish_job_id,
        fulfillment_job_id=args.fulfillment_job_id,
        published_runtime_sha=args.published_runtime_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "logical_slot": proof["logical_slot"], "publication_generation_id": proof["publication_generation_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
