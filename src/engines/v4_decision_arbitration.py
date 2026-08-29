from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from src.engines.v4_freshness import evaluate_freshness
from src.utils import CONFIG, DATA, atomic_json, parse_dt, read_json, utcnow

POLICY = CONFIG / "serving_improvement_registry.json"
OUTFILE = DATA / "decision_arbitration_v4.json"
SEVERITY = {"HOLD": 0, "REVIEW": 1, "CHANGE": 2}


def _f(value: Any, default: float = 0.0) -> float:
    try: return float(value if value is not None else default)
    except (TypeError, ValueError): return float(default)


def _tactical_by_element(tactical: dict) -> dict[int, dict]:
    rows = [*(tactical.get("owned") or []), *(tactical.get("watchlist") or [])]
    return {int(row.get("element") or 0): row.get("tactical") or {} for row in rows if row.get("element") is not None}


def _prediction_map(predictions: dict | None) -> dict[int, dict]:
    return {int(row.get("element") or 0): row for row in (predictions or {}).get("players") or [] if row.get("element") is not None}


def _horizon_deltas(incoming: list[dict], outgoing: list[dict], predictions: dict | None) -> dict:
    pmap = _prediction_map(predictions)
    out = {}
    for horizon in (3, 5, 10, 15):
        key = f"xpts_{horizon}"
        inc = sum(_f((pmap.get(int(row.get("element") or 0)) or {}).get(key)) for row in incoming)
        dec = sum(_f((pmap.get(int(row.get("element") or 0)) or {}).get(key)) for row in outgoing)
        out[f"net_gain_{horizon}gw"] = round(inc-dec, 3) if pmap else None
    return out


def _price_action(prices: dict, owned_ids: set[int]) -> dict:
    confirmed = [row for row in prices.get("confirmed_changes") or [] if int(row.get("element") or 0) in owned_ids]
    return {"action":"REVIEW" if confirmed else "HOLD","reason":"CONFIRMED_OWNED_PRICE_MOVEMENT" if confirmed else "NO_ACTIONABLE_PRICE_TRIGGER","confirmed_owned_changes":confirmed,"price_signal_cannot_independently_trigger_change":True}


def _transfer_resolution(sanity: dict, latest: dict, team: dict, tactical: dict, freshness: dict, predictions: dict | None) -> dict:
    verdict=str(sanity.get("final_verdict") or "KEEP_15");package=sanity.get("recommended_package") or {};replacements=int(package.get("replacements") or 0);incoming=list(package.get("in") or []);outgoing=list(package.get("out") or []);confidence=_f(package.get("evidence_confidence"));planning_gw=int((latest.get("phase") or {}).get("planning_gw") or 0) or None;tactical_map=_tactical_by_element(tactical);blockers=[];horizons=_horizon_deltas(incoming,outgoing,predictions)
    if verdict=="MATERIAL_UPGRADE" and replacements:
        if not freshness.get("fresh_enough_for_execution"):blockers.append("OFFICIAL_FRESHNESS_NOT_EXECUTION_GRADE")
        if confidence<.78:blockers.append("EVIDENCE_CONFIDENCE_BELOW_ACTION_THRESHOLD")
        if team.get("free_transfers") is None:blockers.append("FREE_TRANSFER_OR_HIT_STATE_UNKNOWN")
        if horizons.get("net_gain_5gw") is not None and horizons["net_gain_5gw"]<=0:blockers.append("NON_POSITIVE_5GW_NET_GAIN")
        tactical_states=[str((tactical_map.get(int(row.get("element") or 0)) or {}).get("evidence_state") or "UNAVAILABLE") for row in [*incoming,*outgoing]]
        if not tactical_states or all(state in {"UNAVAILABLE","MODEL_ROLE_ONLY"} for state in tactical_states):blockers.append("TACTICAL_SYSTEM_FIT_NOT_VERIFIED")
        checkpoint=latest.get("checkpoint_context") or {}
        if not bool(checkpoint.get("is_final_review")) and not bool(checkpoint.get("deadline_day_active")):blockers.append("TIMING_NOT_FINAL_EXECUTION_WINDOW")
        common={"planning_gw":planning_gw,"replacements":replacements,"out":outgoing,"in":incoming,"expected_net_gain_3_5gw":package.get("sanity_gain_5"),"multi_horizon_projection":horizons,"affordability":package.get("affordability") or package.get("price_basis"),"start_security":(package.get("evidence") or {}).get("incoming"),"tactical_system_fit_states":tactical_states,"injury_rotation_congestion":"GOVERNED_BY_XMINS_AND_COMPETITIVE_LOAD_EVIDENCE","price_urgency":"REVIEW_SEPARATELY_NO_SINGLE_SIGNAL_EXECUTION","squad_structure":"PACKAGE_AUDIT_LEGALITY_REQUIRED","timing":"FINAL_REVIEW_OR_DEADLINE_DAY_REQUIRED","evidence_confidence":confidence}
        if blockers:return {"action":"REVIEW","candidate_state":"MATERIAL_UPGRADE_NON_ACTIONABLE","material_challenger_label":"NON_ACTIONABLE_MATERIAL_CHALLENGER","blocking_reasons":blockers,"execution_authorized":False,**common}
        return {"action":"CHANGE","candidate_state":"ACTIONABLE_CHANGE","material_challenger_label":"ACTIONABLE_MATERIAL_CHALLENGER","blocking_reasons":[],"execution_authorized":True,**common}
    if verdict=="OPTIONAL_IMPROVEMENT" and replacements:return {"action":"REVIEW","candidate_state":"REVIEW","material_challenger_label":None,"blocking_reasons":["OPTIONAL_GAIN_BELOW_MATERIAL_THRESHOLD"],"planning_gw":planning_gw,"replacements":replacements,"out":outgoing,"in":incoming,"expected_net_gain_3_5gw":package.get("sanity_gain_5"),"multi_horizon_projection":horizons,"evidence_confidence":confidence,"execution_authorized":False}
    return {"action":"HOLD","candidate_state":"WATCH","material_challenger_label":None,"blocking_reasons":[],"planning_gw":planning_gw,"replacements":replacements,"out":outgoing,"in":incoming,"expected_net_gain_3_5gw":package.get("sanity_gain_5"),"multi_horizon_projection":horizons,"evidence_confidence":confidence,"execution_authorized":False}


def _lineup_resolution(lineup: dict) -> dict:
    formation_state=str(lineup.get("formation_state") or "DECIDED");gk_state=str((lineup.get("gk_selection") or {}).get("status") or "DECIDED");bench_state=str((lineup.get("bench_governance") or {}).get("status") or "DECIDED");close=any(state=="OPEN" for state in (formation_state,gk_state,bench_state))
    return {"action":"REVIEW" if close else "HOLD","formation":lineup.get("formation"),"formation_state":formation_state,"gk_state":gk_state,"bench_state":bench_state,"reason":"CLOSE_LINEUP_BATTLE" if close else "NO_ACTIONABLE_XI_CHANGE_SIGNAL"}


def _captain_resolution(lineup: dict) -> dict:
    cap=lineup.get("captain") or {};vice=lineup.get("vice_captain") or {};state=str((lineup.get("captaincy_governance") or {}).get("status") or "DECIDED")
    return {"action":"REVIEW" if state=="OPEN" else "HOLD","captain":cap.get("name"),"vice_captain":vice.get("name"),"status":state,"reason":"CAPTAINCY_CLOSE_CALL" if state=="OPEN" else "CAPTAINCY_LEADER_CLEAR_ENOUGH","reason_decomposition":lineup.get("captaincy_governance") or {}}


def _chip_resolution(lineup: dict, latest: dict) -> dict:
    planning_chip=str((lineup.get("chip_context") or {}).get("active_chip") or "NONE").upper();submitted_chip=str((latest.get("chip_summary") or {}).get("submitted_chip") or "NONE").upper()
    return {"action":"HOLD","planning_chip":planning_chip,"submitted_historical_chip":submitted_chip,"historical_and_planning_separate":True,"reason":"NO_EXECUTABLE_CHIP_CHANGE_RECOMMENDED"}


def validate_resolution(resolution: dict) -> None:
    dimensions=resolution.get("dimensions") or {};overall=resolution.get("overall_action");actions=[str((dimensions.get(name) or {}).get("action") or "HOLD") for name in ("squad","transfer","xi","captaincy","chip","price")];expected=max(actions,key=lambda action:SEVERITY.get(action,-1))
    if overall!=expected:raise RuntimeError(f"canonical decision contradiction: overall={overall} dimensions={actions}")
    transfer=dimensions.get("transfer") or {}
    if transfer.get("candidate_state")=="MATERIAL_UPGRADE_NON_ACTIONABLE" and (transfer.get("material_challenger_label")!="NON_ACTIONABLE_MATERIAL_CHALLENGER" or not transfer.get("blocking_reasons") or transfer.get("action")=="CHANGE"):raise RuntimeError("non-actionable material challenger contract violated")
    if transfer.get("candidate_state")=="ACTIONABLE_CHANGE" and transfer.get("action")!="CHANGE":raise RuntimeError("ACTIONABLE_CHANGE must resolve to CHANGE")


def resolve_decision(sanity:dict,lineup:dict,latest:dict,team:dict,prices:dict,tactical:dict,predictions:dict|None=None,now:datetime|str|None=None)->dict:
    freshness=evaluate_freshness(latest,now=now);transfer=_transfer_resolution(sanity,latest,team,tactical,freshness,predictions);xi=_lineup_resolution(lineup);captaincy=_captain_resolution(lineup);chip=_chip_resolution(lineup,latest);owned_ids={int(row.get("element") or 0) for row in team.get("squad") or []};price=_price_action(prices,owned_ids);squad={"action":transfer["action"],"reason":"SQUAD_CHANGE_FOLLOWS_TRANSFER_ACTIONABILITY" if transfer["action"]!="HOLD" else "KEEP_CURRENT_STRUCTURE"};actions=[squad["action"],transfer["action"],xi["action"],captaincy["action"],chip["action"],price["action"]];overall=max(actions,key=lambda action:SEVERITY[action]);summary={"HOLD":"No actionable change now.","REVIEW":"Review required before any execution.","CHANGE":"Executable change is supported now."}[overall]
    fingerprint=json.dumps({"gw":(latest.get("phase") or {}).get("planning_gw"),"overall":overall,"transfer":transfer.get("candidate_state"),"formation":lineup.get("formation"),"captain":(lineup.get("captain") or {}).get("element"),"chip":chip.get("planning_chip"),"freshness":freshness.get("freshness_state")},sort_keys=True,separators=(",",":"));current=parse_dt(now) if isinstance(now,str) else now;current=current or utcnow()
    resolution={"schema_version":4962,"contract":"CANONICAL_DECISION_ARBITRATION_V1","generated_at":current.isoformat(),"resolution_id":hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],"overall_action":overall,"headline":f"{overall} | Squad {squad['action']} | XI {xi['action']} | C/VC {captaincy['action']} | Chip {chip['action']} | Price {price['action']}","summary":summary,"dimensions":{"squad":squad,"transfer":transfer,"xi":xi,"captaincy":captaincy,"chip":chip,"price":price},"freshness":freshness,"source_verdict":sanity.get("final_verdict"),"guardrails":{"material_upgrade_alone_never_implies_change":True,"single_canonical_resolution":True,"engine_is_advisory":True,"user_final_authority":True,"single_fixture_haul_or_price_move_cannot_independently_trigger_change":True}}
    validate_resolution(resolution);return resolution


def run()->dict:
    resolution=resolve_decision(read_json(DATA/"recommendation_sanity_v4.json",{}),read_json(DATA/"lineup_decision_v4.json",{}),read_json(DATA/"latest.json",{}),read_json(DATA/"team.json",{}),read_json(DATA/"prices.json",{}),read_json(DATA/"tactical_serving_v4.json",{}),read_json(DATA/"predictions_v4.json",{}));atomic_json(OUTFILE,resolution);return resolution
