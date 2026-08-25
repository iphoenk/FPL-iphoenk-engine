from __future__ import annotations
import json
from src.sources.official_fpl import get_json
from src.utils import DATA, atomic_json, iso_now
from src.engines.snapshot_meta import source_meta, age_minutes, snapshot_id, changes
from src.rules import build_chip_ledger, ruleset_metadata
from src.version import ENGINE_VERSION, SCHEMA_VERSION

TEAM_ID=3462711
ENTRY_FIELDS=["summary_overall_points","summary_overall_rank","summary_event_points","summary_event_rank","current_event","last_deadline_bank","last_deadline_value","last_deadline_total_transfers"]


def run_overlay():
    path=DATA/"latest.json"
    current=json.load(open(path))
    previous=current.copy()
    health=current.get("endpoint_health",{})
    phase=current.get("phase",{})
    submitted=phase.get("submitted_gw")

    entry,h=get_json(f"entry/{TEAM_ID}/"); health["entry"]=h
    history,hh=get_json(f"entry/{TEAM_ID}/history/"); health["history"]=hh
    transfers,ht=get_json(f"entry/{TEAM_ID}/transfers/"); health["transfers"]=ht
    picks=None; hp={}
    if submitted:
        picks,hp=get_json(f"entry/{TEAM_ID}/event/{submitted}/picks/"); health["picks"]=hp

    if not entry:
        raise RuntimeError("FAIL CLOSED: Official entry unavailable during reliability overlay")

    entry_summary={k:entry.get(k) for k in ENTRY_FIELDS}
    entry_summary["id"]=entry.get("id")
    entry_summary["fetched_at"]=h.get("fetched_at")
    used_chips=(history or {}).get("chips",[])
    chip_ledger=build_chip_ledger(used_chips, phase.get("planning_gw") or phase.get("current_gw"))
    ruleset=ruleset_metadata()

    native={
        "entry":entry_summary,
        "history":{"current":(history or {}).get("current",[]),"chips":used_chips,"past":(history or {}).get("past",[])},
        "transfers":transfers or [],
        "picks":{"gw":submitted,"payload":picks} if submitted else None,
    }
    provenance={k:source_meta(health,k) for k in ["bootstrap","fixtures","event_status","entry","history","transfers","picks"] if k in health}
    freshness={k:{"fetched_at":v.get("fetched_at"),"age_minutes":age_minutes(v.get("fetched_at")),"status":v.get("status")} for k,v in provenance.items()}

    old_entry=(previous.get("entry") or {})
    delta=changes(old_entry,entry_summary,ENTRY_FIELDS)
    current.update({
        "engine_version":ENGINE_VERSION,"schema_version":SCHEMA_VERSION,"generated_at":iso_now(),
        "endpoint_health":health,"entry":entry_summary,"native":native,"provenance":provenance,"source_freshness":freshness,
        "change_log":delta,"snapshot_id":snapshot_id(native),"ruleset":ruleset,"chip_ledger":chip_ledger,
    })
    atomic_json(path,current)
    atomic_json(DATA/"native.json",{"generated_at":current["generated_at"],"snapshot_id":current["snapshot_id"],**native})
    atomic_json(DATA/"chips.json",{"generated_at":current["generated_at"],"used":used_chips,"ledger":chip_ledger,"ruleset_id":ruleset["id"]})
    return current

if __name__ == "__main__": run_overlay()
