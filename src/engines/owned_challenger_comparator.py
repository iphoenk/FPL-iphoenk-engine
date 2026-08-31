from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "owned_challenger_comparator.json"
OUT = DATA / "owned_challenger_comparator.json"
POSITIONS = ("GK", "DEF", "MID", "FWD")


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
    return {
        _i(row.get("element")): row
        for row in payload.get("players") or []
        if _i(row.get("element")) > 0
    }


def _horizon(proj: dict[str, Any], horizon: int) -> tuple[float, float]:
    horizons = proj.get("horizons") or {}
    direct = horizons.get(str(horizon)) or {}
    if direct.get("mean") is not None:
        return round(_f(direct.get("mean")), 3), round(_f(direct.get("std")), 3)
    rows = list(proj.get("xpts_by_gw") or [])[:horizon]
    return (
        round(sum(_f(row.get("mean")) for row in rows), 3),
        round(math.sqrt(sum(_f(row.get("std")) ** 2 for row in rows)), 3),
    )


def _official_map(snapshot: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("id")): row
        for row in ((snapshot.get("bootstrap") or {}).get("elements") or [])
        if _i(row.get("id")) > 0
    }


def _watchlist_rows(watchlist: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for position in POSITIONS
        for row in ((watchlist.get("positions") or {}).get(position) or [])
    ]


def _owned(team: dict[str, Any], pmap: dict[int, dict[str, Any]], official: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ledger_rows = list(team.get("team_value_ledger") or []) or list(team.get("squad") or [])
    for ledger in ledger_rows:
        element = _i(ledger.get("element"))
        proj = pmap.get(element) or {}
        off = official.get(element) or {}
        if element <= 0:
            continue
        rows.append({
            "element": element,
            "name": ledger.get("name") or off.get("web_name") or proj.get("name"),
            "position": ledger.get("position") or proj.get("position"),
            "team_id": _i(off.get("team", proj.get("team_id", ledger.get("team_id")))),
            "sell_cost": _i(ledger.get("sell_cost", proj.get("now_cost", off.get("now_cost"))), 0),
            "purchase_cost": ledger.get("purchase_cost"),
            "now_cost": _i(off.get("now_cost", ledger.get("now_cost", proj.get("now_cost"))), 0),
            "official_ownership": off.get("selected_by_percent"),
            "status": off.get("status", ledger.get("status", proj.get("status"))),
            "projection": proj,
        })
    return rows


def _team_itb(team: dict[str, Any]) -> int:
    return _i((team.get("totals") or {}).get("itb", team.get("itb")), 0)


def _club_legal(owned: list[dict[str, Any]], out: dict[str, Any], incoming: dict[str, Any]) -> bool:
    counts: dict[int, int] = {}
    for row in owned:
        tid = _i(row.get("team_id"))
        if tid > 0:
            counts[tid] = counts.get(tid, 0) + 1
    out_tid = _i(out.get("team_id"))
    in_tid = _i(incoming.get("team_id"))
    if out_tid > 0:
        counts[out_tid] = max(0, counts.get(out_tid, 0) - 1)
    if in_tid > 0:
        counts[in_tid] = counts.get(in_tid, 0) + 1
    return max(counts.values(), default=0) <= 3


def _package_alternatives(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alternatives: list[dict[str, Any]] = [{
        "replacements": 0,
        "classification": "HOLD",
        "robust_gain_vs_hold": 0.0,
        "hit_cost": 0,
        "legal": True,
        "source": "canonical_package_optimizer",
    }]
    rows = payload.get("best_by_replacement_count") or {}
    if isinstance(rows, dict) and rows:
        iterable = rows.values()
    else:
        iterable = payload.get("packages") or []
    seen: set[tuple[int, tuple[int, ...], tuple[int, ...]]] = set()
    for row in iterable:
        if not isinstance(row, dict):
            continue
        outs = list(row.get("outs") or row.get("out") or [])
        ins = list(row.get("ins") or row.get("in") or [])
        replacements = _i(row.get("replacements", row.get("changes")), len(outs))
        out_ids = tuple(sorted(_i(x.get("element")) for x in outs if _i(x.get("element")) > 0))
        in_ids = tuple(sorted(_i(x.get("element")) for x in ins if _i(x.get("element")) > 0))
        ident = (replacements, out_ids, in_ids)
        if ident in seen:
            continue
        seen.add(ident)
        score = row.get("score") or {}
        robust_gain = row.get("robust_gain_vs_hold")
        if robust_gain is None:
            robust_gain = row.get("adjusted_utility_gain_5")
        if robust_gain is None:
            robust_gain = row.get("delta_best_xi_xpts_5")
        if robust_gain is None:
            robust_gain = score.get("robust_gain_vs_hold")
        alternatives.append({
            "replacements": replacements,
            "out": [{"element": _i(x.get("element")), "name": x.get("name"), "position": x.get("position")} for x in outs],
            "in": [{"element": _i(x.get("element")), "name": x.get("name"), "position": x.get("position")} for x in ins],
            "classification": row.get("classification") or row.get("decision") or row.get("state"),
            "robust_gain_vs_hold": round(_f(robust_gain), 3),
            "net_gain_3gw": row.get("delta_squad_xpts_3"),
            "net_gain_5gw": row.get("delta_squad_xpts_5", row.get("sanity_gain_5")),
            "net_gain_10gw": row.get("delta_squad_xpts_10"),
            "net_gain_15gw": row.get("delta_squad_xpts_15"),
            "hit_cost": _f(row.get("hit_cost"), 0.0),
            "legal": row.get("legal", True),
            "affordability": row.get("affordability") or {"resulting_itb": row.get("target_itb")},
            "chip_context": row.get("chip_context"),
            "free_transfer_context": row.get("free_transfer_context"),
            "source": "canonical_package_optimizer",
        })
    alternatives.sort(key=lambda x: (_i(x.get("replacements"), 0), -_f(x.get("robust_gain_vs_hold"))))
    return alternatives


def _single_package_map(alternatives: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for alt in alternatives:
        if _i(alt.get("replacements"), 0) != 1 or alt.get("legal") is False:
            continue
        outs = alt.get("out") or []
        ins = alt.get("in") or []
        if len(outs) == 1 and len(ins) == 1:
            out[(_i(outs[0].get("element")), _i(ins[0].get("element")))] = alt
    return out


def _price_index(prices: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("element_id", row.get("element"))): row
        for row in prices.get("players") or []
        if _i(row.get("element_id", row.get("element"))) > 0
    }


def _market(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    cfg = load_policy().get("projected_value_market_discovery") or {}
    state = str(row.get("evidence_state") or row.get("status") or "UNAVAILABLE").upper()
    freshness = _f(row.get("freshness_seconds"), 10**9)
    stale = state in {"STALE", "UNAVAILABLE", "SCHEMA_CHANGED", "FIELD_MISSING", "CALIBRATING"} or freshness > _f(cfg.get("max_predictor_freshness_seconds"), 21600)
    direction = str(row.get("direction") or row.get("risk_direction") or "STABLE").upper()
    urgency = str(row.get("model_urgency") or row.get("urgency") or "LOW").upper()
    imminent = (not stale) and direction in {"RISE", "FALL"} and urgency in set(cfg.get("material_urgencies") or ["HIGH", "CRITICAL"])
    return {
        "direction": direction,
        "progress_percent": row.get("current_progress_percent", row.get("official_progress_pct")),
        "trajectory": row.get("trajectory") or row.get("trajectory_state"),
        "predicted_player_change_eta": row.get("eta_human") or row.get("predicted_change_deadline"),
        "next_official_price_update_window": row.get("next_official_price_update_at"),
        "urgency": urgency,
        "freshness_seconds": row.get("freshness_seconds"),
        "evidence_state": state,
        "fresh": not stale,
        "imminent": imminent,
        "confirmed_price_change": row.get("confirmed_price_change"),
        "threshold_crossing_is_not_confirmation": True,
    }


def _route_score(proj: dict[str, Any]) -> dict[str, float]:
    rates = proj.get("rates") or {}
    return {
        "xg90": round(_f(rates.get("xg90")), 4),
        "xa90": round(_f(rates.get("xa90")), 4),
        "bonus90": round(_f(rates.get("bonus90")), 4),
        "defcon90": round(_f(rates.get("dc90")), 4),
        "saves90": round(_f(rates.get("saves90")), 4),
        "aggregate": round(
            4.0 * _f(rates.get("xg90"))
            + 3.0 * _f(rates.get("xa90"))
            + _f(rates.get("bonus90"))
            + _f(rates.get("dc90"))
            + _f(rates.get("saves90")) / 3.0,
            4,
        ),
    }


def _competitive_load_map() -> dict[int, dict[str, Any]]:
    payload = read_json(DATA / "recent_competitive_load.json", {})
    rows = payload.get("players") or {}
    out: dict[int, dict[str, Any]] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            eid = _i(key)
            if eid > 0 and isinstance(value, dict):
                out[eid] = value
    elif isinstance(rows, list):
        for value in rows:
            eid = _i(value.get("element", value.get("player_id")))
            if eid > 0:
                out[eid] = value
    return out


def _candidate_index(
    discovery: dict[str, Any],
    watchlist: dict[str, Any],
    pmap: dict[int, dict[str, Any]],
    official: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    visible = {_i(row.get("element")) for row in _watchlist_rows(watchlist) if _i(row.get("element")) > 0}
    discovery_rows = {
        _i(row.get("element")): row
        for row in discovery.get("candidates") or []
        if _i(row.get("element")) > 0
    }
    ids = visible | set(discovery_rows)
    out: dict[int, dict[str, Any]] = {}
    for eid in ids:
        proj = dict(pmap.get(eid) or {})
        off = official.get(eid) or {}
        if not proj or not off:
            continue
        route = discovery_rows.get(eid) or {}
        off_position = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}.get(_i(off.get("element_type")))
        if off_position:
            proj["position"] = off_position
        proj["team_id"] = _i(off.get("team"), _i(proj.get("team_id")))
        proj["now_cost"] = off.get("now_cost", proj.get("now_cost"))
        proj["ownership_pct"] = off.get("selected_by_percent", proj.get("ownership_pct"))
        proj["status"] = off.get("status", proj.get("status"))
        proj["name"] = off.get("web_name") or proj.get("name")
        types: list[str] = []
        if eid in visible:
            types.append("GOVERNED_WATCHLIST")
        if route:
            if route.get("mandatory_challenger_review"):
                types.append("MANDATORY_VALUE_MARKET_REVIEW")
            elif (route.get("routes") or {}).get("FOOTBALL_EDGE"):
                types.append("FULL_UNIVERSE_DISCOVERY")
            else:
                types.append("EMERGING_CHALLENGER")
        out[eid] = {
            "projection": proj,
            "discovery": route,
            "challenger_types": types or ["GOVERNED_WATCHLIST"],
        }
    return out


def _compare(
    out: dict[str, Any],
    candidate: dict[str, Any],
    *,
    owned: list[dict[str, Any]],
    itb: int,
    prices: dict[int, dict[str, Any]],
    single_packages: dict[tuple[int, int], dict[str, Any]],
    load_map: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    cfg = load_policy()
    decision_cfg = cfg.get("decision") or {}
    incoming = candidate.get("projection") or {}
    out_proj = out.get("projection") or {}
    horizons: dict[str, Any] = {}
    for h in cfg.get("horizons") or [1, 2, 3, 5]:
        om, os = _horizon(out_proj, int(h))
        im, ins = _horizon(incoming, int(h))
        horizons[str(h)] = {
            "owned_xpts": om,
            "challenger_xpts": im,
            "projected_edge": round(im - om, 3),
            "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3),
        }
    strategic: dict[str, Any] = {}
    for h in cfg.get("strategic_horizons") or [10, 15]:
        om, os = _horizon(out_proj, int(h))
        im, ins = _horizon(incoming, int(h))
        strategic[str(h)] = {
            "owned_xpts": om,
            "challenger_xpts": im,
            "projected_edge": round(im - om, 3),
            "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3),
        }

    incoming_id = _i(incoming.get("element"))
    out_id = _i(out.get("element"))
    affordable = _i(incoming.get("now_cost"), 0) <= _i(out.get("sell_cost"), 0) + itb
    club_legal = _club_legal(owned, out, incoming)
    same_position = out.get("position") == incoming.get("position")
    package = single_packages.get((out_id, incoming_id))
    h3 = _f((horizons.get("3") or {}).get("projected_edge"))
    h5 = _f((horizons.get("5") or {}).get("projected_edge"))
    unc = _f((horizons.get("5") or {}).get("combined_uncertainty"))
    snr = h5 / unc if unc > 1e-9 else 0.0
    out_xmins = out_proj.get("xmins") or {}
    in_xmins = incoming.get("xmins") or {}
    start = _f(in_xmins.get("start_probability"))
    expected_minutes = _f(in_xmins.get("expected_minutes"))
    identity = (candidate.get("discovery") or {}).get("identity_sanity") or {"status": "PASS", "downstream_projection_trusted": True}
    tactical_out = out_proj.get("tactical_matchup") or {}
    tactical_in = incoming.get("tactical_matchup") or {}
    load_out = load_map.get(out_id) or {}
    load_in = load_map.get(incoming_id) or {}
    owned_market = _market(prices.get(out_id))
    incoming_market = _market(prices.get(incoming_id))
    out_route = _route_score(out_proj)
    in_route = _route_score(incoming)
    out_h5, _ = _horizon(out_proj, 5)
    in_h5, _ = _horizon(incoming, 5)
    out_price_m = max(_i(out.get("sell_cost"), 0) / 10.0, 0.1)
    in_price_m = max(_i(incoming.get("now_cost"), 0) / 10.0, 0.1)

    missing: list[str] = []
    constraints: list[str] = []
    if not same_position:
        constraints.append("POSITION")
    if not affordable:
        constraints.append("AFFORDABILITY")
    if not club_legal:
        constraints.append("CLUB_LIMIT")
    if not incoming:
        missing.append("canonical_projection")
    if not in_xmins:
        missing.append("canonical_xmins")
    if identity.get("downstream_projection_trusted") is False:
        missing.append("official_identity_sanity")
    if not tactical_in:
        missing.append("tactical_context")
    if not load_in:
        missing.append("competitive_load")

    pair_state = "HOLD"
    if constraints:
        pair_state = "REVIEW"
    elif h5 < _f(decision_cfg.get("review_gain_5gw"), 1.0):
        pair_state = "HOLD"
    elif missing and decision_cfg.get("missing_critical_evidence_caps_at") == "REVIEW":
        pair_state = "REVIEW"
    elif (
        h5 >= _f(decision_cfg.get("strong_gain_5gw"), 5.0)
        and h3 >= _f(decision_cfg.get("minimum_positive_3gw_for_material"), 0.5)
        and snr >= _f(decision_cfg.get("strong_minimum_signal_to_noise"), 0.85)
        and start >= _f(decision_cfg.get("strong_minimum_start_probability"), 0.75)
        and package
    ):
        pair_state = "STRONG_TRANSFER"
    elif (
        h5 >= _f(decision_cfg.get("lean_gain_5gw"), 3.0)
        and h3 >= _f(decision_cfg.get("minimum_positive_3gw_for_material"), 0.5)
        and snr >= _f(decision_cfg.get("lean_minimum_signal_to_noise"), 0.55)
        and start >= _f(decision_cfg.get("minimum_start_probability_for_transfer"), 0.60)
    ):
        pair_state = "LEAN_TRANSFER"
    else:
        pair_state = "REVIEW"

    market_timing = "MODEL_CONTEXT_ONLY"
    if incoming_market.get("fresh") and incoming_market.get("imminent"):
        market_timing = "PRICE_ACTIONABLE"
    elif owned_market.get("fresh") and owned_market.get("imminent"):
        market_timing = "OWNED_PRICE_ACTIONABLE"
    actionability = "WATCH"
    blockers = list(constraints) + list(missing)
    if pair_state == "REVIEW":
        actionability = "REVIEW"
    elif pair_state == "LEAN_TRANSFER":
        actionability = "MATERIAL_UPGRADE"
    elif pair_state == "STRONG_TRANSFER":
        actionability = "ACTIONABLE_CHANGE" if not blockers else "MATERIAL_UPGRADE"

    return {
        "player_out": {
            "element": out_id,
            "name": out.get("name"),
            "position": out.get("position"),
            "sell_cost": out.get("sell_cost"),
            "official_ownership": out.get("official_ownership"),
        },
        "player_in": {
            "element": incoming_id,
            "name": incoming.get("name"),
            "position": incoming.get("position"),
            "now_cost": incoming.get("now_cost"),
            "official_ownership": incoming.get("ownership_pct"),
        },
        "challenger_types": candidate.get("challenger_types") or [],
        "state": pair_state,
        "horizons": horizons,
        "strategic_context": strategic,
        "xmins": {
            "owned": out_xmins.get("expected_minutes"),
            "challenger": in_xmins.get("expected_minutes"),
            "edge": round(expected_minutes - _f(out_xmins.get("expected_minutes")), 3),
        },
        "start_probability": {
            "owned": out_xmins.get("start_probability"),
            "challenger": in_xmins.get("start_probability"),
            "edge": round(start - _f(out_xmins.get("start_probability")), 4),
        },
        "role": {
            "owned_penalty_role": out_proj.get("penalty_role"),
            "challenger_penalty_role": incoming.get("penalty_role"),
            "owned_set_piece_role": out_proj.get("set_piece_role"),
            "challenger_set_piece_role": incoming.get("set_piece_role"),
        },
        "tactical_matchup": {"owned": tactical_out, "challenger": tactical_in},
        "rest_congestion": {"owned": load_out, "challenger": load_in},
        "route_to_points": {
            "owned": out_route,
            "challenger": in_route,
            "edge": round(in_route["aggregate"] - out_route["aggregate"], 4),
        },
        "value": {
            "owned_xpts5_per_million_sell": round(out_h5 / out_price_m, 4),
            "challenger_xpts5_per_million": round(in_h5 / in_price_m, 4),
            "edge": round(in_h5 / in_price_m - out_h5 / out_price_m, 4),
        },
        "uncertainty": {
            "combined_5gw": round(unc, 3),
            "signal_to_noise_5gw": round(snr, 3),
        },
        "finance": {
            "exact_sell_cost": out.get("sell_cost"),
            "purchase_cost": out.get("purchase_cost"),
            "incoming_now_cost": incoming.get("now_cost"),
            "itb": itb,
            "affordable": affordable,
            "canonical_single_transfer_package": package,
            "switching_cost": (package or {}).get("hit_cost"),
            "net_projected_gain": (package or {}).get("robust_gain_vs_hold", h5),
        },
        "legality": {
            "same_position": same_position,
            "club_limit_legal": club_legal,
        },
        "identity_sanity": identity,
        "market_timing": {
            "owned": owned_market,
            "challenger": incoming_market,
            "timing_state": market_timing,
            "football_decision_authority": False,
        },
        "structural_gain": (package or {}).get("robust_gain_vs_hold"),
        "missing_critical_evidence": sorted(set(missing)),
        "constraint_failures": sorted(set(constraints)),
        "confidence": "LOW" if missing else (incoming.get("projection_confidence") or "MEDIUM"),
        "actionability": {
            "level": actionability,
            "blockers": sorted(set(blockers)),
            "market_timing": market_timing,
        },
        "reason": (
            "robust multi-GW upgrade with canonical package support"
            if actionability == "ACTIONABLE_CHANGE"
            else "material challenger edge; review package/timing gates"
            if actionability == "MATERIAL_UPGRADE"
            else "evidence review required"
            if actionability == "REVIEW"
            else "challenger does not clear robust net-gain gates"
        ),
        "flip_conditions": [
            "material 3-5 GW edge changes",
            "starter security or role changes",
            "tactical/rest evidence changes",
            "Official price or sell-value changes",
            "canonical package optimizer net gain changes",
        ],
    }


def _owned_screen(owned: list[dict[str, Any]], comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_owned: dict[int, list[dict[str, Any]]] = {}
    for pair in comparisons:
        by_owned.setdefault(_i((pair.get("player_out") or {}).get("element")), []).append(pair)
    rows: list[dict[str, Any]] = []
    for item in owned:
        eid = _i(item.get("element"))
        comps = by_owned.get(eid, [])
        legal = [
            row for row in comps
            if (row.get("finance") or {}).get("affordable")
            and (row.get("legality") or {}).get("club_limit_legal")
            and (row.get("legality") or {}).get("same_position")
        ]
        best = max(
            legal,
            key=lambda row: (
                _f((row.get("finance") or {}).get("net_projected_gain")),
                _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
            ),
            default=None,
        )
        edge5 = _f((((best or {}).get("horizons") or {}).get("5") or {}).get("projected_edge"))
        edge3 = _f((((best or {}).get("horizons") or {}).get("3") or {}).get("projected_edge"))
        proj = item.get("projection") or {}
        xmins = proj.get("xmins") or {}
        start_risk = max(0.0, 0.75 - _f(xmins.get("start_probability")))
        dnp = _f(xmins.get("dnp_probability"))
        uncertainty = _horizon(proj, 5)[1]
        pressure = max(0.0, edge5) + 1.5 * max(0.0, edge3) + 3.0 * start_risk + 2.0 * dnp + 0.25 * uncertainty
        actionability = ((best or {}).get("actionability") or {}).get("level")
        challenged = actionability in {"MATERIAL_UPGRADE", "ACTIONABLE_CHANGE"}
        rows.append({
            "element": eid,
            "name": item.get("name"),
            "position": item.get("position"),
            "owned_rank": None,
            "challenge_pressure": round(pressure, 4),
            "replacement_opportunity": round(edge5, 3) if best else None,
            "best_challenger": (best or {}).get("player_in"),
            "best_pair_state": (best or {}).get("state"),
            "best_pair_actionability": (best or {}).get("actionability"),
            "state": "CHALLENGED_OWNED" if challenged else "UNCHALLENGED",
            "confidence": (best or {}).get("confidence") or "MEDIUM",
            "ranking_basis": "replacement edge + 3GW edge + xMins/start risk + DNP + uncertainty; xPts alone forbidden",
        })
    rows.sort(key=lambda row: row["challenge_pressure"], reverse=True)
    for idx, row in enumerate(rows, start=1):
        row["owned_rank"] = idx
    return rows


def _main_battles(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [
        row for row in comparisons
        if ((row.get("actionability") or {}).get("level") in {"MATERIAL_UPGRADE", "ACTIONABLE_CHANGE", "REVIEW"})
    ]
    ranked.sort(
        key=lambda row: (
            {"ACTIONABLE_CHANGE": 4, "MATERIAL_UPGRADE": 3, "REVIEW": 2, "WATCH": 1}.get(
                str((row.get("actionability") or {}).get("level")), 0
            ),
            _f((row.get("finance") or {}).get("net_projected_gain")),
            _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
        ),
        reverse=True,
    )
    battles: list[dict[str, Any]] = []
    used_owned: set[int] = set()
    for row in ranked:
        out_id = _i((row.get("player_out") or {}).get("element"))
        if out_id in used_owned:
            continue
        used_owned.add(out_id)
        market = (row.get("market_timing") or {}).get("challenger") or {}
        battles.append({
            "owned": row.get("player_out"),
            "challenger": row.get("player_in"),
            "v3_edge": {
                "3gw": (row.get("horizons") or {}).get("3"),
                "5gw": (row.get("horizons") or {}).get("5"),
                "10_15gw": row.get("strategic_context"),
            },
            "xmins_start": {
                "xmins": row.get("xmins"),
                "start_probability": row.get("start_probability"),
            },
            "role": row.get("role"),
            "next_matchup": row.get("tactical_matchup"),
            "rest_congestion": row.get("rest_congestion"),
            "route_to_points": row.get("route_to_points"),
            "official_price": {
                "out": (row.get("player_out") or {}).get("sell_cost"),
                "in": (row.get("player_in") or {}).get("now_cost"),
            },
            "official_ownership": {
                "out": (row.get("player_out") or {}).get("official_ownership"),
                "in": (row.get("player_in") or {}).get("official_ownership"),
            },
            "predictor": row.get("market_timing"),
            "estimated_price_change": market.get("predicted_player_change_eta"),
            "next_official_price_update_window": market.get("next_official_price_update_window"),
            "structural_impact": row.get("finance"),
            "risk": row.get("missing_critical_evidence"),
            "confidence": row.get("confidence"),
            "decision": (row.get("actionability") or {}).get("level"),
            "reason": row.get("reason"),
            "flip_conditions": row.get("flip_conditions"),
        })
        if len(battles) >= 10:
            break
    return battles


def _decision(
    battles: list[dict[str, Any]],
    alternatives: list[dict[str, Any]],
    mandatory_ids: set[int],
) -> dict[str, Any]:
    cfg = load_policy().get("decision") or {}
    legal = [row for row in alternatives if row.get("legal") is not False]
    changed = [row for row in legal if _i(row.get("replacements"), 0) > 0]
    best = max(changed, key=lambda row: _f(row.get("robust_gain_vs_hold")), default=None)
    actionable = [row for row in battles if row.get("decision") == "ACTIONABLE_CHANGE"]
    material = [row for row in battles if row.get("decision") == "MATERIAL_UPGRADE"]
    mandatory_battles = [
        row for row in battles
        if _i((row.get("challenger") or {}).get("element")) in mandatory_ids
    ]
    best_gain = _f((best or {}).get("robust_gain_vs_hold"))
    if actionable and best and best_gain >= _f(cfg.get("strong_gain_5gw"), 5.0):
        state = "CHANGE"
        reason = "ROBUST_NET_GAIN_AND_CANONICAL_PACKAGE_SUPPORT"
    elif (material or mandatory_battles) and best and best_gain >= _f(cfg.get("review_gain_5gw"), 1.0):
        state = "REVIEW_NOW" if mandatory_battles else "REVIEW"
        reason = "MATERIAL_EDGE_REQUIRES_GOVERNED_REVIEW"
    elif material or mandatory_battles:
        state = "REVIEW"
        reason = "PAIR_EDGE_EXISTS_BUT_PACKAGE_NET_GAIN_NOT_ROBUST"
    else:
        state = "HOLD"
        reason = "NO_ROBUST_EXECUTABLE_TRANSFER"
    return {
        "state": state,
        "execution_authorized": False,
        "reason": reason,
        "no_transfer_recommended": state == "HOLD",
        "no_transfer_message": "NO TRANSFER RECOMMENDED" if state == "HOLD" else None,
        "selected_package_evidence": best,
        "market_timing_is_not_football_authority": True,
        "package_optimizer_is_transfer_structure_authority": True,
    }


def _fact_complete(eids: list[int], official: dict[int, dict[str, Any]]) -> tuple[bool, list[int]]:
    missing = [
        eid for eid in eids
        if not official.get(eid)
        or official[eid].get("now_cost") is None
        or official[eid].get("selected_by_percent") is None
    ]
    return not missing, missing


def _fingerprint(
    projections: dict[str, Any],
    team: dict[str, Any],
    watchlist: dict[str, Any],
    prices: dict[str, Any],
    package_optimizer: dict[str, Any],
) -> str:
    payload = {
        "planning_gw": projections.get("planning_gw"),
        "owned": sorted(_i(row.get("element")) for row in (team.get("team_value_ledger") or team.get("squad") or []) if _i(row.get("element")) > 0),
        "watchlist": sorted(_i(row.get("element")) for row in _watchlist_rows(watchlist) if _i(row.get("element")) > 0),
        "prices_generated_at": prices.get("generated_at"),
        "package_generated_at": package_optimizer.get("generated_at"),
        "watchlist_generated_at": watchlist.get("generated_at"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def build(
    *,
    watchlist: dict[str, Any] | None = None,
    discovery: dict[str, Any] | None = None,
    allow_cached: bool = True,
) -> dict[str, Any]:
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    prices_payload = read_json(DATA / "prices.json", {})
    packages_payload = read_json(DATA / "package_optimizer.json", {})
    snapshot = read_json(DATA / "official_snapshot.json", {})
    watchlist = dict(watchlist or read_json(DATA / "dss_watchlist.json", {}))
    discovery = dict(discovery or watchlist.get("challenger_discovery") or {})
    if not discovery:
        from src.engines.challenger_discovery import build as build_discovery
        discovery = build_discovery()

    fingerprint = _fingerprint(projections, team, watchlist, prices_payload, packages_payload)
    cached = watchlist.get("owned_challenger_decision") or {}
    if (
        allow_cached
        and cached.get("contract") == "OWNED_CHALLENGER_DECISION_V3"
        and cached.get("input_fingerprint") == fingerprint
        and ((cached.get("publication_validation") or {}).get("status") == "PASS")
    ):
        return cached

    pmap = _projection_map(projections)
    official = _official_map(snapshot)
    owned = _owned(team, pmap, official)
    owned_ids = {_i(row.get("element")) for row in owned}
    visible_rows = _watchlist_rows(watchlist)
    visible_ids = [_i(row.get("element")) for row in visible_rows if _i(row.get("element")) > 0]
    candidate_index = _candidate_index(discovery, watchlist, pmap, official)
    alternatives = _package_alternatives(packages_payload)
    single_packages = _single_package_map(alternatives)
    price_map = _price_index(prices_payload)
    load_map = _competitive_load_map()
    itb = _team_itb(team)

    comparisons: list[dict[str, Any]] = []
    for candidate in candidate_index.values():
        incoming = candidate.get("projection") or {}
        position = incoming.get("position")
        for out in owned:
            if out.get("position") != position:
                continue
            comparisons.append(_compare(
                out,
                candidate,
                owned=owned,
                itb=itb,
                prices=price_map,
                single_packages=single_packages,
                load_map=load_map,
            ))

    pair_rank = {"STRONG_TRANSFER": 5, "LEAN_TRANSFER": 4, "REVIEW": 3, "WATCH": 2, "HOLD": 1}
    comparisons.sort(
        key=lambda row: (
            pair_rank.get(str(row.get("state")), 0),
            _f((row.get("finance") or {}).get("net_projected_gain")),
            _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
        ),
        reverse=True,
    )
    owned_screening = _owned_screen(owned, comparisons)
    battles = _main_battles(comparisons)
    mandatory_ids = {
        _i(eid) for eid in discovery.get("mandatory_review_element_ids") or []
        if _i(eid) > 0
    }
    evaluated_ids = {
        _i((row.get("player_in") or {}).get("element"))
        for row in comparisons
        if _i((row.get("player_in") or {}).get("element")) > 0
    }
    decision = _decision(battles, alternatives, mandatory_ids)

    position_counts = {
        position: len((watchlist.get("positions") or {}).get(position) or [])
        for position in POSITIONS
    }
    owned_fact_ok, owned_fact_missing = _fact_complete(sorted(owned_ids), official)
    watch_fact_ok, watch_fact_missing = _fact_complete(visible_ids, official)
    no_overlap = not (owned_ids & set(visible_ids))
    mandatory_covered = mandatory_ids <= evaluated_ids
    blockers: list[str] = []
    if len(owned_screening) != 15:
        blockers.append("OWNED_15_SCREENING_INCOMPLETE")
    if len(visible_ids) != 20 or any(position_counts.get(pos) != 5 for pos in POSITIONS):
        blockers.append("VISIBLE_WATCHLIST_5_PER_POSITION_INCOMPLETE")
    if not no_overlap:
        blockers.append("OWNED_WATCHLIST_OVERLAP")
    if not owned_fact_ok:
        blockers.append("OWNED_OFFICIAL_FACT_INCOMPLETE")
    if not watch_fact_ok:
        blockers.append("WATCHLIST_OFFICIAL_FACT_INCOMPLETE")
    if not mandatory_covered:
        blockers.append("MANDATORY_CHALLENGER_MISSING_FROM_EVALUATION")

    publication_validation = {
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": blockers,
        "owned_expected": 15,
        "owned_screened": len(owned_screening),
        "visible_watchlist_expected": 20,
        "visible_watchlist_screened": len(visible_ids),
        "position_counts": position_counts,
        "owned_watchlist_overlap": sorted(owned_ids & set(visible_ids)),
        "mandatory_expected_ids": sorted(mandatory_ids),
        "mandatory_evaluated_ids": sorted(mandatory_ids & evaluated_ids),
        "mandatory_complete": mandatory_covered,
        "official_fact_completeness": {
            "owned": {"complete": owned_fact_ok, "missing_ids": owned_fact_missing},
            "watchlist": {"complete": watch_fact_ok, "missing_ids": watch_fact_missing},
        },
        "data_join_defect_internal_only": True,
    }
    if blockers:
        decision = {
            **decision,
            "state": "BLOCKED",
            "execution_authorized": False,
            "reason": "PUBLICATION_VALIDATION_FAILED",
        }

    lifecycle: dict[str, str] = {}
    for eid, candidate in candidate_index.items():
        material_pairs = [
            row for row in comparisons
            if _i((row.get("player_in") or {}).get("element")) == eid
            and ((row.get("actionability") or {}).get("level") in {"MATERIAL_UPGRADE", "ACTIONABLE_CHANGE"})
        ]
        route = candidate.get("discovery") or {}
        if material_pairs:
            lifecycle[str(eid)] = "ACTIVE_CHALLENGER"
        elif route:
            lifecycle[str(eid)] = "EMERGING_CHALLENGER"
        else:
            lifecycle[str(eid)] = "DISCOVERED"

    result = {
        "schema_version": 5,
        "contract": "OWNED_CHALLENGER_DECISION_V3",
        "generated_at": iso_now(),
        "owner": "decision.owned_challenger_evaluation",
        "status": "READY" if not blockers else "BLOCKED",
        "input_fingerprint": fingerprint,
        "owned_count": len(owned),
        "governed_watchlist_count": len(visible_ids),
        "full_universe_count": discovery.get("universe_count"),
        "material_candidate_count": discovery.get("material_candidate_count"),
        "mandatory_review_count": len(mandatory_ids),
        "comparison_count": len(comparisons),
        "owned_screening": owned_screening,
        "challenged_owned": [row for row in owned_screening if row.get("state") == "CHALLENGED_OWNED"],
        "pairwise_matrix": comparisons,
        "top_comparisons": comparisons[:40],
        "multi_transfer_alternatives": alternatives,
        "main_transfer_battles": battles,
        "challenger_lifecycle": lifecycle,
        "decision": decision,
        "v3_view": {
            "status": "READY" if not blockers else "BLOCKED",
            "decision": decision.get("state"),
            "confidence": "GOVERNED_BY_PAIR_AND_PACKAGE_EVIDENCE",
        },
        "publication_validation": publication_validation,
        "state_counts": {
            state: sum(1 for row in comparisons if row.get("state") == state)
            for state in load_policy().get("pair_states") or []
        },
        "actionability_counts": {
            state: sum(1 for row in comparisons if (row.get("actionability") or {}).get("level") == state)
            for state in load_policy().get("actionability_states") or []
        },
        "governance": {
            **(load_policy().get("governance") or {}),
            "all_15_screened": len(owned_screening) == 15,
            "full_universe_discovery_consumed": bool(discovery),
            "mandatory_candidates_cannot_disappear": mandatory_covered,
            "weakest_link_is_not_lowest_xpts_alone": True,
            "no_player_specific_out_hardcode": True,
            "price_timing_not_decision_authority": True,
            "weather_alone_cannot_transfer": True,
            "data_join_defect_internal_only": True,
            "canonical_package_optimizer_is_multi_transfer_authority": True,
            "reporting_reuses_persisted_decision": True,
        },
    }
    return result


def run() -> dict[str, Any]:
    result = build(allow_cached=False)
    if (result.get("publication_validation") or {}).get("status") != "PASS":
        raise RuntimeError("FAIL CLOSED: owned challenger publication validation failed")
    atomic_json(OUT, result)
    latest = read_json(DATA / "latest.json", {})
    latest["owned_challenger_comparator"] = {
        "status": result.get("status"),
        "owned_count": result.get("owned_count"),
        "governed_watchlist_count": result.get("governed_watchlist_count"),
        "full_universe_count": result.get("full_universe_count"),
        "mandatory_review_count": result.get("mandatory_review_count"),
        "comparison_count": result.get("comparison_count"),
        "challenged_owned_count": len(result.get("challenged_owned") or []),
        "decision": (result.get("decision") or {}).get("state"),
        "publication_validation": (result.get("publication_validation") or {}).get("status"),
    }
    atomic_json(DATA / "latest.json", latest)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
