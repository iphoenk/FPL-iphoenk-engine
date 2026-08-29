from __future__ import annotations

from typing import Any, Callable

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_tactical_decision_consumption.json"
DECISION_CONFIG = "config/v5_decision_registry.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def policy() -> dict[str, Any]:
    return load_json_config(CONFIG)


def lineup_gap() -> float:
    return _f((policy().get("lineup") or {}).get("close_score_gap"), .35)


def watchlist_gap() -> float:
    return _f((policy().get("watchlist") or {}).get("close_dss_score_gap"), .05)


def tactical_key(player: dict[str, Any]) -> tuple[int, int, int]:
    cfg = policy()
    matchup = player.get("tactical_matchup") if isinstance(player.get("tactical_matchup"), dict) else {}
    if str(matchup.get("status") or "") != "READY":
        return (0, 0, 0)
    routes = {str(x) for x in matchup.get("player_return_routes") or [] if x}
    vulnerabilities = {str(x) for x in matchup.get("opponent_vulnerabilities") or [] if x}
    overlap = routes & vulnerabilities
    highlights = [x for x in matchup.get("highlights") or [] if x]
    rank = cfg.get("confidence_rank") or {}
    confidence = str(matchup.get("evidence_confidence") or "NONE").upper()
    if not overlap and not highlights:
        return (0, 0, 0)
    return (len(overlap), len(highlights), int(rank.get(confidence, 0)))


def close_group_sort(rows: list[Any], *, score: Callable[[Any], float], player: Callable[[Any], dict[str, Any]], gap: float) -> list[Any]:
    """Sort only within score-close groups using tactical evidence; base scores are immutable."""
    if len(rows) < 2:
        return list(rows)
    base = sorted(rows, key=score, reverse=True)
    out: list[Any] = []
    index = 0
    while index < len(base):
        anchor = score(base[index]); group = [base[index]]; index += 1
        while index < len(base) and anchor - score(base[index]) <= gap + 1e-9:
            group.append(base[index]); index += 1
        if any(tactical_key(player(item)) != (0, 0, 0) for item in group):
            group.sort(key=lambda item: (tactical_key(player(item)), score(item)), reverse=True)
        out.extend(group)
    return out


def compact_tactical(player: dict[str, Any]) -> dict[str, Any]:
    matchup = player.get("tactical_matchup") if isinstance(player.get("tactical_matchup"), dict) else {}
    return {
        "status": matchup.get("status") or "UNAVAILABLE",
        "opponent_team_id": matchup.get("opponent_team_id"),
        "player_role": matchup.get("player_role"),
        "player_return_routes": list(matchup.get("player_return_routes") or [])[:4],
        "opponent_vulnerabilities": list(matchup.get("opponent_vulnerabilities") or [])[:3],
        "opponent_strengths": list(matchup.get("opponent_strengths") or [])[:3],
        "route_vulnerability_overlap": sorted(set(matchup.get("player_return_routes") or []) & set(matchup.get("opponent_vulnerabilities") or []))[:3],
        "highlights": list(matchup.get("highlights") or [])[:2],
        "tactical_key": list(tactical_key(player)),
        "advisory_only": True,
    }


def _prediction_map(prediction: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in prediction.get("players") or [] if isinstance(row, dict) and row.get("element") is not None}


def _aggregate_key(ids: list[int], pmap: dict[int, dict[str, Any]]) -> tuple[int, int, int]:
    keys = [tactical_key(pmap.get(int(eid), {})) for eid in ids]
    return tuple(sum(key[i] for key in keys) for i in range(3))  # type: ignore[return-value]


def apply_lineup_overlay(lineup: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    """Resolve already-canonical close XI/C/VC/bench choices using tactical evidence.

    The overlay never changes projection values, never invents an XI outside canonical
    alternatives, and reuses lineup_optimizer.player_score for all rebuilt player scores.
    """
    if lineup.get("status") != "READY":
        return lineup
    from src.v5.decision.lineup_optimizer import player_score

    out = {**lineup}
    pmap = _prediction_map(prediction)
    gw = int(lineup.get("planning_gw") or prediction.get("planning_gw") or 1)
    alternatives = [row for row in lineup.get("alternatives") or [] if isinstance(row, dict)]
    base_ids = [int(row["element"]) for row in lineup.get("starters") or [] if isinstance(row, dict) and row.get("element") is not None]
    base_score = _f(lineup.get("selection_score"))
    close = [row for row in alternatives if base_score - _f(row.get("selection_score")) <= lineup_gap() + 1e-9]
    selected = None
    if close:
        ranked = sorted(close, key=lambda row: (_aggregate_key([int(x) for x in row.get("element_ids") or []], pmap), _f(row.get("selection_score"))), reverse=True)
        if ranked and _aggregate_key([int(x) for x in ranked[0].get("element_ids") or []], pmap) != (0, 0, 0):
            selected = ranked[0]
    selected_ids = [int(x) for x in selected.get("element_ids") or []] if selected else base_ids
    if len(selected_ids) != 11 or any(eid not in pmap for eid in selected_ids):
        selected_ids = base_ids; selected = None

    def view(eid: int, profile: str) -> dict[str, Any]:
        player = pmap[eid]; xmins = player.get("xmins") if isinstance(player.get("xmins"), dict) else {}
        return {"element":eid,"name":player.get("name"),"position":player.get("position"),"team_id":player.get("team_id"),"start_probability":round(_f(xmins.get("start_probability")),4),"dnp_probability":round(_f(xmins.get("dnp_probability"),max(0,1-_f(xmins.get("start_probability")))),4),"score":round(player_score(player,gw,profile),4),"tactical":compact_tactical(player)}

    xi_changed = set(selected_ids) != set(base_ids)
    if xi_changed and selected:
        out["starters"] = [view(eid,"player_score") for eid in selected_ids]
        out["formation"] = selected.get("formation")
        out["selection_score"] = selected.get("selection_score")
        out["expected_starting_xi_mean"] = selected.get("mean")

    selected_set = set(selected_ids)
    bench_ids = [eid for eid in pmap if eid not in selected_set]
    # Overlay is only valid for a complete 15-player owned projection universe.
    if len(bench_ids) == 4:
        bench_rows = [view(eid,"bench_score") for eid in bench_ids]
        gks = [row for row in bench_rows if row.get("position") == "GK"]
        outfield = [row for row in bench_rows if row.get("position") != "GK"]
        outfield = close_group_sort(outfield, score=lambda row:_f(row.get("score")), player=lambda row:pmap[int(row["element"])], gap=lineup_gap())
        out["bench"] = outfield + gks

    decision_cfg = load_json_config(DECISION_CONFIG)
    safety = ((decision_cfg.get("lineup") or {}).get("captain_safety") or {})
    min_start = _f(safety.get("minimum_start_probability"), .70); max_dnp = _f(safety.get("maximum_dnp_probability"), .15); pool_size = max(2,int(safety.get("safe_pool_size") or 5))
    captain_pool = [view(eid,"captain_score") for eid in selected_ids if _f((pmap[eid].get("xmins") or {}).get("start_probability")) >= min_start and _f((pmap[eid].get("xmins") or {}).get("dnp_probability")) <= max_dnp]
    if len(captain_pool) < 2:
        captain_pool = [view(eid,"captain_score") for eid in selected_ids]
    captain_pool = close_group_sort(captain_pool, score=lambda row:_f(row.get("score")), player=lambda row:pmap[int(row["element"])], gap=lineup_gap())[:pool_size]
    captain = captain_pool[0]; vice_candidates=[view(int(row["element"]),"vice_score") for row in captain_pool[1:]]; vice_candidates=close_group_sort(vice_candidates,score=lambda row:_f(row.get("score")),player=lambda row:pmap[int(row["element"])],gap=lineup_gap()); vice=vice_candidates[0]
    old_c = int((lineup.get("captain") or {}).get("element") or -1); old_v=int((lineup.get("vice_captain") or {}).get("element") or -1)
    out["captain"] = captain; out["vice_captain"] = vice; out["captain_safe_pool"] = captain_pool
    battle = dict(out.get("main_starting_xi_battle") or {}); battle["tactical_tiebreak"]={"eligible":battle.get("status")=="CLOSE" or bool(close),"applied_to_xi":xi_changed,"base_xi_key":list(_aggregate_key(base_ids,pmap)),"selected_xi_key":list(_aggregate_key(selected_ids,pmap)),"policy":"close-call tactical evidence only; canonical scores unchanged"}; out["main_starting_xi_battle"]=battle
    out.setdefault("governance",{}).update({"tactical_consumption_contract":"TACTICAL_DECISION_CONSUMPTION_V1","tactical_close_call_tiebreak_enabled":True,"tactical_direct_xpts_mutation":False,"tactical_xi_tiebreak_applied":xi_changed,"tactical_captain_tiebreak_applied":old_c!=int(captain["element"]),"tactical_vice_tiebreak_applied":old_v!=int(vice["element"])})
    return out
