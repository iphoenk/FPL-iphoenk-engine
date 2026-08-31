from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, iso_now, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "owned_challenger_comparator.json"
OUT = DATA / "owned_challenger_comparator.json"

POSITION_ORDER = ("GK", "DEF", "MID", "FWD")
TERMINAL_DECISIONS = {"HOLD", "REVIEW", "REVIEW_NOW", "CHANGE", "BLOCKED"}


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
        int(row["element"]): row
        for row in payload.get("players") or []
        if row.get("element") is not None
    }


def _horizon(proj: dict[str, Any], horizon: int) -> tuple[float, float]:
    rows = list(proj.get("xpts_by_gw") or [])[: max(0, int(horizon))]
    return (
        round(sum(_f(row.get("mean")) for row in rows), 3),
        round(math.sqrt(sum(_f(row.get("std")) ** 2 for row in rows)), 3),
    )


def _watchlist_rows(watchlist: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in POSITION_ORDER:
        for row in (watchlist.get("positions") or {}).get(position) or []:
            element = _i(row.get("element"))
            if element > 0:
                rows.append({**row, "element": element, "position": row.get("position") or position})
    return rows


def _owned(team: dict[str, Any], pmap: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ledger in team.get("team_value_ledger") or []:
        element = _i(ledger.get("element"))
        proj = pmap.get(element)
        if not proj:
            continue
        rows.append(
            {
                "element": element,
                "name": ledger.get("name") or proj.get("name"),
                "position": proj.get("position"),
                "team_id": _i(proj.get("team_id")),
                "sell_cost": _i(ledger.get("sell_cost", proj.get("now_cost")), 0),
                "now_cost": _i(ledger.get("now_cost", proj.get("now_cost")), 0),
                "projection": proj,
            }
        )
    return rows


def _team_itb(team: dict[str, Any]) -> int:
    return _i((team.get("totals") or {}).get("itb", team.get("itb")), 0)


def _club_legal(
    owned: list[dict[str, Any]], out: dict[str, Any], incoming: dict[str, Any]
) -> bool:
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


def _price_map() -> dict[int, dict[str, Any]]:
    payload = read_json(DATA / "prices.json", {})
    rows = payload.get("players") or payload.get("rows") or []
    return {
        _i(row.get("element", row.get("element_id"))): row
        for row in rows
        if _i(row.get("element", row.get("element_id"))) > 0
    }


def _market_view(price: dict[str, Any] | None) -> dict[str, Any]:
    row = price or {}
    return {
        "official_price": row.get("current_price"),
        "now_cost": row.get("now_cost"),
        "ownership_percent": row.get("ownership_percent", row.get("ownership_pct")),
        "net_transfers": row.get("net_transfers"),
        "direction": row.get("direction", row.get("risk_direction")),
        "progress_percent": row.get("current_progress_percent", row.get("official_progress_pct")),
        "trajectory": row.get("trajectory"),
        "model_urgency": row.get("model_urgency", row.get("urgency")),
        "predicted_change_cycle": row.get("predicted_change_cycle"),
        "predicted_change_at": row.get("predicted_change_at", row.get("predicted_change_deadline")),
        "next_official_price_update_at": row.get("next_official_price_update_at"),
        "eta_human": row.get("eta_human"),
        "evidence_state": row.get("evidence_state", row.get("official_projection_health")),
        "confidence": row.get("confidence"),
        "source": row.get("source"),
        "confirmed_price_change": row.get("confirmed_price_change"),
        "narrative": row.get("narrative"),
    }


def _package_maps(payload: dict[str, Any]) -> tuple[dict[tuple[int, int], dict[str, Any]], list[dict[str, Any]]]:
    hold = _f((((payload.get("hold") or {}).get("score") or {}).get("robust_score")))
    singles: dict[tuple[int, int], dict[str, Any]] = {}
    multi: list[dict[str, Any]] = []
    for package in payload.get("packages") or []:
        if package.get("legal") is not True or (package.get("score") or {}).get("valid") is not True:
            continue
        outs = [row for row in package.get("outs") or [] if row.get("element") is not None]
        ins = [row for row in package.get("ins") or [] if row.get("element") is not None]
        robust = _f((package.get("score") or {}).get("robust_score"))
        summary = {
            "package_id": package.get("id"),
            "outs": [{"element": _i(x.get("element")), "name": x.get("name")} for x in outs],
            "ins": [{"element": _i(x.get("element")), "name": x.get("name")} for x in ins],
            "changes": max(len(outs), len(ins)),
            "robust_gain_vs_hold": round(robust - hold, 3),
            "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
            "legal": True,
            "score": package.get("score"),
            "hit_cost": package.get("hit_cost"),
        }
        if len(outs) == 1 and len(ins) == 1:
            singles[(_i(outs[0].get("element")), _i(ins[0].get("element")))] = summary
        if len(outs) >= 2 and len(outs) == len(ins):
            multi.append(summary)
    multi.sort(key=lambda row: _f(row.get("robust_gain_vs_hold")), reverse=True)
    return singles, multi


def _match_stats() -> dict[int, dict[str, float]]:
    payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    out: dict[int, dict[str, float]] = {}
    for row in payload.get("rows") or []:
        element = _i(row.get("player_id"))
        if element <= 0:
            continue
        agg = out.setdefault(
            element,
            {
                "returns": 0.0,
                "xgi": 0.0,
                "shots": 0.0,
                "box_touches": 0.0,
                "chances_created": 0.0,
            },
        )
        agg["returns"] += _f(row.get("goals")) + _f(row.get("assists"))
        agg["xgi"] += _f(row.get("xg")) + _f(row.get("xa"))
        agg["shots"] += _f(row.get("total_shots"))
        agg["box_touches"] += _f(row.get("touches_opposition_box"))
        agg["chances_created"] += _f(row.get("chances_created"))
    return out


def _emerging_candidates(
    pmap: dict[int, dict[str, Any]], excluded: set[int]
) -> list[tuple[dict[str, Any], list[str], bool]]:
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
        if _f(s.get("returns")) >= _f(cfg.get("strong_match_return_trigger"), 2):
            triggers.append("MULTIPLE_MATCH_RETURNS")
        if _f(s.get("xgi")) >= _f(cfg.get("strong_xgi_trigger"), 0.75):
            triggers.append("STRONG_XGI")
        if _f(s.get("shots")) >= _f(cfg.get("shots_trigger"), 4):
            triggers.append("HIGH_SHOT_VOLUME")
        if _f(s.get("box_touches")) >= _f(cfg.get("box_touches_trigger"), 8):
            triggers.append("HIGH_BOX_INVOLVEMENT")
        if _f(s.get("chances_created")) >= _f(cfg.get("chances_created_trigger"), 4):
            triggers.append("HIGH_CHANCE_CREATION")
        sustainable = (
            len(set(triggers)) >= _i(cfg.get("sustainable_minimum_trigger_count"), 2)
            and _f(xmins.get("start_probability"))
            >= _f(cfg.get("sustainable_minimum_start_probability"), 0.60)
        )
        if triggers:
            rows.append((proj, sorted(set(triggers)), sustainable))
    rows.sort(key=lambda item: _horizon(item[0], 5)[0], reverse=True)
    return rows[: _i(cfg.get("max_candidates"), 12)]


def _external_state(external: dict[str, Any], element: int) -> dict[str, Any]:
    matches = []
    for subject in external.get("subjects") or []:
        if str(element) in json.dumps(subject, ensure_ascii=False):
            matches.append(
                {
                    "subject": subject.get("subject"),
                    "classification": subject.get("classification"),
                }
            )
    return {
        "overall": external.get("overall") or "INSUFFICIENT_EVIDENCE",
        "player_specific": matches,
        "advisory_only": True,
    }


def _competitive_load(element: int) -> dict[str, Any]:
    payload = read_json(DATA / "recent_competitive_load.json", {})
    rows = payload.get("players") or {}
    return rows.get(str(element)) or rows.get(element) or {}


def _critical_evidence(
    out: dict[str, Any],
    incoming: dict[str, Any],
    affordable: bool,
    club_legal: bool,
    external: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, str]:
    out_proj = out.get("projection") or {}
    tactical = incoming.get("tactical_matchup") or {}
    load_available = bool(_competitive_load(_i(incoming.get("element"))))
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
        "market_context": "AVAILABLE" if market.get("evidence_state") not in {None, "FIELD_MISSING", "SCHEMA_CHANGED"} else "UNAVAILABLE",
        "external_consensus": "AVAILABLE" if ext["overall"] != "INSUFFICIENT_EVIDENCE" else "UNAVAILABLE",
    }


def _route_to_points(proj: dict[str, Any]) -> dict[str, Any]:
    rates = proj.get("rates") or {}
    return {
        "xg90": rates.get("xg90"),
        "xa90": rates.get("xa90"),
        "bps90": rates.get("bps90"),
        "def_actions90": rates.get("def_actions90"),
        "penalty_role": proj.get("penalty_role"),
        "set_piece_role": proj.get("set_piece_role"),
    }


def _decision_state(
    *,
    h3_edge: float,
    h5_edge: float,
    snr: float,
    start_probability: float,
    affordable: bool,
    club_legal: bool,
    missing: list[str],
    market: dict[str, Any],
    package: dict[str, Any] | None,
    sustainable: bool,
    challenger_type: str,
) -> tuple[str, list[str]]:
    cfg = load_policy().get("decision") or {}
    blockers: list[str] = []
    if not affordable:
        blockers.append("NOT_AFFORDABLE")
    if not club_legal:
        blockers.append("CLUB_LIMIT")
    if start_probability < _f(cfg.get("minimum_start_probability_for_change"), 0.60):
        blockers.append("START_SECURITY")
    if missing and cfg.get("missing_critical_evidence_caps_change", True):
        blockers.append("CRITICAL_EVIDENCE")
    if challenger_type == "EMERGING_CHALLENGER" and not sustainable:
        return "HOLD", ["UNSUSTAINABLE_EMERGING_SIGNAL"]
    if not affordable or not club_legal:
        return "BLOCKED", sorted(set(blockers))
    review_edge = _f(cfg.get("review_gain_5gw"), 1.0)
    review_now_edge = _f(cfg.get("review_now_gain_5gw"), 3.0)
    change_edge = _f(cfg.get("change_gain_5gw"), 5.0)
    change_snr = _f(cfg.get("change_minimum_signal_to_noise"), 0.85)
    min_h3 = _f(cfg.get("minimum_positive_3gw_for_change"), 0.5)
    timing_ready = (
        market.get("model_urgency") in set(cfg.get("market_actionable_urgencies") or ["CRITICAL", "HIGH"])
        or market.get("predicted_change_cycle") == "NEXT_UPDATE"
    )
    if h5_edge < review_edge:
        return "HOLD", sorted(set(blockers))
    if h5_edge >= change_edge and h3_edge >= min_h3 and snr >= change_snr and not blockers:
        if cfg.get("change_requires_canonical_package", True) and not package:
            return "REVIEW_NOW" if timing_ready else "REVIEW", ["CANONICAL_PACKAGE_NOT_FOUND"]
        return "CHANGE", []
    if h5_edge >= review_now_edge and (timing_ready or package):
        return "REVIEW_NOW", sorted(set(blockers))
    return "REVIEW", sorted(set(blockers))


def _compare(
    out: dict[str, Any],
    incoming: dict[str, Any],
    challenger_type: str,
    triggers: list[str],
    sustainable: bool,
    owned: list[dict[str, Any]],
    itb: int,
    packages: dict[tuple[int, int], dict[str, Any]],
    external: dict[str, Any],
    price_rows: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    cfg = load_policy()
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
    affordable = _i(incoming.get("now_cost"), 0) <= _i(out.get("sell_cost"), 0) + itb
    club_legal = _club_legal(owned, out, incoming)
    package = packages.get((_i(out.get("element")), _i(incoming.get("element"))))
    h3 = horizons.get("3") or {}
    h5 = horizons.get("5") or {}
    edge3 = _f(h3.get("projected_edge"))
    edge5 = _f(h5.get("projected_edge"))
    unc = _f(h5.get("combined_uncertainty"))
    snr = edge5 / unc if unc > 1e-9 else 0.0
    start_p = _f((incoming.get("xmins") or {}).get("start_probability"))
    incoming_market = _market_view(price_rows.get(_i(incoming.get("element"))))
    owned_market = _market_view(price_rows.get(_i(out.get("element"))))
    evidence = _critical_evidence(out, incoming, affordable, club_legal, external, incoming_market)
    missing = [k for k, v in evidence.items() if v in {"UNAVAILABLE", "PARTIAL"}]
    state, blockers = _decision_state(
        h3_edge=edge3,
        h5_edge=edge5,
        snr=snr,
        start_probability=start_p,
        affordable=affordable,
        club_legal=club_legal,
        missing=missing,
        market=incoming_market,
        package=package,
        sustainable=sustainable,
        challenger_type=challenger_type,
    )
    if state not in TERMINAL_DECISIONS:
        raise RuntimeError(f"invalid challenger decision state: {state}")
    net_gain = None
    net_gain_source = "UNAVAILABLE"
    if package and package.get("robust_gain_vs_hold") is not None:
        net_gain = package.get("robust_gain_vs_hold")
        net_gain_source = "CANONICAL_PACKAGE_OPTIMIZER_ROBUST_GAIN_VS_HOLD"
    return {
        "player_out": {
            "element": out.get("element"),
            "name": out.get("name"),
            "position": out.get("position"),
            "sell_cost": out.get("sell_cost"),
        },
        "player_in": {
            "element": incoming.get("element"),
            "name": incoming.get("name"),
            "position": incoming.get("position"),
            "now_cost": incoming.get("now_cost"),
        },
        "challenger_type": challenger_type,
        "lifecycle_state": "EMERGING_CHALLENGER" if challenger_type == "EMERGING_CHALLENGER" else "ACTIVE_CHALLENGER",
        "decision": state,
        "state": state,
        "horizons": horizons,
        "strategic_context": strategic,
        "xmins": {
            "owned": (out_proj.get("xmins") or {}).get("expected_minutes"),
            "challenger": (incoming.get("xmins") or {}).get("expected_minutes"),
        },
        "start_probability": {
            "owned": (out_proj.get("xmins") or {}).get("start_probability"),
            "challenger": (incoming.get("xmins") or {}).get("start_probability"),
        },
        "role_security": {
            "owned_dnp": (out_proj.get("xmins") or {}).get("dnp_probability"),
            "challenger_dnp": (incoming.get("xmins") or {}).get("dnp_probability"),
        },
        "route_to_points": {
            "owned": _route_to_points(out_proj),
            "challenger": _route_to_points(incoming),
        },
        "tactical_matchup": incoming.get("tactical_matchup") or {"evidence_state": "UNAVAILABLE"},
        "competitive_load": {
            "owned": _competitive_load(_i(out.get("element"))),
            "challenger": _competitive_load(_i(incoming.get("element"))),
        },
        "finance": {
            "exact_sell_cost": out.get("sell_cost"),
            "incoming_now_cost": incoming.get("now_cost"),
            "itb": itb,
            "affordable": affordable,
            "canonical_package": package,
        },
        "legality": {
            "same_position": out.get("position") == incoming.get("position"),
            "club_limit_legal": club_legal,
        },
        "market": {"owned": owned_market, "challenger": incoming_market},
        "external_consensus": _external_state(external, _i(incoming.get("element"))),
        "emerging_triggers": triggers,
        "anti_haul_chasing": {
            "single_haul_is_not_sufficient": True,
            "sustainable_candidate": sustainable if challenger_type == "EMERGING_CHALLENGER" else None,
        },
        "uncertainty": {"signal_to_noise_5gw": round(snr, 3), "combined_5gw": unc},
        "critical_evidence": evidence,
        "missing_critical_evidence": missing,
        "blockers": blockers,
        "net_projected_gain": net_gain,
        "net_projected_gain_source": net_gain_source,
        "confidence": "LOW" if missing else (incoming.get("projection_confidence") or "MEDIUM"),
        "execution_authorized": False,
        "reason": _decision_reason(state),
    }


def _decision_reason(state: str) -> str:
    return {
        "HOLD": "Belum ada keunggulan multi-GW yang cukup kuat untuk mengganti pemain milik sendiri.",
        "REVIEW": "Ada challenger yang layak ditinjau, tetapi evidence atau net benefit belum cukup untuk tindakan sekarang.",
        "REVIEW_NOW": "Battle transfer sudah material dan perlu ditinjau sekarang karena edge, package, atau timing pasar mulai relevan.",
        "CHANGE": "Challenger unggul secara multi-GW dan lolos gate canonical yang tersedia; keputusan tetap advisory sampai authority eksekusi mengizinkan.",
        "BLOCKED": "Secara model ada battle, tetapi transfer terhalang affordability atau aturan skuad.",
    }[state]


def _retention_score(profile: dict[str, Any]) -> float:
    cfg = load_policy().get("owned_ranking") or {}
    return (
        _f(cfg.get("h5_weight"), 1.0) * _f(profile.get("xpts_5gw"))
        + _f(cfg.get("h3_weight"), 0.35) * _f(profile.get("xpts_3gw"))
        + _f(cfg.get("start_probability_weight"), 3.0) * _f(profile.get("start_probability"))
        - _f(cfg.get("dnp_probability_weight"), 2.0) * _f(profile.get("dnp_probability"))
        - _f(cfg.get("uncertainty_weight"), 0.25) * _f(profile.get("uncertainty_5gw"))
    )


def _owned_profiles(
    owned: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    price_rows: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    state_pressure = {"CHANGE": 5, "REVIEW_NOW": 4, "REVIEW": 3, "BLOCKED": 2, "HOLD": 1}
    by_out: dict[int, list[dict[str, Any]]] = {}
    for row in comparisons:
        by_out.setdefault(_i((row.get("player_out") or {}).get("element")), []).append(row)
    for item in owned:
        proj = item.get("projection") or {}
        h3, _ = _horizon(proj, 3)
        h5, u5 = _horizon(proj, 5)
        battles = by_out.get(_i(item.get("element")), [])
        battles.sort(
            key=lambda row: (
                state_pressure.get(str(row.get("decision")), 0),
                _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
            ),
            reverse=True,
        )
        best = battles[0] if battles else None
        challenge_pressure = str(best.get("decision")) if best else "UNCHALLENGED"
        lifecycle = "CHALLENGED_OWNED" if best and best.get("decision") != "HOLD" else "UNCHALLENGED"
        profile = {
            "element": item.get("element"),
            "name": item.get("name"),
            "position": item.get("position"),
            "xpts_3gw": h3,
            "xpts_5gw": h5,
            "uncertainty_5gw": u5,
            "xmins": (proj.get("xmins") or {}).get("expected_minutes"),
            "start_probability": (proj.get("xmins") or {}).get("start_probability"),
            "dnp_probability": (proj.get("xmins") or {}).get("dnp_probability"),
            "sell_cost": item.get("sell_cost"),
            "market": _market_view(price_rows.get(_i(item.get("element")))),
            "lifecycle_state": lifecycle,
            "challenge_pressure": challenge_pressure,
            "replacement_opportunity": (
                {
                    "element": (best.get("player_in") or {}).get("element"),
                    "name": (best.get("player_in") or {}).get("name"),
                    "decision": best.get("decision"),
                    "edge_5gw": ((best.get("horizons") or {}).get("5") or {}).get("projected_edge"),
                    "net_projected_gain": best.get("net_projected_gain"),
                }
                if best
                else None
            ),
            "confidence": "LOW" if not battles else best.get("confidence"),
        }
        profile["_retention_score"] = round(_retention_score(profile), 4)
        profiles.append(profile)
    profiles.sort(key=lambda row: (_f(row.get("_retention_score")), str(row.get("name") or "")))
    for idx, row in enumerate(profiles, start=1):
        row["owned_rank"] = idx
        row["weakness_rank"] = idx
        row["weakest_link"] = idx == 1
        row.pop("_retention_score", None)
    return profiles


def _battle_rows(comparisons: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    rank = {"CHANGE": 5, "REVIEW_NOW": 4, "REVIEW": 3, "BLOCKED": 2, "HOLD": 1}
    qualified = [row for row in comparisons if row.get("decision") in {"CHANGE", "REVIEW_NOW", "REVIEW", "BLOCKED"}]
    qualified.sort(
        key=lambda row: (
            rank.get(str(row.get("decision")), 0),
            _f(row.get("net_projected_gain"), -999),
            _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
        ),
        reverse=True,
    )
    return qualified[: max(0, int(limit))]


def _multi_transfer_rows(packages: list[dict[str, Any]], owned_ids: set[int], challenger_ids: set[int], limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package in packages:
        outs = {int(row["element"]) for row in package.get("outs") or [] if _i(row.get("element")) > 0}
        ins = {int(row["element"]) for row in package.get("ins") or [] if _i(row.get("element")) > 0}
        if not outs or not ins or not outs.issubset(owned_ids):
            continue
        if not ins.issubset(challenger_ids):
            continue
        rows.append(
            {
                **package,
                "decision": "CHANGE" if _f(package.get("robust_gain_vs_hold")) > 0 else "HOLD",
                "execution_authorized": False,
                "net_gain_source": "CANONICAL_PACKAGE_OPTIMIZER_ROBUST_GAIN_VS_HOLD",
            }
        )
    rows.sort(key=lambda row: _f(row.get("robust_gain_vs_hold")), reverse=True)
    return rows[: max(0, int(limit))]


def build() -> dict[str, Any]:
    cfg = load_policy()
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    external = read_json(DATA / "external_consensus.json", {})
    framework = read_json(DATA / "framework_health.json", {})
    pmap = _projection_map(projections)
    owned = _owned(team, pmap)
    owned_ids = {int(row["element"]) for row in owned}
    watchlist_rows = _watchlist_rows(watchlist)
    governed_ids = [int(row["element"]) for row in watchlist_rows if int(row["element"]) not in owned_ids]
    singles, multi_packages = _package_maps(package_optimizer)
    price_rows = _price_map()
    itb = _team_itb(team)
    comparisons: list[dict[str, Any]] = []
    max_targets = _i((cfg.get("owned_targeting") or {}).get("max_owned_targets_per_challenger"), 15)

    for element in governed_ids:
        incoming = pmap.get(element)
        if not incoming:
            continue
        targets = [row for row in owned if row.get("position") == incoming.get("position")]
        targets.sort(key=lambda row: _horizon(row.get("projection") or {}, 5)[0])
        for out in targets[:max_targets]:
            comparisons.append(
                _compare(out, incoming, "GOVERNED_WATCHLIST", [], True, owned, itb, singles, external, price_rows)
            )

    excluded = owned_ids | set(governed_ids)
    emerging = _emerging_candidates(pmap, excluded)
    for incoming, triggers, sustainable in emerging:
        targets = [row for row in owned if row.get("position") == incoming.get("position")]
        targets.sort(key=lambda row: _horizon(row.get("projection") or {}, 5)[0])
        for out in targets[:max_targets]:
            comparisons.append(
                _compare(
                    out,
                    incoming,
                    "EMERGING_CHALLENGER",
                    triggers,
                    sustainable,
                    owned,
                    itb,
                    singles,
                    external,
                    price_rows,
                )
            )

    state_rank = {"CHANGE": 5, "REVIEW_NOW": 4, "REVIEW": 3, "BLOCKED": 2, "HOLD": 1}
    comparisons.sort(
        key=lambda row: (
            state_rank.get(str(row.get("decision")), 0),
            _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
        ),
        reverse=True,
    )
    owned_profiles = _owned_profiles(owned, comparisons, price_rows)
    battles = _battle_rows(comparisons, _i((cfg.get("publication") or {}).get("max_main_transfer_battles"), 8))
    challenger_ids = set(governed_ids) | {_i(row[0].get("element")) for row in emerging}
    multi = _multi_transfer_rows(
        multi_packages,
        owned_ids,
        challenger_ids,
        _i((cfg.get("publication") or {}).get("max_multi_transfer_packages"), 8),
    )
    completeness = {
        "owned": {"actual": len(owned), "expected": 15, "complete": len(owned) == 15},
        "watchlist": {"actual": len(governed_ids), "expected": 20, "complete": len(governed_ids) == 20},
    }
    publishable = completeness["owned"]["complete"] and completeness["watchlist"]["complete"]
    overall_decision = "NO_TRANSFER_RECOMMENDED"
    if any(row.get("decision") == "CHANGE" for row in battles):
        overall_decision = "CHANGE"
    elif any(row.get("decision") == "REVIEW_NOW" for row in battles):
        overall_decision = "REVIEW_NOW"
    elif battles:
        overall_decision = "REVIEW"

    framework_state = str(framework.get("overall") or "UNKNOWN").upper()
    result = {
        "schema_version": 4,
        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",
        "engine_view": "V3",
        "generated_at": iso_now(),
        "owner": cfg.get("owner"),
        "status": "READY" if publishable else "INCOMPLETE_OFFICIAL_FACTS",
        "capability_status": cfg.get("capability_status"),
        "execution_authorized": False,
        "official_fact_completeness": completeness,
        "owned_count": len(owned),
        "governed_watchlist_count": len(governed_ids),
        "emerging_candidate_count": len(emerging),
        "comparison_count": len(comparisons),
        "owned_screening": owned_profiles,
        "comparisons": comparisons,
        "main_transfer_battles": battles if publishable else [],
        "multi_transfer_packages": multi if publishable else [],
        "overall_decision": overall_decision if publishable else "BLOCKED",
        "no_transfer_recommended": publishable and not battles,
        "framework_state": framework_state,
        "degraded_engine_weighting": framework_state not in {"GREEN", "PASS"},
        "consensus": {
            "state": "NEUTRAL",
            "reason": "V3 artifact never infers V4 output; cross-engine consensus is composed only when both governed artifacts are supplied.",
        },
        "publication": {
            "publishable": publishable,
            "main_transfer_battles_section": True,
            "data_join_defect_publication_forbidden": True,
            "no_false_certainty_for_price_eta": True,
        },
        "governance": cfg.get("governance"),
    }
    return result


def run() -> dict[str, Any]:
    result = build()
    atomic_json(OUT, result)
    latest = read_json(DATA / "latest.json", {})
    latest["owned_challenger_decision"] = {
        "status": result.get("status"),
        "owned_count": result.get("owned_count"),
        "governed_watchlist_count": result.get("governed_watchlist_count"),
        "comparison_count": result.get("comparison_count"),
        "main_transfer_battle_count": len(result.get("main_transfer_battles") or []),
        "multi_transfer_package_count": len(result.get("multi_transfer_packages") or []),
        "overall_decision": result.get("overall_decision"),
        "execution_authorized": False,
    }
    latest.setdefault("files", {})["owned_challenger_decision"] = "data/owned_challenger_comparator.json"
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(latest["owned_challenger_decision"], ensure_ascii=False))
    return result


if __name__ == "__main__":
    run()
