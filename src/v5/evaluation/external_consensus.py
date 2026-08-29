from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_external_consensus.json"


def normalize(observations: dict[str, Any] | None, native_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    payload = observations if isinstance(observations, dict) else {}
    if payload.get("contract") == cfg["contract"] and payload.get("native_conclusion_frozen_before_overlay") is True:
        return payload
    source_map = cfg["sources"]
    allowed_availability = set(cfg["availability_states"])
    allowed_directions = set(cfg["directions"])
    rows = []
    for raw in payload.get("observations") or []:
        if not isinstance(raw, dict): continue
        source = str(raw.get("source") or raw.get("source_id") or "").lower()
        if source not in source_map: continue
        availability = str(raw.get("availability") or "UNAVAILABLE")
        if availability not in allowed_availability: availability = "UNAVAILABLE"
        direction = str(raw.get("normalized_direction") or "INSUFFICIENT_EVIDENCE")
        if direction not in allowed_directions: direction = "INSUFFICIENT_EVIDENCE"
        if availability in {"UNAVAILABLE", "STALE"}: direction = "INSUFFICIENT_EVIDENCE"
        elif availability == "NO_MATERIAL_UPDATE": direction = "NEUTRAL"
        rows.append({"source":source,"source_role":source_map[source],"observed_at":raw.get("observed_at"),"freshness":raw.get("freshness"),"availability":availability,"subject":raw.get("subject"),"horizon":raw.get("horizon"),"signal":raw.get("signal"),"native_metric_if_visible":raw.get("native_metric_if_visible"),"normalized_direction":direction,"confidence":raw.get("confidence"),"evidence_note":raw.get("evidence_note"),"possible_factual_error":bool(raw.get("possible_factual_error"))})
    subjects = {}
    for row in rows: subjects.setdefault(str(row.get("subject") or "UNSPECIFIED"), []).append(row)
    subject_results=[]
    for subject, items in sorted(subjects.items()):
        current=[r for r in items if r["availability"] in {"AVAILABLE","PARTIAL"}]; dirs={r["normalized_direction"] for r in current}
        if not current: cls="INSUFFICIENT_EVIDENCE"
        elif "SUPPORT_NATIVE" in dirs and "OPPOSE_NATIVE" in dirs: cls="REVIEW_DIVERGENCE"
        elif dirs <= {"SUPPORT_NATIVE","NEUTRAL"} and "SUPPORT_NATIVE" in dirs: cls="ALIGN"
        elif dirs <= {"OPPOSE_NATIVE","NEUTRAL"} and "OPPOSE_NATIVE" in dirs: cls="DIVERGE"
        else: cls="NEUTRAL"
        subject_results.append({"subject":subject,"classification":cls,"observations":items})
    current=[r for r in rows if r["availability"] in {"AVAILABLE","PARTIAL"}]
    if not current: overall="INSUFFICIENT_EVIDENCE"
    elif any(x["classification"]=="REVIEW_DIVERGENCE" for x in subject_results): overall="REVIEW_DIVERGENCE"
    elif any(x["classification"]=="DIVERGE" for x in subject_results): overall="DIVERGE"
    elif any(x["classification"]=="ALIGN" for x in subject_results): overall="ALIGN"
    else: overall="NEUTRAL"
    factual_refresh=any(r["possible_factual_error"] for r in current)
    return {"schema_version":1,"contract":cfg["contract"],"generated_at":datetime.now(timezone.utc).isoformat(),"owner":cfg["owner"],"native_conclusion_frozen_before_overlay":True,"native_snapshot":native_snapshot or {},"overall":overall,"requires_official_refresh":factual_refresh,"observations":rows,"subjects":subject_results,"source_status":{source:next((r["availability"] for r in rows if r["source"]==source),"UNAVAILABLE") for source in source_map},"governance":{**cfg["governance"],"advisory_only":True,"majority_vote_used":False,"native_truth_mutated":False,"outage_fail_neutral":True,"factual_divergence_action":"REFRESH_OFFICIAL_AND_RERUN_NATIVE" if factual_refresh else "NONE"}}
