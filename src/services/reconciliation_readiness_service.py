from __future__ import annotations

import json
import re

from src.engines import v4_backtest_store as store
from src.release import RELEASE_VERSION
from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

RAW_SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
LIFECYCLE = DATA / "validation" / "lifecycle_v4.json"
OUTFILE = DATA / "validation" / "reconciliation_readiness_v4.json"
OWNERSHIP = CONFIG / "architecture_ownership_registry.json"


def _snapshot_gws() -> list[int]:
    if not store.SNAPDIR.exists():
        return []
    out: list[int] = []
    for path in store.SNAPDIR.glob("gw*.json"):
        match = re.fullmatch(r"gw(\d+)\.json", path.name)
        if match:
            out.append(int(match.group(1)))
    return sorted(set(out))


def _target_gw() -> int | None:
    snapshots = _snapshot_gws()
    if not snapshots:
        return None
    unreconciled = [gw for gw in snapshots if not store.reconciled_path(gw).exists()]
    return max(unreconciled or snapshots)


def classify_stage(*, before_deadline: bool, submitted_picks_ready: bool, finished: bool, actuals_ready: bool, archive_ready: bool) -> str:
    if archive_ready:
        return "RECONCILED"
    if before_deadline:
        return "PREDEADLINE_READY"
    if not submitted_picks_ready:
        return "WAITING_SUBMITTED_PICKS"
    if not finished:
        return "WAITING_GW_FINISH"
    if actuals_ready:
        return "READY_TO_RECONCILE"
    return "ACTUALS_REFRESH_REQUIRED"


def run() -> dict:
    raw = read_json(RAW_SNAPSHOT, {})
    lifecycle = read_json(LIFECYCLE, {})
    ownership = read_json(OWNERSHIP, {})
    target = _target_gw()
    blockers: list[str] = []
    pending: list[str] = []

    if raw.get("schema") != "snapshot.v1":
        blockers.append("runtime_snapshot_v1_missing")
    if lifecycle.get("status") != "PASS":
        blockers.append("validation_lifecycle_not_passed")
    if target is None:
        blockers.append("no_frozen_deadline_snapshot")

    snapshot = read_json(store.deadline_snapshot_path(target), {}) if target is not None else {}
    snapshot_ok = False
    snapshot_reason = "no_target_gw"
    if target is not None:
        snapshot_ok, snapshot_reason = store.snapshot_integrity(snapshot, target)
        if not snapshot_ok:
            blockers.append(f"deadline_snapshot_invalid:{snapshot_reason}")

    owners = {row.get("id"): row.get("owner") for row in ownership.get("responsibilities") or []}
    ownership_chain = {
        "official_fpl_acquisition": owners.get("OFFICIAL_FPL_ACQUISITION") == "raw_snapshot",
        "validation_store": owners.get("VALIDATION_STORE") == "validation",
        "reconciliation_truth": owners.get("RECONCILIATION_TRUTH") == "validation",
        "validation_lifecycle": owners.get("VALIDATION_LIFECYCLE") == "validation",
        "reconciliation_readiness": owners.get("RECONCILIATION_READINESS") == "validation",
    }
    if not all(ownership_chain.values()):
        blockers.append("reconciliation_ownership_chain_invalid")

    phase = raw.get("phase") or {}
    submitted_gw = int(phase.get("submitted_gw") or 0) or None
    last_finished_gw = int(phase.get("last_finished_gw") or 0) or None
    scoring_gw = int(phase.get("scoring_gw") or 0) or None
    deadline = parse_dt(snapshot.get("deadline_time")) if snapshot else None
    current = parse_dt(raw.get("as_of")) or parse_dt(raw.get("generated_at")) or utcnow()
    before_deadline = bool(deadline and current < deadline)

    official = raw.get("official") or {}
    picks_count = len(((official.get("picks") or {}).get("picks") or [])) if submitted_gw == target else 0
    submitted_picks_ready = bool(target is not None and submitted_gw == target and picks_count == 15)
    finished = bool(target is not None and last_finished_gw is not None and last_finished_gw >= target)
    event_live_elements = len(((official.get("event_live") or {}).get("elements") or [])) if scoring_gw == target else 0
    actuals_ready = bool(finished and scoring_gw == target and event_live_elements > 0)

    archive = read_json(store.reconciled_path(target), {}) if target is not None else {}
    archive_exists = bool(archive)
    archive_ready = False
    archive_reason = None
    if archive_exists:
        archive_ready, archive_reason = store.reconciled_integrity(archive)
        if not archive_ready:
            blockers.append(f"reconciliation_archive_invalid:{archive_reason}")

    eligible_gws = set(int(gw) for gw in ((lifecycle.get("eligibility") or {}).get("eligible_gws") or []))
    calibration_entry_ready = bool(target is not None and archive_ready and target in eligible_gws)

    if target is not None and snapshot_ok:
        if before_deadline:
            pending.extend(["official_submitted_picks_after_deadline", "gw_finish", "official_event_live_actuals", "post_gw_reconciliation"])
        elif not submitted_picks_ready:
            pending.append("official_submitted_picks_for_target_gw")
        if not finished:
            pending.append("gw_finish")
        if finished and not archive_ready and not actuals_ready:
            pending.append("official_event_live_actuals_for_target_gw")
        if actuals_ready and not archive_ready:
            pending.append("post_gw_reconciliation")
        if archive_ready and not calibration_entry_ready:
            pending.append("eligible_calibration_view_refresh")

    stage = "BLOCKED" if blockers else classify_stage(
        before_deadline=before_deadline,
        submitted_picks_ready=submitted_picks_ready,
        finished=finished,
        actuals_ready=actuals_ready,
        archive_ready=archive_ready,
    )
    out = {
        "schema_version": 4962,
        "release": RELEASE_VERSION,
        "service": "reconciliation_readiness",
        "execution_boundary": "validation",
        "status": "FAIL" if blockers else "PASS",
        "target_gw": target,
        "stage": stage,
        "ready_for_reconciliation_now": stage == "READY_TO_RECONCILE",
        "checks": {
            "snapshot_integrity": {"pass": snapshot_ok, "reason": snapshot_reason, "players": len(snapshot.get("players") or [])},
            "validation_lifecycle": {"pass": lifecycle.get("status") == "PASS", "snapshot_status": (lifecycle.get("snapshot") or {}).get("status")},
            "ownership_chain": {"pass": all(ownership_chain.values()), "owners": ownership_chain},
            "submitted_picks": {"pass": submitted_picks_ready, "submitted_gw": submitted_gw, "picks": picks_count, "expected_gw": target},
            "finished_gw": {"pass": finished, "last_finished_gw": last_finished_gw, "expected_gw": target},
            "official_actuals": {"pass": actuals_ready, "scoring_gw": scoring_gw, "elements": event_live_elements, "expected_gw": target},
            "reconciliation_archive": {"pass": archive_ready, "exists": archive_exists, "reason": archive_reason},
            "calibration_entry": {"pass": calibration_entry_ready, "eligible_gws": sorted(eligible_gws)},
        },
        "blockers": blockers,
        "pending": sorted(set(pending)),
        "guardrails": {
            "read_only_audit": True,
            "official_api_refetch": False,
            "deadline_snapshot_integrity_reused_from_validation_store": True,
            "reconciliation_integrity_reused_from_validation_store": True,
            "reconciliation_truth_not_reimplemented": True,
            "official_fpl_single_acquisition_owner": True,
            "expected_future_state_is_pending_not_failure": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({"service": "reconciliation_readiness", "status": out["status"], "target_gw": target, "stage": stage, "blockers": blockers, "pending": out["pending"]}, ensure_ascii=False))
    if blockers:
        raise SystemExit(2)
    return out


if __name__ == "__main__":
    run()
