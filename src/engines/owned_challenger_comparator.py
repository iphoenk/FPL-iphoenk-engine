from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "owned_challenger_comparator.json"
OUT = DATA / "owned_challenger_comparator.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _projection_map(projections: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in projections.get("players") or [] if row.get("element") is not None}


def _watchlist_rows(watchlist: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in ("GK", "DEF", "MID", "FWD"):
        for row in (watchlist.get("positions") or {}).get(position) or []:
            if row.get("element") is not None:
                rows.append(row)
    return rows


def _team_itb(team: dict[str, Any]) -> int:
    totals = team.get("totals") if isinstance(team.get("totals"), dict) else {}
    return _i(totals.get("itb", team.get("itb")), 0)


def _owned_rows(team: dict[str, Any], pmap: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ledger in team.get("team_value_ledger") or []:
        element = _i(ledger.get("element"))
        proj = pmap.get(element)
        if not proj:
            continue
        rows.append({
            "element": element,
            "name": ledger.get("name") or proj.get("name"),
            "team_id": _i(proj.get("team_id")),
            "team": proj.get("team"),
            "position": proj.get("position"),
            "now_cost": _i(ledger.get("now_cost", proj.get("now_cost")), 0),
            "sell_cost": _i(ledger.get("sell_cost", proj.get("now_cost")), 0),
            "projection": proj,
        })
    return rows


def _lineup_ids(lineup: dict[str, Any]) -> set[int]:
    candidates: list[Any] = []
    for key in ("starting_xi", "selected_xi", "xi"):
        value = lineup.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            for nested in ("players", "elements", "selected_xi"):
                if isinstance(value.get(nested), list):
                    candidates.extend(value.get(nested) or [])
    selected: set[int] = set()
    for row in candidates:
        if isinstance(row, dict):
            element = row.get("element") or row.get("id")
        else:
            element = row
        if element is not None and _i(element) > 0:
            selected.add(_i(element))
    return selected


def _package_map(package_optimizer: dict[str, Any]) -> dict[int, dict[str, Any]]:
    hold = _f((((package_optimizer.get("hold") or {}).get("score") or {}).get("robust_score")))
    out: dict[int, dict[str, Any]] = {}
    for package in package_optimizer.get("packages") or []:
        if package.get("legal") is not True or ((package.get("score") or {}).get("valid")) is not True:
            continue
        robust = _f((package.get("score") or {}).get("robust_score"))
        for incoming in package.get("ins") or []:
            element = _i(incoming.get("element"))
            if element <= 0:
                continue
            candidate = {
                "package_id": package.get("id"),
                "robust_gain_vs_hold": round(robust - hold, 3),
                "resulting_itb": (package.get("affordability") or {}).get("resulting_itb"),
                "changes": package.get("changes"),
                "legal": True,
            }
            if element not in out or _f(candidate["robust_gain_vs_hold"]) > _f(out[element]["robust_gain_vs_hold"]):
                out[element] = candidate
    return out


def _match_stats(payload: dict[str, Any]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for row in payload.get("rows") or []:
        element = _i(row.get("player_id"))
        if element <= 0:
            continue
        agg = out.setdefault(element, {
            "matches": 0.0, "minutes": 0.0, "goals": 0.0, "assists": 0.0, "xg": 0.0, "xa": 0.0,
            "shots": 0.0, "box_touches": 0.0, "chances_created": 0.0, "penalties_scored": 0.0,
        })
        agg["matches"] += 1.0
        agg["minutes"] += _f(row.get("minutes_played"))
        agg["goals"] += _f(row.get("goals"))
        agg["assists"] += _f(row.get("assists"))
        agg["xg"] += _f(row.get("xg"))
        agg["xa"] += _f(row.get("xa"))
        agg["shots"] += _f(row.get("total_shots"))
        agg["box_touches"] += _f(row.get("touches_opposition_box"))
        agg["chances_created"] += _f(row.get("chances_created"))
        agg["penalties_scored"] += _f(row.get("penalties_scored"))
    return out


def _horizon(proj: dict[str, Any], horizon: int) -> tuple[float, float]:
    rows = list(proj.get("xpts_by_gw") or [])[:horizon]
    return (
        round(sum(_f(row.get("mean")) for row in rows), 3),
        round(math.sqrt(sum(_f(row.get("std")) ** 2 for row in rows)), 3),
    )


def _team_names(pmap: dict[int, dict[str, Any]]) -> dict[int, str]:
    out: dict[int, str] = {}
    for row in pmap.values():
        tid = _i(row.get("team_id"))
        if tid > 0 and row.get("team"):
            out[tid] = str(row.get("team"))
    return out


def _fixture_context(proj: dict[str, Any], gw_index: int, team_names: dict[int, str]) -> dict[str, Any]:
    rows = list(proj.get("xpts_by_gw") or [])
    if gw_index >= len(rows):
        return {"status": "UNVERIFIED", "reason": "projection horizon row unavailable"}
    row = rows[gw_index]
    fixtures = []
    for fixture in row.get("fixtures") or []:
        opponent = _i(fixture.get("opponent"))
        fixtures.append({
            "opponent_team_id": opponent,
            "opponent": team_names.get(opponent),
            "home_away": "H" if fixture.get("home") is True else "A",
            "kickoff_time": fixture.get("kickoff_time"),
            "xpts": fixture.get("mean"),
            "std": fixture.get("std"),
        })
    return {
        "gw": row.get("gw"),
        "xpts": row.get("mean"),
        "std": row.get("std"),
        "fixtures": fixtures,
    }


def _tactical_for_gw(proj: dict[str, Any], gw_index: int) -> dict[str, Any]:
    if gw_index == 0 and isinstance(proj.get("tactical_matchup"), dict):
        return proj.get("tactical_matchup") or {}
    return {
        "evidence_state": "UNVERIFIED",
        "decision_usage": "ADVISORY_ONLY",
        "reason": "future-GW fixture-specific tactical matchup is not materialized by the canonical tactical engine",
    }


def _last_pl_history(official_detail: dict[str, Any], element: int) -> dict[str, Any] | None:
    summary = (official_detail.get("element_summaries") or {}).get(str(element)) or {}
    history = [row for row in summary.get("history") or [] if isinstance(row, dict)]
    return history[-1] if history else None


def _rest_context(official_detail: dict[str, Any], element: int, fixture: dict[str, Any]) -> dict[str, Any]:
    history = _last_pl_history(official_detail, element)
    kickoff = None
    fixtures = fixture.get("fixtures") or []
    if fixtures:
        kickoff = _parse_dt(fixtures[0].get("kickoff_time"))
    previous = _parse_dt((history or {}).get("kickoff_time"))
    rest_days = None
    if kickoff and previous and kickoff >= previous:
        rest_days = round((kickoff - previous).total_seconds() / 86400.0, 2)
    return {
        "state": "PARTIAL" if history else "UNVERIFIED",
        "premier_league_previous_minutes": (history or {}).get("minutes"),
        "premier_league_previous_kickoff": (history or {}).get("kickoff_time"),
        "days_from_previous_pl_match": rest_days,
        "cross_competition_load": "PENDING_REPORT_TIME",
        "international_context": "PENDING_REPORT_TIME",
        "source_contract": load_policy().get("evidence", {}).get("recent_competitive_load_contract"),
    }


def _emerging_signal(proj: dict[str, Any], stats: dict[str, float] | None) -> tuple[str, list[str], dict[str, Any]]:
    cfg = load_policy().get("emerging_screen") or {}
    triggers: list[str] = []
    stats = stats or {}
    returns = _f(stats.get("goals")) + _f(stats.get("assists"))
    xgi = _f(stats.get("xg")) + _f(stats.get("xa"))
    if returns >= _f(cfg.get("strong_match_return_trigger"), 2.0):
        triggers.append("MULTIPLE_MATCH_RETURNS")
    if xgi >= _f(cfg.get("strong_xgi_trigger"), 0.75):
        triggers.append("STRONG_MATCH_XGI")
    if _f(stats.get("shots")) >= _f(cfg.get("shots_trigger"), 4.0):
        triggers.append("HIGH_SHOT_VOLUME")
    if _f(stats.get("box_touches")) >= _f(cfg.get("box_touches_trigger"), 8.0):
        triggers.append("HIGH_BOX_INVOLVEMENT")
    if _f(stats.get("chances_created")) >= _f(cfg.get("chances_created_trigger"), 4.0):
        triggers.append("HIGH_CHANCE_CREATION")
    if _f(stats.get("penalties_scored")) > 0:
        triggers.append("OBSERVED_PENALTY_EVENT")
    rates = proj.get("rates") or {}
    xgi90 = _f(rates.get("xg90")) + _f(rates.get("xa90"))
    pos_trigger = _f((cfg.get("position_xgi90_trigger") or {}).get(str(proj.get("position"))), 99.0)
    if xgi90 >= pos_trigger:
        triggers.append("HIGH_CANONICAL_XGI_RATE")

    xmins = proj.get("xmins") or {}
    h5, _ = _horizon(proj, 5)
    screen = {
        "eligibility": str(proj.get("status")) in set(cfg.get("allowed_statuses") or ["a", "d"]),
        "position": str(proj.get("position")) in {"GK", "DEF", "MID", "FWD"},
        "price": _i(proj.get("now_cost"), 0) > 0,
        "xmins": _f(xmins.get("expected_minutes")) >= _f(cfg.get("minimum_expected_minutes"), 50.0),
        "start_probability": _f(xmins.get("start_probability")) >= _f(cfg.get("minimum_start_probability"), 0.45),
        "dnp_risk": _f(xmins.get("dnp_probability")) <= _f(cfg.get("maximum_dnp_probability"), 0.35),
        "role_sustainability": _f(xmins.get("start_probability")) >= _f(cfg.get("minimum_start_probability"), 0.45),
        "data_quality": bool(proj.get("rates")) and bool(proj.get("xmins")),
        "next_3_5_relevance": h5 >= _f(cfg.get("minimum_h5_points"), 12.0),
    }
    passed = all(screen.values())
    sustainable = (
        passed
        and len(set(triggers)) >= _i(cfg.get("sustainable_minimum_trigger_count"), 2)
        and _f(xmins.get("start_probability")) >= _f(cfg.get("sustainable_minimum_start_probability"), 0.60)
    )
    if sustainable:
        label = "SUSTAINABLE_CANDIDATE"
    elif len(set(triggers)) >= 2:
        label = "STRONG"
    elif triggers:
        label = "INTERESTING"
    else:
        label = "NOISE"
    return label, sorted(set(triggers)), {"passed": passed, "checks": screen}


def _club_legal(owned: list[dict[str, Any]], player_out: dict[str, Any], player_in: dict[str, Any]) -> tuple[bool, dict[str, int]]:
    counts: dict[str, int] = {}
    for row in owned:
        key = str(row.get("team_id"))
        counts[key] = counts.get(key, 0) + 1
    out_key = str(player_out.get("team_id"))
    in_key = str(player_in.get("team_id"))
    counts[out_key] = max(0, counts.get(out_key, 0) - 1)
    counts[in_key] = counts.get(in_key, 0) + 1
    return max(counts.values() or [0]) <= 3, counts


def _target_outs(challenger: dict[str, Any], owned: list[dict[str, Any]], xi_ids: set[int], itb: int) -> list[dict[str, Any]]:
    cfg = load_policy().get("owned_targeting") or {}
    same = [row for row in owned if row.get("position") == challenger.get("position")]
    incoming_cost = _i(challenger.get("now_cost"), 0)
    ranked = []
    for row in same:
        proj = row.get("projection") or {}
        h5, _ = _horizon(proj, 5)
        xmins = proj.get("xmins") or {}
        affordable = incoming_cost <= _i(row.get("sell_cost"), 0) + itb
        ranked.append({
            **row,
            "direct_affordable": affordable,
            "in_starting_xi": _i(row.get("element")) in xi_ids,
            "h5": h5,
            "start_probability": _f(xmins.get("start_probability")),
            "dnp_probability": _f(xmins.get("dnp_probability")),
            "price_gap": abs(incoming_cost - _i(row.get("sell_cost"), 0)),
        })
    ranked.sort(key=lambda row: (
        0 if row.get("direct_affordable") else 1,
        0 if not row.get("in_starting_xi") else 1,
        _f(row.get("h5")),
        _f(row.get("start_probability")),
        -_f(row.get("dnp_probability")),
        _f(row.get("price_gap")),
    ))
    limit = _i(cfg.get("max_owned_targets_per_challenger"), 3)
    return ranked[:limit]


def _player_summary(row: dict[str, Any]) -> dict[str, Any]:
    proj = row.get("projection") or row
    xmins = proj.get("xmins") or {}
    return {
        "element": _i(proj.get("element", row.get("element"))),
        "name": proj.get("name") or row.get("name"),
        "team": proj.get("team") or row.get("team"),
        "team_id": _i(proj.get("team_id", row.get("team_id"))),
        "position": proj.get("position") or row.get("position"),
        "price": round(_f(proj.get("now_cost", row.get("now_cost"))) / 10.0, 1),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "dnp_probability": xmins.get("dnp_probability"),
        "projection_confidence": proj.get("projection_confidence"),
    }


def _role_sustainability(proj: dict[str, Any]) -> dict[str, Any]:
    xmins = proj.get("xmins") or {}
    rates = proj.get("rates") or {}
    current = proj.get("current_season") or {}
    return {
        "starts": current.get("starts"),
        "minutes": current.get("minutes"),
        "expected_minutes": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "dnp_probability": xmins.get("dnp_probability"),
        "xg90": rates.get("xg90"),
        "xa90": rates.get("xa90"),
        "tactical_role": proj.get("tactical_role"),
        "set_piece_penalty": {
            "state": "VERIFIED" if any(proj.get(key) is not None for key in ("penalty_role", "penalty_share", "set_piece_role", "set_piece_share")) else "UNVERIFIED",
            "penalty_role": proj.get("penalty_role"),
            "set_piece_role": proj.get("set_piece_role"),
        },
    }


def _comparison(
    owned_target: dict[str, Any],
    challenger_proj: dict[str, Any],
    challenger_type: str,
    performance_signal: str,
    performance_triggers: list[str],
    screening: dict[str, Any],
    owned: list[dict[str, Any]],
    itb: int,
    packages: dict[int, dict[str, Any]],
    official_detail: dict[str, Any],
    team_names: dict[int, str],
    candidate_out_rank: list[dict[str, Any]],
) -> dict[str, Any]:
    out_proj = owned_target.get("projection") or {}
    horizons = load_policy().get("horizons") or [1, 2, 3, 5]
    horizon_rows: dict[str, Any] = {}
    for horizon in horizons:
        out_mean, out_std = _horizon(out_proj, int(horizon))
        in_mean, in_std = _horizon(challenger_proj, int(horizon))
        combined = math.sqrt(out_std ** 2 + in_std ** 2)
        horizon_rows[str(horizon)] = {
            "owned_xpts": out_mean,
            "challenger_xpts": in_mean,
            "projected_edge": round(in_mean - out_mean, 3),
            "combined_uncertainty": round(combined, 3),
        }

    fixture_by_fixture = []
    for index in range(5):
        out_fix = _fixture_context(out_proj, index, team_names)
        in_fix = _fixture_context(challenger_proj, index, team_names)
        out_mean = _f(out_fix.get("xpts"))
        in_mean = _f(in_fix.get("xpts"))
        fixture_by_fixture.append({
            "gw": in_fix.get("gw") or out_fix.get("gw"),
            "owned": {
                **out_fix,
                "xmins": (out_proj.get("xmins") or {}).get("expected_minutes"),
                "start_probability": (out_proj.get("xmins") or {}).get("start_probability"),
                "tactical_matchup": _tactical_for_gw(out_proj, index),
                "rest_congestion": _rest_context(official_detail, _i(out_proj.get("element")), out_fix),
            },
            "challenger": {
                **in_fix,
                "xmins": (challenger_proj.get("xmins") or {}).get("expected_minutes"),
                "start_probability": (challenger_proj.get("xmins") or {}).get("start_probability"),
                "tactical_matchup": _tactical_for_gw(challenger_proj, index),
                "rest_congestion": _rest_context(official_detail, _i(challenger_proj.get("element")), in_fix),
            },
            "projected_edge": round(in_mean - out_mean, 3),
        })

    affordable = _i(challenger_proj.get("now_cost"), 0) <= _i(owned_target.get("sell_cost"), 0) + itb
    club_legal, resulting_club_counts = _club_legal(owned, owned_target, challenger_proj)
    package = packages.get(_i(challenger_proj.get("element")))
    direct_legal = affordable and club_legal and out_proj.get("position") == challenger_proj.get("position")
    structural = {
        "state": "CANONICAL_PACKAGE_AVAILABLE" if package else ("DIRECT_SWAP_LEGAL_BY_CURRENT_FACTS" if direct_legal else "STRUCTURAL_CHANGE_REQUIRED"),
        "club_limit_legal": club_legal,
        "resulting_club_counts": resulting_club_counts,
        "direct_swap_affordable": affordable,
        "owned_sell_cost": round(_i(owned_target.get("sell_cost"), 0) / 10.0, 1),
        "challenger_purchase_price": round(_i(challenger_proj.get("now_cost"), 0) / 10.0, 1),
        "current_itb": round(itb / 10.0, 1),
        "canonical_package": package,
    }
    raw_gain_2 = _f((horizon_rows.get("2") or {}).get("projected_edge"))
    raw_gain_3 = _f((horizon_rows.get("3") or {}).get("projected_edge"))
    raw_gain_5 = _f((horizon_rows.get("5") or {}).get("projected_edge"))
    unc5 = _f((horizon_rows.get("5") or {}).get("combined_uncertainty"))
    snr = raw_gain_5 / unc5 if unc5 > 1e-9 else 0.0
    start_in = _f((challenger_proj.get("xmins") or {}).get("start_probability"))
    cfg = load_policy().get("decision") or {}

    if not direct_legal and not package:
        decision = "REVIEW"
    elif challenger_type == "EMERGING_CHALLENGER" and cfg.get("emerging_requires_sustainable_candidate_for_transfer_labels", True) and performance_signal != "SUSTAINABLE_CANDIDATE":
        decision = "WATCH_CHALLENGER"
    elif raw_gain_5 <= 0:
        decision = "HOLD_OWNED"
    elif raw_gain_5 < _f(cfg.get("review_gain_5gw"), 1.0):
        decision = "HOLD_OWNED"
    elif raw_gain_5 >= _f(cfg.get("strong_gain_5gw"), 5.0) and snr >= _f(cfg.get("strong_minimum_signal_to_noise"), 0.85) and start_in >= _f(cfg.get("strong_minimum_start_probability"), 0.75) and package:
        decision = "LEAN_TRANSFER"  # report-time congestion/team-news evidence still required before STRONG in ADVISORY_ONLY mode
    elif raw_gain_5 >= _f(cfg.get("lean_gain_5gw"), 3.0) and snr >= _f(cfg.get("lean_minimum_signal_to_noise"), 0.55) and start_in >= _f(cfg.get("minimum_start_probability_for_transfer"), 0.60):
        decision = "LEAN_TRANSFER"
    else:
        decision = "REVIEW"

    tactical = challenger_proj.get("tactical_matchup") or {}
    reasons = [f"5GW projected edge {raw_gain_5:+.2f}", f"challenger start probability {start_in:.0%}"]
    highlights = tactical.get("highlights") or []
    if highlights:
        reasons.append(str(highlights[0]))
    if package:
        reasons.append(f"canonical package robust gain {float(package.get('robust_gain_vs_hold') or 0):+.2f}")
    if challenger_type == "EMERGING_CHALLENGER":
        reasons.append(f"performance signal {performance_signal}")

    risks = []
    if unc5 > 0:
        risks.append(f"5GW combined uncertainty ±{unc5:.2f}")
    if str(tactical.get("evidence_state") or "") not in {"READY", "CUKUP"}:
        risks.append("tactical evidence not fully READY")
    risks.append("non-PL congestion/international schedule requires report-time verification")
    if not package:
        risks.append("no canonical package context for this incoming player")

    reversal = [
        "challenger fails to start or xMins falls materially",
        "positional competitor returns or role becomes deeper",
        "owned player's role/xMins improves materially",
        "new injury, suspension or verified team-news changes availability",
        "European/domestic-cup/international workload changes the recovery window",
        "fixture rearrangement or tactical system change",
        "price move destroys affordability",
        "underlying process regresses across subsequent matches",
    ]
    confidence = "MEDIUM"
    if str(out_proj.get("projection_confidence")) == "LOW" or str(challenger_proj.get("projection_confidence")) == "LOW":
        confidence = "LOW"

    return {
        "player_out": _player_summary(owned_target),
        "player_in": _player_summary(challenger_proj),
        "challenger_type": challenger_type,
        "candidate_out_rank": candidate_out_rank,
        "comparison_timestamp": _now(),
        "planning_gw": (challenger_proj.get("xpts_by_gw") or [{}])[0].get("gw"),
        "horizon_1gw": horizon_rows.get("1"),
        "horizon_2gw": horizon_rows.get("2"),
        "horizon_3gw": horizon_rows.get("3"),
        "horizon_5gw": horizon_rows.get("5"),
        "fixture_by_fixture": fixture_by_fixture,
        "xpts_by_gw": {
            "owned": [{"gw": row.get("gw"), "mean": row.get("mean"), "std": row.get("std")} for row in (out_proj.get("xpts_by_gw") or [])[:5]],
            "challenger": [{"gw": row.get("gw"), "mean": row.get("mean"), "std": row.get("std")} for row in (challenger_proj.get("xpts_by_gw") or [])[:5]],
        },
        "xmins_by_gw": {"owned": (out_proj.get("xmins") or {}).get("expected_minutes"), "challenger": (challenger_proj.get("xmins") or {}).get("expected_minutes"), "note": "canonical xMins is reused; it is not recomputed per fixture here"},
        "start_probability_by_gw": {"owned": (out_proj.get("xmins") or {}).get("start_probability"), "challenger": (challenger_proj.get("xmins") or {}).get("start_probability"), "note": "canonical start probability reused"},
        "tactical_matchup_by_gw": [{"gw": row.get("gw"), "owned": row["owned"].get("tactical_matchup"), "challenger": row["challenger"].get("tactical_matchup")} for row in fixture_by_fixture],
        "rest_congestion_by_gw": [{"gw": row.get("gw"), "owned": row["owned"].get("rest_congestion"), "challenger": row["challenger"].get("rest_congestion")} for row in fixture_by_fixture],
        "midweek_schedule": {"state": "PENDING_REPORT_TIME", "scope": "UEFA/domestic cups/other official competitions between PL GWs"},
        "international_context": {"state": "PENDING_REPORT_TIME", "scope": "call-up, minutes, travel and recovery"},
        "role_sustainability": {"owned": _role_sustainability(out_proj), "challenger": _role_sustainability(challenger_proj)},
        "performance_signal": performance_signal,
        "performance_triggers": performance_triggers,
        "emerging_screen": screening if challenger_type == "EMERGING_CHALLENGER" else None,
        "raw_gain_2gw": round(raw_gain_2, 3),
        "raw_gain_3gw": round(raw_gain_3, 3),
        "raw_gain_5gw": round(raw_gain_5, 3),
        "structural_cost": structural,
        "opportunity_cost": {"state": "NOT_NUMERIC_WITHOUT_VERIFIED_TRANSFER_STATE", "active_chip_or_ft_state": "PENDING_AUTHORITY"},
        "net_transfer_value": package.get("robust_gain_vs_hold") if package else None,
        "affordability": affordable,
        "confidence": confidence,
        "signal_to_noise_5gw": round(snr, 3),
        "decision": decision,
        "decision_reasons": reasons[:5],
        "decision_risks": risks[:5],
        "reversal_triggers": reversal,
        "data_quality": {
            "canonical_projection": bool(out_proj and challenger_proj),
            "canonical_xmins": bool(out_proj.get("xmins")) and bool(challenger_proj.get("xmins")),
            "canonical_tactical_current_gw": isinstance(challenger_proj.get("tactical_matchup"), dict),
            "canonical_package": bool(package),
            "cross_competition_congestion": "PENDING_REPORT_TIME",
            "external_consensus": "PENDING_REPORT_TIME",
        },
        "external_model_consensus": {"state": "PENDING_REPORT_TIME", "allowed_states": ["ALIGN", "DIVERGE", "REVIEW_DIVERGENCE", "NEUTRAL"], "majority_vote_forbidden": True},
        "advisory_only": True,
    }


def build() -> dict[str, Any]:
    projections = read_json(DATA / "projections.json", {})
    team = read_json(DATA / "team.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    universe = read_json(DATA / "universe.json", {})
    match_stats_payload = read_json(DATA / "stats" / "playermatchstats_current.json", {})
    package_optimizer = read_json(DATA / "package_optimizer.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    official_detail = read_json(DATA / "official_detail.json", {})

    if not projections.get("players") or not team.get("team_value_ledger"):
        raise RuntimeError("owned challenger comparator requires canonical projections and owned team ledger")
    if watchlist.get("status") not in {"READY", "INSUFFICIENT_EVIDENCE"}:
        raise RuntimeError("owned challenger comparator requires governed DSS watchlist artifact")

    pmap = _projection_map(projections)
    owned = _owned_rows(team, pmap)
    if len(owned) != 15:
        raise RuntimeError(f"owned challenger comparator expected 15 owned players, got {len(owned)}")
    owned_ids = {int(row["element"]) for row in owned}
    watch_rows = _watchlist_rows(watchlist)
    watch_ids = {int(row["element"]) for row in watch_rows}
    stats_map = _match_stats(match_stats_payload)
    packages = _package_map(package_optimizer)
    xi_ids = _lineup_ids(lineup)
    itb = _team_itb(team)
    team_names = _team_names(pmap)

    challengers: list[dict[str, Any]] = []
    for row in watch_rows:
        element = _i(row.get("element"))
        proj = pmap.get(element)
        if proj:
            challengers.append({"projection": proj, "type": "GOVERNED_WATCHLIST", "performance_signal": "GOVERNED_WATCHLIST", "triggers": [], "screening": {"passed": True, "source": "DSS_WATCHLIST"}})

    emerging: list[dict[str, Any]] = []
    for element, proj in pmap.items():
        if element in owned_ids or element in watch_ids:
            continue
        signal, triggers, screening = _emerging_signal(proj, stats_map.get(element))
        if signal == "NOISE" or not triggers:
            continue
        emerging.append({"projection": proj, "type": "EMERGING_CHALLENGER", "performance_signal": signal, "triggers": triggers, "screening": screening})
    emerging.sort(key=lambda row: (
        1 if row.get("performance_signal") == "SUSTAINABLE_CANDIDATE" else 0,
        len(row.get("triggers") or []),
        _horizon(row.get("projection") or {}, 5)[0],
    ), reverse=True)
    emerging = emerging[:_i((load_policy().get("emerging_screen") or {}).get("max_candidates"), 12)]
    challengers.extend(emerging)

    comparisons: list[dict[str, Any]] = []
    for challenger in challengers:
        proj = challenger["projection"]
        targets = _target_outs(proj, owned, xi_ids, itb)
        rank_summary = [
            {
                "rank": index,
                "element": row.get("element"),
                "name": row.get("name"),
                "direct_affordable": row.get("direct_affordable"),
                "in_starting_xi": row.get("in_starting_xi"),
                "h5": row.get("h5"),
                "start_probability": row.get("start_probability"),
                "reason": "same position; ranked by direct affordability, squad role, weaker 5GW outlook, xMins and price proximity",
            }
            for index, row in enumerate(targets, start=1)
        ]
        for target in targets:
            comparisons.append(_comparison(
                target,
                proj,
                str(challenger["type"]),
                str(challenger["performance_signal"]),
                list(challenger.get("triggers") or []),
                challenger.get("screening") or {},
                owned,
                itb,
                packages,
                official_detail,
                team_names,
                rank_summary,
            ))

    decision_order = {"STRONG_TRANSFER": 5, "LEAN_TRANSFER": 4, "REVIEW": 3, "WATCH_CHALLENGER": 2, "PROMOTE_TO_WATCHLIST": 2, "HOLD_OWNED": 1}
    comparisons.sort(key=lambda row: (decision_order.get(str(row.get("decision")), 0), _f(row.get("raw_gain_5gw"))), reverse=True)
    by_owned: dict[str, list[dict[str, Any]]] = {}
    for row in comparisons:
        key = str((row.get("player_out") or {}).get("element"))
        by_owned.setdefault(key, []).append({
            "player_in": row.get("player_in"),
            "challenger_type": row.get("challenger_type"),
            "raw_gain_5gw": row.get("raw_gain_5gw"),
            "decision": row.get("decision"),
            "confidence": row.get("confidence"),
        })
    for key in list(by_owned):
        by_owned[key] = by_owned[key][:5]

    payload = {
        "schema_version": 1,
        "contract": load_policy().get("contract"),
        "generated_at": _now(),
        "planning_gw": projections.get("planning_gw"),
        "capability_status": load_policy().get("capability_status"),
        "owned_count": len(owned),
        "challenger_counts": {
            "governed_watchlist": len([row for row in challengers if row.get("type") == "GOVERNED_WATCHLIST"]),
            "emerging": len(emerging),
            "comparisons": len(comparisons),
        },
        "emerging_challengers": [
            {
                "player": _player_summary(row.get("projection") or {}),
                "performance_signal": row.get("performance_signal"),
                "triggers": row.get("triggers"),
                "screening": row.get("screening"),
            }
            for row in emerging
        ],
        "top_comparisons": comparisons[:12],
        "comparisons": comparisons,
        "by_owned": by_owned,
        "common_output_semantics": [
            "player_out", "player_in", "challenger_type", "comparison_timestamp", "planning_gw",
            "horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw", "fixture_by_fixture",
            "xpts_by_gw", "xmins_by_gw", "start_probability_by_gw", "tactical_matchup_by_gw",
            "rest_congestion_by_gw", "midweek_schedule", "international_context", "role_sustainability",
            "performance_signal", "raw_gain_2gw", "raw_gain_3gw", "raw_gain_5gw", "structural_cost",
            "opportunity_cost", "net_transfer_value", "affordability", "confidence", "decision",
            "decision_reasons", "decision_risks", "reversal_triggers", "data_quality"
        ],
        "governance": {
            **(load_policy().get("governance") or {}),
            "watchlist_membership_not_mutated": True,
            "canonical_transfer_recommendation_not_mutated": True,
            "starting_xi_captain_vice_chip_not_mutated": True,
            "emerging_performance_is_discovery_signal_only": True,
            "cross_competition_load_requires_report_time_evidence": True,
            "external_consensus_requires_report_time_evidence": True,
        },
    }
    return payload


def run() -> dict[str, Any]:
    payload = build()
    atomic_json(OUT, payload)
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {})["owned_challenger_comparator"] = "data/owned_challenger_comparator.json"
    latest["owned_challenger_comparator_summary"] = {
        "contract": payload.get("contract"),
        "capability_status": payload.get("capability_status"),
        "planning_gw": payload.get("planning_gw"),
        "owned": payload.get("owned_count"),
        "challengers": payload.get("challenger_counts"),
        "top_decision": ((payload.get("top_comparisons") or [{}])[0]).get("decision"),
        "advisory_only": True,
    }
    atomic_json(DATA / "latest.json", latest)
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({
        "contract": result.get("contract"),
        "status": result.get("capability_status"),
        "owned": result.get("owned_count"),
        "challengers": result.get("challenger_counts"),
        "top": [
            {
                "out": (row.get("player_out") or {}).get("name"),
                "in": (row.get("player_in") or {}).get("name"),
                "type": row.get("challenger_type"),
                "gain5": row.get("raw_gain_5gw"),
                "decision": row.get("decision"),
            }
            for row in (result.get("top_comparisons") or [])[:3]
        ],
    }, ensure_ascii=False))
