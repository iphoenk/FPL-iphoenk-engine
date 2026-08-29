from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _element(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("element")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _best_legal_xi_points(owned_rows: list[dict[str, Any]], actual: dict[int, dict[str, Any]]) -> float | None:
    by_pos: dict[str, list[float]] = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for row in owned_rows:
        if not isinstance(row, dict):
            continue
        element = _element(row)
        position = str(row.get("position") or "").upper()
        if element not in actual or position not in by_pos:
            continue
        by_pos[position].append(float(actual[element].get("points") or 0.0))
    if len(by_pos["GK"]) < 1:
        return None
    for values in by_pos.values():
        values.sort(reverse=True)
    best: float | None = None
    for defenders in range(3, 6):
        for mids in range(2, 6):
            forwards = 10 - defenders - mids
            if forwards < 1 or forwards > 3:
                continue
            if len(by_pos["DEF"]) < defenders or len(by_pos["MID"]) < mids or len(by_pos["FWD"]) < forwards:
                continue
            total = (
                by_pos["GK"][0]
                + sum(by_pos["DEF"][:defenders])
                + sum(by_pos["MID"][:mids])
                + sum(by_pos["FWD"][:forwards])
            )
            best = total if best is None else max(best, total)
    return best


def capture(
    context: dict[str, Any],
    decision: dict[str, Any],
    team: dict[str, Any],
    comparator: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    planning_gw = int(context.get("planning_gw") or 0)
    deadline = _dt(context.get("deadline_time"))
    base = previous if isinstance(previous, dict) and previous.get("contract") == "V5_DECISION_VALIDATION_SNAPSHOTS_V1" else {"schema_version":1,"contract":"V5_DECISION_VALIDATION_SNAPSHOTS_V1","owner":"evaluation.decision_validation","records":{}}
    records = dict(base.get("records") or {})
    if planning_gw <= 0 or deadline is None or current_time >= deadline or str(context.get("phase") or "") != "PRE_DEADLINE":
        return {**base,"records":records,"updated_at":current_time.isoformat(),"last_capture":{"status":"NO_PREDEADLINE_CAPTURE","planning_gw":planning_gw}}
    if str(planning_gw) in records:
        return {**base,"records":records,"updated_at":current_time.isoformat(),"last_capture":{"status":"ALREADY_FROZEN","planning_gw":planning_gw}}
    lineup = decision.get("lineup") if isinstance(decision.get("lineup"),dict) else {}
    starters = []
    for row in lineup.get("starters") or lineup.get("starting_xi") or []:
        element = _element(row)
        if element is not None:
            starters.append({"element":element,"position":row.get("position") if isinstance(row,dict) else None})
    owned = []
    for row in team.get("squad") or []:
        element = _element(row)
        if element is not None:
            owned.append({"element":element,"position":row.get("position") if isinstance(row,dict) else None})
    captain = _element(lineup.get("captain")); vice = _element(lineup.get("vice_captain"))
    comparisons=[]
    for row in comparator.get("top_comparisons") or []:
        if not isinstance(row,dict):
            continue
        player_out=row.get("player_out") or {}; player_in=row.get("player_in") or {}; out_id=_element(player_out); in_id=_element(player_in)
        if out_id is None or in_id is None:
            continue
        economics=row.get("transfer_economics") if isinstance(row.get("transfer_economics"),dict) else {}
        hit_cost=economics.get("exact_hit_cost")
        comparisons.append({"player_out":out_id,"player_in":in_id,"classification":row.get("classification"),"exact_hit_cost":hit_cost,"hit_cost_state":"AVAILABLE" if hit_cost is not None else "UNAVAILABLE_EXACT_HIT_COST"})
    records[str(planning_gw)]={"gw":planning_gw,"captured_at":current_time.isoformat(),"deadline_time":context.get("deadline_time"),"status":"PREDEADLINE_CAPTURED","decision_authority":team.get("authority") or team.get("squad_authority"),"lineup":{"starting_xi":starters,"owned_squad":owned,"captain":captain,"vice_captain":vice},"comparator":{"contract":comparator.get("contract"),"advisory_only":True,"comparisons":comparisons[:20]},"governance":{"genuine_predeadline_only":True,"postdeadline_overwrite_forbidden":True,"retroactive_reconstruction_forbidden":True,"exact_hit_cost_required_for_transfer_net_gain":True,"optimizer_change_penalty_is_not_hit_cost":True}}
    return {**base,"records":records,"updated_at":current_time.isoformat(),"last_capture":{"status":"PREDEADLINE_CAPTURED","planning_gw":planning_gw,"xi":len(starters),"owned":len(owned),"comparisons":len(comparisons[:20])}}


def decision_regret(snapshot: dict[str, Any] | None, actual: dict[int, dict[str, Any]]) -> dict[str, Any]:
    missing={"captain_regret":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"value":None},"xi_regret":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"value":None},"transfer_comparator_realized_net_gain":{"status":"NO_GENUINE_PREDEADLINE_SAMPLE","sample_size":0,"value":None}}
    if not isinstance(snapshot,dict):
        return missing
    lineup=snapshot.get("lineup") or {}; captain=_element(lineup.get("captain")); xi=[_element(r) for r in lineup.get("starting_xi") or []]; xi=[x for x in xi if x is not None]
    if captain in actual:
        chosen=float(actual[captain].get("points") or 0.0); pool=[_element(r) for r in lineup.get("owned_squad") or []]; candidates=[x for x in pool if x in actual]
        if candidates:
            best=max(float(actual[x].get("points") or 0.0) for x in candidates); missing["captain_regret"]={"status":"SETTLED","sample_size":1,"value":round(max(0.0,best-chosen),4),"chosen_actual_points":chosen,"best_owned_actual_points":best}
    if len(xi)==11 and all(x in actual for x in xi):
        selected=sum(float(actual[x].get("points") or 0.0) for x in xi)
        best_legal = _best_legal_xi_points([r for r in lineup.get("owned_squad") or [] if isinstance(r, dict)], actual)
        if best_legal is not None:
            missing["xi_regret"]={"status":"SETTLED","sample_size":1,"value":round(max(0.0,best_legal-selected),4),"selected_xi_actual_points":round(selected,4),"best_legal_owned_xi_actual_points":round(best_legal,4)}
        else:
            missing["xi_regret"]={"status":"PARTIAL_SELECTED_XI_ONLY","sample_size":0,"value":None,"selected_xi_actual_points":round(selected,4),"note":"owned positional settlement evidence incomplete"}
    gross_rows=[]; exact=[]
    for row in (snapshot.get("comparator") or {}).get("comparisons") or []:
        out_id=_element(row.get("player_out")); in_id=_element(row.get("player_in"))
        if out_id not in actual or in_id not in actual:
            continue
        gross=float(actual[in_id].get("points") or 0.0)-float(actual[out_id].get("points") or 0.0); hit=row.get("exact_hit_cost"); net=None if hit is None else gross-float(hit); gross_rows.append({"player_out":out_id,"player_in":in_id,"realized_gross_points_delta_1gw":round(gross,4),"exact_hit_cost":hit,"realized_net_gain_1gw":round(net,4) if net is not None else None})
        if net is not None:
            exact.append(net)
    if gross_rows:
        missing["transfer_comparator_realized_net_gain"]={"status":"SETTLED" if exact else "PARTIAL_GROSS_ONLY","sample_size":len(exact),"value":round(sum(exact)/len(exact),4) if exact else None,"gross_pair_count":len(gross_rows),"comparisons":gross_rows}
    return missing
