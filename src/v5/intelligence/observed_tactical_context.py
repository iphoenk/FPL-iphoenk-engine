from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_observed_tactical_context.json"


def _cfg() -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    if cfg.get("contract") != "TACTICAL_OBSERVED_CONTEXT_V1":
        raise RuntimeError("unexpected V5 observed tactical context contract")
    return cfg


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(float(default if value in (None, "") else value))
    except (TypeError, ValueError):
        return int(default)


def _b(value: Any) -> bool:
    return value if isinstance(value, bool) else str(value).strip().lower() in {"true", "1", "yes"}


def percentile(value: float, universe: list[float]) -> float:
    values = sorted(float(x) for x in universe)
    if not values:
        return 0.0
    less = sum(1 for x in values if x < value)
    equal = sum(1 for x in values if x == value)
    return round((less + 0.5 * equal) / len(values), 4)


def _confidence(matches: int, cfg: dict[str, Any]) -> str:
    mapping = (cfg.get("classification") or {}).get("confidence_by_matches") or {}
    label = "NONE"
    for minimum, candidate in sorted((int(k), str(v)) for k, v in mapping.items()):
        if matches >= minimum:
            label = candidate
    return label


def _shot_zone(row: dict[str, Any], cfg: dict[str, Any]) -> str | None:
    if row.get("start_x") in (None, "") or row.get("start_y") in (None, ""):
        return None
    x, y = _f(row.get("start_x")), _f(row.get("start_y"))
    z = cfg.get("shot_zones") or {}
    lateral = "central" if _f(z.get("central_y_min"), 35) <= y <= _f(z.get("central_y_max"), 65) else ("left" if y < _f(z.get("central_y_min"), 35) else "right")
    if x <= _f(z.get("close_distance_max"), 12):
        return f"close_{lateral}"
    if x <= _f(z.get("box_distance_max"), 18):
        return f"box_{lateral}"
    return "long_range"


def _player_team(elements: list[dict[str, Any]]) -> dict[int, int]:
    return {_i(p.get("id")): _i(p.get("team")) for p in elements if _i(p.get("id")) > 0 and _i(p.get("team")) > 0}


def build_current_rows(
    elements: list[dict[str, Any]],
    match_payload: dict[str, Any],
    shots_payload: dict[str, Any],
    team_system_context: dict[str, Any] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    cfg = _cfg()
    match_rows = [r for r in match_payload.get("rows") or [] if isinstance(r, dict)]
    shot_rows = [r for r in shots_payload.get("rows") or [] if isinstance(r, dict)]
    gw = _i(match_payload.get("gw"), 0)
    if gw <= 0 or not match_rows:
        return {}
    pteam = _player_team(elements)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    match_teams: dict[str, set[int]] = defaultdict(set)
    for row in match_rows:
        mid = str(row.get("match_id") or "").strip(); tid = pteam.get(_i(row.get("player_id")))
        if mid and tid:
            grouped[(mid, tid)].append(row); match_teams[mid].add(tid)
    homeaway: dict[str, dict[bool, int]] = defaultdict(dict)
    for row in shot_rows:
        mid = str(row.get("match_id") or "").strip(); tid = pteam.get(_i(row.get("player_id")))
        if mid and tid:
            homeaway[mid][_b(row.get("is_home"))] = tid
    shots_by: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in shot_rows:
        mid = str(row.get("match_id") or "").strip(); tid = pteam.get(_i(row.get("player_id")))
        if not tid:
            tid = (homeaway.get(mid) or {}).get(_b(row.get("is_home")))
        if mid and tid:
            shots_by[(mid, tid)].append(row)
    fields = {"xg":"xg","xa":"xa","shots":"total_shots","shots_on_target":"shots_on_target","box_touches":"touches_opposition_box","chances_created":"chances_created","final_third_passes":"final_third_passes","accurate_crosses":"accurate_crosses","corners":"corners","recoveries":"recoveries","tackles":"tackles","interceptions":"interceptions"}
    agg: dict[tuple[str, int], dict[str, Any]] = {}
    for key, rows in grouped.items():
        mid, tid = key; metrics = {n: round(sum(_f(r.get(f)) for r in rows),4) for n,f in fields.items()}
        metrics["defensive_activity"] = round(metrics["recoveries"]+metrics["tackles"]+metrics["interceptions"],4)
        team_shots = shots_by.get(key) or []
        situations = Counter(str(r.get("situation") or "").strip().lower() for r in team_shots if r.get("situation"))
        metrics["fast_break_shots"] = situations.get("fast-break",0)
        metrics["set_piece_shots"] = sum(situations.get(x,0) for x in ("corner","free-kick","penalty"))
        teams = match_teams.get(mid) or set(); opp = next(iter(teams-{tid}),None) if len(teams)==2 else None
        home = True if (homeaway.get(mid) or {}).get(True)==tid else (False if (homeaway.get(mid) or {}).get(False)==tid else None)
        agg[key] = {"match_id":mid,"team_id":tid,"opponent_team_id":opp,"home":home,"metrics":metrics,"shot_zones":dict(Counter(filter(None,(_shot_zone(r,cfg) for r in team_shots))))}
    metric_map = {"box_pressure":"box_touches","shot_volume":"shots","chance_creation":"chances_created","final_third_progression":"final_third_passes","wide_delivery":"accurate_crosses","set_piece_activity":"set_piece_shots","transition_threat":"fast_break_shots","defensive_activity_proxy":"defensive_activity"}
    universes = {m:[_f(r["metrics"].get(m)) for r in agg.values()] for m in set(metric_map.values())}
    high = _f((cfg.get("classification") or {}).get("high_percentile"),.75); maximum = int((cfg.get("classification") or {}).get("maximum_team_signals") or 3)
    systems = team_system_context or {}; shape: dict[tuple[str,int],str|None] = {}
    for tk, block in systems.items():
        tid=_i(tk)
        for r in (block or {}).get("matches") or []:
            if r.get("match_id"): shape[(str(r["match_id"]),tid)] = r.get("fpl_position_shape") if r.get("valid") else None
    out: dict[int,list[dict[str,Any]]] = defaultdict(list)
    for key,row in agg.items():
        ranked=[]
        for sig,metric in metric_map.items():
            value=_f(row["metrics"].get(metric)); ranked.append((sig,percentile(value,universes.get(metric) or []),value))
        ranked.sort(key=lambda x:x[1],reverse=True)
        strengths=[s for s,p,v in ranked if s!="defensive_activity_proxy" and p>=high and v>0][:maximum]
        opp = agg.get((row["match_id"],int(row["opponent_team_id"]))) if row.get("opponent_team_id") else None
        vulnerabilities=[]
        if opp:
            concessions=[]
            for sig,metric in metric_map.items():
                if sig=="defensive_activity_proxy": continue
                value=_f(opp["metrics"].get(metric)); concessions.append((sig,percentile(value,universes.get(metric) or []),value))
            vulnerabilities=[s for s,p,v in sorted(concessions,key=lambda x:x[1],reverse=True) if p>=high and v>0][:maximum]
        zones=lambda d:[z for z,c in sorted(((str(z),_f(c)) for z,c in d.items()),key=lambda x:x[1],reverse=True)[:2] if c>0]
        out[row["team_id"]].append({"gw":gw,"match_id":row["match_id"],"opponent_team_id":row.get("opponent_team_id"),"home":row.get("home"),"formation":shape.get((row["match_id"],row["team_id"])),"possession_pattern":None,"pressing_pattern":None,"chance_creation_zones":zones(row.get("shot_zones") or {}),"chance_concession_zones":zones((opp or {}).get("shot_zones") or {}),"role_changes":[],"strengths":strengths,"vulnerabilities":vulnerabilities,"observed_style_proxies":[{"signal":s,"percentile":p,"observed_value":v} for s,p,v in ranked if v>0][:maximum],"observed_metrics":row["metrics"],"confidence":"LOW","evidence":{"class":"OBSERVED_MATCH_EVENT_AGGREGATE","source":match_payload.get("source") or cfg.get("source"),"dataset":match_payload.get("dataset"),"fetched_at":match_payload.get("fetched_at"),"true_pressing_not_inferred":True,"true_possession_not_inferred":True}})
    return dict(out)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg=_cfg(); valid=[r for r in rows if isinstance(r,dict)]; maximum=int((cfg.get("classification") or {}).get("maximum_team_signals") or 3)
    strengths=Counter(s for r in valid for s in r.get("strengths") or []); vulnerabilities=Counter(s for r in valid for s in r.get("vulnerabilities") or []); shapes=Counter(str(r.get("formation")) for r in valid if r.get("formation")); style=Counter(str(x.get("signal")) for r in valid for x in r.get("observed_style_proxies") or [] if isinstance(x,dict) and x.get("signal"))
    return {"matches":len(valid),"confidence":_confidence(len(valid),cfg),"dominant_shape":shapes.most_common(1)[0][0] if shapes else None,"formation_variants":[s for s,_ in shapes.most_common()],"strengths":[s for s,_ in strengths.most_common(maximum)],"vulnerabilities":[s for s,_ in vulnerabilities.most_common(maximum)],"observed_style_proxies":[s for s,_ in style.most_common(maximum)]}


def player_return_routes(player_metrics: dict[str, Any]) -> dict[str, Any]:
    routes=[]; zones=[]
    if _f(player_metrics.get("box_touches",player_metrics.get("touches_opposition_box")))>0: routes.append("box_pressure"); zones.append("box_involvement")
    if _f(player_metrics.get("shots",player_metrics.get("total_shots")))>0 or _f(player_metrics.get("xg"))>0: routes.append("shot_volume")
    if _f(player_metrics.get("chances_created"))>0 or _f(player_metrics.get("xa"))>0: routes.append("chance_creation"); zones.append("chance_creation")
    if _f(player_metrics.get("corners"))>0: routes.append("set_piece_activity")
    if _f(player_metrics.get("penalties_scored"))+_f(player_metrics.get("penalties_missed"))>0: routes.append("penalty_route")
    routes=list(dict.fromkeys(routes)); priority=["box_pressure","shot_volume","chance_creation","set_piece_activity","penalty_route"]
    return {"zones":list(dict.fromkeys(zones)),"set_pieces":"CORNERS_OBSERVED" if "set_piece_activity" in routes else None,"penalties":"PENALTY_EVENT_OBSERVED" if "penalty_route" in routes else None,"progression_route":next((r for r in priority if r in routes),None),"return_routes":routes}


def build_context(elements: list[dict[str, Any]], match_payload: dict[str, Any], shots_payload: dict[str, Any], team_system_context: dict[str, Any] | None = None) -> dict[str, Any]:
    rows=build_current_rows(elements,match_payload,shots_payload,team_system_context)
    return {"schema_version":1,"model":_cfg().get("model_id"),"contract":_cfg().get("contract"),"status":"ACTIVE" if rows else "UNAVAILABLE","teams":{str(t):{"recent":r,"summary":summarize(r)} for t,r in rows.items()},"governance":_cfg().get("policy") or {}}
