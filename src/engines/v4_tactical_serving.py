from __future__ import annotations

from collections import defaultdict
from typing import Any

from src.engines.fpl_rules_2026 import POSITION_COUNTS
from src.engines.v4_official_fact_integrity import extract_public_fact
from src.engines.v4_owned_challenger_evaluation import build_owned_challenger_evaluation
from src.engines.v4_serving_policy import watchlist_position_counts
from src.utils import DATA, read_json

EXTERNAL_EVIDENCE = DATA / "tactical_external_evidence.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _avg_start(pred: dict) -> float:
    values = []
    for fixture in (pred.get("fixtures") or [])[:5]:
        xm = fixture.get("xmins") or {}
        if xm.get("start_probability") is not None:
            values.append(_f(xm.get("start_probability")))
    return sum(values) / len(values) if values else 0.0


def _return_routes(pred: dict) -> list[str]:
    fixture = ((pred.get("fixtures") or [{}])[0]) or {}
    components = fixture.get("components") or {}
    mapping = {"attack": "GOAL_ASSIST", "clean_sheet": "CLEAN_SHEET", "saves": "SAVES", "defcon": "DEFCON", "bonus": "BONUS", "set_piece_penalty_adjustment": "SET_PIECE_PENALTY_ROLE", "appearance": "APPEARANCE_MINUTES"}
    routes = [label for key, label in mapping.items() if abs(_f(components.get(key))) >= 0.05]
    return routes or ["NO_MATERIAL_ROUTE_MODELLED"]


def _external_row(external: dict, player: dict, opponent_id: int | None) -> dict:
    by_player = external.get("players") or {}; by_team = external.get("teams") or {}; row = by_player.get(str(player.get("element"))) or by_player.get(player.get("name")) or {}
    if row: return row
    if opponent_id is not None: return by_team.get(str(opponent_id)) or {}
    return {}


def _compact_tactical(pred: dict, universe_row: dict, external: dict) -> dict:
    fixture = ((pred.get("fixtures") or [{}])[0]) or {}; priors = pred.get("priors") or {}; opponent_id = fixture.get("opponent"); evidence = _external_row(external, {"element": pred.get("element"), "name": universe_row.get("name")}, opponent_id); verified = evidence.get("verified") is True; opponent_system = evidence.get("opponent_system") or {}; role_fit = evidence.get("role_vs_opponent_fit"); tactical_delta = _f((fixture.get("components") or {}).get("tactical_adjustment"), 0.0)
    if not verified: tactical_delta = 0.0
    if verified and opponent_system: state = "VERIFIED"
    elif priors.get("tactical_role"): state = "MODEL_ROLE_ONLY"
    else: state = "UNAVAILABLE"
    return {"player_role": priors.get("tactical_role") or universe_row.get("position"), "player_role_source": priors.get("tactical_role_source") or "fpl_position_fallback", "return_routes": _return_routes(pred), "opponent_id": opponent_id, "opponent_coach_system_evidence": evidence.get("coach_system_evidence"), "observed_base_shape": opponent_system.get("observed_base_shape"), "build_up_press_block_traits": opponent_system.get("build_up_press_block_traits"), "transition_threat": opponent_system.get("transition_threat"), "central_wide_vulnerability": opponent_system.get("central_wide_vulnerability"), "set_piece_aerial_context": opponent_system.get("set_piece_aerial_context"), "recent_tactical_adjustment": opponent_system.get("recent_tactical_adjustment"), "role_vs_opponent_fit": role_fit, "tactical_edge_risk": evidence.get("tactical_edge_risk"), "evidence_state": state, "external_evidence_state": "VERIFIED" if verified and opponent_system else "EVIDENCE_GATED", "evidence_source": evidence.get("source"), "evidence_verified_at": evidence.get("verified_at"), "tactical_delta_applied": round(tactical_delta, 4), "tactical_delta_hidden_in_xpts": False}


def _prediction_score(pred: dict) -> float:
    x5 = _f(pred.get("xpts_5")); x15 = _f(pred.get("xpts_15")) / 3.0; start = _avg_start(pred); uncertainty = max(0.0, _f(pred.get("uncertainty"))); value = _f((pred.get("value") or {}).get("xpts5_per_million"))
    return x5 + 0.20 * x15 + 0.65 * start + 0.30 * value - 0.35 * uncertainty


def governed_watchlist(predictions: dict, universe: dict, owned_ids: set[int], previous: dict | None = None) -> dict:
    expected_counts = watchlist_position_counts(); expected_total = sum(expected_counts.values()); positions = list(expected_counts); umap = {int(row.get("element") or 0): row for row in universe.get("players") or [] if row.get("element") is not None}; groups: dict[str, list[dict]] = defaultdict(list)
    for pred in predictions.get("players") or []:
        element = int(pred.get("element") or 0)
        if not element or element in owned_ids: continue
        uni = umap.get(element) or {}; position = uni.get("position") or pred.get("position")
        if position not in expected_counts: continue
        fact = extract_public_fact(uni, expected_element=element)
        groups[position].append({**fact, "score": round(_prediction_score(pred), 4), "xpts_5": round(_f(pred.get("xpts_5")), 3), "xpts_15": round(_f(pred.get("xpts_15")), 3), "start_probability_5": round(_avg_start(pred), 4), "uncertainty": round(_f(pred.get("uncertainty")), 4), "selection_basis": "prediction_horizon+start_security+value-uncertainty", "tactical_signal_used_for_promotion": False})
    selected = []
    for position in positions:
        exact = expected_counts[position]; rows = sorted(groups.get(position, []), key=lambda row: (row["score"], row["xpts_5"], row["start_probability_5"]), reverse=True)[:exact]
        if len(rows) != exact: raise RuntimeError(f"governed watchlist requires exactly {exact} {position}, got {len(rows)}")
        selected.extend(rows)
    if len(selected) != expected_total: raise RuntimeError(f"governed watchlist must contain exactly {expected_total} external players")
    previous_ids = {int(row.get("element") or 0) for row in (previous or {}).get("watchlist") or []}; selected_ids = {row["element"] for row in selected}; exited = sorted(previous_ids - selected_ids)
    for row in selected:
        row["lifecycle"] = "RETAINED" if row["element"] in previous_ids else "NEW"; row["entry_reason"] = row["selection_basis"]; row["exit_reason"] = None
    return {"watchlist": selected, "exited_elements": exited, "counts": {position: sum(row["position"] == position for row in selected) for position in positions}, "expected_total": expected_total, "exact_20": len(selected) == expected_total, "owned_excluded": not bool(selected_ids & owned_ids)}


def build_tactical_serving(predictions: dict, universe: dict, team: dict, external: dict | None = None, previous: dict | None = None) -> dict:
    external = external if external is not None else read_json(EXTERNAL_EVIDENCE, {}); pmap = {int(row.get("element") or 0): row for row in predictions.get("players") or [] if row.get("element") is not None}; umap = {int(row.get("element") or 0): row for row in universe.get("players") or [] if row.get("element") is not None}; owned_ids = {int(row.get("element") or 0) for row in team.get("squad") or []}; owned_expected = sum(int(count) for count in POSITION_COUNTS.values())
    if len(owned_ids) != owned_expected: raise RuntimeError(f"tactical serving requires exact {owned_expected} owned, got {len(owned_ids)}")
    watch = governed_watchlist(predictions, universe, owned_ids, previous); owned_rows = []
    for element in sorted(owned_ids):
        pred, uni = pmap.get(element), umap.get(element)
        if not pred or not uni: raise RuntimeError(f"DATA_JOIN_DEFECT: owned tactical row missing prediction/universe evidence for element_id={element}")
        fact = extract_public_fact(uni, expected_element=element); owned_rows.append({**fact, "tactical": _compact_tactical(pred, uni, external)})
    watch_rows = []
    for row in watch["watchlist"]:
        element = row["element"]; pred, uni = pmap.get(element), umap.get(element)
        if not pred or not uni: raise RuntimeError(f"DATA_JOIN_DEFECT: watchlist row missing prediction/universe evidence for element_id={element}")
        fact = extract_public_fact(row, expected_element=element)
        same_pos = [p for p in owned_rows if p["position"] == row["position"]]
        reference_candidates = []
        for owned in same_pos:
            owned_pred = pmap[owned["element"]]; start_risk = max(0.0, 0.75 - _avg_start(owned_pred)); weakness = -_f(owned_pred.get("xpts_5")) + 3.0 * start_risk + 0.25 * _f(owned_pred.get("uncertainty")); reference_candidates.append((weakness, owned))
        reference = max(reference_candidates, key=lambda x: x[0])[1] if reference_candidates else None; reference_x5 = _f(pmap[reference["element"]].get("xpts_5")) if reference else 0.0
        watch_rows.append({**row, **fact, "replacement_context": {"owned_element": reference.get("element") if reference else None, "owned_name": reference.get("name") if reference else None, "xpts5_delta": round(_f(pred.get("xpts_5")) - reference_x5, 3) if reference else None, "selection_basis": "multi_factor_reference_not_lowest_xpts_only", "all_same_position_owned_evaluated_in_owned_challenger_evaluation": True}, "tactical": _compact_tactical(pred, uni, external)})
    result = {"schema_version": 4963, "contract": "TACTICAL_SERVING_15_20_V2", "authoritative_owned_ids": sorted(owned_ids), "owned": owned_rows, "watchlist": watch_rows, "exited_watchlist_elements": watch["exited_elements"], "counts": {"owned": len(owned_rows), "watchlist": len(watch_rows), **watch["counts"]}, "guardrails": {"exact_15_owned": len(owned_rows) == owned_expected, "exact_20_watchlist": len(watch_rows) == watch["expected_total"], "owned_authority_ids_embedded": True, "owned_excluded_from_watchlist": watch["owned_excluded"], "official_fact_hydration_element_id_based": True, "official_fact_hydration_from_canonical_universe": True, "report_specific_fact_hydration_forbidden": True, "tactical_external_signal_cannot_independently_promote": True, "weakest_link_is_not_lowest_xpts_alone": True, "unverified_tactical_delta_is_zero": all(row["tactical"]["tactical_delta_applied"] == 0.0 for row in [*owned_rows, *watch_rows] if row["tactical"]["external_evidence_state"] != "VERIFIED"), "no_fabricated_opponent_system_evidence": True}}
    result["owned_challenger_evaluation"] = build_owned_challenger_evaluation(predictions, team, result, read_json(DATA / "wc_package_audit_v4.json", {}), read_json(DATA / "prices.json", {}), read_json(DATA / "recommendation_sanity_v4.json", {}), read_json(DATA / "latest.json", {}))
    return result
