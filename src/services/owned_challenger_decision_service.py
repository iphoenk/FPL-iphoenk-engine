from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.engines.v4_decision_pipeline import effective_planning_squad
from src.engines.v4_wc_optimizer import build_candidates, reconcile_owned_costs
from src.utils import CONFIG, DATA, atomic_json, read_json, utcnow

POLICY_PATH = CONFIG / "intelligence" / "owned_challenger_decision_v4.json"
OUT = DATA / "owned_challenger_decision_v4.json"


@lru_cache(maxsize=1)
def load_policy() -> dict[str, Any]:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if payload.get("contract") != "OWNED_CHALLENGER_DECISION_ENGINE_V1":
        raise RuntimeError("invalid V4 owned challenger policy contract")
    return payload


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


def _prediction_map(predictions: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("element")): row
        for row in predictions.get("players") or []
        if _i(row.get("element")) > 0
    }


def _universe_map(universe: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("element", row.get("id"))): row
        for row in universe.get("players") or []
        if _i(row.get("element", row.get("id"))) > 0
    }


def _avg_xmins(pred: dict[str, Any], horizon: int = 5) -> dict[str, float | None]:
    starts: list[float] = []
    expected: list[float] = []
    dnp: list[float] = []
    for fixture in list(pred.get("fixtures") or [])[: max(1, int(horizon))]:
        xmins = fixture.get("xmins") or {}
        if xmins.get("start_probability") is not None:
            starts.append(_f(xmins.get("start_probability")))
        if xmins.get("expected_minutes") is not None:
            expected.append(_f(xmins.get("expected_minutes")))
        if xmins.get("dnp_probability") is not None:
            dnp.append(_f(xmins.get("dnp_probability")))
    return {
        "start_probability": round(sum(starts) / len(starts), 4) if starts else None,
        "expected_minutes": round(sum(expected) / len(expected), 2) if expected else None,
        "dnp_probability": round(sum(dnp) / len(dnp), 4) if dnp else None,
    }


def _horizon(candidate: Any, horizon: int) -> float:
    return {
        3: _f(candidate.x3),
        5: _f(candidate.x5),
        10: _f(candidate.x10),
        15: _f(candidate.x15),
    }.get(int(horizon), sum(_f(x) for x in list(candidate.gw_xpts)[: max(0, int(horizon))]))


def _price_map(prices: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        _i(row.get("element_id", row.get("element"))): row
        for row in prices.get("players") or []
        if _i(row.get("element_id", row.get("element"))) > 0
    }


def _market_view(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        "official_price": row.get("current_price"),
        "now_cost": row.get("now_cost"),
        "ownership_percent": row.get("ownership_percent", row.get("ownership_pct")),
        "transfers_in_event": row.get("transfers_in_event"),
        "transfers_out_event": row.get("transfers_out_event"),
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


def _tactical_maps(tactical: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    owned = {
        _i(row.get("element")): row
        for row in tactical.get("owned") or []
        if _i(row.get("element")) > 0
    }
    watch = {
        _i(row.get("element")): row
        for row in tactical.get("watchlist") or []
        if _i(row.get("element")) > 0
    }
    return owned, watch


def _package_rows(package_audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for replacement_count, packages in (package_audit.get("packages") or {}).items():
        for package in packages or []:
            out_ids = tuple(sorted(_i(row.get("element")) for row in package.get("out") or [] if _i(row.get("element")) > 0))
            in_ids = tuple(sorted(_i(row.get("element")) for row in package.get("in") or [] if _i(row.get("element")) > 0))
            if not out_ids or not in_ids:
                continue
            rows.append({
                **package,
                "replacements": _i(package.get("replacements", replacement_count), len(out_ids)),
                "out_ids": out_ids,
                "in_ids": in_ids,
            })
    return rows


def _single_package_map(rows: list[dict[str, Any]]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    for package in rows:
        if package.get("replacements") == 1 and len(package.get("out_ids") or ()) == 1 and len(package.get("in_ids") or ()) == 1:
            out[(package["out_ids"][0], package["in_ids"][0])] = package
    return out


def _free_transfer_evidence(team: dict[str, Any], latest: dict[str, Any]) -> int | None:
    candidates = [
        team.get("free_transfers"),
        (team.get("transfers") or {}).get("free_transfers") if isinstance(team.get("transfers"), dict) else None,
        (latest.get("transfers") or {}).get("free_transfers") if isinstance(latest.get("transfers"), dict) else None,
        (latest.get("personal_team_state") or {}).get("free_transfers") if isinstance(latest.get("personal_team_state"), dict) else None,
    ]
    for value in candidates:
        if value is not None:
            parsed = _i(value, -1)
            if parsed >= 0:
                return parsed
    return None


def _hit_context(replacements: int, wildcard_active: bool, free_transfers: int | None) -> dict[str, Any]:
    replacements = max(0, int(replacements))
    if wildcard_active:
        return {
            "state": "KNOWN",
            "wildcard_active": True,
            "free_transfers": free_transfers,
            "hit_cost": 0,
            "reason": "WILDCARD_ACTIVE",
        }
    if free_transfers is None:
        return {
            "state": "UNKNOWN",
            "wildcard_active": False,
            "free_transfers": None,
            "hit_cost": None,
            "reason": "FREE_TRANSFER_EVIDENCE_UNAVAILABLE",
        }
    return {
        "state": "KNOWN",
        "wildcard_active": False,
        "free_transfers": free_transfers,
        "hit_cost": max(0, replacements - free_transfers) * 4,
        "reason": "OFFICIAL_OR_PERSONAL_TEAM_TRANSFER_STATE",
    }


def _package_net(package: dict[str, Any] | None, hit: dict[str, Any]) -> dict[str, Any]:
    if not package:
        return {
            "canonical_adjusted_utility_gain_5": None,
            "hit_cost": hit.get("hit_cost"),
            "net_projected_gain_5": None,
            "state": "NO_CANONICAL_PACKAGE",
        }
    gross = _f(package.get("adjusted_utility_gain_5"))
    if hit.get("state") != "KNOWN":
        return {
            "canonical_adjusted_utility_gain_5": gross,
            "hit_cost": None,
            "net_projected_gain_5": None,
            "state": "HIT_COST_UNKNOWN",
        }
    hit_cost = _i(hit.get("hit_cost"), 0)
    return {
        "canonical_adjusted_utility_gain_5": gross,
        "hit_cost": hit_cost,
        "net_projected_gain_5": round(gross - hit_cost, 3),
        "state": "KNOWN",
    }


def _club_legal(owned_candidates: list[Any], outgoing: Any, incoming: Any) -> bool:
    counts: dict[int, int] = {}
    for row in owned_candidates:
        counts[int(row.team_id)] = counts.get(int(row.team_id), 0) + 1
    counts[int(outgoing.team_id)] = max(0, counts.get(int(outgoing.team_id), 0) - 1)
    counts[int(incoming.team_id)] = counts.get(int(incoming.team_id), 0) + 1
    return max(counts.values(), default=0) <= 3


def _route_to_points(pred: dict[str, Any], tactical_row: dict[str, Any] | None) -> dict[str, Any]:
    fixture = ((pred.get("fixtures") or [{}])[0]) or {}
    return {
        "components": fixture.get("components") or {},
        "return_routes": ((tactical_row or {}).get("tactical") or {}).get("return_routes") or [],
        "tactical_role": (pred.get("priors") or {}).get("tactical_role"),
    }


def _decision(
    *,
    challenger_type: str,
    edge5: float,
    snr: float,
    start_probability: float | None,
    affordable: bool,
    club_legal: bool,
    package: dict[str, Any] | None,
    net: dict[str, Any],
    market: dict[str, Any],
    sustainable: bool,
) -> tuple[str, list[str]]:
    cfg = load_policy().get("decision") or {}
    blockers: list[str] = []
    if not affordable:
        blockers.append("NOT_AFFORDABLE")
    if not club_legal:
        blockers.append("CLUB_LIMIT")
    if start_probability is None or start_probability < _f(cfg.get("minimum_start_probability"), 0.60):
        blockers.append("START_SECURITY")
    if challenger_type == "EMERGING_CHALLENGER":
        if not sustainable:
            return "HOLD", ["UNSUSTAINABLE_EMERGING_SIGNAL"]
        return ("REVIEW" if edge5 >= _f(cfg.get("review_edge_5gw"), 1.0) else "HOLD"), []
    if not affordable or not club_legal:
        return "BLOCKED", blockers
    if edge5 < _f(cfg.get("review_edge_5gw"), 1.0):
        return "HOLD", blockers

    timing_ready = (
        market.get("model_urgency") in set(cfg.get("market_actionable_urgencies") or ["HIGH", "CRITICAL"])
        or market.get("predicted_change_cycle") == "NEXT_UPDATE"
    )
    material_package = bool(package and package.get("classification") == "MATERIAL_UPGRADE")
    net_gain = net.get("net_projected_gain_5")
    hit_known = net.get("state") == "KNOWN"
    if (
        material_package
        and snr >= _f(cfg.get("minimum_signal_to_noise"), 0.75)
        and hit_known
        and net_gain is not None
        and _f(net_gain) > 0
        and not blockers
    ):
        return "CHANGE", []
    if material_package and not hit_known:
        return "REVIEW_NOW", ["HIT_COST_UNKNOWN"]
    if edge5 >= _f(cfg.get("review_now_edge_5gw"), 3.0) and (package or timing_ready):
        return "REVIEW_NOW", blockers
    return "REVIEW", blockers


def _emerging_candidates(
    candidates: list[Any],
    pmap: dict[int, dict[str, Any]],
    umap: dict[int, dict[str, Any]],
    excluded: set[int],
) -> list[tuple[Any, list[str], bool]]:
    cfg = load_policy().get("emerging") or {}
    rows: list[tuple[Any, list[str], bool]] = []
    for candidate in candidates:
        if candidate.element in excluded or candidate.x5 < _f(cfg.get("minimum_xpts_5"), 12.0):
            continue
        pred = pmap.get(candidate.element) or {}
        xmins = _avg_xmins(pred)
        if _f(xmins.get("start_probability")) < _f(cfg.get("minimum_start_probability"), 0.45):
            continue
        uni = umap.get(candidate.element) or {}
        triggers: list[str] = []
        if _i(uni.get("event_points"), 0) >= _i(cfg.get("event_points_trigger"), 8):
            triggers.append("STRONG_MATCH_RETURN")
        if _i(uni.get("transfers_in_event"), 0) >= _i(cfg.get("transfers_in_event_trigger"), 50000):
            triggers.append("TRANSFER_MOMENTUM")
        if not triggers:
            continue
        sustainable = _f(xmins.get("start_probability")) >= _f(cfg.get("sustainable_start_probability"), 0.60)
        rows.append((candidate, triggers, sustainable))
    rows.sort(key=lambda row: (row[0].x5, row[0].objective), reverse=True)
    return rows[: _i(cfg.get("maximum_candidates"), 12)]


def _compare(
    outgoing: Any,
    incoming: Any,
    *,
    challenger_type: str,
    triggers: list[str],
    sustainable: bool,
    owned_candidates: list[Any],
    bank: int,
    pmap: dict[int, dict[str, Any]],
    tactical_owned: dict[int, dict[str, Any]],
    tactical_watch: dict[int, dict[str, Any]],
    prices: dict[int, dict[str, Any]],
    single_packages: dict[tuple[int, int], dict[str, Any]],
    wildcard_active: bool,
    free_transfers: int | None,
) -> dict[str, Any]:
    out_pred = pmap.get(outgoing.element) or {}
    in_pred = pmap.get(incoming.element) or {}
    out_xmins = _avg_xmins(out_pred)
    in_xmins = _avg_xmins(in_pred)
    horizons: dict[str, Any] = {}
    for horizon in load_policy().get("horizons") or [1, 2, 3, 5]:
        out_x = _horizon(outgoing, int(horizon))
        in_x = _horizon(incoming, int(horizon))
        horizons[str(horizon)] = {
            "owned_xpts": round(out_x, 3),
            "challenger_xpts": round(in_x, 3),
            "projected_edge": round(in_x - out_x, 3),
        }
    strategic: dict[str, Any] = {}
    for horizon in load_policy().get("strategic_horizons") or [10, 15]:
        out_x = _horizon(outgoing, int(horizon))
        in_x = _horizon(incoming, int(horizon))
        strategic[str(horizon)] = {
            "owned_xpts": round(out_x, 3),
            "challenger_xpts": round(in_x, 3),
            "projected_edge": round(in_x - out_x, 3),
        }

    edge5 = _f((horizons.get("5") or {}).get("projected_edge"))
    combined_uncertainty = math.sqrt(max(0.0, outgoing.uncertainty ** 2 + incoming.uncertainty ** 2))
    snr = edge5 / combined_uncertainty if combined_uncertainty > 1e-9 else 0.0
    affordable = int(incoming.cost) <= int(outgoing.cost) + int(bank)
    legal = _club_legal(owned_candidates, outgoing, incoming)
    package = single_packages.get((outgoing.element, incoming.element))
    hit = _hit_context(1, wildcard_active, free_transfers)
    net = _package_net(package, hit)
    incoming_market = _market_view(prices.get(incoming.element))
    outgoing_market = _market_view(prices.get(outgoing.element))
    state, blockers = _decision(
        challenger_type=challenger_type,
        edge5=edge5,
        snr=snr,
        start_probability=in_xmins.get("start_probability"),
        affordable=affordable,
        club_legal=legal,
        package=package,
        net=net,
        market=incoming_market,
        sustainable=sustainable,
    )
    critical_evidence = {
        "canonical_projection": "AVAILABLE" if out_pred and in_pred else "UNAVAILABLE",
        "canonical_xmins": "AVAILABLE" if out_xmins.get("start_probability") is not None and in_xmins.get("start_probability") is not None else "UNAVAILABLE",
        "tactical_context": "AVAILABLE" if tactical_owned.get(outgoing.element) and tactical_watch.get(incoming.element) else "PARTIAL",
        "market_context": "AVAILABLE" if incoming_market.get("source") else "UNAVAILABLE",
        "canonical_package": "AVAILABLE" if package else "UNAVAILABLE",
        "hit_cost": hit.get("state"),
        "external_consensus": "UNAVAILABLE",
        "competitive_load": "UNAVAILABLE",
    }
    missing = [key for key, value in critical_evidence.items() if value in {"UNAVAILABLE", "PARTIAL", "UNKNOWN"}]
    return {
        "player_out": {
            "element": outgoing.element,
            "name": outgoing.name,
            "position": outgoing.position,
            "sell_cost": outgoing.cost,
        },
        "player_in": {
            "element": incoming.element,
            "name": incoming.name,
            "position": incoming.position,
            "now_cost": incoming.cost,
        },
        "challenger_type": challenger_type,
        "lifecycle_state": "EMERGING_CHALLENGER" if challenger_type == "EMERGING_CHALLENGER" else "ACTIVE_CHALLENGER",
        "decision": state,
        "state": state,
        "horizons": horizons,
        "strategic_context": strategic,
        "xmins": {"owned": out_xmins.get("expected_minutes"), "challenger": in_xmins.get("expected_minutes")},
        "start_probability": {"owned": out_xmins.get("start_probability"), "challenger": in_xmins.get("start_probability")},
        "role_security": {"owned_dnp": out_xmins.get("dnp_probability"), "challenger_dnp": in_xmins.get("dnp_probability")},
        "route_to_points": {
            "owned": _route_to_points(out_pred, tactical_owned.get(outgoing.element)),
            "challenger": _route_to_points(in_pred, tactical_watch.get(incoming.element)),
        },
        "tactical_matchup": ((tactical_watch.get(incoming.element) or {}).get("tactical") or {"evidence_state": "UNAVAILABLE"}),
        "competitive_load": {"state": "UNAVAILABLE", "reason": "NO_V4_CANONICAL_COMPETITIVE_LOAD_ARTIFACT"},
        "finance": {
            "exact_sell_cost": outgoing.cost,
            "incoming_now_cost": incoming.cost,
            "itb": bank,
            "affordable": affordable,
            "canonical_package": package,
            "hit_context": hit,
            "net_benefit": net,
        },
        "legality": {"same_position": outgoing.position == incoming.position, "club_limit_legal": legal},
        "market": {"owned": outgoing_market, "challenger": incoming_market},
        "external_consensus": {"state": "UNAVAILABLE", "advisory_only": True},
        "emerging_triggers": triggers,
        "anti_haul_chasing": {
            "single_haul_is_not_sufficient": True,
            "sustainable_candidate": sustainable if challenger_type == "EMERGING_CHALLENGER" else None,
        },
        "uncertainty": {"combined_5gw": round(combined_uncertainty, 3), "signal_to_noise_5gw": round(snr, 3)},
        "critical_evidence": critical_evidence,
        "missing_critical_evidence": missing,
        "blockers": blockers,
        "net_projected_gain": net.get("net_projected_gain_5"),
        "net_projected_gain_source": "V4_PACKAGE_ADJUSTED_UTILITY_MINUS_FPL_HIT" if net.get("state") == "KNOWN" else "UNAVAILABLE",
        "confidence": "LOW" if in_xmins.get("start_probability") is None else "MEDIUM",
        "execution_authorized": False,
        "reason": {
            "HOLD": "Belum ada keunggulan multi-GW yang cukup kuat.",
            "REVIEW": "Challenger layak dipantau, tetapi belum memenuhi seluruh gate tindakan.",
            "REVIEW_NOW": "Battle transfer sudah material, tetapi masih membutuhkan konfirmasi evidence atau hit cost.",
            "CHANGE": "Canonical package V4 menunjukkan upgrade material dengan net gain positif setelah hit yang diketahui.",
            "BLOCKED": "Battle terhalang affordability atau aturan skuad.",
        }[state],
    }


def _owned_screening(
    owned_candidates: list[Any],
    pmap: dict[int, dict[str, Any]],
    comparisons: list[dict[str, Any]],
    prices: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    state_rank = {"CHANGE": 5, "REVIEW_NOW": 4, "REVIEW": 3, "BLOCKED": 2, "HOLD": 1}
    by_out: dict[int, list[dict[str, Any]]] = {}
    for row in comparisons:
        by_out.setdefault(_i((row.get("player_out") or {}).get("element")), []).append(row)
    rows: list[dict[str, Any]] = []
    for candidate in owned_candidates:
        pred = pmap.get(candidate.element) or {}
        xmins = _avg_xmins(pred)
        battles = by_out.get(candidate.element, [])
        battles.sort(
            key=lambda row: (
                state_rank.get(str(row.get("decision")), 0),
                _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
            ),
            reverse=True,
        )
        best = battles[0] if battles else None
        rows.append({
            "element": candidate.element,
            "name": candidate.name,
            "position": candidate.position,
            "xpts_3gw": round(candidate.x3, 3),
            "xpts_5gw": round(candidate.x5, 3),
            "xpts_10gw": round(candidate.x10, 3),
            "xpts_15gw": round(candidate.x15, 3),
            "uncertainty": round(candidate.uncertainty, 3),
            "canonical_objective": round(candidate.objective, 4),
            "xmins": xmins.get("expected_minutes"),
            "start_probability": xmins.get("start_probability"),
            "dnp_probability": xmins.get("dnp_probability"),
            "sell_cost": candidate.cost,
            "market": _market_view(prices.get(candidate.element)),
            "lifecycle_state": "CHALLENGED_OWNED" if best and best.get("decision") != "HOLD" else "UNCHALLENGED",
            "challenge_pressure": best.get("decision") if best else "UNCHALLENGED",
            "replacement_opportunity": (
                {
                    "element": (best.get("player_in") or {}).get("element"),
                    "name": (best.get("player_in") or {}).get("name"),
                    "decision": best.get("decision"),
                    "edge_5gw": ((best.get("horizons") or {}).get("5") or {}).get("projected_edge"),
                    "net_projected_gain": best.get("net_projected_gain"),
                }
                if best else None
            ),
            "confidence": best.get("confidence") if best else "MEDIUM",
        })
    rows.sort(key=lambda row: (row["canonical_objective"], row["xpts_5gw"], str(row.get("name") or "")))
    for index, row in enumerate(rows, start=1):
        row["owned_rank"] = index
        row["weakness_rank"] = index
        row["weakest_link"] = index == 1
    return rows


def _main_battles(comparisons: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    order = {"CHANGE": 5, "REVIEW_NOW": 4, "REVIEW": 3, "BLOCKED": 2, "HOLD": 1}
    rows = [row for row in comparisons if row.get("decision") in {"CHANGE", "REVIEW_NOW", "REVIEW", "BLOCKED"}]
    rows.sort(
        key=lambda row: (
            order.get(str(row.get("decision")), 0),
            _f(row.get("net_projected_gain"), -999.0),
            _f(((row.get("horizons") or {}).get("5") or {}).get("projected_edge")),
        ),
        reverse=True,
    )
    return rows[: max(0, int(limit))]


def _multi_packages(
    rows: list[dict[str, Any]],
    *,
    owned_ids: set[int],
    challenger_ids: set[int],
    wildcard_active: bool,
    free_transfers: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for package in rows:
        replacements = _i(package.get("replacements"), 0)
        if replacements < 2:
            continue
        if not set(package.get("out_ids") or ()).issubset(owned_ids):
            continue
        if not set(package.get("in_ids") or ()).issubset(challenger_ids):
            continue
        hit = _hit_context(replacements, wildcard_active, free_transfers)
        net = _package_net(package, hit)
        decision = "REVIEW"
        if package.get("classification") == "MATERIAL_UPGRADE" and net.get("state") == "KNOWN" and _f(net.get("net_projected_gain_5")) > 0:
            decision = "CHANGE"
        elif package.get("classification") in {"MATERIAL_UPGRADE", "OPTIONAL_IMPROVEMENT"}:
            decision = "REVIEW_NOW"
        out.append({
            "replacements": replacements,
            "out": package.get("out") or [],
            "in": package.get("in") or [],
            "classification": package.get("classification"),
            "canonical_adjusted_utility_gain_5": package.get("adjusted_utility_gain_5"),
            "canonical_adjusted_best_xi_gain_5": package.get("adjusted_best_xi_gain_5"),
            "delta_squad_xpts_3": package.get("delta_squad_xpts_3"),
            "delta_squad_xpts_5": package.get("delta_squad_xpts_5"),
            "delta_squad_xpts_10": package.get("delta_squad_xpts_10"),
            "delta_squad_xpts_15": package.get("delta_squad_xpts_15"),
            "target_itb": package.get("target_itb"),
            "hit_context": hit,
            "net_projected_gain": net.get("net_projected_gain_5"),
            "decision": decision,
            "execution_authorized": False,
        })
    out.sort(key=lambda row: (_f(row.get("net_projected_gain"), -999.0), _f(row.get("canonical_adjusted_utility_gain_5"))), reverse=True)
    return out[: max(0, int(limit))]


def build() -> dict[str, Any]:
    cfg = load_policy()
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
    team = read_json(DATA / "team.json", {})
    latest = read_json(DATA / "latest.json", {})
    tactical = read_json(DATA / "tactical_serving_v4.json", {})
    prices_payload = read_json(DATA / "prices.json", {})
    package_audit = read_json(DATA / "wc_package_audit_v4.json", {})
    decision_pipeline = read_json(DATA / "decision_pipeline_v4.json", {})

    configured_lock = read_json(CONFIG / "locked_squad.json", {})
    locked = effective_planning_squad(team, configured_lock, latest)
    candidates = build_candidates(predictions, universe)
    effective_candidates, affordability = reconcile_owned_costs(candidates, locked)
    cmap = {row.element: row for row in effective_candidates}
    pmap = _prediction_map(predictions)
    umap = _universe_map(universe)
    prices = _price_map(prices_payload)
    tactical_owned, tactical_watch = _tactical_maps(tactical)

    owned_ids = {int(row.get("element") or 0) for row in locked.get("players") or []}
    owned_candidates = [cmap[element] for element in sorted(owned_ids) if element in cmap]
    watchlist_ids = [int(row.get("element") or 0) for row in tactical.get("watchlist") or [] if int(row.get("element") or 0) > 0]
    governed_ids = [element for element in watchlist_ids if element not in owned_ids and element in cmap]
    all_packages = _package_rows(package_audit)
    single_packages = _single_package_map(all_packages)
    wildcard_active = bool(locked.get("wildcard_active"))
    free_transfers = _free_transfer_evidence(team, latest)
    bank = _i(affordability.get("bank_tenths"), _i(locked.get("itb_tenths"), 0))

    comparisons: list[dict[str, Any]] = []
    for incoming_id in governed_ids:
        incoming = cmap[incoming_id]
        for outgoing in owned_candidates:
            if outgoing.position != incoming.position:
                continue
            comparisons.append(_compare(
                outgoing,
                incoming,
                challenger_type="GOVERNED_WATCHLIST",
                triggers=[],
                sustainable=True,
                owned_candidates=owned_candidates,
                bank=bank,
                pmap=pmap,
                tactical_owned=tactical_owned,
                tactical_watch=tactical_watch,
                prices=prices,
                single_packages=single_packages,
                wildcard_active=wildcard_active,
                free_transfers=free_transfers,
            ))

    excluded = owned_ids | set(governed_ids)
    emerging = _emerging_candidates(effective_candidates, pmap, umap, excluded)
    for incoming, triggers, sustainable in emerging:
        for outgoing in owned_candidates:
            if outgoing.position != incoming.position:
                continue
            comparisons.append(_compare(
                outgoing,
                incoming,
                challenger_type="EMERGING_CHALLENGER",
                triggers=triggers,
                sustainable=sustainable,
                owned_candidates=owned_candidates,
                bank=bank,
                pmap=pmap,
                tactical_owned=tactical_owned,
                tactical_watch=tactical_watch,
                prices=prices,
                single_packages=single_packages,
                wildcard_active=wildcard_active,
                free_transfers=free_transfers,
            ))

    screening = _owned_screening(owned_candidates, pmap, comparisons, prices)
    publish_cfg = cfg.get("publication") or {}
    completeness = {
        "owned": {"expected": _i(publish_cfg.get("exact_owned"), 15), "actual": len(owned_candidates), "complete": len(owned_candidates) == _i(publish_cfg.get("exact_owned"), 15)},
        "watchlist": {"expected": _i(publish_cfg.get("exact_watchlist"), 20), "actual": len(governed_ids), "complete": len(governed_ids) == _i(publish_cfg.get("exact_watchlist"), 20)},
    }
    publishable = completeness["owned"]["complete"] and completeness["watchlist"]["complete"]
    battles = _main_battles(comparisons, _i(publish_cfg.get("max_main_transfer_battles"), 8)) if publishable else []
    challenger_ids = set(governed_ids) | {candidate.element for candidate, _, _ in emerging}
    multi = _multi_packages(
        all_packages,
        owned_ids=owned_ids,
        challenger_ids=challenger_ids,
        wildcard_active=wildcard_active,
        free_transfers=free_transfers,
        limit=_i(publish_cfg.get("max_multi_transfer_packages"), 8),
    ) if publishable else []

    overall = "NO_TRANSFER_RECOMMENDED"
    if any(row.get("decision") == "CHANGE" for row in battles) or any(row.get("decision") == "CHANGE" for row in multi):
        overall = "CHANGE"
    elif any(row.get("decision") == "REVIEW_NOW" for row in battles) or any(row.get("decision") == "REVIEW_NOW" for row in multi):
        overall = "REVIEW_NOW"
    elif battles or multi:
        overall = "REVIEW"
    if not publishable:
        overall = "BLOCKED"

    execution_authorized = bool(decision_pipeline.get("execution_authorized"))
    return {
        "schema_version": 1,
        "contract": "OWNED_CHALLENGER_DECISION_ENGINE_V1",
        "engine_view": "V4",
        "generated_at": utcnow().isoformat(),
        "owner": cfg.get("owner"),
        "status": "READY" if publishable else "INCOMPLETE_OFFICIAL_FACTS",
        "capability_status": "GOVERNED_DECISION_ENRICHMENT",
        "execution_authorized": execution_authorized,
        "official_fact_completeness": completeness,
        "owned_count": len(owned_candidates),
        "governed_watchlist_count": len(governed_ids),
        "emerging_candidate_count": len(emerging),
        "comparison_count": len(comparisons),
        "owned_screening": screening,
        "comparisons": comparisons,
        "main_transfer_battles": battles,
        "multi_transfer_packages": multi,
        "overall_decision": overall,
        "no_transfer_recommended": publishable and not battles and not multi,
        "transfer_cost_evidence": {
            "wildcard_active": wildcard_active,
            "free_transfers": free_transfers,
            "state": "KNOWN" if wildcard_active or free_transfers is not None else "UNKNOWN",
        },
        "framework_state": (decision_pipeline.get("framework_state") or decision_pipeline.get("status") or "UNKNOWN"),
        "degraded_engine_weighting": str(decision_pipeline.get("status") or "").upper() in {"DEGRADED", "FAIL", "FAILED", "BLOCKED"},
        "consensus": {
            "state": "NEUTRAL",
            "reason": "V4 artifact does not infer V3 output; cross-engine consensus requires both governed artifacts.",
        },
        "publication": {
            "publishable": publishable,
            "main_transfer_battles_section": True,
            "data_join_defect_publication_forbidden": True,
            "no_false_certainty_for_price_eta": True,
        },
        "provenance": {
            "predictions": "data/predictions_v4.json",
            "tactical": "data/tactical_serving_v4.json",
            "packages": "data/wc_package_audit_v4.json",
            "prices": "data/prices.json",
            "network_refetch": False,
        },
        "governance": cfg.get("governance"),
    }


def run() -> dict[str, Any]:
    out = build()
    atomic_json(OUT, out)
    print(json.dumps({
        "status": out.get("status"),
        "owned_count": out.get("owned_count"),
        "governed_watchlist_count": out.get("governed_watchlist_count"),
        "comparison_count": out.get("comparison_count"),
        "main_transfer_battle_count": len(out.get("main_transfer_battles") or []),
        "multi_transfer_package_count": len(out.get("multi_transfer_packages") or []),
        "overall_decision": out.get("overall_decision"),
        "execution_authorized": out.get("execution_authorized"),
    }, ensure_ascii=False))
    return out

if __name__ == "__main__":
    run()
