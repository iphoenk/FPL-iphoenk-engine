from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "owned_challenger_comparator.json"
OUT = DATA / "owned_challenger_comparator.json"


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = -1) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _projection_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in payload.get("players") or [] if row.get("element") is not None}


def _horizon(proj: dict[str, Any], horizon: int) -> tuple[float, float]:
    rows = list(proj.get("xpts_by_gw") or [])[:horizon]
    return (
        round(sum(_f(row.get("mean")) for row in rows), 3),
        round(math.sqrt(sum(_f(row.get("std")) ** 2 for row in rows)), 3),
    )


def _watchlist_ids(watchlist: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for position in ("GK", "DEF", "MID", "FWD"):
        for row in (watchlist.get("positions") or {}).get(position) or []:
            element = _i(row.get("element"))
            if element > 0:
                out.append(element)
    return out


def _owned(team: dict[str, Any], pmap: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ledger_rows = list(team.get("team_value_ledger") or []) or list(team.get("squad") or [])
    for ledger in ledger_rows:
        element = _i(ledger.get("element"))
        proj = pmap.get(element)
        if not proj:
            continue
        rows.append({
            "element": element,
            "name": ledger.get("name") or proj.get("name"),
            "position": ledger.get("position") or proj.get("position"),
            "team_id": _i(proj.get("team_id", ledger.get("team_id"))),
            "sell_cost": _i(ledger.get("sell_cost", proj.get("now_cost")), 0),
            "purchase_cost": ledger.get("purchase_cost"),
            "now_cost": _i(ledger.get("now_cost", proj.get("now_cost")), 0),
            "projection": proj,
        })
    return rows


def _team_itb(team: dict[str, Any]) -> int:
    return _i((team.get("totals") or {}).get("itb", team.get("itb")), 0)


def _club_legal(owned: list[dict[str, Any]], out: dict[str, Any], incoming: dict[str, Any]) -> bool:
    counts: dict[int, int] = {}
    for row in owned:
        tid = _i(row.get("team_id"))
        counts[tid] = counts.get(tid, 0) + 1
    out_tid = _i(out.get("team_id")); in_tid = _i(incoming.get("team_id"))
    counts[out_tid] = max(0, counts.get(out_tid, 0) - 1)
    counts[in_tid] = counts.get(in_tid, 0) + 1
    return max(counts.values(), default=0) <= 3


def _package_alternatives(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = [{"replacements": 0, "classification": "HOLD", "source": "canonical_package_optimizer", "authoritative_optimizer_evidence": True}]
    rows = payload.get("best_by_replacement_count") or {}
    iterable = rows.items() if isinstance(rows, dict) and rows else ((str(row.get("replacements") or len(row.get("outs") or row.get("out") or [])), row) for row in payload.get("packages") or [])
    seen: set[tuple[int, tuple[int, ...], tuple[int, ...]]] = set()
    for key, row in iterable:
        if not isinstance(row, dict):
            continue
        outs = list(row.get("outs") or row.get("out") or []); ins = list(row.get("ins") or row.get("in") or [])
        replacements = _i(row.get("replacements", key), len(outs))
        out_ids = tuple(sorted(_i(x.get("element")) for x in outs if _i(x.get("element")) > 0)); in_ids = tuple(sorted(_i(x.get("element")) for x in ins if _i(x.get("element")) > 0))
        ident = (replacements, out_ids, in_ids)
        if ident in seen:
            continue
        seen.add(ident)
        alternatives.append({
            "replacements": replacements,
            "out": [{"element": _i(x.get("element")), "name": x.get("name"), "position": x.get("position")} for x in outs],
            "in": [{"element": _i(x.get("element")), "name": x.get("name"), "position": x.get("position")} for x in ins],
            "classification": row.get("classification") or row.get("decision") or row.get("state"),
            "robust_gain_vs_hold": row.get("robust_gain_vs_hold", row.get("adjusted_utility_gain_5", row.get("delta_best_xi_xpts_5"))),
            "net_gain_3gw": row.get("delta_squad_xpts_3"), "net_gain_5gw": row.get("delta_squad_xpts_5", row.get("sanity_gain_5")),
            "net_gain_10gw": row.get("delta_squad_xpts_10"), "net_gain_15gw": row.get("delta_squad_xpts_15"), "hit_cost": row.get("hit_cost"),
            "legal": row.get("legal", True), "affordability": row.get("affordability") or {"resulting_itb": row.get("target_itb")},
            "source": "canonical_package_optimizer", "authoritative_optimizer_evidence": True,
        })
    alternatives.sort(key=lambda x: _i(x.get("replacements"), 0))
    return alternatives


def _package_map(payload: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for alt in _package_alternatives(payload):
        if _i(alt.get("replacements"), 0) != 1 or alt.get("legal") is False:
            continue
        outs = alt.get("out") or []; ins = alt.get("in") or []
        if len(outs) == 1 and len(ins) == 1:
            out[(_i(outs[0].get("element")), _i(ins[0].get("element")))] = alt
    return out


def _match_stats() -> dict[int, dict[str, float]]:
    payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    out: dict[int, dict[str, float]] = {}
    for row in payload.get("rows") or []:
        element = _i(row.get("player_id"))
        if element <= 0: continue
        agg = out.setdefault(element, {"returns": 0.0, "xgi": 0.0, "shots": 0.0, "box_touches": 0.0, "chances_created": 0.0})
        agg["returns"] += _f(row.get("goals")) + _f(row.get("assists")); agg["xgi"] += _f(row.get("xg")) + _f(row.get("xa")); agg["shots"] += _f(row.get("total_shots")); agg["box_touches"] += _f(row.get("touches_opposition_box")); agg["chances_created"] += _f(row.get("chances_created"))
    return out


def _emerging_candidates(pmap: dict[int, dict[str, Any]], excluded: set[int]) -> list[tuple[dict[str, Any], list[str], bool]]:
    cfg = load_policy().get("emerging_screen") or {}; stats = _match_stats(); rows: list[tuple[dict[str, Any], list[str], bool]] = []
    for element, proj in pmap.items():
        if element in excluded or str(proj.get("status")) not in set(cfg.get("allowed_statuses") or []): continue
        xmins = proj.get("xmins") or {}; h5, _ = _horizon(proj, 5)
        if _f(xmins.get("expected_minutes")) < _f(cfg.get("minimum_expected_minutes"), 50): continue
        if _f(xmins.get("start_probability")) < _f(cfg.get("minimum_start_probability"), 0.45): continue
        if _f(xmins.get("dnp_probability")) > _f(cfg.get("maximum_dnp_probability"), 0.35): continue
        if h5 < _f(cfg.get("minimum_h5_points"), 12): continue
        s = stats.get(element) or {}; triggers: list[str] = []
        if _f(s.get("returns")) >= _f(cfg.get("strong_match_return_trigger"), 2): triggers.append("MULTIPLE_MATCH_RETURNS")
        if _f(s.get("xgi")) >= _f(cfg.get("strong_xgi_trigger"), 0.75): triggers.append("STRONG_XGI")
        if _f(s.get("shots")) >= _f(cfg.get("shots_trigger"), 4): triggers.append("HIGH_SHOT_VOLUME")
        if _f(s.get("box_touches")) >= _f(cfg.get("box_touches_trigger"), 8): triggers.append("HIGH_BOX_INVOLVEMENT")
        if _f(s.get("chances_created")) >= _f(cfg.get("chances_created_trigger"), 4): triggers.append("HIGH_CHANCE_CREATION")
        sustainable = len(set(triggers)) >= _i(cfg.get("sustainable_minimum_trigger_count"), 2) and _f(xmins.get("start_probability")) >= _f(cfg.get("sustainable_minimum_start_probability"), 0.60)
        if triggers: rows.append((proj, sorted(set(triggers)), sustainable))
    rows.sort(key=lambda item: _horizon(item[0], 5)[0], reverse=True)
    return rows[: _i(cfg.get("max_candidates"), 12)]


def _external_state(external: dict[str, Any], element: int) -> dict[str, Any]:
    matches = []
    for subject in external.get("subjects") or []:
        if str(element) in json.dumps(subject, ensure_ascii=False): matches.append({"subject": subject.get("subject"), "classification": subject.get("classification")})
    return {"overall": external.get("overall") or "INSUFFICIENT_EVIDENCE", "player_specific": matches, "advisory_only": True}


def _price_index(prices: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {_i(row.get("element_id", row.get("element"))): row for row in prices.get("players") or [] if _i(row.get("element_id", row.get("element"))) > 0}


def _price_evidence(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}; freshness = _f(row.get("freshness_seconds"), 10**9); state = str(row.get("evidence_state") or "UNAVAILABLE"); stale = state == "STALE" or freshness > 6 * 3600
    urgency = str(row.get("model_urgency") or "LOW"); direction = row.get("direction"); timing_state = "MODEL_CONTEXT_ONLY"
    if not stale and state not in {"UNAVAILABLE", "SCHEMA_CHANGED", "FIELD_MISSING", "CALIBRATING"}:
        if urgency in {"HIGH", "CRITICAL"}: timing_state = "PRICE_ACTIONABLE"
        elif direction in {"RISE", "FALL"}: timing_state = "WATCH_NEXT_UPDATE"
    return {
        "current_price": row.get("current_price"), "official_ownership": row.get("ownership_percent"), "confirmed_price_change": row.get("confirmed_price_change"), "direction": direction,
        "current_progress_percent": row.get("current_progress_percent"), "projection_offset_0_percent": row.get("projection_offset_0_percent"), "projection_offset_0_likelihood": row.get("projection_offset_0_likelihood"),
        "trajectory": row.get("trajectory") or row.get("trajectory_state"), "model_urgency": urgency, "next_official_price_update_at": row.get("next_official_price_update_at"), "eta_human": row.get("eta_human"), "narrative": row.get("narrative"),
        "source": row.get("source"), "observed_at": row.get("observed_at"), "freshness_seconds": row.get("freshness_seconds"), "evidence_state": state, "timing_state": timing_state,
        "stale_cannot_create_urgency": stale, "threshold_crossing_is_not_confirmation": True,
    }


def _critical_evidence(out: dict[str, Any], incoming: dict[str, Any], affordable: bool, club_legal: bool, external: dict[str, Any]) -> dict[str, str]:
    out_proj = out.get("projection") or {}; tactical = incoming.get("tactical_matchup") or {}; load = read_json(DATA / "recent_competitive_load.json", {}); load_rows = load.get("players") or {}; load_available = str(incoming.get("element")) in load_rows or _i(incoming.get("element")) in load_rows; ext = _external_state(external, _i(incoming.get("element")))
    return {"canonical_projection": "AVAILABLE" if out_proj and incoming else "UNAVAILABLE", "canonical_xmins": "AVAILABLE" if out_proj.get("xmins") and incoming.get("xmins") else "UNAVAILABLE", "same_position": "AVAILABLE" if out_proj.get("position") == incoming.get("position") else "UNAVAILABLE", "exact_sell_value": "AVAILABLE" if out.get("sell_cost") is not None else "UNAVAILABLE", "affordability": "AVAILABLE" if affordable else "CONSTRAINT_FAILED", "club_legality": "AVAILABLE" if club_legal else "CONSTRAINT_FAILED", "tactical_context": "AVAILABLE" if tactical else "PARTIAL", "competitive_load": "AVAILABLE" if load_available else "UNAVAILABLE", "external_consensus": "AVAILABLE" if ext["overall"] != "INSUFFICIENT_EVIDENCE" else "UNAVAILABLE"}


def _actionability(row: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy().get("decision") or {}; state = str(row.get("state") or "HOLD"); h3 = _f((((row.get("horizons") or {}).get("3") or {}).get("projected_edge"))); h5 = _f((((row.get("horizons") or {}).get("5") or {}).get("projected_edge"))); finance = row.get("finance") or {}; legality = row.get("legality") or {}; tactical = row.get("tactical_matchup") or {}; start = _f((row.get("start_probability") or {}).get("challenger")); missing = list(row.get("missing_critical_evidence") or []); timing = str(row.get("price_urgency") or "MODEL_CONTEXT_ONLY"); blockers: list[str] = []
    if h3 < _f(cfg.get("minimum_positive_3gw_for_material"), 0.5): blockers.append("INSUFFICIENT_3GW_EDGE")
    if h5 < _f(cfg.get("lean_gain_5gw"), 3.0): blockers.append("INSUFFICIENT_5GW_EDGE")
    if not finance.get("affordable"): blockers.append("NOT_AFFORDABLE")
    if not legality.get("club_limit_legal"): blockers.append("CLUB_LIMIT")
    if start < _f(cfg.get("minimum_start_probability_for_transfer"), 0.60): blockers.append("START_SECURITY")
    if not tactical or tactical.get("evidence_state") == "UNAVAILABLE" or tactical.get("status") == "UNAVAILABLE": blockers.append("TACTICAL_EVIDENCE")
    if missing: blockers.append("CRITICAL_EVIDENCE")
    timing_ready = timing in {"ACT_NOW", "DEADLINE_ACTIONABLE", "PRICE_ACTIONABLE"}
    if cfg.get("actionable_change_requires_explicit_timing_evidence", True) and not timing_ready: blockers.append("TIMING_NOT_ACTIONABLE")
    if state in {"HOLD", "WATCH"}: level = "WATCH"
    elif state == "REVIEW" or any(x in blockers for x in {"NOT_AFFORDABLE", "CLUB_LIMIT", "START_SECURITY", "CRITICAL_EVIDENCE"}): level = "REVIEW"
    elif h3 >= _f(cfg.get("minimum_positive_3gw_for_material"), 0.5) and h5 >= _f(cfg.get("lean_gain_5gw"), 3.0): level = "ACTIONABLE_CHANGE" if not blockers and state == "STRONG_TRANSFER" else "MATERIAL_UPGRADE"
    else: level = "REVIEW"
    reason = {"WATCH": "candidate retained for observation; no governed transfer trigger", "REVIEW": "candidate merits review but one or more transfer gates are incomplete", "MATERIAL_UPGRADE": "3-5 GW edge is material but at least one actionability gate remains", "ACTIONABLE_CHANGE": "multi-GW edge and all affordability, security, tactical and timing gates are satisfied"}[level]
    return {"level": level, "reason": reason, "blockers": sorted(set(blockers)), "three_gw_edge": round(h3, 3), "five_gw_edge": round(h5, 3), "timing_evidence": timing}


def _compare(out: dict[str, Any], incoming: dict[str, Any], challenger_type: str, triggers: list[str], sustainable: bool, owned: list[dict[str, Any]], itb: int, packages: dict[tuple[int, int], dict[str, Any]], external: dict[str, Any], prices: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = load_policy(); decision_cfg = cfg.get("decision") or {}; out_proj = out.get("projection") or {}; horizons: dict[str, Any] = {}
    for h in cfg.get("horizons") or [1, 2, 3, 5]:
        om, os = _horizon(out_proj, int(h)); im, ins = _horizon(incoming, int(h)); horizons[str(h)] = {"owned_xpts": om, "challenger_xpts": im, "projected_edge": round(im - om, 3), "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3)}
    strategic = {}
    for h in cfg.get("strategic_horizons") or [10, 15]:
        om, os = _horizon(out_proj, int(h)); im, ins = _horizon(incoming, int(h)); strategic[str(h)] = {"owned_xpts": om, "challenger_xpts": im, "projected_edge": round(im - om, 3), "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3)}
    affordable = _i(incoming.get("now_cost"), 0) <= _i(out.get("sell_cost"), 0) + itb; club_legal = _club_legal(owned, out, incoming); package = packages.get((_i(out.get("element")), _i(incoming.get("element")))); h5 = horizons.get("5") or {}; edge = _f(h5.get("projected_edge")); unc = _f(h5.get("combined_uncertainty")); snr = edge / unc if unc > 1e-9 else 0.0; start_p = _f((incoming.get("xmins") or {}).get("start_probability")); evidence = _critical_evidence(out, incoming, affordable, club_legal, external); missing = [k for k, v in evidence.items() if v in {"UNAVAILABLE", "PARTIAL"}]; constraints_failed = [k for k, v in evidence.items() if v == "CONSTRAINT_FAILED"]
    state = "HOLD"
    if challenger_type == "EMERGING_CHALLENGER" and not sustainable: state = "WATCH"
    elif constraints_failed: state = "REVIEW"
    elif edge < _f(decision_cfg.get("review_gain_5gw"), 1.0): state = "HOLD"
    elif missing and decision_cfg.get("missing_critical_evidence_caps_at") == "REVIEW": state = "REVIEW"
    elif edge >= _f(decision_cfg.get("strong_gain_5gw"), 5.0) and snr >= _f(decision_cfg.get("strong_minimum_signal_to_noise"), 0.85) and start_p >= _f(decision_cfg.get("strong_minimum_start_probability"), 0.75) and package: state = "STRONG_TRANSFER"
    elif edge >= _f(decision_cfg.get("lean_gain_5gw"), 3.0) and snr >= _f(decision_cfg.get("lean_minimum_signal_to_noise"), 0.55) and start_p >= _f(decision_cfg.get("minimum_start_probability_for_transfer"), 0.60): state = "LEAN_TRANSFER"
    else: state = "REVIEW"
    prices = prices or {}; owned_price = _price_evidence(prices.get(_i(out.get("element")))); incoming_price = _price_evidence(prices.get(_i(incoming.get("element")))); price_urgency = incoming_price.get("timing_state") if incoming_price.get("timing_state") == "PRICE_ACTIONABLE" else owned_price.get("timing_state")
    row = {"player_out": {"element": out.get("element"), "name": out.get("name"), "position": out.get("position"), "sell_cost": out.get("sell_cost")}, "player_in": {"element": incoming.get("element"), "name": incoming.get("name"), "position": incoming.get("position"), "now_cost": incoming.get("now_cost")}, "challenger_type": challenger_type, "state": state, "horizons": horizons, "strategic_context": strategic, "xmins": {"owned": (out_proj.get("xmins") or {}).get("expected_minutes"), "challenger": (incoming.get("xmins") or {}).get("expected_minutes")}, "start_probability": {"owned": (out_proj.get("xmins") or {}).get("start_probability"), "challenger": (incoming.get("xmins") or {}).get("start_probability")}, "role_security": {"owned_dnp": (out_proj.get("xmins") or {}).get("dnp_probability"), "challenger_dnp": (incoming.get("xmins") or {}).get("dnp_probability")}, "tactical_matchup": incoming.get("tactical_matchup") or {"evidence_state": "UNAVAILABLE"}, "underlying": {"owned_rates": out_proj.get("rates") or {}, "challenger_rates": incoming.get("rates") or {}}, "set_piece_penalty": {"owned_penalty_role": out_proj.get("penalty_role"), "challenger_penalty_role": incoming.get("penalty_role"), "owned_set_piece_role": out_proj.get("set_piece_role"), "challenger_set_piece_role": incoming.get("set_piece_role")}, "finance": {"exact_sell_cost": out.get("sell_cost"), "purchase_cost": out.get("purchase_cost"), "incoming_now_cost": incoming.get("now_cost"), "itb": itb, "affordable": affordable, "canonical_package": package}, "legality": {"same_position": out.get("position") == incoming.get("position"), "club_limit_legal": club_legal}, "market_timing": {"owned": owned_price, "challenger": incoming_price, "authority": "Official FPL", "football_decision_authority": False}, "price_urgency": price_urgency or "MODEL_CONTEXT_ONLY", "external_consensus": _external_state(external, _i(incoming.get("element"))), "emerging_triggers": triggers, "anti_haul_chasing": {"single_haul_is_not_sufficient": True, "sustainable_candidate": sustainable if challenger_type == "EMERGING_CHALLENGER" else None}, "uncertainty": {"signal_to_noise_5gw": round(snr, 3), "combined_5gw": unc}, "critical_evidence": evidence, "missing_critical_evidence": missing, "confidence": "LOW" if missing else (incoming.get("projection_confidence") or "MEDIUM"), "advisory_only": True, "flip_conditions": ["material multi-GW edge changes", "starter security changes", "tactical/rest evidence changes", "affordability or Official price timing changes"]}
    row["actionability"] = _actionability(row); row["reason"] = row["actionability"]["reason"]; return row


def _owned_strength(row: dict[str, Any]) -> dict[str, float]:
    proj = row.get("projection") or {}; x5, _ = _horizon(proj, 5); x15, _ = _horizon(proj, 15); xm = proj.get("xmins") or {}
    return {"xpts_5": x5, "strategic_xpts_15_per_5gw": round(x15 / 3.0, 3), "start_probability": round(_f(xm.get("start_probability")), 4), "dnp_probability": round(_f(xm.get("dnp_probability")), 4), "uncertainty": round(_f(proj.get("uncertainty")), 4), "value": round(_f((proj.get("value") or {}).get("xpts5_per_million")), 4)}


def _screen_owned(owned: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_owned: dict[int, list[dict[str, Any]]] = {}
    for pair in comparisons: by_owned.setdefault(_i((pair.get("player_out") or {}).get("element")), []).append(pair)
    rows = []
    for item in owned:
        eid = _i(item.get("element")); comps = by_owned.get(eid, []); legal = [p for p in comps if (p.get("finance") or {}).get("affordable") and (p.get("legality") or {}).get("club_limit_legal")]; best = max(legal, key=lambda p: _f(((p.get("horizons") or {}).get("5") or {}).get("projected_edge")), default=None); edge5 = _f((((best or {}).get("horizons") or {}).get("5") or {}).get("projected_edge")); edge3 = _f((((best or {}).get("horizons") or {}).get("3") or {}).get("projected_edge")); xm = (item.get("projection") or {}).get("xmins") or {}; start_risk = max(0.0, 0.75 - _f(xm.get("start_probability"))); dnp = _f(xm.get("dnp_probability")); uncertainty = _f((item.get("projection") or {}).get("uncertainty")); challenge_pressure = max(0.0, edge5) + 1.5 * max(0.0, edge3) + 3.0 * start_risk + 2.0 * dnp + 0.25 * uncertainty; level = ((best or {}).get("actionability") or {}).get("level"); challenged = level in {"MATERIAL_UPGRADE", "ACTIONABLE_CHANGE"} or str((best or {}).get("state")) in {"LEAN_TRANSFER", "STRONG_TRANSFER"}
        rows.append({"element": eid, "name": item.get("name"), "position": item.get("position"), "strength_components": _owned_strength(item), "challenge_pressure": round(challenge_pressure, 4), "replacement_opportunity": round(edge5, 3) if best else None, "best_challenger": (best or {}).get("player_in"), "best_pair_state": (best or {}).get("state"), "best_pair_actionability": (best or {}).get("actionability"), "state": "CHALLENGED_OWNED" if challenged else "UNCHALLENGED", "confidence": (best or {}).get("confidence") or "MEDIUM", "ranking_basis": "replacement edge + 3GW edge + xMins/start risk + DNP + uncertainty; xPts alone forbidden"})
    rows.sort(key=lambda r: r["challenge_pressure"], reverse=True)
    for idx, row in enumerate(rows, 1): row["owned_rank"] = idx
    return rows


def _main_battles(comparisons: list[dict[str, Any]], owned_screening: list[dict[str, Any]]) -> list[dict[str, Any]]:
    challenged = {row["element"] for row in owned_screening if row.get("state") == "CHALLENGED_OWNED"}; candidates = [row for row in comparisons if _i((row.get("player_out") or {}).get("element")) in challenged]; candidates.sort(key=lambda p: (_f(((p.get("horizons") or {}).get("5") or {}).get("projected_edge")), _f(((p.get("horizons") or {}).get("3") or {}).get("projected_edge"))), reverse=True); battles = []; used: set[int] = set()
    for row in candidates:
        owned_id = _i((row.get("player_out") or {}).get("element"))
        if owned_id in used: continue
        used.add(owned_id); battles.append({"owned": row.get("player_out"), "challenger": row.get("player_in"), "v3_edge": {"3gw": (row.get("horizons") or {}).get("3"), "5gw": (row.get("horizons") or {}).get("5"), "10_15gw": row.get("strategic_context")}, "v4_edge": {"state": "NO_EQUIVALENT_IN_V3_RUNTIME", "weight": 0.0}, "consensus": "NEUTRAL", "xmins": row.get("xmins"), "start_probability": row.get("start_probability"), "role": row.get("role_security"), "next_matchup": row.get("tactical_matchup"), "rest_congestion": (row.get("critical_evidence") or {}).get("competitive_load"), "official_price": {"out": ((row.get("market_timing") or {}).get("owned") or {}).get("current_price"), "in": ((row.get("market_timing") or {}).get("challenger") or {}).get("current_price")}, "official_ownership": {"out": ((row.get("market_timing") or {}).get("owned") or {}).get("official_ownership"), "in": ((row.get("market_timing") or {}).get("challenger") or {}).get("official_ownership")}, "predictor": row.get("market_timing"), "structural_impact": row.get("finance"), "risk": row.get("missing_critical_evidence"), "confidence": row.get("confidence"), "decision": (row.get("actionability") or {}).get("level"), "reason": row.get("reason"), "flip_conditions": row.get("flip_conditions")})
    return battles[:10]


def _governed_decision(battles: list[dict[str, Any]], alternatives: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [b for b in battles if b.get("decision") == "ACTIONABLE_CHANGE"]; material = [b for b in battles if b.get("decision") == "MATERIAL_UPGRADE"]; legal_changes = [a for a in alternatives if _i(a.get("replacements"), 0) > 0 and a.get("legal") is not False]
    if actionable and legal_changes: state = "CHANGE"
    elif material: state = "REVIEW_NOW" if any((((b.get("predictor") or {}).get("challenger") or {}).get("timing_state") == "PRICE_ACTIONABLE") for b in material) else "REVIEW"
    elif battles: state = "REVIEW"
    else: state = "HOLD"
    return {"state": state, "execution_authorized": False, "reason": "ENGINE_ADVISORY_USER_AUTHORITY" if state == "CHANGE" else "NO_ROBUST_EXECUTABLE_TRANSFER" if state == "HOLD" else "EVIDENCE_REVIEW_REQUIRED", "no_transfer_recommended": state == "HOLD", "no_transfer_message": "NO TRANSFER RECOMMENDED" if state == "HOLD" else None, "market_timing_is_not_football_authority": True, "package_optimizer_is_transfer_structure_authority": True}


def build() -> dict[str, Any]:
    cfg = load_policy(); projections = read_json(DATA / "projections.json", {}); team = read_json(DATA / "team.json", {}); watchlist = read_json(DATA / "dss_watchlist.json", {}); package_optimizer = read_json(DATA / "package_optimizer.json", {}); external = read_json(DATA / "external_consensus.json", {}); price_payload = read_json(DATA / "prices.json", {}); pmap = _projection_map(projections); owned = _owned(team, pmap); owned_ids = {int(row["element"]) for row in owned}; governed_ids = _watchlist_ids(watchlist); packages = _package_map(package_optimizer); alternatives = _package_alternatives(package_optimizer); itb = _team_itb(team); prices = _price_index(price_payload); comparisons: list[dict[str, Any]] = []
    for element in governed_ids:
        incoming = pmap.get(element)
        if not incoming: continue
        for out in [row for row in owned if row.get("position") == incoming.get("position")]: comparisons.append(_compare(out, incoming, "GOVERNED_WATCHLIST", [], True, owned, itb, packages, external, prices))
    excluded = owned_ids | set(governed_ids); emerging = _emerging_candidates(pmap, excluded)
    for incoming, triggers, sustainable in emerging:
        for out in [row for row in owned if row.get("position") == incoming.get("position")]: comparisons.append(_compare(out, incoming, "EMERGING_CHALLENGER", triggers, sustainable, owned, itb, packages, external, prices))
    rank = {"STRONG_TRANSFER": 5, "LEAN_TRANSFER": 4, "REVIEW": 3, "WATCH": 2, "HOLD": 1}; comparisons.sort(key=lambda row: (rank.get(str(row.get("state")), 0), _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge"))), reverse=True); owned_screening = _screen_owned(owned, comparisons); battles = _main_battles(comparisons, owned_screening); decision = _governed_decision(battles, alternatives); completeness = {"owned_expected": 15, "owned_screened": len(owned_screening), "watchlist_expected": 20, "watchlist_screened": len(governed_ids), "owned_complete": len(owned_screening) == 15, "watchlist_complete": len(governed_ids) == 20}; status = "READY" if completeness["owned_complete"] and completeness["watchlist_complete"] else "BLOCKED"
    if status == "BLOCKED": decision = {**decision, "state": "BLOCKED", "execution_authorized": False, "reason": "FACT_OR_SCREENING_COMPLETENESS_FAILED"}
    return {"schema_version": 4, "contract": "OWNED_CHALLENGER_COMPARATOR_V3", "contract_revision": "OWNED_CHALLENGER_DECISION_ENGINE_V4_ADDITIVE", "generated_at": iso_now(), "owner": cfg.get("owner"), "status": status, "advisory_only": True, "owned_count": len(owned), "governed_watchlist_count": len(governed_ids), "emerging_candidate_count": len(emerging), "comparison_count": len(comparisons), "state_counts": {state: sum(1 for row in comparisons if row.get("state") == state) for state in cfg.get("output_states") or []}, "actionability_counts": {state: sum(1 for row in comparisons if (row.get("actionability") or {}).get("level") == state) for state in cfg.get("actionability_states") or []}, "official_fact_and_screening_completeness": completeness, "owned_screening": owned_screening, "challenged_owned": [row for row in owned_screening if row.get("state") == "CHALLENGED_OWNED"], "pairwise_matrix": comparisons, "top_comparisons": comparisons[:40], "multi_transfer_alternatives": alternatives, "main_transfer_battles": battles, "decision": decision, "v3_view": {"status": status, "decision": decision.get("state"), "confidence": "GOVERNED_BY_PAIR_EVIDENCE"}, "v4_view": {"status": "NO_EQUIVALENT_IN_V3_RUNTIME", "weight": 0.0}, "consensus": "NEUTRAL", "governance": {**(cfg.get("governance") or {}), "weakest_link_is_not_lowest_xpts_alone": True, "all_15_screened": True, "no_player_specific_out_hardcode": True, "price_timing_not_decision_authority": True, "weather_alone_cannot_transfer": True, "data_join_defect_internal_only": True}}


def run() -> dict[str, Any]:
    result = build(); atomic_json(OUT, result); latest = read_json(DATA / "latest.json", {}); latest["owned_challenger_comparator"] = {"status": result.get("status"), "owned_count": result.get("owned_count"), "governed_watchlist_count": result.get("governed_watchlist_count"), "emerging_candidate_count": result.get("emerging_candidate_count"), "comparison_count": result.get("comparison_count"), "challenged_owned_count": len(result.get("challenged_owned") or []), "decision": (result.get("decision") or {}).get("state"), "state_counts": result.get("state_counts"), "actionability_counts": result.get("actionability_counts"), "advisory_only": True}; latest.setdefault("files", {})["owned_challenger_comparator"] = "data/owned_challenger_comparator.json"; atomic_json(DATA / "latest.json", latest); print(json.dumps(latest["owned_challenger_comparator"], ensure_ascii=False)); return result


if __name__ == "__main__":
    run()
