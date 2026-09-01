from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from src.engines.p1_decision_governance import bench_battles
from src.utils import DATA, ROOT, atomic_json, read_json

CONSUMPTION_CONFIG = ROOT / "config" / "intelligence" / "tactical_decision_consumption.json"
LINEUP_CONFIG = ROOT / "config" / "intelligence" / "lineup_governance.json"
TACTICAL_CONFIG = ROOT / "config" / "intelligence" / "tactical_matchup.json"
CONFIDENCE_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    payload = json.loads(CONSUMPTION_CONFIG.read_text(encoding="utf-8"))
    if payload.get("contract") != "TACTICAL_DECISION_CONSUMPTION_V1":
        raise RuntimeError("unexpected tactical decision consumption contract")
    return payload


@lru_cache(maxsize=1)
def _lineup_config() -> dict[str, Any]:
    return json.loads(LINEUP_CONFIG.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _tactical_config() -> dict[str, Any]:
    return json.loads(TACTICAL_CONFIG.read_text(encoding="utf-8"))


def _projection_map(projections: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["element"]): row
        for row in projections.get("players") or []
        if row.get("element") is not None
    }


def _matchup(projection: dict[str, Any] | None) -> dict[str, Any]:
    row = (projection or {}).get("tactical_matchup") or {}
    return row if isinstance(row, dict) else {}


def _route_overlap(matchup: dict[str, Any]) -> list[str]:
    routes = {str(x) for x in matchup.get("player_return_routes") or [] if x}
    vulnerabilities = {str(x) for x in matchup.get("opponent_vulnerabilities") or [] if x}
    return sorted(routes & vulnerabilities)


def tactical_key(projection: dict[str, Any] | None) -> tuple[int, int, int]:
    """Lexicographic close-call key. Never alters xPts or base model scores."""
    matchup = _matchup(projection)
    if str(matchup.get("status") or "") != "READY":
        return (0, 0, 0)
    overlap = _route_overlap(matchup)
    highlights = [str(x) for x in matchup.get("highlights") or [] if x]
    if not overlap and not highlights:
        return (0, 0, 0)
    confidence = str(matchup.get("evidence_confidence") or "NONE").upper()
    return (len(overlap), len(highlights), CONFIDENCE_RANK.get(confidence, 0))


def compact_tactical(projection: dict[str, Any] | None) -> dict[str, Any]:
    matchup = _matchup(projection)
    status = str(matchup.get("status") or "UNAVAILABLE")
    state = {"READY": "CUKUP", "PARTIAL": "TERBATAS", "UNAVAILABLE": "TIDAK_TERSEDIA"}.get(status, "TERBATAS")
    return {
        "evidence_state": state,
        "opponent_team_id": matchup.get("opponent_team_id"),
        "player_role": matchup.get("player_role"),
        "player_return_routes": list(matchup.get("player_return_routes") or [])[:4],
        "opponent_observed_style": list(matchup.get("opponent_observed_style_proxies") or [])[:3],
        "opponent_strengths": list(matchup.get("opponent_strengths") or [])[:3],
        "opponent_vulnerabilities": list(matchup.get("opponent_vulnerabilities") or [])[:3],
        "route_vulnerability_overlap": _route_overlap(matchup)[:3],
        "highlights": [str(x) for x in matchup.get("highlights") or [] if x][:2],
        "verified_coach": matchup.get("opponent_coach"),
        "verified_shape": matchup.get("opponent_shape"),
        "shape_evidence": matchup.get("opponent_shape_evidence"),
    }


def _aggregate_key(element_ids: list[int], pmap: dict[int, dict[str, Any]]) -> tuple[int, int, int]:
    keys = [tactical_key(pmap.get(int(element))) for element in element_ids]
    return tuple(sum(key[index] for key in keys) for index in range(3))  # type: ignore[return-value]


def _close_group_sort(
    rows: list[dict[str, Any]],
    *,
    score_field: str,
    gap: float,
    pmap: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return list(rows)
    base = sorted(rows, key=lambda row: _f(row.get(score_field)), reverse=True)
    out: list[dict[str, Any]] = []
    index = 0
    while index < len(base):
        anchor = _f(base[index].get(score_field))
        group = [base[index]]
        index += 1
        while index < len(base) and anchor - _f(base[index].get(score_field)) <= gap + 1e-9:
            group.append(base[index])
            index += 1
        if any(tactical_key(pmap.get(int(row.get("element") or -1))) != (0, 0, 0) for row in group):
            group.sort(
                key=lambda row: (
                    tactical_key(pmap.get(int(row.get("element") or -1))),
                    _f(row.get(score_field)),
                ),
                reverse=True,
            )
        out.extend(group)
    return out


def _sync_formation_comparison(
    lineup: dict[str, Any],
    alternatives: list[dict[str, Any]],
    selected_ids: list[int],
) -> None:
    raw_rows = list(lineup.get("formation_comparison") or [])
    if not raw_rows:
        return
    selected_set = set(selected_ids)
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        row = dict(raw)
        alternative = alternatives[index] if index < len(alternatives) else {}
        alternative_ids = {int(value) for value in alternative.get("element_ids") or []}
        row["selected"] = bool(alternative_ids) and alternative_ids == selected_set
        rows.append(row)
    selected_rows = [row for row in rows if row.get("selected") is True]
    if len(selected_rows) != 1:
        raise RuntimeError(
            "tactical lineup overlay could not reconcile formation comparison with final XI: "
            f"selected_rows={len(selected_rows)}"
        )
    if selected_rows[0].get("formation") != lineup.get("formation"):
        raise RuntimeError("tactical lineup overlay formation comparison disagrees with final formation")
    lineup["formation_comparison"] = rows


def apply_lineup_overlay(
    lineup: dict[str, Any] | None = None,
    projections: dict[str, Any] | None = None,
    *,
    persist: bool = True,
) -> dict[str, Any]:
    lineup = dict(lineup or read_json(DATA / "lineup_decision.json", {}))
    projections = projections or read_json(DATA / "projections.json", {})
    if not lineup or not projections:
        raise RuntimeError("tactical lineup overlay requires lineup_decision and projections")
    pmap = _projection_map(projections)
    alternatives = list(lineup.get("alternatives") or [])
    squad_rows = [dict(row) for row in lineup.get("squad_rows") or []]
    squad_map = {int(row["element"]): row for row in squad_rows if row.get("element") is not None}
    base_selected_ids = [int(row.get("element")) for row in lineup.get("starting_xi") or [] if row.get("element") is not None]
    base_score = _f((lineup.get("lineup_score") or {}).get("robust"))
    selection_gap = _f((_lineup_config().get("battle") or {}).get("close_margin_threshold"))
    close_candidates = [
        row for row in alternatives
        if base_score - _f(row.get("score")) <= selection_gap + 1e-9
    ]
    selected_alt = None
    if close_candidates:
        ranked = sorted(
            close_candidates,
            key=lambda row: (
                _aggregate_key([int(x) for x in row.get("element_ids") or []], pmap),
                _f(row.get("score")),
            ),
            reverse=True,
        )
        if ranked and _aggregate_key([int(x) for x in ranked[0].get("element_ids") or []], pmap) != (0, 0, 0):
            selected_alt = ranked[0]

    selected_ids = base_selected_ids
    xi_changed = False
    if selected_alt:
        candidate_ids = [int(x) for x in selected_alt.get("element_ids") or []]
        if len(candidate_ids) == 11 and all(element in squad_map for element in candidate_ids):
            selected_ids = candidate_ids
            xi_changed = set(selected_ids) != set(base_selected_ids)

    starters = [dict(squad_map[element]) for element in selected_ids if element in squad_map]
    starters.sort(key=lambda row: ({"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}.get(str(row.get("position")), 9), -_f(row.get("selection_score"))))
    if len(starters) != 11:
        raise RuntimeError("tactical lineup overlay must preserve 11 starters")

    if xi_changed and selected_alt:
        lineup["starting_xi"] = starters
        lineup["formation"] = selected_alt.get("formation")
        lineup["lineup_score"] = {
            "robust": selected_alt.get("decision_score", selected_alt.get("score")),
            "base_robust": selected_alt.get("base_score"),
            "xpts_mean": selected_alt.get("xpts_mean"),
            "xpts_std": selected_alt.get("xpts_std"),
            "risk_adjustment": selected_alt.get("risk_adjustment"),
        }

    _sync_formation_comparison(lineup, alternatives, selected_ids)

    starter_ids = {int(row["element"]) for row in starters}
    bench_rows = [dict(row) for row in squad_rows if int(row.get("element") or -1) not in starter_ids]
    bench_gk = next((row for row in bench_rows if row.get("position") == "GK"), None)
    outfield = [row for row in bench_rows if row.get("position") != "GK"]
    close_gap = _f((_tactical_config().get("materiality") or {}).get("close_xpts_gap"), 0.35)
    outfield = _close_group_sort(outfield, score_field="bench_score", gap=close_gap, pmap=pmap)
    if bench_gk is None or len(outfield) != 3:
        raise RuntimeError("tactical lineup overlay must preserve legal bench structure")
    lineup["bench"] = {
        "gk": {
            "element": bench_gk.get("element"),
            "name": bench_gk.get("name"),
            "position": bench_gk.get("position"),
            "bench_score": bench_gk.get("bench_score"),
        },
        "order": [
            {
                "element": row.get("element"),
                "name": row.get("name"),
                "position": row.get("position"),
                "bench_score": row.get("bench_score"),
                "lower80": row.get("lower80"),
                "upper80": row.get("upper80"),
            }
            for row in outfield
        ],
        "close_battles": bench_battles(outfield, _lineup_config()),
    }

    captain_cfg = _lineup_config().get("captaincy") or {}
    eligible = [
        row for row in starters
        if _f(row.get("start_probability")) >= _f(captain_cfg.get("minimum_start_probability"), 0.70)
        and _f(row.get("dnp_probability")) <= _f(captain_cfg.get("maximum_dnp_probability"), 0.15)
    ]
    if len(eligible) < 2:
        eligible = list(starters)
    eligible = _close_group_sort(eligible, score_field="captain_score", gap=close_gap, pmap=pmap)
    safe_size = max(2, int(captain_cfg.get("safe_pool_size") or 5))
    safe_pool = eligible[:safe_size]
    captain = safe_pool[0]
    vice = next(row for row in safe_pool[1:] if int(row.get("element")) != int(captain.get("element")))
    old_captain = int((lineup.get("captain") or {}).get("element") or -1)
    old_vice = int((lineup.get("vice_captain") or {}).get("element") or -1)
    lineup["captain"] = {
        "element": captain.get("element"),
        "name": captain.get("name"),
        "captain_score": captain.get("captain_score"),
        "dnp_probability": captain.get("dnp_probability"),
        "lower80": captain.get("lower80"),
        "upper80": captain.get("upper80"),
        "score_decomposition": captain.get("score_decomposition"),
    }
    lineup["vice_captain"] = {
        "element": vice.get("element"),
        "name": vice.get("name"),
        "captain_score": vice.get("captain_score"),
        "vice_score": vice.get("vice_score"),
        "dnp_probability": vice.get("dnp_probability"),
        "attack_ceiling_proxy": vice.get("attack_ceiling_proxy"),
        "focality_proxy": vice.get("focality_proxy"),
        "score_decomposition": vice.get("score_decomposition"),
    }
    lineup["captain_safe_pool"] = [
        {
            "element": row.get("element"),
            "name": row.get("name"),
            "captain_score": row.get("captain_score"),
            "vice_score": row.get("vice_score"),
            "start_probability": row.get("start_probability"),
            "dnp_probability": row.get("dnp_probability"),
            "attack_ceiling_proxy": row.get("attack_ceiling_proxy"),
            "focality_proxy": row.get("focality_proxy"),
        }
        for row in safe_pool
    ]

    battle = dict(lineup.get("main_starting_xi_battle") or {})
    battle["tactical_tiebreak"] = {
        "eligible": battle.get("status") == "CLOSE",
        "applied_to_xi": xi_changed,
        "base_xi_key": list(_aggregate_key(base_selected_ids, pmap)),
        "selected_xi_key": list(_aggregate_key(selected_ids, pmap)),
        "selected_formation": lineup.get("formation"),
        "policy": "tactical evidence resolves close calls only; xPts unchanged",
    }
    lineup["main_starting_xi_battle"] = battle
    lineup.setdefault("governance", {}).update({
        "tactical_close_call_tiebreak_enabled": True,
        "tactical_direct_xpts_mutation": False,
        "tactical_xi_tiebreak_applied": xi_changed,
        "tactical_captain_tiebreak_applied": old_captain != int(captain.get("element") or -1),
        "tactical_vice_tiebreak_applied": old_vice != int(vice.get("element") or -1),
        "tactical_consumption_contract": "TACTICAL_DECISION_CONSUMPTION_V1",
        "tactical_overlay_preserves_decision_transparency": True,
        "formation_comparison_reconciled_to_final_xi": bool(lineup.get("formation_comparison")),
    })
    if persist:
        atomic_json(DATA / "lineup_decision.json", lineup)
    return lineup


def apply_watchlist_overlay(
    payload: dict[str, Any] | None = None,
    projections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(payload or read_json(DATA / "dss_watchlist.json", {}))
    projections = projections or read_json(DATA / "projections.json", {})
    pmap = _projection_map(projections)
    gap = _f((load_config().get("watchlist") or {}).get("close_dss_score_gap"), 1.0)
    positions: dict[str, list[dict[str, Any]]] = {}
    reranked = 0
    for position, raw_rows in (payload.get("positions") or {}).items():
        rows = [dict(row) for row in raw_rows or []]
        before = [int(row.get("element") or -1) for row in rows]
        rows = _close_group_sort(rows, score_field="dss_score", gap=gap, pmap=pmap)
        after = [int(row.get("element") or -1) for row in rows]
        if before != after:
            reranked += 1
        for rank, row in enumerate(rows, start=1):
            element = int(row.get("element") or -1)
            projection = pmap.get(element)
            tactical = compact_tactical(projection)
            row["rank"] = rank
            row["tactical_matchup"] = tactical
            material = list(tactical.get("highlights") or [])
            if material:
                existing = [str(x) for x in row.get("reasons") or []]
                row["reasons"] = (existing + ["matchup lawan: " + material[0]])[:3]
        positions[str(position)] = rows
    payload["positions"] = positions
    payload.setdefault("governance", {}).update({
        "tactical_tiebreak_close_dss_only": True,
        "tactical_membership_promotion_forbidden": True,
        "tactical_reranked_position_count": reranked,
        "tactical_consumption_contract": "TACTICAL_DECISION_CONSUMPTION_V1",
    })
    return payload


def _find_projection(row: dict[str, Any], pmap: dict[int, dict[str, Any]], by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if row.get("element") is not None:
        found = pmap.get(int(row.get("element") or -1))
        if found:
            return found
    name = str(row.get("name") or "").casefold()
    return by_name.get(name) if name else None


def decorate_report_payload(
    payload: dict[str, Any],
    projections: dict[str, Any],
    lineup: dict[str, Any],
) -> dict[str, Any]:
    pmap = _projection_map(projections)
    by_name = {str(row.get("name") or "").casefold(): row for row in pmap.values() if row.get("name")}

    owned_rows = ((payload.get("owned_squad") or {}).get("facts") or []) if "owned_squad" in payload else (payload.get("owned_15") or [])
    owned_decorated = []
    for source in owned_rows:
        row = dict(source)
        projection = _find_projection(row, pmap, by_name)
        row["tactical_matchup"] = compact_tactical(projection)
        owned_decorated.append(row)
    if "owned_squad" in payload:
        payload.setdefault("owned_squad", {})["facts"] = owned_decorated
    else:
        payload["owned_15"] = owned_decorated

    watch_container = payload.get("external_watchlist") if "external_watchlist" in payload else None
    if isinstance(watch_container, dict):
        positions = watch_container.get("positions") or {}
    else:
        positions = payload.get("watchlist_20") or {}
    watch_count = 0
    for _, rows in positions.items():
        for row in rows or []:
            projection = _find_projection(row, pmap, by_name)
            row["tactical_matchup"] = compact_tactical(projection)
            watch_count += 1

    battle = ((payload.get("starting_xi") or {}).get("model") or {}).get("battle") if "starting_xi" in payload else payload.get("main_starting_xi_battle")
    if isinstance(battle, dict):
        for key in ("leader_metrics", "challenger_metrics"):
            metrics = battle.get(key)
            if isinstance(metrics, dict):
                metrics["tactical_matchup"] = compact_tactical(_find_projection(metrics, pmap, by_name))
        battle["tactical_tiebreak"] = (lineup.get("main_starting_xi_battle") or {}).get("tactical_tiebreak") or {}

    captaincy = payload.get("captaincy") or {}
    model = captaincy.get("model") if isinstance(captaincy, dict) else None
    if isinstance(model, dict):
        for key in ("captain", "vice"):
            row = model.get(key)
            if isinstance(row, dict):
                row["tactical_matchup"] = compact_tactical(_find_projection(row, pmap, by_name))
    elif isinstance(captaincy, dict):
        captain_name = captaincy.get("captain")
        vice_name = captaincy.get("vice")
        captaincy["tactical_comparison"] = {
            "captain": compact_tactical(by_name.get(str(captain_name or "").casefold())),
            "vice": compact_tactical(by_name.get(str(vice_name or "").casefold())),
        }

    states = [str((row.get("tactical_matchup") or {}).get("evidence_state") or "") for row in owned_decorated]
    payload["tactical_context"] = {
        "owned_players": len(owned_decorated),
        "watchlist_players": watch_count,
        "owned_evidence": {
            "cukup": sum(1 for value in states if value == "CUKUP"),
            "terbatas": sum(1 for value in states if value == "TERBATAS"),
            "tidak_tersedia": sum(1 for value in states if value == "TIDAK_TERSEDIA"),
        },
        "decision_usage": {
            "starting_xi_close_call": bool((lineup.get("governance") or {}).get("tactical_xi_tiebreak_applied")),
            "captain_close_call": bool((lineup.get("governance") or {}).get("tactical_captain_tiebreak_applied")),
            "vice_close_call": bool((lineup.get("governance") or {}).get("tactical_vice_tiebreak_applied")),
            "direct_xpts_mutation": False,
        },
        "policy": "matchup lawan wajib dibaca untuk keputusan; tactical hanya memecahkan close call dan tidak mengubah xPts",
    }
    return payload


def apply_report_overlay() -> dict[str, Any]:
    projections = read_json(DATA / "projections.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    result = {}
    for name in ("user_report.json", "decision_brief.json", "deep_review_payload.json"):
        path = DATA / name
        payload = read_json(path, {})
        if not payload:
            continue
        decorated = decorate_report_payload(payload, projections, lineup)
        atomic_json(path, decorated)
        result[name] = {
            "owned": int((decorated.get("tactical_context") or {}).get("owned_players") or 0),
            "watchlist": int((decorated.get("tactical_context") or {}).get("watchlist_players") or 0),
        }
    return result
