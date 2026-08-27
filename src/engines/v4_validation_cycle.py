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
        return {
            "status": "SKIP",
            "reason": "planning_deadline_not_future",
            "gw": int(gw),
            "deadline_time": deadline,
        }

    path = deadline_snapshot_path(int(gw))
    existed = path.exists()
    snapshot = persist_deadline_snapshot(
        int(gw),
        deadline,
        predictions,
        predictions.get("generated_at"),
        now=current,
    )
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
        return {
            "status": "PASS",
            "action": "PRESERVED",
            "gw": int(gw),
            "metrics": metrics,
            "model_version": (result or {}).get("model_version"),
        }

    if not deadline_snapshot_path(int(gw)).exists():
        # Important early-season behavior: never fabricate a retroactive baseline.
        return {"status": "SKIP", "reason": "no_predeadline_snapshot", "gw": int(gw)}

    scoring_gw = phase.get("scoring_gw")
    if int(scoring_gw or -1) != int(gw):
        return {
            "status": "SKIP",
            "reason": "raw_snapshot_does_not_carry_finished_gw_actuals",
            "gw": int(gw),
            "scoring_gw": scoring_gw,
        }

    live = ((raw.get("official") or {}).get("event_live") or {})
    if not list(live.get("elements") or []):
        return {"status": "SKIP", "reason": "finished_live_unavailable_in_raw_snapshot", "gw": int(gw)}

    result = reconcile_finished_gw(int(gw), live, now=now)
    if not result:
        return {"status": "SKIP", "reason": "no_predeadline_snapshot", "gw": int(gw)}
    metrics = ((result.get("report") or {}).get("metrics") or {})
    return {
        "status": "PASS",
        "action": "CREATED",
        "gw": int(gw),
        "metrics": metrics,
        "model_version": result.get("model_version"),
        "actual_elements": result.get("actual_elements"),
        "official_start_evidence_elements": result.get("official_start_evidence_elements"),
    }


def cycle(now: datetime | None = None) -> dict:
    raw = read_json(RAW_SNAPSHOT, {})
    predictions = read_json(PREDICTIONS, {})
    if raw.get("schema") != "snapshot.v1":
        raise RuntimeError("validation lifecycle requires runtime snapshot.v1")
    if not predictions.get("model_version") or not predictions.get("players"):
        raise RuntimeError("validation lifecycle requires current predictions_v4.json")

    simulated = _is_simulation(raw)
    if simulated:
        snapshot = {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
        reconciliation = {"status": "SKIP", "reason": "simulation_never_mutates_validation_store"}
        eligibility = {
            "model_version": predictions.get("model_version"),
            "eligible_samples": None,
            "health_view_rebuilt": False,
            "reason": "simulation_never_mutates_validation_store",
        }
    else:
        # Reconcile the finished GW first, then freeze the current planning GW.
        reconciliation = reconcile_latest_finished(raw, now=now)
        snapshot = snapshot_current(raw, predictions, now=now)
        eligibility = refresh_eligible_view(predictions.get("model_version"))

    out = {
        "schema_version": 4943,
        "engine": "v4.9.4.3-validation-lifecycle-truthful-starts",
        "status": "PASS",
        "simulated": simulated,
        "snapshot": snapshot,
        "reconciliation": reconciliation,
        "eligibility": eligibility,
        "guardrails": {
            "raw_snapshot_only": True,
            "official_api_refetch": False,
            "retroactive_snapshot_rejected": True,
            "deadline_snapshot_immutable": True,
            "reconciliation_archive_immutable": True,
            "reconciliation_idempotent": True,
            "health_view_current_model_only": True,
            "simulation_never_mutates_store": True,
            "started_from_official_stats_starts_only": True,
            "minutes_never_infer_started": True,
            "missing_starts_excluded_from_start_brier": True,
        },
    }
    atomic_json(OUTFILE, out)
    print(
        json.dumps(
            {
                "service": "validation_lifecycle",
                "snapshot": snapshot.get("status"),
                "reconciliation": reconciliation.get("status"),
                "eligible_samples": eligibility.get("eligible_samples"),
                "simulated": simulated,
            },
            ensure_ascii=False,
        )
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "reconcile", "cycle"])
    args = parser.parse_args()
    if args.action == "snapshot":
        out = snapshot_current()
    elif args.action == "reconcile":
        out = reconcile_latest_finished()
    else:
        out = cycle()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
