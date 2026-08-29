from __future__ import annotations

from datetime import datetime

from src.engines import v4_backtest_store as store
from src.engines.v4_submitted_state import submitted_state_path, submitted_state_integrity
from src.engines.v4_validation import reconcile_prediction_snapshot
from src.utils import atomic_json, read_json, utcnow


def actual_by_element(live: dict) -> dict[int, dict]:
    out={}
    for item in (live or {}).get("elements",[]):
        if item.get("id") is None:continue
        stats=item.get("stats") or {};starts=stats.get("starts")
        if starts is None:started=None;started_source=None
        else:
            try:started=bool(int(starts))
            except (TypeError,ValueError) as exc:raise RuntimeError(f"invalid Official stats.starts for element {item.get('id')}: {starts!r}") from exc
            started_source="official_event_live.stats.starts"
        out[int(item["id"])]={"total_points":float(stats.get("total_points",0) or 0),"minutes":float(stats.get("minutes",0) or 0),"started":started,"started_source":started_source}
    return out


def reconcile_finished_gw(gw:int,live:dict,now:datetime|None=None)->dict|None:
    path=store.reconciled_path(gw);existing=read_json(path,None)
    if existing:
        ok,reason=store.reconciled_integrity(existing)
        if not ok:raise RuntimeError(f"existing reconciliation failed integrity: {reason}")
        return existing
    snapshot=read_json(store.deadline_snapshot_path(gw),None)
    if not snapshot:return None
    ok,reason=store.snapshot_integrity(snapshot,int(gw))
    if not ok:raise RuntimeError(f"deadline snapshot is not eligible for reconciliation: {reason}")
    actual=actual_by_element(live)
    if not actual:raise RuntimeError("finished GW live payload has no player actuals")
    submitted=read_json(submitted_state_path(gw),None)
    if submitted:
        submitted_ok,submitted_reason=submitted_state_integrity(submitted,gw)
        if not submitted_ok:raise RuntimeError(f"submitted-state archive failed integrity: {submitted_reason}")
    report=reconcile_prediction_snapshot(snapshot,actual,event=int(gw),deadline=snapshot.get("deadline_time"),submitted_state=submitted)
    metrics=report.get("metrics") or {}
    if metrics.get("status")!="PASS" or int(metrics.get("n") or 0)<=0:raise RuntimeError(f"reconciliation produced no safe sample: {metrics}")
    if int(metrics.get("leakage_rejected") or 0)!=0:raise RuntimeError("reconciliation rejected leakage rows; snapshot is not safe")
    current=now or utcnow()
    if current.tzinfo is None:raise RuntimeError("reconciliation timestamp must be timezone-aware")
    start_evidence=sum(row.get("started") is not None for row in actual.values())
    out={"schema_version":4962,"kind":"post_gw_reconciliation","gw":int(gw),"generated_at":current.isoformat(),"model_version":snapshot.get("model_version"),"deadline_time":snapshot.get("deadline_time"),"source_snapshot_sha256":store._digest(snapshot),"submitted_state_sha256":store._digest(submitted) if submitted else None,"immutable":True,"sample_eligible":True,"actual_elements":len(actual),"official_start_evidence_elements":start_evidence,"report":report,"guardrails":{"started_from_official_stats_starts_only":True,"minutes_never_infer_started":True,"missing_starts_remain_unknown":True,"historical_forecast_never_reconstructed_after_fact":True,"submitted_state_regret_uses_immutable_official_archive":True}}
    atomic_json(path,out);return out
