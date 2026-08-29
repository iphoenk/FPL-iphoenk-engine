from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_owned_challenger_comparator.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(default if value is None else value)
    except (TypeError, ValueError):
        return int(default)


def _player_map(prediction: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["element"]): row
        for row in prediction.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _finance_map(team: dict[str, Any]) -> dict[int, dict[str, Any]]:
    finance = team.get("finance") if isinstance(team.get("finance"), dict) else {}
    return {
        int(row["element"]): row
        for row in finance.get("players") or []
        if isinstance(row, dict) and row.get("element") is not None
    }


def _watchlist_rows(watchlist: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for position, rows in (watchlist.get("positions") or {}).items():
        for row in rows or []:
            if not isinstance(row, dict) or row.get("element") is None:
                continue
            out.append({**row, "position": str(row.get("position") or position), "challenger_lane": "GOVERNED_WATCHLIST"})
    return out


def _emerging_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("element") is None:
            continue
        if not bool(row.get("triggered", True)):
            continue
        out.append({**row, "challenger_lane": "EMERGING_CHALLENGER"})
    return out


def _gw_rows(player: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in player.get("xpts_by_gw") or [] if isinstance(row, dict)]


def _horizon(player: dict[str, Any], count: int) -> tuple[float, float, list[dict[str, Any]]]:
    rows = _gw_rows(player)[:count]
    mean = sum(_f(row.get("mean", row.get("xpts"))) for row in rows)
    std = math.sqrt(sum(_f(row.get("std")) ** 2 for row in rows))
    fixture_rows: list[dict[str, Any]] = []
    for row in rows:
        details = row.get("fixtures") if isinstance(row.get("fixtures"), list) else []
        if details:
            for fixture in details:
                if not isinstance(fixture, dict):
                    continue
                fixture_rows.append(
                    {
                        "gw": row.get("gw"),
                        "home": fixture.get("home"),
                        "opponent": fixture.get("opponent"),
                        "kickoff_time": fixture.get("kickoff_time"),
                        "xpts": round(_f(fixture.get("mean", fixture.get("xpts"))), 3),
                        "std": round(_f(fixture.get("std")), 3),
                    }
                )
        else:
            fixture_rows.append(
                {
                    "gw": row.get("gw"),
                    "home": None,
                    "opponent": None,
                    "kickoff_time": None,
                    "xpts": round(_f(row.get("mean", row.get("xpts"))), 3),
                    "std": round(_f(row.get("std")), 3),
                }
            )
    return round(mean, 3), round(std, 3), fixture_rows


def _xmins(player: dict[str, Any]) -> dict[str, float]:
    data = player.get("xmins") if isinstance(player.get("xmins"), dict) else {}
    start = _f(data.get("start_probability"))
    return {
        "expected_minutes": round(_f(data.get("expected_minutes")), 2),
        "start_probability": round(start, 4),
        "dnp_probability": round(_f(data.get("dnp_probability"), max(0.0, 1.0 - start)), 4),
    }


def _tactical(player: dict[str, Any]) -> dict[str, Any]:
    tactical = player.get("tactical_matchup") if isinstance(player.get("tactical_matchup"), dict) else {}
    status = "VERIFIED" if tactical else "UNVERIFIED"
    return {"status": status, "current_gw": tactical or None, "future_gw": "UNVERIFIED"}


def _workload(element: int, workload_context: dict[str, Any] | None) -> dict[str, Any]:
    supplied = workload_context if isinstance(workload_context, dict) else {}
    row = supplied.get(str(element)) or supplied.get(element)
    if isinstance(row, dict):
        return {"status": str(row.get("status") or "VERIFIED"), **row}
    return {"status": "UNVERIFIED", "reason": "PLAYER_COMPETITIVE_LOAD_NOT_SUPPLIED"}


def _role(player: dict[str, Any]) -> dict[str, Any]:
    role = player.get("role") if isinstance(player.get("role"), dict) else {}
    xm = _xmins(player)
    return {
        "status": "VERIFIED" if role else "PARTIAL",
        "start_probability": xm["start_probability"],
        "expected_minutes": xm["expected_minutes"],
        "rotation_risk": role.get("rotation_risk"),
        "competition_pressure": role.get("competition_pressure"),
        "set_piece_share": role.get("set_piece_share"),
        "penalty_share": role.get("penalty_share"),
    }


def _eligible(challenger: dict[str, Any], cfg: dict[str, Any]) -> bool:
    xm = _xmins(challenger)
    rules = cfg.get("eligibility") or {}
    if xm["start_probability"] < _f(rules.get("minimum_start_probability"), .45):
        return False
    if xm["dnp_probability"] > _f(rules.get("maximum_dnp_probability"), .35):
        return False
    if bool(rules.get("block_unavailable_status", True)) and str(challenger.get("status") or "a") not in {"a", "d"}:
        return False
    return True


def _owned_targets(
    challenger: dict[str, Any],
    players: dict[int, dict[str, Any]],
    finance: dict[int, dict[str, Any]],
    owned_ids: set[int],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    pairing = cfg.get("pairing") or {}
    position = str(challenger.get("position") or "")
    price = _i(challenger.get("now_cost"))
    band = int(pairing.get("price_band_tenths") or 20)
    rows = []
    for eid in owned_ids:
        player = players.get(eid)
        if not isinstance(player, dict):
            continue
        if bool(pairing.get("same_position_required", True)) and str(player.get("position") or "") != position:
            continue
        fin = finance.get(eid) or {}
        sell = fin.get("sell_cost")
        anchor = _i(sell, _i(player.get("now_cost")))
        if price and abs(price - anchor) > band:
            continue
        xm = _xmins(player)
        rows.append(
            {
                "player": player,
                "finance": fin,
                "sort": (
                    _f(player.get("xpts_5")),
                    xm["start_probability"],
                    -_f(sell, _f(player.get("now_cost"))),
                ),
            }
        )
    rows.sort(key=lambda row: row["sort"])
    limit = int(pairing.get("max_owned_targets_per_challenger") or 3)
    return rows[:limit]


def _affordability(
    owned_finance: dict[str, Any],
    challenger: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    bank = (team.get("finance") or {}).get("bank") if isinstance(team.get("finance"), dict) else None
    sell = owned_finance.get("sell_cost")
    cost = challenger.get("now_cost")
    if sell is None or bank is None or cost is None:
        return {
            "status": "UNVERIFIED",
            "affordable": None,
            "owned_sell_cost": sell,
            "bank": bank,
            "challenger_cost": cost,
        }
    available = int(sell) + int(bank)
    return {
        "status": "VERIFIED",
        "affordable": available >= int(cost),
        "owned_sell_cost": int(sell),
        "bank": int(bank),
        "challenger_cost": int(cost),
        "available_tenths": available,
        "headroom_tenths": available - int(cost),
    }


def _signal(gain5: float, signal_to_noise: float, cfg: dict[str, Any]) -> str:
    rules = cfg.get("signal") or {}
    if gain5 >= _f(rules.get("sustainable_gain_5gw"), 4.0) and signal_to_noise >= _f(rules.get("minimum_signal_to_noise"), .75):
        return "SUSTAINABLE_CANDIDATE"
    if gain5 >= _f(rules.get("strong_gain_5gw"), 2.5):
        return "STRONG"
    if gain5 >= _f(rules.get("interesting_gain_5gw"), .75):
        return "INTERESTING"
    return "NOISE"


def _transfer_context(context: dict[str, Any], transfer_state: dict[str, Any] | None) -> dict[str, Any]:
    state = transfer_state if isinstance(transfer_state, dict) else {}
    chip = str(state.get("active_chip") or context.get("active_chip") or "").lower()
    wildcard = chip in {"wildcard", "wc"} or bool(state.get("wildcard_active"))
    free_hit = chip in {"freehit", "free_hit", "fh"} or bool(state.get("free_hit_active"))
    ft = state.get("free_transfers")
    return {
        "wildcard_active": wildcard,
        "free_hit_active": free_hit,
        "free_transfers": int(ft) if ft is not None else None,
        "authoritative_transfer_state": bool(state.get("authoritative", False)),
    }


def _decision(
    gain5: float,
    signal_to_noise: float,
    affordability: dict[str, Any],
    evidence: dict[str, Any],
    transfer_context: dict[str, Any],
    cfg: dict[str, Any],
) -> tuple[str, list[str]]:
    rules = cfg.get("decision") or {}
    reasons: list[str] = []
    if affordability.get("affordable") is False:
        return "HOLD_OWNED", ["DIRECT_SWAP_NOT_AFFORDABLE"]
    if gain5 < _f(rules.get("watch_gain_5gw"), .75):
        return "HOLD_OWNED", ["MULTI_GW_GAIN_BELOW_WATCH_THRESHOLD"]
    label = "WATCH_CHALLENGER"
    if gain5 >= _f(rules.get("review_gain_5gw"), 1.5):
        label = "REVIEW"
    if gain5 >= _f(rules.get("lean_gain_5gw"), 3.0) and signal_to_noise >= _f(rules.get("minimum_lean_signal_to_noise"), .8):
        label = "LEAN_TRANSFER"
    if gain5 >= _f(rules.get("strong_gain_5gw"), 5.0) and signal_to_noise >= _f(rules.get("minimum_strong_signal_to_noise"), 1.1):
        label = "STRONG_TRANSFER"

    critical_missing = [name for name, status in evidence.items() if name in {"future_tactical", "workload_context"} and status != "VERIFIED"]
    if critical_missing and bool(rules.get("cap_to_review_when_critical_evidence_missing", True)) and label in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
        label = "REVIEW"
        reasons.append("CRITICAL_EVIDENCE_MISSING_CAPS_ACTIONABILITY")
    if transfer_context.get("free_hit_active") and label in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
        label = str(rules.get("free_hit_permanent_transfer_cap") or "REVIEW")
        reasons.append("FREE_HIT_CAPS_PERMANENT_TRANSFER_ACTIONABILITY")
    if not transfer_context.get("wildcard_active") and transfer_context.get("free_transfers") is None and label in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
        label = str(rules.get("unknown_ft_cost_cap") or "REVIEW")
        reasons.append("TRANSFER_COST_UNVERIFIED")
    if label == "WATCH_CHALLENGER":
        reasons.append("POSITIVE_BUT_NOT_YET_TRANSFER_GRADE")
    elif label == "REVIEW":
        reasons.append("MATERIAL_MULTI_GW_CHALLENGE_REQUIRES_REVIEW")
    elif label in {"LEAN_TRANSFER", "STRONG_TRANSFER"}:
        reasons.append("MULTI_GW_ADVANTAGE_AND_SIGNAL_TO_NOISE_CLEAR")
    return label, reasons


def compare(
    *,
    prediction: dict[str, Any],
    team: dict[str, Any],
    watchlist: dict[str, Any],
    context: dict[str, Any] | None = None,
    emerging_candidates: list[dict[str, Any]] | None = None,
    workload_context: dict[str, Any] | None = None,
    transfer_state: dict[str, Any] | None = None,
    external_consensus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG)
    players = _player_map(prediction)
    finance = _finance_map(team)
    owned_ids = {int(x) for x in team.get("owned_ids") or []}
    candidates = _watchlist_rows(watchlist) + _emerging_rows(emerging_candidates)
    seen: set[int] = set()
    pairs: list[dict[str, Any]] = []
    transfer = _transfer_context(context or {}, transfer_state)
    pair_limit = int((cfg.get("pairing") or {}).get("max_pairs_total") or 24)

    for candidate_row in candidates:
        cid = int(candidate_row["element"])
        if cid in seen or cid in owned_ids:
            continue
        seen.add(cid)
        challenger = players.get(cid)
        if not isinstance(challenger, dict) or not _eligible(challenger, cfg):
            continue
        targets = _owned_targets(challenger, players, finance, owned_ids, cfg)
        for target in targets:
            owned = target["player"]
            owned_fin = target["finance"]
            horizon_rows: dict[str, Any] = {}
            for horizon in cfg.get("horizons_gw") or [1, 2, 3, 5]:
                h = int(horizon)
                c_mean, c_std, c_fixtures = _horizon(challenger, h)
                o_mean, o_std, o_fixtures = _horizon(owned, h)
                gain = c_mean - o_mean
                combined_std = math.sqrt(c_std**2 + o_std**2)
                horizon_rows[str(h)] = {
                    "owned_xpts": o_mean,
                    "challenger_xpts": c_mean,
                    "raw_gain": round(gain, 3),
                    "combined_uncertainty": round(combined_std, 3),
                    "signal_to_noise": round(gain / max(combined_std, .01), 3),
                    "owned_fixtures": o_fixtures,
                    "challenger_fixtures": c_fixtures,
                }
            h5 = horizon_rows.get("5") or {}
            gain5 = _f(h5.get("raw_gain"))
            snr = _f(h5.get("signal_to_noise"))
            affordability = _affordability(owned_fin, challenger, team)
            owned_tactical = _tactical(owned)
            challenger_tactical = _tactical(challenger)
            owned_workload = _workload(int(owned["element"]), workload_context)
            challenger_workload = _workload(cid, workload_context)
            evidence_status = {
                "current_tactical": "VERIFIED" if owned_tactical["status"] == challenger_tactical["status"] == "VERIFIED" else "UNVERIFIED",
                "future_tactical": "UNVERIFIED",
                "workload_context": "VERIFIED" if owned_workload["status"] == challenger_workload["status"] == "VERIFIED" else "UNVERIFIED",
                "finance": affordability["status"],
            }
            label, reasons = _decision(gain5, snr, affordability, evidence_status, transfer, cfg)
            consensus = (external_consensus or {}).get(str(cid)) or (external_consensus or {}).get(cid)
            consensus_label = str((consensus or {}).get("state") or "NEUTRAL") if isinstance(consensus, dict) else "NEUTRAL"
            pair = {
                "owned": {
                    "element": int(owned["element"]),
                    "name": owned.get("name"),
                    "position": owned.get("position"),
                    "team_id": owned.get("team_id"),
                    "now_cost": owned.get("now_cost"),
                    "sell_cost": owned_fin.get("sell_cost"),
                    "xmins": _xmins(owned),
                    "role_sustainability": _role(owned),
                    "tactical": owned_tactical,
                    "workload": owned_workload,
                },
                "challenger": {
                    "element": cid,
                    "name": challenger.get("name"),
                    "position": challenger.get("position"),
                    "team_id": challenger.get("team_id"),
                    "now_cost": challenger.get("now_cost"),
                    "lane": candidate_row.get("challenger_lane"),
                    "watchlist_admission_status": candidate_row.get("admission_status"),
                    "xmins": _xmins(challenger),
                    "role_sustainability": _role(challenger),
                    "tactical": challenger_tactical,
                    "workload": challenger_workload,
                },
                "horizons": horizon_rows,
                "performance_signal": _signal(gain5, snr, cfg),
                "affordability": affordability,
                "transfer_context": transfer,
                "evidence": evidence_status,
                "external_consensus": {
                    "state": consensus_label,
                    "governance": "ADVISORY_ONLY_NO_MAJORITY_VOTE",
                },
                "classification": label,
                "confidence": "HIGH" if snr >= 1.1 and not any(v == "UNVERIFIED" for v in evidence_status.values()) else ("MEDIUM" if snr >= .6 else "LOW"),
                "reasons": reasons,
                "risks": [key for key, value in evidence_status.items() if value != "VERIFIED"],
                "reversal_triggers": [
                    "XMINS_OR_START_SECURITY_DETERIORATES",
                    "TACTICAL_MATCHUP_CHANGES",
                    "INJURY_OR_SUSPENSION",
                    "PRICE_OR_AFFORDABILITY_CHANGES",
                    "FIXTURE_OR_CONGESTION_CHANGES",
                    "UNDERLYING_PROCESS_REGRESSES",
                ],
            }
            pairs.append(pair)
            if len(pairs) >= pair_limit:
                break
        if len(pairs) >= pair_limit:
            break

    priority = {"STRONG_TRANSFER": 6, "LEAN_TRANSFER": 5, "REVIEW": 4, "PROMOTE_TO_WATCHLIST": 3, "WATCH_CHALLENGER": 2, "HOLD_OWNED": 1}
    pairs.sort(
        key=lambda row: (
            -priority.get(str(row.get("classification")), 0),
            -_f(((row.get("horizons") or {}).get("5") or {}).get("raw_gain")),
        )
    )
    counts: dict[str, int] = {}
    for row in pairs:
        label = str(row.get("classification") or "UNKNOWN")
        counts[label] = counts.get(label, 0) + 1
    return {
        "schema_version": int(cfg.get("schema_version") or 1),
        "model": cfg.get("model_id"),
        "generated_at": _now(),
        "status": cfg.get("status"),
        "authority": cfg.get("authority"),
        "planning_gw": prediction.get("planning_gw"),
        "candidate_count": len(seen),
        "pair_count": len(pairs),
        "classification_counts": counts,
        "pairs": pairs,
        "top_comparisons": pairs[:8],
        "governance": {
            **(cfg.get("governance") or {}),
            "candidate_universe_is_bounded": True,
            "single_match_haul_never_direct_transfer": True,
            "missing_evidence_never_fabricated": True,
            "canonical_decision_mutation": False,
        },
    }
