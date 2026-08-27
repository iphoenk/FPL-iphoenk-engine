from __future__ import annotations

from datetime import datetime

from src.engines import v4_backtest_store as store
from src.engines.v4_validation import reconcile_prediction_snapshot
from src.utils import atomic_json, read_json, utcnow


def actual_by_element(live: dict) -> dict[int, dict]:
    """Build truthful actuals from Official event-live stats.

    Starting status is taken only from Official ``stats.starts``. Minutes are
    never used as a proxy: a starter can leave before 45 minutes and a substitute
    can play more than 45 minutes. Missing Official start evidence is represented
    as ``None`` so start-probability calibration can exclude it rather than invent
    a label.
    """
    out: dict[int, dict] = {}
    for item in (live or {}).get("elements", []):
        if item.get("id") is None:
            continue
        stats = item.get("stats") or {}
        starts = stats.get("starts")
        if starts is None:
            started = None
            started_source = None
        else:
            try:
                started = bool(int(starts))
            except (TypeError, ValueError) as exc:
                raise RuntimeError(f"invalid Official stats.starts for element {item.get('id')}: {starts!r}") from exc
            started_source = "official_event_live.stats.starts"
        out[int(item["id"])] = {
            "total_points": float(stats.get("total_points", 0) or 0),
            "minutes": float(stats.get("minutes", 0) or 0),
            "started": started,
            "started_source": started_source,
        }
    return out


def reconcile_finished_gw(gw: int, live: dict, now: datetime | None = None) -> dict | None:
    """Truthful reconciliation using Official start evidence only."""
    path = store.reconciled_path(gw)
    existing = read_json(path, None)
    if existing:
        ok, reason = store.reconciled_integrity(existing)
        if not ok:
            raise RuntimeError(f"existing reconciliation failed integrity: {reason}")
        return existing

    snapshot = read_json(store.deadline_snapshot_path(gw), None)
    if not snapshot:
        return None
    ok, reason = store.snapshot_integrity(snapshot, int(gw))
    if not ok:
        raise RuntimeError(f"deadline snapshot is not eligible for reconciliation: {reason}")

    actual = actual_by_element(live)
    if not actual:
        raise RuntimeError("finished GW live payload has no player actuals")
    report = reconcile_prediction_snapshot(snapshot, actual, event=int(gw), deadline=snapshot.get("deadline_time"))
    metrics = report.get("metrics") or {}
    if metrics.get("status") != "PASS" or int(metrics.get("n") or 0) <= 0:
        raise RuntimeError(f"reconciliation produced no safe sample: {metrics}")
    if int(metrics.get("leakage_rejected") or 0) != 0:
        raise RuntimeError("reconciliation rejected leakage rows; snapshot is not safe")

    current = now or utcnow()
    if current.tzinfo is None:
        raise RuntimeError("reconciliation timestamp must be timezone-aware")
    start_evidence = sum(row.get("started") is not None for row in actual.values())
    out = {
        "schema_version": 4943,
        "kind": "post_gw_reconciliation",
        "gw": int(gw),
        "generated_at": current.isoformat(),
        "model_version": snapshot.get("model_version"),
        "deadline_time": snapshot.get("deadline_time"),
        "source_snapshot_sha256": store._digest(snapshot),
        "immutable": True,
        "sample_eligible": True,
        "actual_elements": len(actual),
        "official_start_evidence_elements": start_evidence,
        "report": report,
        "guardrails": {
            "started_from_official_stats_starts_only": True,
            "minutes_never_infer_started": True,
            "missing_starts_remain_unknown": True,
        },
    }
    atomic_json(path, out)
    return out
