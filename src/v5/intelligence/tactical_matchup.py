from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/tactical_matchup.json"


def _by_id(payload: Any, kind: str) -> dict[int, dict[str, Any]]:
    if not isinstance(payload, (dict, list)): return {}
    rows: Any = payload
    if isinstance(payload, dict): rows = payload.get(kind) or payload.get("profiles") or payload
    out: dict[int, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            if not isinstance(value, dict): continue
            try: out[int(key)] = value
            except (TypeError, ValueError): continue
    elif isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict): continue
            raw = row.get("team_id") if kind == "teams" else row.get("element"); raw = raw if raw is not None else row.get("id")
            try: out[int(raw)] = row
            except (TypeError, ValueError): continue
    return out


def _recent(payload: Any) -> dict[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict): return {}
    rows = payload.get("teams") or payload.get("recent") or payload
    if not isinstance(rows, dict): return {}
    out = {}
    for key, value in rows.items():
        try: team_id = int(key)
        except (TypeError, ValueError): continue
        if isinstance(value, list): games=value
        elif isinstance(value, dict): games=value.get("recent") or value.get("games") or value.get("gws") or []
        else: games=[]
        out[team_id] = [row for row in games if isinstance(row, dict)]
    return out


def _current_fixture(player: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    for row in player.get("xpts_by_gw") or []:
        if int(row.get("gw") or -1) != planning_gw: continue
        fixtures=[x for x in row.get("fixtures") or [] if isinstance(x,dict)]
        if fixtures:return fixtures[0]
    return {}


def _role_from_projection(player: dict[str, Any]) -> dict[str, Any]:
    role=player.get("role") if isinstance(player.get("role"),dict) else {}
    if not role:return {}
    return {"role":role.get("role") or role.get("tactical_role"),"position":player.get("position"),"set_piece_share":role.get("set_piece_share"),"penalty_share":role.get("penalty_share"),"return_routes":role.get("return_routes") or [],"progression_route":role.get("progression_route"),"source":role.get("set_piece_source") or "v5_role_intelligence","evidence_class":role.get("evidence_class")}


def _evidence_state(value: Any, *, partial: bool = False) -> str:
    available = value is not None and value != "" and value != [] and value != {}
    return ("PARTIAL" if partial else "AVAILABLE") if available else "UNAVAILABLE"


def _role_evidence_label(role: dict[str, Any]) -> str:
    evidence_class=str(role.get("evidence_class") or (role.get("evidence") or {}).get("class") or "")
    if role.get("role") and evidence_class in {"OBSERVED_ADVANCED_ROLE_PROFILE","OBSERVED_ROLE"}: return "OBSERVED_ROLE"
    if role.get("role"): return "INFERRED_ROLE"
    if role.get("position"): return "FPL_POSITION_ONLY"
    return "UNKNOWN"


def _system_formation_fit(own: dict[str, Any], role: dict[str, Any]) -> dict[str, Any]:
    role_label=_role_evidence_label(role); shape=own.get("base_formation")
    status="PARTIAL" if shape and role_label in {"OBSERVED_ROLE","INFERRED_ROLE"} else "UNAVAILABLE"
    missing=[]
    if not own.get("coach"): missing.append("coach_system")
    if not shape: missing.append("recent_xi_shape")
    missing.extend(["reliable_true_lineup_position","heatmap_position","role_change_history","competition_specific_role","structural_injury_role_effect"])
    return {"status":status,"role_evidence_label":role_label,"observed_or_inferred_role":role.get("role"),"fpl_position":role.get("position"),"fpl_position_shape_proxy":shape,"true_tactical_formation":None,"fit_score":None,"missing_inputs":missing,"governance":{"fpl_position_shape_is_not_true_tactical_formation":True,"no_fit_score_without_reliable_system_and_role_evidence":True,"missing_role_or_system_evidence_is_not_inferred":True,"advisory_only":True}}


def _dimension_matrix(opponent: dict[str, Any], recent_rows: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, str]:
    vulnerabilities=opponent.get("vulnerabilities") or []; strengths=opponent.get("strengths") or []; style=opponent.get("observed_style_proxies") or []
    venue=fixture.get("venue") if fixture.get("venue") is not None else fixture.get("home") if "home" in fixture else fixture.get("is_home")
    return {"opponent_coach":_evidence_state(opponent.get("coach")),"formation_or_variants":_evidence_state(opponent.get("base_formation") or opponent.get("formation_variants"),partial=True),"build_up":_evidence_state(opponent.get("build_up")),"press_height_intensity_triggers":_evidence_state(opponent.get("pressing")),"mid_low_block":"UNAVAILABLE","defensive_line":_evidence_state(opponent.get("defensive_line")),"wide_half_space_protection":_evidence_state(opponent.get("width")),"fullback_wingback_positioning":"UNAVAILABLE","transition_defense":_evidence_state(opponent.get("transition")),"counter_profile":_evidence_state("transition_threat" in style,partial=True) if style else "UNAVAILABLE","set_pieces":_evidence_state(opponent.get("set_piece_profile") or ("set_piece_activity" in style),partial=True) if (opponent.get("set_piece_profile") or style) else "UNAVAILABLE","aerial_profile":"UNAVAILABLE","central_wide_vulnerability":_evidence_state(vulnerabilities,partial=True),"box_protection":_evidence_state(("box_pressure" in vulnerabilities) or ("shot_volume" in vulnerabilities),partial=True) if vulnerabilities else "UNAVAILABLE","second_balls":"UNAVAILABLE","gk_distribution_shot_stopping":"UNAVAILABLE","expected_possession_game_state":"UNAVAILABLE","venue":_evidence_state(venue),"recent_tactical_adjustments_2_5":_evidence_state(recent_rows,partial=True),"structural_injuries_suspensions":"UNAVAILABLE","observed_strengths":_evidence_state(strengths,partial=True)}


def _edge_risk_label(opponent: dict[str, Any], role: dict[str, Any]) -> tuple[str,list[str],list[str]]:
    routes={str(x) for x in role.get("return_routes") or []}; vulnerabilities={str(x) for x in opponent.get("vulnerabilities") or []}; strengths={str(x) for x in opponent.get("strengths") or []}; edge=sorted(routes & vulnerabilities); risk=sorted(routes & strengths)
    label="MIXED" if edge and risk else "POSITIVE_EDGE" if edge else "TACTICAL_RISK" if risk else "NEUTRAL_OBSERVED" if routes and (vulnerabilities or strengths) else "INSUFFICIENT_EVIDENCE"
    return label,edge,risk


def _highlights(opponent: dict[str, Any], role: dict[str, Any], recent_rows: list[dict[str, Any]], limit: int) -> list[str]:
    result=[]; vulnerabilities=opponent.get("vulnerabilities") or []; routes=role.get("return_routes") or []
    if isinstance(vulnerabilities,str):vulnerabilities=[vulnerabilities]
    if isinstance(routes,str):routes=[routes]
    overlap=[str(route) for route in routes if any(str(route).lower() in str(v).lower() or str(v).lower() in str(route).lower() for v in vulnerabilities)]
    if overlap:result.append(f"role matchup mendukung: {', '.join(overlap[:2])}")
    if opponent.get("pressing") and role.get("progression_route"):result.append(f"lawan {opponent.get('pressing')}; route pemain {role.get('progression_route')}")
    if recent_rows:
        latest=sorted(recent_rows,key=lambda x:int(x.get("gw") or 0),reverse=True)[0]; note=latest.get("notes") or latest.get("chance_concession_zones") or latest.get("pressing_pattern")
        if note:result.append(f"recent-GW lawan: {note}")
    return result[:max(1,limit)]


def attach_tactical_matchups(predictions: dict[str, Any], planning_gw: int, tactical_context: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg=load_json_config(CONFIG); context=tactical_context if isinstance(tactical_context,dict) else {}; teams=_by_id(context.get("team_profiles"),"teams"); explicit_roles=_by_id(context.get("player_roles"),"players"); recent=_recent(context.get("recent_form")); minimum=int((cfg.get("materiality") or {}).get("minimum_evidence_items") or 2); window=int(cfg.get("recent_gw_window") or 5); limit=int((cfg.get("materiality") or {}).get("maximum_report_highlights_per_player") or 2); ready=partial=unavailable=0; role_labels=Counter(); generated_at=datetime.now(timezone.utc).isoformat()
    for player in predictions.get("players") or []:
        try: element=int(player.get("element") or -1); team_id=int(player.get("team_id") or -1)
        except (TypeError,ValueError): continue
        fixture=_current_fixture(player,planning_gw)
        try: opponent_id=int(fixture.get("opponent") or -1)
        except (TypeError,ValueError): opponent_id=-1
        own=teams.get(team_id) or {}; opponent=teams.get(opponent_id) or {}; role=explicit_roles.get(element) or _role_from_projection(player); role.setdefault("position",player.get("position")); recent_rows=sorted(recent.get(opponent_id) or [],key=lambda x:int(x.get("gw") or 0),reverse=True)[:window]; tactical_evidence=sum(bool(x) for x in (own,opponent,recent_rows)); evidence_count=tactical_evidence+int(bool(role))
        if opponent_id>0 and tactical_evidence>=minimum:status="READY";ready+=1
        elif opponent_id>0 and evidence_count:status="PARTIAL";partial+=1
        else:status="UNAVAILABLE";unavailable+=1
        role_label=_role_evidence_label(role); role_labels[role_label]+=1; tactical_label,edge,risk=_edge_risk_label(opponent,role); dimensions=_dimension_matrix(opponent,recent_rows,fixture)
        player["tactical_matchup"]={"status":status,"tactical_matchup_label":tactical_label,"tactical_edge":edge,"tactical_risk":risk,"planning_gw":planning_gw,"opponent_team_id":opponent_id if opponent_id>0 else None,"coach":own.get("coach"),"own_shape":own.get("base_formation"),"opponent_coach":opponent.get("coach"),"opponent_shape":opponent.get("base_formation"),"opponent_shape_evidence":opponent.get("evidence_class"),"player_role":role.get("role"),"player_role_evidence_label":role_label,"player_return_routes":list(role.get("return_routes") or []),"player_progression_route":role.get("progression_route"),"opponent_strengths":list(opponent.get("strengths") or []),"opponent_vulnerabilities":list(opponent.get("vulnerabilities") or []),"opponent_observed_style_proxies":list(opponent.get("observed_style_proxies") or []),"system_formation_fit":_system_formation_fit(own,role),"evidence_dimensions":dimensions,"evidence_dimension_counts":dict(Counter(dimensions.values())),"evidence_confidence":opponent.get("confidence") or (recent_rows[0].get("confidence") if recent_rows else None),"evidence_timestamp":generated_at,"evidence_count":evidence_count,"recent_gw_evidence_count":len(recent_rows),"highlights":_highlights(opponent,role,recent_rows,limit) if tactical_evidence else [],"advisory_only":True,"xpts_mutated":False,"xmins_mutated":False}
    predictions["tactical_matchup_summary"]={"model":cfg.get("model_id"),"planning_gw":planning_gw,"generated_at":generated_at,"ready":ready,"partial":partial,"unavailable":unavailable,"role_evidence_labels":dict(role_labels),"context_supplied":bool(context),"advisory_only":True,"xpts_mutation":False,"xmins_mutation":False,"deep_tactical_dimensions_explicit":True,"system_formation_fit_truthful":True}
    predictions.setdefault("governance",{})["tactical_matchup"]={"background_analysis_required_for_owned_and_watchlist":True,"report_only_material_highlights":True,"never_directly_mutate_xpts":True,"never_directly_mutate_xmins":True,"allow_selection_tiebreaker_only_when_gap_is_close":True,"missing_evidence_is_never_fabricated":True,"fpl_position_shape_is_not_true_tactical_formation":True}
    return predictions
