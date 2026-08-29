from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
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
    for ledger in team.get("team_value_ledger") or []:
        element = _i(ledger.get("element"))
        proj = pmap.get(element)
        if not proj:
            continue
        rows.append({
            "element": element,
            "name": ledger.get("name") or proj.get("name"),
            "position": proj.get("position"),
            "team_id": _i(proj.get("team_id")),
            "sell_cost": _i(ledger.get("sell_cost", proj.get("now_cost")), 0),
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
    out_tid = _i(out.get("team_id"))
    in_tid = _i(incoming.get("team_id"))
    counts[out_tid] = max(0, counts.get(out_tid, 0) - 1)
    counts[in_tid] = counts.get(in_tid, 0) + 1
    return max(counts.values(), default=0) <= 3


def _package_map(payload: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    hold = _f((((payload.get("hold") or {}).get("score") or {}).get("robust_score")))
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for package in payload.get("packages") or []:
        if package.get("legal") is not True or (package.get("score") or {}).get("valid") is not True:
            continue
        outs = package.get("outs") or []
        ins = package.get("ins") or []
        if len(outs) != 1 or len(ins) != 1:
            continue
        key = (_i(outs[0].get("element")), _i(ins[0].get("element")))
        robust = _f((package.get("score") or {}).get("robust_score"))
        out[key] = {
            "package_id": package.get("id"),
            "robust_gain_vs_hold": round(robust - hold, 3),
            "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
            "legal": True,
        }
    return out


def _match_stats() -> dict[int, dict[str, float]]:
    payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    out: dict[int, dict[str, float]] = {}
    for row in payload.get("rows") or []:
        element = _i(row.get("player_id"))
        if element <= 0:
            continue
        agg = out.setdefault(element, {"returns": 0.0, "xgi": 0.0, "shots": 0.0, "box_touches": 0.0, "chances_created": 0.0})
        agg["returns"] += _f(row.get("goals")) + _f(row.get("assists"))
        agg["xgi"] += _f(row.get("xg")) + _f(row.get("xa"))
        agg["shots"] += _f(row.get("total_shots"))
        agg["box_touches"] += _f(row.get("touches_opposition_box"))
        agg["chances_created"] += _f(row.get("chances_created"))
    return out


def _emerging_candidates(pmap: dict[int, dict[str, Any]], excluded: set[int]) -> list[tuple[dict[str, Any], list[str], bool]]:
    cfg = load_policy().get("emerging_screen") or {}
    stats = _match_stats()
    rows: list[tuple[dict[str, Any], list[str], bool]] = []
    for element, proj in pmap.items():
        if element in excluded or str(proj.get("status")) not in set(cfg.get("allowed_statuses") or []):
            continue
        xmins = proj.get("xmins") or {}
        h5, _ = _horizon(proj, 5)
        if _f(xmins.get("expected_minutes")) < _f(cfg.get("minimum_expected_minutes"), 50):
            continue
        if _f(xmins.get("start_probability")) < _f(cfg.get("minimum_start_probability"), 0.45):
            continue
        if _f(xmins.get("dnp_probability")) > _f(cfg.get("maximum_dnp_probability"), 0.35):
            continue
        if h5 < _f(cfg.get("minimum_h5_points"), 12):
            continue
        s = stats.get(element) or {}
        triggers: list[str] = []
        if _f(s.get("returns")) >= _f(cfg.get("strong_match_return_trigger"), 2): triggers.append("MULTIPLE_MATCH_RETURNS")
        if _f(s.get("xgi")) >= _f(cfg.get("strong_xgi_trigger"), 0.75): triggers.append("STRONG_XGI")
        if _f(s.get("shots")) >= _f(cfg.get("shots_trigger"), 4): triggers.append("HIGH_SHOT_VOLUME")
        if _f(s.get("box_touches")) >= _f(cfg.get("box_touches_trigger"), 8): triggers.append("HIGH_BOX_INVOLVEMENT")
        if _f(s.get("chances_created")) >= _f(cfg.get("chances_created_trigger"), 4): triggers.append("HIGH_CHANCE_CREATION")
        sustainable = len(set(triggers)) >= _i(cfg.get("sustainable_minimum_trigger_count"), 2) and _f(xmins.get("start_probability")) >= _f(cfg.get("sustainable_minimum_start_probability"), 0.60)
        if triggers:
            rows.append((proj, sorted(set(triggers)), sustainable))
    rows.sort(key=lambda item: _horizon(item[0], 5)[0], reverse=True)
    return rows[: _i(cfg.get("max_candidates"), 12)]


def _external_state(external: dict[str, Any], element: int) -> dict[str, Any]:
    matches = []
    for subject in external.get("subjects") or []:
        text = json.dumps(subject, ensure_ascii=False)
        if str(element) in text:
            matches.append({"subject": subject.get("subject"), "classification": subject.get("classification")})
    return {
        "overall": external.get("overall") or "INSUFFICIENT_EVIDENCE",
        "player_specific": matches,
        "advisory_only": True,
    }


def _critical_evidence(out: dict[str, Any], incoming: dict[str, Any], affordable: bool, club_legal: bool, external: dict[str, Any]) -> dict[str, str]:
    out_proj = out.get("projection") or {}
    tactical = incoming.get("tactical_matchup") or {}
    load = read_json(DATA / "recent_competitive_load.json", {})
    load_rows = load.get("players") or {}
    load_available = str(incoming.get("element")) in load_rows or _i(incoming.get("element")) in load_rows
    ext = _external_state(external, _i(incoming.get("element")))
    return {
        "canonical_projection": "AVAILABLE" if out_proj and incoming else "UNAVAILABLE",
        "canonical_xmins": "AVAILABLE" if out_proj.get("xmins") and incoming.get("xmins") else "UNAVAILABLE",
        "same_position": "AVAILABLE" if out_proj.get("position") == incoming.get("position") else "UNAVAILABLE",
        "exact_sell_value": "AVAILABLE" if out.get("sell_cost") is not None else "UNAVAILABLE",
        "affordability": "AVAILABLE" if affordable else "CONSTRAINT_FAILED",
        "club_legality": "AVAILABLE" if club_legal else "CONSTRAINT_FAILED",
        "tactical_context": "AVAILABLE" if tactical else "PARTIAL",
        "competitive_load": "AVAILABLE" if load_available else "UNAVAILABLE",
        "external_consensus": "AVAILABLE" if ext["overall"] != "INSUFFICIENT_EVIDENCE" else "UNAVAILABLE",
    }


def _compare(out: dict[str, Any], incoming: dict[str, Any], challenger_type: str, triggers: list[str], sustainable: bool, owned: list[dict[str, Any]], itb: int, packages: dict[tuple[int, int], dict[str, Any]], external: dict[str, Any]) -> dict[str, Any]:
    cfg = load_policy()
    decision_cfg = cfg.get("decision") or {}
    out_proj = out.get("projection") or {}
    horizons: dict[str, Any] = {}
    for h in cfg.get("horizons") or [1, 2, 3, 5]:
        om, os = _horizon(out_proj, int(h))
        im, ins = _horizon(incoming, int(h))
        horizons[str(h)] = {"owned_xpts": om, "challenger_xpts": im, "projected_edge": round(im - om, 3), "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3)}
    strategic = {}
    for h in cfg.get("strategic_horizons") or [10, 15]:
        om, os = _horizon(out_proj, int(h)); im, ins = _horizon(incoming, int(h))
        strategic[str(h)] = {"owned_xpts": om, "challenger_xpts": im, "projected_edge": round(im - om, 3), "combined_uncertainty": round(math.sqrt(os * os + ins * ins), 3)}

    affordable = _i(incoming.get("now_cost"), 0) <= _i(out.get("sell_cost"), 0) + itb
    club_legal = _club_legal(owned, out, incoming)
    package = packages.get((_i(out.get("element")), _i(incoming.get("element"))))
    h5 = horizons.get("5") or {}
    edge = _f(h5.get("projected_edge")); unc = _f(h5.get("combined_uncertainty")); snr = edge / unc if unc > 1e-9 else 0.0
    start_p = _f((incoming.get("xmins") or {}).get("start_probability"))
    evidence = _critical_evidence(out, incoming, affordable, club_legal, external)
    missing = [k for k, v in evidence.items() if v in {"UNAVAILABLE", "PARTIAL"}]
    constraints_failed = [k for k, v in evidence.items() if v == "CONSTRAINT_FAILED"]

    state = "HOLD"
    if challenger_type == "EMERGING_CHALLENGER" and not sustainable:
        state = "WATCH"
    elif constraints_failed:
        state = "REVIEW"
    elif edge < _f(decision_cfg.get("review_gain_5gw"), 1.0):
        state = "HOLD"
    elif missing and decision_cfg.get("missing_critical_evidence_caps_at") == "REVIEW":
        state = "REVIEW"
    elif edge >= _f(decision_cfg.get("strong_gain_5gw"), 5.0) and snr >= _f(decision_cfg.get("strong_minimum_signal_to_noise"), 0.85) and start_p >= _f(decision_cfg.get("strong_minimum_start_probability"), 0.75) and package:
        state = "STRONG_TRANSFER"
    elif edge >= _f(decision_cfg.get("lean_gain_5gw"), 3.0) and snr >= _f(decision_cfg.get("lean_minimum_signal_to_noise"), 0.55) and start_p >= _f(decision_cfg.get("minimum_start_probability_for_transfer"), 0.60):
        state = "LEAN_TRANSFER"
    else:
        state = "REVIEW"

    return {
        "player_out": {"element": out.get("element"), "name": out.get("name"), "position": out.get("position"), "sell_cost": out.get("sell_cost")},
        "player_in": {"element": incoming.get("element"), "name": incoming.get("name"), "position": incoming.get("position"), "now_cost": incoming.get("now_cost")},
        "challenger_type": challenger_type,
        "state": state,
        "horizons": horizons,
        "strategic_context": strategic,
        "xmins": {"owned": (out_proj.get("xmins") or {}).get("expected_minutes"), "challenger": (incoming.get("xmins") or {}).get("expected_minutes")},
        "start_probability": {"owned": (out_proj.get("xmins") or {}).get("start_probability"), "challenger": (incoming.get("xmins") or {}).get("start_probability")},
        "role_security": {"owned_dnp": (out_proj.get("xmins") or {}).get("dnp_probability"), "challenger_dnp": (incoming.get("xmins") or {}).get("dnp_probability")},
        "tactical_matchup": incoming.get("tactical_matchup") or {"evidence_state": "UNAVAILABLE"},
        "underlying": {"owned_rates": out_proj.get("rates") or {}, "challenger_rates": incoming.get("rates") or {}},
        "set_piece_penalty": {"owned_penalty_role": out_proj.get("penalty_role"), "challenger_penalty_role": incoming.get("penalty_role"), "owned_set_piece_role": out_proj.get("set_piece_role"), "challenger_set_piece_role": incoming.get("set_piece_role")},
        "finance": {"exact_sell_cost": out.get("sell_cost"), "incoming_now_cost": incoming.get("now_cost"), "itb": itb, "affordable": affordable, "canonical_package": package},
        "legality": {"same_position": out.get("position") == incoming.get("position"), "club_limit_legal": club_legal},
        "price_urgency": "MODEL_CONTEXT_ONLY",
        "external_consensus": _external_state(external, _i(incoming.get("element"))),
        "emerging_triggers": triggers,
        "anti_haul_chasing": {"single_haul_is_not_sufficient": True, "sustainable_candidate": sustainable if challenger_type == "EMERGING_CHALLENGER" else None},
        "uncertainty": {"signal_to_noise_5gw": round(snr, 3), "combined_5gw": unc},
        "critical_evidence": evidence,
        "missing_critical_evidence": missing,
        "confidence": "LOW" if missing else (incoming.get("projection_confidence") or "MEDIUM"),
        "advisory_only": True,
    }


def build() -> dict[str, Any]:
    cfg = load_policy()
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    external = read_json(DATA / "external_consensus.json", {})
    pmap = _projection_map(projections)
    owned = _owned(team, pmap)
    owned_ids = {int(row["element"]) for row in owned}
    governed_ids = _watchlist_ids(watchlist)
    packages = _package_map(package_optimizer)
    itb = _team_itb(team)

    comparisons: list[dict[str, Any]] = []
    for element in governed_ids:
        incoming = pmap.get(element)
        if not incoming:
            continue
        targets = [row for row in owned if row.get("position") == incoming.get("position")]
        targets.sort(key=lambda row: _horizon(row.get("projection") or {}, 5)[0])
        for out in targets[: _i((cfg.get("owned_targeting") or {}).get("max_owned_targets_per_challenger"), 3)]:
            comparisons.append(_compare(out, incoming, "GOVERNED_WATCHLIST", [], True, owned, itb, packages, external))

    excluded = owned_ids | set(governed_ids)
    emerging = _emerging_candidates(pmap, excluded)
    for incoming, triggers, sustainable in emerging:
        targets = [row for row in owned if row.get("position") == incoming.get("position")]
        targets.sort(key=lambda row: _horizon(row.get("projection") or {}, 5)[0])
        for out in targets[: _i((cfg.get("owned_targeting") or {}).get("max_owned_targets_per_challenger"), 3)]:
            comparisons.append(_compare(out, incoming, "EMERGING_CHALLENGER", triggers, sustainable, owned, itb, packages, external))

    rank = {"STRONG_TRANSFER": 5, "LEAN_TRANSFER": 4, "REVIEW": 3, "WATCH": 2, "HOLD": 1}
    comparisons.sort(key=lambda row: (rank.get(str(row.get("state")), 0), _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge"))), reverse=True)
    result = {
        "schema_version": 2,
        "contract": "OWNED_CHALLENGER_COMPARATOR_V2",
        "generated_at": iso_now(),
        "owner": cfg.get("owner"),
        "status": "READY",
        "advisory_only": True,
        "owned_count": len(owned),
        "governed_watchlist_count": len(governed_ids),
        "emerging_candidate_count": len(emerging),
        "comparison_count": len(comparisons),
        "state_counts": {state: sum(1 for row in comparisons if row.get("state") == state) for state in cfg.get("output_states") or []},
        "top_comparisons": comparisons[:40],
        "governance": cfg.get("governance"),
    }
    return result


def run() -> dict[str, Any]:
    result = build()
    atomic_json(OUT, result)
    latest = read_json(DATA / "latest.json", {})
    latest["owned_challenger_comparator"] = {
        "status": result.get("status"),
        "owned_count": result.get("owned_count"),
        "governed_watchlist_count": result.get("governed_watchlist_count"),
        "emerging_candidate_count": result.get("emerging_candidate_count"),
        "comparison_count": result.get("comparison_count"),
        "state_counts": result.get("state_counts"),
        "advisory_only": True,
    }
    latest.setdefault("files", {})["owned_challenger_comparator"] = "data/owned_challenger_comparator.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["owned_challenger_comparator"], ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
