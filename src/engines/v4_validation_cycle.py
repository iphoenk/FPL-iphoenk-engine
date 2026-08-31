from __future__ import annotations

import argparse
import json
from datetime import datetime

from src.engines.v4_backtest_store import (
    deadline_snapshot_path,
    persist_deadline_snapshot,
    reconciled_path,
    refresh_eligible_view,
)
from src.engines.v4_reconciliation_truth import reconcile_finished_gw
from src.engines.v4_submitted_state import persist_submitted_state, submitted_state_path
from src.release import RELEASE_VERSION
from src.utils import DATA, atomic_json, parse_dt, read_json, utcnow

RAW_SNAPSHOT = DATA / "runtime" / "snapshot.v1.json"
PREDICTIONS = DATA / "predictions_v4.json"
OUTFILE = DATA / "validation" / "lifecycle_v4.json"


def _is_simulation(raw: dict) -> bool:
    checkpoint = raw.get("checkpoint_context") or {}
    return bool(raw.get("as_of") or checkpoint.get("is_simulation"))


def snapshot_current(raw: dict | None = None, predictions: dict | None = None, now: datetime | None = None) -> dict:
    raw = raw or read_json(RAW_SNAPSHOT, {})
    predictions = predictions or read_json(PREDICTIONS, {})
    if _is_simulation(raw):
        return {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
    phase = raw.get("phase") or {}
    gw = phase.get("planning_gw")
    deadline = phase.get("deadline_time")
    if not gw or not deadline:
        return {"status": "SKIP", "reason": "no_planning_gw_or_deadline"}
    deadline_dt = parse_dt(deadline)
    current = now or utcnow()
    if not deadline_dt or deadline_dt.tzinfo is None:
        raise RuntimeError("planning deadline is missing or timezone-naive")
    if current >= deadline_dt:
        return {"status": "SKIP", "reason": "planning_deadline_not_future", "gw": int(gw), "deadline_time": deadline}
    path = deadline_snapshot_path(int(gw))
    existed = path.exists()
    snapshot = persist_deadline_snapshot(int(gw), deadline, predictions, predictions.get("generated_at"), now=current)
    return {
        "status": "PASS",
        "action": "PRESERVED" if existed else "FROZEN",
        "gw": int(gw),
        "deadline_time": deadline,
        "players": len(snapshot.get("players") or []),
        "model_version": snapshot.get("model_version"),
        "captured_at": snapshot.get("captured_at"),
        "immutable": snapshot.get("immutable") is True,
    }


def capture_submitted_state(raw: dict | None = None, now: datetime | None = None) -> dict:
    raw = raw or read_json(RAW_SNAPSHOT, {})
    if _is_simulation(raw):
        return {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
    phase = raw.get("phase") or {}
    gw = int(phase.get("submitted_gw") or 0) or None
    deadline = phase.get("current_deadline_time")
    current = now or utcnow()
    if not gw or not deadline:
        return {"status": "SKIP", "reason": "submitted_gw_or_deadline_missing"}
    deadline_dt = parse_dt(deadline)
    if not deadline_dt or deadline_dt.tzinfo is None or current.tzinfo is None:
        raise RuntimeError("submitted state capture requires timezone-aware timestamps")
    if current < deadline_dt:
        return {"status": "SKIP", "reason": "deadline_not_passed", "gw": gw}
    picks = ((raw.get("official") or {}).get("picks") or {})
    if len(picks.get("picks") or []) != 15:
        return {"status": "SKIP", "reason": "official_submitted_picks_not_ready", "gw": gw}
    path = submitted_state_path(gw)
    existed = path.exists()
    archived = persist_submitted_state(gw, deadline, picks, now=current)
    submitted = archived.get("submitted") or {}
    return {
        "status": "PASS",
        "action": "PRESERVED" if existed else "ARCHIVED",
        "gw": gw,
        "immutable": archived.get("immutable") is True,
        "players": len(submitted.get("players") or []),
        "starting_xi": len(submitted.get("starting_xi") or []),
        "bench": len(submitted.get("bench") or []),
        "captain": submitted.get("captain"),
        "vice_captain": submitted.get("vice_captain"),
        "active_chip": submitted.get("active_chip"),
        "baseline_comparison": archived.get("baseline_comparison") or {},
    }


def reconcile_latest_finished(raw: dict | None = None, now: datetime | None = None) -> dict:
    raw = raw or read_json(RAW_SNAPSHOT, {})
    if _is_simulation(raw):
        return {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
    phase = raw.get("phase") or {}
    gw = phase.get("last_finished_gw")
    if not gw:
        return {"status": "SKIP", "reason": "no_finished_gw"}
    archive_path = reconciled_path(int(gw))
    if archive_path.exists():
        result = reconcile_finished_gw(int(gw), {}, now=now)
        metrics = ((result or {}).get("report") or {}).get("metrics") or {}
        return {"status": "PASS", "action": "PRESERVED", "gw": int(gw), "metrics": metrics, "model_version": (result or {}).get("model_version")}
    if not deadline_snapshot_path(int(gw)).exists():
        return {"status": "SKIP", "reason": "no_predeadline_snapshot", "gw": int(gw)}
    scoring_gw = phase.get("scoring_gw")
    source_key = "event_live"
    if int(scoring_gw or -1) != int(gw):
        reconciliation_actuals = raw.get("reconciliation_actuals") or {}
        if int(reconciliation_actuals.get("event") or -1) != int(gw):
            return {
                "status": "SKIP",
                "reason": "raw_snapshot_reconciliation_actuals_event_mismatch",
                "gw": int(gw),
                "scoring_gw": scoring_gw,
                "actuals_event": reconciliation_actuals.get("event"),
            }
        if reconciliation_actuals.get("source_key") != "reconciliation_event_live":
            return {
                "status": "SKIP",
                "reason": "raw_snapshot_reconciliation_actuals_source_invalid",
                "gw": int(gw),
                "scoring_gw": scoring_gw,
            }
        source_key = "reconciliation_event_live"
    live = ((raw.get("official") or {}).get(source_key) or {})
    if not list(live.get("elements") or []):
        return {
            "status": "SKIP",
            "reason": "finished_live_unavailable_in_raw_snapshot",
            "gw": int(gw),
            "actuals_source_key": source_key,
        }
    result = reconcile_finished_gw(int(gw), live, now=now)
    if not result:
        return {"status": "SKIP", "reason": "no_predeadline_snapshot", "gw": int(gw)}
    metrics = ((result.get("report") or {}).get("metrics") or {})
    return {
        "status": "PASS", "action": "CREATED", "gw": int(gw), "metrics": metrics,
        "model_version": result.get("model_version"), "actual_elements": result.get("actual_elements"),
        "official_start_evidence_elements": result.get("official_start_evidence_elements"),
        "actuals_source_key": source_key,
    }


def cycle(now: datetime | None = None, raw: dict | None = None, predictions: dict | None = None) -> dict:
    """Run validation lifecycle against one optional preloaded immutable snapshot.

    Default callers retain the file-backed contract. Consolidated validation may
    provide the exact raw/prediction objects it already loaded so lifecycle and
    framework PRE-FLIGHT evaluate the same point-in-time evidence without parsing
    the large prediction artifact twice.
    """
    raw = raw if raw is not None else read_json(RAW_SNAPSHOT, {})
    predictions = predictions if predictions is not None else read_json(PREDICTIONS, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("validation lifecycle requires runtime snapshot.v1")
    if not predictions.get("model_version") or not predictions.get("players"):
        raise RuntimeError("validation lifecycle requires current predictions_v4.json")
    simulated = _is_simulation(raw)
    if simulated:
        snapshot = {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
        submitted = {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
        reconciliation = {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
        eligibility = {"model_version": predictions.get("model_version"), "eligible_samples": None, "health_view_rebuilt": False, "reason": "simulation_never_mutates_validation_store"}
    else:
        submitted = capture_submitted_state(raw, now=now)
        reconciliation = reconcile_latest_finished(raw, now=now)
        snapshot = snapshot_current(raw, predictions, now=now)
        eligibility = refresh_eligible_view(predictions.get("model_version"))
    out = {
        "schema_version": 4943,
        "engine": "v4.9.3-validation-lifecycle-v4.9.4.3-truthful-starts",
        "release": RELEASE_VERSION,
        "status": "PASS",
        "simulated": simulated,
        "snapshot": snapshot,
        "submitted_state": submitted,
        "reconciliation": reconciliation,
        "eligibility": eligibility,
        "guardrails": {
            "raw_snapshot_only": True,
            "official_api_refetch": False,
            "retroactive_snapshot_rejected": True,
            "deadline_snapshot_immutable": True,
            "submitted_state_immutable": True,
            "submitted_state_from_official_picks_only": True,
            "submitted_state_conflict_fails_closed": True,
            "reconciliation_archive_immutable": True,
            "reconciliation_idempotent": True,
            "health_view_current_model_only": True,
            "simulation_never_mutates_store": True,
            "started_from_official_stats_starts_only": True,
            "minutes_never_infer_started": True,
            "missing_starts_excluded_from_start_brier": True,
            "preloaded_snapshot_contract_equivalent": True,
            "rollover_actuals_acquired_by_raw_snapshot_only": True,
            "rollover_actuals_event_bound": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(json.dumps({
        "service": "validation_lifecycle", "snapshot": snapshot.get("status"), "submitted_state": submitted.get("status"),
        "reconciliation": reconciliation.get("status"), "eligible_samples": eligibility.get("eligible_samples"), "simulated": simulated,
    }, ensure_ascii=False))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "submitted", "reconcile", "cycle"])
    args = parser.parse_args()
    if args.action == "snapshot":
        out = snapshot_current()
    elif args.action == "submitted":
        out = capture_submitted_state()
    elif args.action == "reconcile":
        out = reconcile_latest_finished()
    else:
        out = cycle()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
